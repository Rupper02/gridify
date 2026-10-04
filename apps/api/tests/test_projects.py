"""Projects: the built-in NGED one behind the same routes as before, and any grid imported from a file
becoming a project with its own main, baseline, model, branches and runs. A CGMES zip of NGED's own
export re-imports with the same elements; a pandapower JSON with no coordinates gets a synthetic
layout; a branch with a hand-entered project at one of its buses runs through the same engine."""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("GRIDFORGE_SCENARIOS_DB", str(Path(tempfile.mkdtemp()) / "scenarios.duckdb"))
os.environ.setdefault("GRIDFORGE_PROJECTS_DIR", str(Path(tempfile.mkdtemp()) / "projects"))

import pandapower as pp
import pandapower.networks as pn
import pytest
from fastapi.testclient import TestClient

from gridforge_api.config import NGED_PROJECT_ID, WAREHOUSE
from gridforge_api.main import app

pytestmark = pytest.mark.skipif(not WAREHOUSE.exists(), reason="pipeline warehouse DB not materialized")

client = TestClient(app)


def _import(filename: str, data: bytes, name: str = "", **fields) -> dict:
    r = client.post("/projects", files={"file": (filename, data, "application/octet-stream")}, data={"name": name, **{k: str(v) for k, v in fields.items()}})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_built_in_project_is_listed_and_the_unprefixed_routes_are_its_aliases():
    ps = client.get("/projects").json()["projects"]
    nged = next(p for p in ps if p["project_id"] == NGED_PROJECT_ID)
    assert nged["builtin"] and nged["main_id"] == "main" and nged["capabilities"]["registry"] and nged["source_kind"] == "nged"
    m, alias = client.get(f"/projects/{NGED_PROJECT_ID}/model"), client.get("/model")
    assert m.status_code == 200 and alias.status_code == 200 and m.json() == alias.json() and m.json()["crs"] == "wgs84"
    assert client.get(f"/projects/{NGED_PROJECT_ID}/registry").json() == client.get("/registry").json()
    assert client.get(f"/projects/{NGED_PROJECT_ID}/boundary").json() == client.get("/boundary").json()
    a = client.get("/projects/nged-bickerfen/assumptions").json()["assumptions"]
    assert {x["key"] for x in a} >= {"rating_fallback", "tap_target"}
    assert client.get("/projects/nope").status_code == 404
    assert client.delete(f"/projects/{NGED_PROJECT_ID}").status_code == 409
    branches = client.get(f"/projects/{NGED_PROJECT_ID}/branches").json()["branches"]
    assert branches and branches[0]["branch_id"] == "main" and branches[0]["project_id"] == NGED_PROJECT_ID


