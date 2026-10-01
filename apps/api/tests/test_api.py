"""API tests. Point the scenarios DB at a throwaway file BEFORE importing the app (the path is read
at import time), then drive the branch/PR workflow through the FastAPI TestClient.

Grid-agnostic: bus ids are derived from the live /model, so the suite passes for whatever network
the warehouse holds (NGED, mv_oberrhein, a future DNO region)."""

import os
import tempfile
from pathlib import Path

os.environ["GRIDFORGE_SCENARIOS_DB"] = str(Path(tempfile.mkdtemp()) / "scenarios.duckdb")

import pytest
from fastapi.testclient import TestClient

from gridforge_api.main import WAREHOUSE, app

pytestmark = pytest.mark.skipif(
    not WAREHOUSE.exists(), reason="pipeline warehouse DB not materialized"
)

client = TestClient(app)


def _buses():
    return client.get("/model").json()["buses"]


def _stiff_bus():
    """Top-voltage bus — absorbs a connection (grid-agnostic 'good' point)."""
    return max(_buses(), key=lambda b: b["vn_kv"])["bus_id"]


def _weak_buses(n):
    return [b["bus_id"] for b in sorted(_buses(), key=lambda b: (b["vn_kv"], b["bus_id"]))[:n]]


def _good(**kw):
    return {"applicant": "Acme", "bus_id": _stiff_bus(), "technology": "solar",
            "rating_mw": 5.0, "readiness_score": 0.9, **kw}


def _saturating(n=10, mw=50.0):
    wb = _weak_buses(n)
    return [{"applicant": f"Sat-{i}", "bus_id": wb[i % len(wb)], "technology": "wind",
             "rating_mw": mw, "readiness_score": 0.9} for i in range(n)]


def _create(name, **kw):
    r = client.post("/branches", json={"name": name, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_main_branch_seeded_and_unique():
    branches = client.get("/branches").json()["branches"]
    mains = [b for b in branches if b["branch_id"] == "main"]
    assert len(mains) == 1  # migration seeds exactly one main, idempotently
    assert mains[0]["status"] == "open"


def test_backcompat_endpoints_still_work():
    assert client.get("/health").json()["ok"] is True
    assert "buses" in client.get("/model").json()
    assert client.get("/optimize/candidates").json()  # non-empty candidate list
    q = client.post("/optimize", json={"with_justification": False}).json()
    assert "queue" in q and "phases" in q and q["branch_id"] == "main"
    base = client.get("/baseline").json()
    assert base["exists"] and "scenario" in base["params"]


def test_branch_create_list_get():
    b = _create("Test branch", added_projects=[_good()])
    bid = b["branch_id"]
    assert bid.startswith("br-") and b["n_added"] >= 1

    listed = {x["branch_id"] for x in client.get("/branches").json()["branches"]}
    assert "main" in listed and bid in listed

    detail = client.get(f"/branches/{bid}").json()
    assert detail["added_project_ids"]  # the added project is present
    assert client.get("/branches/does-not-exist").status_code == 404


def test_branch_diff_shows_added_project():
    b = _create("Adds a project", added_projects=[_good()])
    diff = client.get(f"/branches/{b['branch_id']}/diff").json()
    assert diff["base_branch"] == "main" and diff["head_branch"] == b["branch_id"]
    changes = {p["request_id"]: p["change"] for p in diff["projects"]}
    assert [rid for rid, ch in changes.items() if ch == "added"]  # the new project shows up as an addition


def test_two_branches_do_not_share_cache():
    # regression: _compute must key on the candidate set, not just scenario params
    wb = _weak_buses(1)[0]
    a = _create("Branch A", added_projects=[_good(applicant="A")])["branch_id"]
    b = _create("Branch B", added_projects=[_good(applicant="B", bus_id=wb)])["branch_id"]
    qa = client.post(f"/branches/{a}/optimize", json={"with_justification": False}).json()
    qb = client.post(f"/branches/{b}/optimize", json={"with_justification": False}).json()
    ids_a = {x["request_id"] for x in qa["queue"]}
    ids_b = {x["request_id"] for x in qb["queue"]}
    assert ids_a != ids_b  # each branch sees its own project, never the other's cached run


def test_suggestions_for_grid_deferred_branch():
    b = _create("Saturated queue", added_projects=_saturating(10))
    bid = b["branch_id"]
    q = client.post(f"/branches/{bid}/optimize", json={"with_justification": False}).json()
    deferred = [x for x in q["queue"] if x["status"] == "Deferred" and x.get("reason")
                and x["reason"].get("type") in ("line", "trafo", "voltage")]
    assert deferred, "saturating the weakest buses must produce grid-constrained deferrals"

    sugs = client.get(f"/branches/{bid}/suggestions").json()["suggestions"]
    assert sugs
    s = sugs[0]
    assert "action" in s and "freed_mw_2035" in s and "caveat" in s
    assert s["extra_solves"] > 0


def test_merge_adopts_branch_into_main():
    b = _create("To merge", added_projects=[_good(applicant="MergeMe")])
    bid = b["branch_id"]
    added_ids = set(client.get(f"/branches/{bid}").json()["added_project_ids"])

    merged = client.post(f"/branches/{bid}/merge", json={"into": "main"})
    assert merged.status_code == 200, merged.text
    assert merged.json()["branch_id"] == "main"

    main_added = set(client.get("/branches/main").json()["added_project_ids"])
    assert added_ids <= main_added  # main adopted the branch's projects

    assert client.get(f"/branches/{bid}").json()["status"] == "merged"
    assert client.post(f"/branches/{bid}/merge", json={"into": "main"}).status_code == 409


def test_discard_and_main_guard():
    b = _create("To discard")
    bid = b["branch_id"]
    assert client.post(f"/branches/{bid}/discard").json()["status"] == "discarded"
    assert client.post("/branches/main/discard").status_code == 400
    assert client.post("/branches/main/merge", json={"into": "main"}).status_code == 400
