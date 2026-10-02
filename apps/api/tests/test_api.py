"""API tests. Point the scenarios DB at a throwaway file BEFORE importing the app (the path is read
at import time), then drive the branch/PR workflow through the FastAPI TestClient.

Grid-agnostic: bus ids are derived from the live /model, so the suite passes for whatever network
the warehouse holds (today the NGED Bicker Fen GSP; any future DNO region)."""

import os
import tempfile
from pathlib import Path

os.environ["GRIDFORGE_SCENARIOS_DB"] = str(Path(tempfile.mkdtemp()) / "scenarios.duckdb")

import pytest
from fastapi.testclient import TestClient

from gridforge_api.config import WAREHOUSE
from gridforge_api.main import app

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


def _saturating(n=5, mw=50.0):
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


def _queue_ids(branch_id):
    """Request ids in a branch's plan, as the planner sees them (main runs via /optimize)."""
    path = "/optimize" if branch_id == "main" else f"/branches/{branch_id}/optimize"
    return {x["request_id"] for x in client.post(path, json={"with_justification": False}).json()["queue"]}


def _branch(branch_id):
    return next(b for b in client.get("/branches").json()["branches"] if b["branch_id"] == branch_id)


def test_core_read_endpoints():
    assert client.get("/health").json()["ok"] is True
    assert "buses" in client.get("/model").json()
    assert client.get("/registry").json()  # non-empty registry of optional projects
    assert "export_limit_mw" in client.get("/boundary").json()
    q = client.post("/optimize", json={"with_justification": False}).json()
    assert "queue" in q and "phases" in q and q["branch_id"] == "main"


def test_cgmes_download_is_a_deterministic_zip():
    import io
    import zipfile

    r = client.get("/model/cgmes")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert [n.rsplit("_", 1)[1] for n in names] == ["EQ.xml", "GL.xml", "SSH.xml", "TP.xml"]
    assert client.get("/model/cgmes").content == r.content  # same snapshot, same bytes


def test_versions_and_edition_changes():
    snaps = client.get("/snapshots").json()
    assert snaps["current"] and snaps["snapshots"][0]["snapshot_id"] == snaps["current"]
    assert snaps["snapshots"][0]["ltds_edition"]  # every version names the edition it was built from

    ch = client.get("/editions/changes").json()
    assert ch["n_changes"]["new"] > 0 and ch["n_changes"]["removed"] > 0
    assert {r["change"] for r in ch["rows"]} <= {"new", "removed", "updated"}
    assert sum(ch["n_changes"].values()) == len(ch["rows"])
    assert "demand_mw" in ch["model"]["delta"] and "gsp_export_mw" in ch["physics"]["delta"]
    assert ch["caveats"]

    reg = client.get("/registry/changes").json()
    assert "editions" in reg and "changes" in reg  # empty until the scheduled ECR fetch has run


def test_branch_create_and_list():
    b = _create("Test branch", added_projects=[_good()])
    bid = b["branch_id"]
    assert bid.startswith("br-") and b["n_added"] >= 1

    listed = {x["branch_id"] for x in client.get("/branches").json()["branches"]}
    assert "main" in listed and bid in listed

    assert _queue_ids(bid)  # the added project is in the branch's plan
    assert client.post("/branches/does-not-exist/optimize", json={}).status_code == 404


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


def test_schedule_persists_and_flags_against_recommendation():
    b = _create("Scheduled", added_projects=[_good()])
    bid = b["branch_id"]
    q = client.post(f"/branches/{bid}/optimize", json={"with_justification": False}).json()
    item = next(x for x in q["queue"] if x["status"] in ("Phase1", "Phase2"))
    rid, rec = item["request_id"], item["recommended_year"]
    assert rec is not None and item["scheduled_year"] is None  # follows the recommendation by default

    # the operator schedules it EARLIER than the grid supports -> persisted + flagged
    r = client.post(f"/branches/{bid}/schedule", json={"request_id": rid, "year": rec - 1})
    assert r.status_code == 200, r.text
    q = client.post(f"/branches/{bid}/optimize", json={"with_justification": False}).json()
    item = next(x for x in q["queue"] if x["request_id"] == rid)
    assert item["scheduled_year"] == rec - 1 and item["against_recommendation"] is True
    assert item["status"] in ("Phase1", "Phase2")  # scheduling never changes the verdict

    # clearing it returns to the recommendation
    client.post(f"/branches/{bid}/schedule", json={"request_id": rid, "year": None})
    q = client.post(f"/branches/{bid}/optimize", json={"with_justification": False}).json()
    item = next(x for x in q["queue"] if x["request_id"] == rid)
    assert item["scheduled_year"] is None and item["against_recommendation"] is False

    # guards: out-of-range year, project not on the branch
    assert client.post(f"/branches/{bid}/schedule", json={"request_id": rid, "year": 2050}).status_code == 422
    assert client.post(f"/branches/{bid}/schedule", json={"request_id": "NOPE", "year": 2030}).status_code == 404


def test_suggestions_for_grid_deferred_branch():
    b = _create("Saturated queue", added_projects=_saturating(5))
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
    added_ids = _queue_ids(bid)
    assert added_ids

    merged = client.post(f"/branches/{bid}/merge", json={"into": "main"})
    assert merged.status_code == 200, merged.text
    assert merged.json()["branch_id"] == "main"

    assert added_ids <= _queue_ids("main")  # main adopted the branch's projects

    assert _branch(bid)["status"] == "merged"
    assert client.post(f"/branches/{bid}/merge", json={"into": "main"}).status_code == 409


def test_discard_and_main_guard():
    b = _create("To discard")
    bid = b["branch_id"]
    assert client.post(f"/branches/{bid}/discard").json()["status"] == "discarded"
    assert client.post("/branches/main/discard").status_code == 400
    assert client.post("/branches/main/merge", json={"into": "main"}).status_code == 400


def test_background_job_runs_a_branch_and_reports_progress():
    b = _create("Job branch", added_projects=[_good()])
    bid = b["branch_id"]
    job = client.post(f"/branches/{bid}/optimize/jobs", json={"with_justification": False}).json()
    assert job["status"] in ("queued", "running", "done") and job["job_id"].startswith("job-")
    import time as _t
    for _ in range(600):
        j = client.get(f"/jobs/{job['job_id']}").json()
        if j["status"] in ("done", "failed"):
            break
        _t.sleep(0.5)
    assert j["status"] == "done", j.get("error")
    assert j["stage"] == "done" and j["fraction"] == 1.0 and j["elapsed_ms"] >= 0
    sync = client.post(f"/branches/{bid}/optimize", json={"with_justification": False}).json()
    assert j["result"]["queue"] == sync["queue"]  # the job computed exactly what the sync endpoint returns
    assert client.get("/jobs/job-nope").status_code == 404


def test_results_are_cached_durably_and_keyed_by_engine():
    from gridforge_api.deps import cache

    b = _create("Cache branch", added_projects=[_good()])
    bid = b["branch_id"]
    first = client.post(f"/branches/{bid}/optimize", json={"with_justification": False}).json()
    stats = client.get("/cache").json()
    assert stats["engine"] == cache.engine and any(e["kind"] == "optimize" and e["engine"] == cache.engine for e in stats["entries"])
    # a "restart": the in-process caches are gone, the DuckDB row is not
    cache.clear()
    import time as _t
    t0 = _t.perf_counter()
    second = client.post(f"/branches/{bid}/optimize", json={"with_justification": False}).json()
    assert second["queue"] == first["queue"]
    assert _t.perf_counter() - t0 < 5.0  # served from the durable cache, not re-solved
