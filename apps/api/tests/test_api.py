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


_VERDICTS = {"feasible", "curtailment", "demand_at_risk", "not_feasible"}


def test_branch_diff_is_year_aware_and_compares_planned_works_with_main():
    """The diff carries every plan year (lines, transformers, GSP, N-1) and each branch window's
    verdict on main's plan vs the branch's; the extra study on main's plan is cached durably."""
    from gridforge_api.deps import cache

    bid = _create("Year diff", added_projects=[_good(), *_saturating(3)])["branch_id"]
    line = _first("line")
    oid = client.post(f"/branches/{bid}/outages", json={"element_kind": "line", "element_id": line,
                                                       "season": "Summer", "year": 2035}).json()["outage_id"]
    d = client.get(f"/branches/{bid}/diff").json()
    assert sorted(d["years"]) == [str(y) for y in range(2026, 2036)]
    y35 = d["years"]["2035"]
    for k in ("worst_line_delta", "worst_trafo_delta", "gsp_export_delta", "n1_findings_delta",
              "newly_overloaded_trafo_ids", "top_line_deltas", "top_trafo_deltas", "energised_only_head"):
        assert k in y35, k
    connected = {p["request_id"] for p in d["projects"] if p["head_status"] in ("Phase1", "Phase2")}
    assert set(y35["energised_only_head"]) <= connected and (not connected or y35["energised_only_head"])
    assert all({"element_id", "base_pct", "head_pct", "delta", "crossed"} <= t.keys() for t in y35["top_trafo_deltas"])
    assert d["phases"] and "mw_2030_delta" in d["headline"]  # the 2030/2035 headline is still there

    [w] = d["works"]
    assert w["outage_id"] == oid and w["year"] == 2035
    assert w["verdict_on_main"] in _VERDICTS and w["verdict_on_branch"] in _VERDICTS
    assert w["change"] in ("worse", "better", "unchanged") and w["consequence"].endswith(".")
    assert any(e["kind"] == "works" for e in client.get("/cache").json()["entries"])
    # a "restart": the diff (queue, years and the works study on main's plan) comes from the durable cache
    cache.clear()
    import time as _t
    t0 = _t.perf_counter()
    assert client.get(f"/branches/{bid}/diff").json()["works"] == d["works"]
    assert _t.perf_counter() - t0 < 5.0


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


def _run_job(branch_id, **body):
    """Run a branch as a background job and wait for it (the planner's path)."""
    import time as _t
    job = client.post(f"/branches/{branch_id}/optimize/jobs", json={"with_justification": False, **body}).json()
    for _ in range(2400):
        if job["status"] not in ("queued", "running"):
            break
        _t.sleep(0.25)
        job = client.get(f"/jobs/{job['job_id']}").json()
    assert job["status"] == "done", job.get("error")
    return job["result"]


def test_every_year_of_the_plan_is_solved_in_one_run():
    """One run solves 2026..2035; demand grows with the years, so loading does too."""
    r = _run_job("main", view_year=2028)
    assert sorted(r["years"]) == [str(y) for y in range(2026, 2036)] and r["years_total"] == 10
    assert r["years"]["2028"]["growth"] < r["years"]["2032"]["growth"]
    assert r["years"]["2032"]["worst_line_loading_pct"] >= r["years"]["2028"]["worst_line_loading_pct"]
    assert "2030" in r["phases"] and "2035" in r["phases"]  # the queue's two phases are still there


def test_a_running_job_publishes_partial_results():
    import threading

    from gridforge_api.deps import jobs

    gate = threading.Event()

    def fn(progress, publish):
        publish({"queue": [], "years": {}})
        gate.wait(10)
        return {"queue": [], "years": {"2030": {}}}

    rec = jobs.start("test", fn)
    import time as _t
    for _ in range(200):
        j = client.get(f"/jobs/{rec['job_id']}?partial=true").json()
        if j["has_partial"]:
            break
        _t.sleep(0.05)
    assert j["status"] == "running" and j["partial"] == {"queue": [], "years": {}}
    gate.set()
    for _ in range(200):
        j = client.get(f"/jobs/{rec['job_id']}?partial=true").json()
        if j["status"] == "done":
            break
        _t.sleep(0.05)
    assert j["partial"] is None and j["result"]["years"] == {"2030": {}}  # the final result replaces it


def test_profile_persists_across_runs():
    """Profile changes persist: re-runs use the selected profile, not the originally stored one."""
    client.post("/branches/main/scenario", json={"scenario": "ee", "growth_2030": 1.10, "growth_2035": 1.42})
    r1 = _run_job("main", view_year=2028)
    r2 = _run_job("main", view_year=2028)
    assert r1["params"]["scenario"] == r2["params"]["scenario"] == "ee"
    assert r2["params"]["growth_2030"] == 1.10
    client.post("/branches/main/scenario", json={"scenario": "ht", "growth_2030": 1.08, "growth_2035": 1.35})
    r_std = _run_job("main", view_year=2028)
    # High grows demand faster than Standard, year for year
    assert r2["years"]["2033"]["growth"] > r_std["years"]["2033"]["growth"]


