"""Projects: the built-in NGED one behind the same routes as before, and any grid imported from a file
becoming a project with its own main, baseline, model, branches and runs. A CGMES zip of NGED's own
export re-imports with the same elements; a pandapower JSON with no coordinates gets a synthetic
layout; a branch with a hand-entered project at one of its buses runs through the same engine."""

import time
from concurrent.futures import ThreadPoolExecutor

import pandapower as pp
import pandapower.networks as pn

from gridforge_api.config import NGED_PROJECT_ID
from gridforge_optimizer.config import PLAN_START_YEAR
from _support import client, requires_warehouse

pytestmark = requires_warehouse


def _import(filename: str, data: bytes, name: str = "", **fields) -> dict:
    r = client.post("/projects", files={"file": (filename, data, "application/octet-stream")}, data={"name": name, **{k: str(v) for k, v in fields.items()}})
    assert r.status_code == 200, r.text
    return r.json()


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
    assert item["lon"] is not None  # a synthetic layout still places the project
    assert run["snapshot_id"] == p["snapshot_id"]
    d = client.get(f"/branches/{b['branch_id']}/diff").json()
    assert d["base_branch"] == main and d["head_branch"] == b["branch_id"]
    # a project out of this grid's buses is refused as before; a works window names its own elements
    bad = client.post("/optimize/candidates", json={"applicant": "X", "bus_id": 9999, "technology": "solar", "rating_mw": 5.0, "readiness_score": 0.9, "branch_id": b["branch_id"]}).json()
    assert bad["status"] == "rejected"
    line = m["lines"][0]["line_id"]
    w = client.post(f"/branches/{b['branch_id']}/outages", json={"element_kind": "line", "element_id": str(line), "season": "Summer", "year": PLAN_START_YEAR + 3, "weeks": 4})
    assert w.status_code == 200, w.text
    assert client.post(f"/branches/{b['branch_id']}/outages", json={"element_kind": "line", "element_id": "999", "season": "Summer", "year": PLAN_START_YEAR + 3, "weeks": 4}).status_code == 422
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
    bnd = client.get("/boundary").json()  # the limits the operator would enter: the ones the export was built with
    limits = {"gsp_export_limit_mw": bnd["export_limit_mw"], "gsp_name": bnd["gsp_name"], "min_demand_factor": 0.5, "summer_rating_ratio": 0.9}
    p = _import("nged.zip", z.content, name="NGED re-imported", **limits)
    pid = p["project_id"]
    assert p["source_kind"] == "cgmes" and p["report"]["ok"] and p["report"]["cases"] == ["winter_peak", "summer_min"]
    assert p["capabilities"]["boundary"] and p["capabilities"]["summer_case"] and p["capabilities"]["crs"] == "wgs84"
    assert p["meta"]["gsp_export_limit_mw"] == float(bnd["export_limit_mw"])
    nged = client.get("/model").json()
    m = client.get(f"/projects/{pid}/model").json()
    assert (len(m["buses"]), len(m["lines"]), len(m["transformers"]), len(m["loads"])) == (len(nged["buses"]), len(nged["lines"]), len(nged["transformers"]), len(nged["loads"]))
    assert m["regions"] == []  # firm capacities are not in a CGMES file
    b = client.get(f"/projects/{pid}/boundary").json()
    assert b["export_limit_mw"] == float(bnd["export_limit_mw"]) and b["export_today_mw"] > 0 and b["source"] == "operator-entered at import"
    entered = [a for a in client.get(f"/projects/{pid}/assumptions").json()["assumptions"] if a["source"] == "operator-entered"]
    assert {a["key"] for a in entered} >= {"gsp_limit_entered", "min_demand_entered", "summer_ratio_entered"}
    # the same file twice is two projects with the same baseline (results are shared by the fingerprint)
    p2 = _import("nged.zip", z.content, name="again", **limits)
    assert p2["snapshot_id"] == p["snapshot_id"] and p2["project_id"] != pid
    client.delete(f"/projects/{p2['project_id']}")
    client.delete(f"/projects/{pid}")


def test_the_boundary_is_one_power_flow_however_many_ask_at_once(monkeypatch):
    """The planner's boot and the startup warm-up ask for the boundary together on a cold process; each ask
    used to run its own power flow, and the first page load waited for the slowest of them."""
    from gridforge_api import deps
    from gridforge_api.projects import WarehouseNgedSource

    calls: list[int] = []

    def slow_boundary(self):
        calls.append(1)
        time.sleep(0.3)  # long enough for every request to be waiting on the first
        return {"gsp_name": "stub", "export_limit_mw": 1.0}

    monkeypatch.setattr(WarehouseNgedSource, "boundary", slow_boundary)
    deps.projects.forget()  # the earlier tests cached the real card
    try:
        with ThreadPoolExecutor(max_workers=6) as ex:
            rs = list(ex.map(lambda _: client.get(f"/projects/{NGED_PROJECT_ID}/boundary"), range(6)))
        assert all(r.status_code == 200 for r in rs) and {r.json()["gsp_name"] for r in rs} == {"stub"}
        assert len(calls) == 1
    finally:
        deps.projects.forget()  # the stub must not outlive the test