def test_bad_files_are_refused_with_the_reason():
    r = client.post("/projects", files={"file": ("grid.csv", b"a,b\n1,2\n", "text/csv")}, data={"name": "csv"})
    assert r.status_code == 415
    r = client.post("/projects", files={"file": ("broken.json", b"{not json", "application/json")}, data={"name": "broken"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unreadable"
    net = pp.create_empty_network()
    b1, b2 = pp.create_bus(net, 33.0), pp.create_bus(net, 0.0)  # a bus with no voltage
    pp.create_line_from_parameters(net, b1, b2, 1.0, 0.1, 0.1, 0.0, 0.4)
    pp.create_ext_grid(net, b1)
    r = client.post("/projects", files={"file": ("novolt.json", pp.to_json(net).encode(), "application/json")}, data={"name": "no volt"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid" and r.json()["detail"]["report"]["errors"]


def test_a_pandapower_json_becomes_a_project_you_can_branch_and_run():
    c9 = pn.case9()
    c9.bus["geo"] = None
    p = _import("case9.json", pp.to_json(c9).encode(), name="IEEE 9-bus")
    pid, main = p["project_id"], p["main_id"]
    assert p["source_kind"] == "pandapower_json" and main == f"{pid}-main" and not p["builtin"]
    assert p["report"]["ok"] and p["report"]["cases"] == ["winter_peak"] and p["capabilities"]["crs"] == "synthetic"
    assert not p["capabilities"]["boundary"] and not p["capabilities"]["registry"] and not p["capabilities"]["summer_case"]
    m = client.get(f"/projects/{pid}/model").json()
    assert m["crs"] == "synthetic" and len(m["buses"]) == 9 and m["regions"] == [] and len(m["generators"]) == 2
    assert client.get(f"/projects/{pid}/boundary").status_code == 404
    assert client.get(f"/projects/{pid}/registry").json() == []
    keys = {a["key"] for a in client.get(f"/projects/{pid}/assumptions").json()["assumptions"]}
    assert {"gen_to_sgen", "no_gsp_limit", "gb_voltage_bands"} <= keys
    # its main runs (an empty queue), on the same engine
    r = client.post(f"/projects/{pid}/optimize", json={"with_justification": False}).json()
    assert r["queue"] == [] and r["project_id"] == pid and r["snapshot_id"] == p["snapshot_id"] and len(r["years"]) == 10
    # a branch off its main with a hand-entered project at one of its buses
    bus = max(m["buses"], key=lambda b: b["vn_kv"])["bus_id"]
    b = client.post("/branches", json={"name": "c9 solar", "from_branch": main,
                                       "added_projects": [{"applicant": "Nine", "bus_id": bus, "technology": "solar", "rating_mw": 5.0, "readiness_score": 0.9}]}).json()
    assert b["project_id"] == pid and b["parent_id"] == main and b["n_added"] == 1
    assert [x["branch_id"] for x in client.get(f"/projects/{pid}/branches").json()["branches"]][0] == main
    assert all(x["project_id"] == pid for x in client.get(f"/projects/{pid}/branches").json()["branches"])
    run = client.post(f"/branches/{b['branch_id']}/optimize", json={"with_justification": False}).json()
    item = run["queue"][0]
    assert item["status"] in ("Phase1", "Phase2", "Deferred", "Rejected") and item["lon"] is not None
    assert run["snapshot_id"] == p["snapshot_id"]
    d = client.get(f"/branches/{b['branch_id']}/diff").json()
    assert d["base_branch"] == main and d["head_branch"] == b["branch_id"]
    # a project out of this grid's buses is refused as before; a works window names its own elements
    bad = client.post("/optimize/candidates", json={"applicant": "X", "bus_id": 9999, "technology": "solar", "rating_mw": 5.0, "readiness_score": 0.9, "branch_id": b["branch_id"]}).json()
    assert bad["status"] == "rejected" or bad["status"] == "needs_review"
    line = m["lines"][0]["line_id"]
    w = client.post(f"/branches/{b['branch_id']}/outages", json={"element_kind": "line", "element_id": str(line), "season": "Summer", "year": 2029, "weeks": 4})
    assert w.status_code == 200, w.text
    assert client.post(f"/branches/{b['branch_id']}/outages", json={"element_kind": "line", "element_id": "999", "season": "Summer", "year": 2029, "weeks": 4}).status_code == 422
    # its CGMES export round-trips
    z = client.get(f"/projects/{pid}/model/cgmes")
    assert z.status_code == 200 and z.content[:2] == b"PK"
    # delete cascades
    out = client.delete(f"/projects/{pid}").json()
    assert out["deleted"] and out["branches_removed"] >= 2
    assert client.get(f"/projects/{pid}").status_code == 404 and client.get(f"/branches/{b['branch_id']}/findings").status_code == 404


def test_nged_own_cgmes_export_imports_as_a_project_with_the_same_elements_and_entered_limits():
    z = client.get("/model/cgmes")
    assert z.status_code == 200
    p = _import("nged.zip", z.content, name="NGED re-imported", gsp_export_limit_mw=527, gsp_name="Bicker Fen", min_demand_factor=0.5, summer_rating_ratio=0.9)
    pid = p["project_id"]
    assert p["source_kind"] == "cgmes" and p["report"]["ok"] and p["report"]["cases"] == ["winter_peak", "summer_min"]
    assert p["capabilities"]["boundary"] and p["capabilities"]["summer_case"] and p["capabilities"]["crs"] == "wgs84"
    assert p["meta"]["gsp_export_limit_mw"] == 527.0
    nged = client.get("/model").json()
    m = client.get(f"/projects/{pid}/model").json()
    assert (len(m["buses"]), len(m["lines"]), len(m["transformers"]), len(m["loads"])) == (len(nged["buses"]), len(nged["lines"]), len(nged["transformers"]), len(nged["loads"]))
    assert m["regions"] == []  # firm capacities are not in a CGMES file
    b = client.get(f"/projects/{pid}/boundary").json()
    assert b["export_limit_mw"] == 527.0 and b["export_today_mw"] > 0 and b["source"] == "operator-entered at import"
    entered = [a for a in client.get(f"/projects/{pid}/assumptions").json()["assumptions"] if a["source"] == "operator-entered"]
    assert {a["key"] for a in entered} >= {"gsp_limit_entered", "min_demand_entered", "summer_ratio_entered"}
    # the same file twice is two projects with the same baseline (results are shared by the fingerprint)
    p2 = _import("nged.zip", z.content, name="again", gsp_export_limit_mw=527, gsp_name="Bicker Fen", min_demand_factor=0.5, summer_rating_ratio=0.9)
    assert p2["snapshot_id"] == p["snapshot_id"] and p2["project_id"] != pid
    client.delete(f"/projects/{p2['project_id']}")
    client.delete(f"/projects/{pid}")