def test_fresh_load_reads_stored_scenario():
    """On page reload the UI initialises from main's stored scenario, not the hardcoded default."""
    update = client.post("/branches/main/scenario", json={"scenario": "fb", "growth_2030": 1.04, "growth_2035": 1.15}).json()
    assert update["scenario"] == "fb"
    main = _branch("main")
    assert main["scenario"] == "fb" and main["growth_2035"] == 1.15
    r = _run_job("main")
    assert r["params"]["scenario"] == "fb"
    client.post("/branches/main/scenario", json={"scenario": "ht", "growth_2030": 1.08, "growth_2035": 1.35})


def _first(kind):
    m = client.get("/model").json()
    if kind == "line":
        return str(max(m["lines"], key=lambda ln: ln["voltage_kv"])["line_id"])
    return m["generators"][0]["request_id"]


def test_planned_outages_are_studied_in_their_year_and_copy_with_the_branch():
    b = _create("Maintenance", added_projects=[_good()])
    bid = b["branch_id"]
    line = _first("line")
    r = client.post(f"/branches/{bid}/outages", json={"element_kind": "line", "element_id": line,
                                                     "season": "Summer", "year": 2029, "weeks": 6})
    assert r.status_code == 200, r.text
    oid = r.json()["outage_id"]
    assert [o["outage_id"] for o in client.get(f"/branches/{bid}/outages").json()["outages"]] == [oid]

    res = _run_job(bid, view_year=2029)
    assert res["studied"]["outage_ids"] == [oid]
    studies = res["years"]["2029"]["outage_studies"]
    assert [s["outage_id"] for s in studies] == [oid] and studies[0]["cases"] == ["summer_min"]
    assert res["years"]["2030"]["outage_studies"] == []

    # a child branch inherits it; guards: main is read-only, unknown elements are refused
    child = _create("Child", from_branch=bid)["branch_id"]
    assert [o["outage_id"] for o in client.get(f"/branches/{child}/outages").json()["outages"]] == [oid]
    assert client.post("/branches/main/outages", json={"element_kind": "line", "element_id": line,
                                                       "season": "Summer", "year": 2029}).status_code == 409
    assert client.post(f"/branches/{bid}/outages", json={"element_kind": "line", "element_id": "999999",
                                                        "season": "Summer", "year": 2029}).status_code == 422
    assert client.post(f"/branches/{bid}/outages", json={"element_kind": "line", "element_id": line,
                                                        "season": "Monsoon", "year": 2029}).status_code == 422
    assert client.delete(f"/branches/{bid}/outages/{oid}").json()["removed"] is True
    assert client.get(f"/branches/{bid}/outages").json()["outages"] == []


def test_a_generator_outage_can_be_scheduled():
    bid = _create("Gen maintenance")["branch_id"]
    gen = _first("gen")
    r = client.post(f"/branches/{bid}/outages", json={"element_kind": "gen", "element_id": gen,
                                                     "season": "Winter", "year": 2031, "kind": "derate"})
    assert r.status_code == 200, r.text
    res = _run_job(bid)
    assert res["years"]["2031"]["outage_studies"][0]["cases"] == ["winter_peak"]


def test_works_types_are_stored_validated_and_studied():
    """Repowering / replacement windows: the fields round-trip, bad combinations are 422s, and a
    run returns each study's verdict, its combined windows and the repowered element's later years."""
    bid = _create("Works")["branch_id"]
    lines = sorted(client.get("/model").json()["lines"], key=lambda ln: (-ln["voltage_kv"], ln["line_id"]))
    line, other = str(lines[0]["line_id"]), str(lines[1]["line_id"])
    base = {"element_kind": "line", "element_id": line, "season": "Summer", "year": 2029}
    bad = [
        {"work": "rebuild"},
        {"work": "maintenance", "repower": "uprate", "factor": 2.0},
        {"work": "replacement", "factor": 2.0},
        {"work": "replacement", "kind": "derate"},
        {"work": "repowering"},  # no repower
        {"work": "repowering", "repower": "uprate"},  # no factor
        {"work": "repowering", "repower": "uprate", "factor": 1.0},
        {"work": "repowering", "repower": "uprate", "factor": 4.5},
        {"work": "repowering", "repower": "add_parallel", "factor": 2.0},
        {"work": "repowering", "repower": "uprate", "factor": 2.0, "kind": "derate"},
    ]
    for extra in bad:
        assert client.post(f"/branches/{bid}/outages", json={**base, **extra}).status_code == 422, extra

    rp = client.post(f"/branches/{bid}/outages", json={**base, "work": "repowering", "repower": "uprate", "factor": 2.0})
    assert rp.status_code == 200, rp.text
    assert {k: rp.json()[k] for k in ("work", "repower", "factor")} == {"work": "repowering", "repower": "uprate", "factor": 2.0}
    plain = client.post(f"/branches/{bid}/outages", json={**base, "element_id": other})
    assert plain.json()["work"] == "maintenance" and plain.json()["repower"] is None
    rows = {o["outage_id"]: o for o in client.get(f"/branches/{bid}/outages").json()["outages"]}
    assert rows[rp.json()["outage_id"]]["factor"] == 2.0

    res = _run_job(bid, view_year=2029)
    studies = {s["outage_id"]: s for s in res["years"]["2029"]["outage_studies"]}
    a, b = rp.json()["outage_id"], plain.json()["outage_id"]
    assert studies[a]["with_ids"] == [b] and studies[b]["with_ids"] == [a]  # same season and year: studied together
    assert studies[a]["work"] == "repowering" and studies[a]["after"].startswith("from 2030")
    for s in studies.values():
        assert s["verdict"] in ("feasible", "curtailment", "demand_at_risk", "not_feasible")
        assert {"curtailment", "curtailed_mw", "demand_at_risk_mw", "n1_during", "message"} <= s.keys()
    # the uprated line carries the same flow against twice the rating from the following year
    lid = int(line)
    before, after = res["years"]["2029"]["line_loading"][str(lid)], res["years"]["2030"]["line_loading"][str(lid)]
    assert after < before or before == 0


def test_the_outage_table_migrates_from_the_pre_works_schema(tmp_path):
    """An existing scenarios DB (branch_outages without work/repower/factor) gains the columns, and
    its rows read back as maintenance."""
    import duckdb

    from gridforge_api import repository
    from gridforge_api.store import Cursor, migrate

    con = duckdb.connect(str(tmp_path / "old.duckdb"))
    con.execute("CREATE TABLE branch_outages (branch_id VARCHAR, outage_id VARCHAR, element_kind VARCHAR, "
                "element_id VARCHAR, season VARCHAR, year INTEGER, weeks INTEGER, kind VARCHAR, created_at VARCHAR)")
    con.execute("INSERT INTO branch_outages VALUES ('b', 'mw-old', 'line', '0', 'Summer', 2030, 4, 'outage', '2026-01-01')")
    cur = Cursor(con.cursor(), "duckdb")
    migrate(cur)
    migrate(cur)  # idempotent
    assert {"work", "repower", "factor"} <= set(cur.columns("branch_outages"))
    [o] = repository.outages(cur, "b")
    assert (o.work, o.repower, o.factor) == ("maintenance", None, None)
    con.close()


def test_a_reinforcement_on_a_branch_changes_its_result():
    """Try on branch: one more supergrid transformer raises the GSP limit in every year."""
    bid = _create("Reinforced", added_projects=[_good()])["branch_id"]
    before = _run_job(bid)
    r = client.post(f"/branches/{bid}/reinforcements", json={"kind": "gsp", "element_id": 0, "label": "Third SGT"})
    assert r.status_code == 200, r.text
    after = _run_job(bid)
    assert after["studied"]["reinforcements"] and not before["studied"]["reinforcements"]
    lim_b, lim_a = before["years"]["2030"]["gsp_limit_mw"], after["years"]["2030"]["gsp_limit_mw"]
    assert lim_b is not None and lim_a > lim_b
    assert client.post("/branches/main/reinforcements", json={"kind": "gsp", "element_id": 0}).status_code == 409
    rid = r.json()["reinforcement_id"]
    assert client.delete(f"/branches/{bid}/reinforcements/{rid}").json()["removed"] is True


def test_a_demand_connection_is_accepted_at_intake():
    dc = {"applicant": "DC", "bus_id": _stiff_bus(), "technology": "demand", "import_mw": 20.0, "readiness_score": 0.8}
    bid = _create("Data centre", added_projects=[dc])["branch_id"]
    row = next(r for r in client.post(f"/branches/{bid}/optimize", json={}).json()["queue"] if r["technology"] == "demand")
    assert row["status"] != "Rejected" and row["import_mw"] == 20.0


def test_suggestions_can_target_one_project():
    b = _create("Saturated, one target", added_projects=_saturating(5))
    bid = b["branch_id"]
    q = client.post(f"/branches/{bid}/optimize", json={"with_justification": False}).json()
    target = next(x["request_id"] for x in q["queue"] if x["status"] == "Deferred")
    out = client.get(f"/branches/{bid}/suggestions?request_id={target}").json()
    assert out["request_id"] == target
    assert all(target in s["blocked_project_ids"] for s in out["suggestions"])


def test_reinforcements_are_validated():
    bid = _create("Bad lever")["branch_id"]
    assert client.post(f"/branches/{bid}/reinforcements", json={"kind": "trafo", "element_id": 0, "action": "uprate", "factor": 0}).status_code == 422
    assert client.post(f"/branches/{bid}/reinforcements", json={"kind": "line", "element_id": 999999}).status_code == 422
