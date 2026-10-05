"""API tests: the branch / pull-request workflow through the FastAPI TestClient, limited to what must
never break: the diff, the cache keys, the merge gate, the findings ledger and "main changes only by
merging".

Grid-agnostic: bus ids and years come from the live /model and the plan config, and no test asserts which
project connects (a plain `project()` has whatever outcome the engine gives it; `broken_project()` always
fails intake). A solve of a branch that has not been run costs 25-40 s, so the tests share the
`project_branch` fixture (conftest.py), solved once, and put back whatever they edit. The tests that merge
into main come last: main is shared state."""

from gridforge_optimizer.config import PLAN_END_YEAR, PLAN_START_YEAR
from gridforge_optimizer.findings import against_recommendation
from gridforge_optimizer.years import PLAN_YEARS

from _support import add_project, another_bus, branch, broken_project, client, create_branch, first_line, project, projects, requires_warehouse, run, run_job, stiff_bus, wait_job

pytestmark = requires_warehouse

MID_YEAR = PLAN_START_YEAR + 3  # an interior plan year for works windows (the engine studies it, and the one after)

_VERDICTS = {"feasible", "curtailment", "demand_at_risk", "not_feasible"}


# --- branches, the diff, the cache ---------------------------------------------------------------------------------
def test_branch_diff_is_year_aware_and_compares_planned_works_with_main():
    """The diff carries the added project, every plan year (lines, transformers, GSP, N-1) and each branch
    window's verdict on main's plan vs the branch's; the extra study on main's plan is cached durably."""
    from gridforge_api.deps import cache

    bid = create_branch("Year diff", added_projects=projects(4))["branch_id"]
    oid = client.post(f"/branches/{bid}/outages", json={"element_kind": "line", "element_id": first_line(),
                                                       "season": "Summer", "year": PLAN_END_YEAR}).json()["outage_id"]
    d = client.get(f"/branches/{bid}/diff").json()
    assert d["base_branch"] == "main" and d["head_branch"] == bid
    assert [p for p in d["projects"] if p["change"] == "added"]  # the new projects show up as additions
    assert sorted(d["years"]) == [str(y) for y in PLAN_YEARS]
    y35 = d["years"][str(PLAN_END_YEAR)]  # the last plan year
    for k in ("worst_line_delta", "worst_trafo_delta", "gsp_export_delta", "n1_findings_delta",
              "newly_overloaded_trafo_ids", "top_line_deltas", "top_trafo_deltas", "energised_only_head"):
        assert k in y35, k
    connected = {p["request_id"] for p in d["projects"] if p["head_status"] in ("Phase1", "Phase2")}
    assert set(y35["energised_only_head"]) <= connected and (not connected or y35["energised_only_head"])
    assert all({"element_id", "base_pct", "head_pct", "delta", "crossed"} <= t.keys() for t in y35["top_trafo_deltas"])
    assert d["phases"] and "mw_2030_delta" in d["headline"]

    [w] = d["works"]
    assert w["outage_id"] == oid and w["year"] == PLAN_END_YEAR
    assert w["verdict_on_main"] in _VERDICTS and w["verdict_on_branch"] in _VERDICTS
    assert w["change"] in ("worse", "better", "unchanged") and w["consequence"].endswith(".")
    assert any(e["kind"] == "works" for e in client.get("/cache").json()["entries"])
    # a "restart": the diff (queue, years and the works study on main's plan) comes from the durable cache
    cache.clear()
    assert client.get(f"/branches/{bid}/diff").json()["works"] == d["works"]


def test_the_diff_previews_what_a_merge_adds_to_and_removes_from_the_parent():
    """Merge replaces the parent's planned works and reinforcements with the branch's: the diff says
    which it adds and which it removes, and the merge does exactly that (into a branch, so main and
    the other tests are untouched)."""
    line = first_line()
    parent = create_branch("Merge parent")["branch_id"]
    kept = client.post(f"/branches/{parent}/outages", json={"element_kind": "line", "element_id": line,
                                                            "season": "Summer", "year": PLAN_START_YEAR + 1}).json()["outage_id"]
    gone = client.post(f"/branches/{parent}/outages", json={"element_kind": "line", "element_id": line,
                                                            "season": "Winter", "year": PLAN_START_YEAR + 2}).json()["outage_id"]
    child = create_branch("Merge child", from_branch=parent)["branch_id"]
    assert {o["outage_id"] for o in client.get(f"/branches/{child}/outages").json()["outages"]} == {kept, gone}
    assert client.delete(f"/branches/{child}/outages/{gone}").status_code == 200
    new = client.post(f"/branches/{child}/outages", json={"element_kind": "line", "element_id": line,
                                                          "season": "Spring", "year": PLAN_START_YEAR + 3}).json()["outage_id"]
    rid = client.post(f"/branches/{child}/reinforcements", json={"kind": "line", "element_id": int(line), "action": "uprate", "factor": 2.0, "label": "Uprate"}).json()["reinforcement_id"]

    m = client.get(f"/branches/{child}/diff").json()["on_merge"]
    assert [w["outage_id"] for w in m["works_added"]] == [new]
    assert [w["outage_id"] for w in m["works_removed"]] == [gone]
    assert [r["reinforcement_id"] for r in m["reinforcements_added"]] == [rid] and not m["reinforcements_removed"]
    assert m["works_added"][0]["season"] == "Spring" and "created_at" not in m["works_added"][0]

    # the gate: both sides must be run, and a removed window is a warning the operator acknowledges
    run(child)
    run(parent)
    refused = client.post(f"/branches/{child}/merge", json={"into": parent})
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "warnings_unacknowledged"
    assert "proposals_removed" in {w["kind"] for w in refused.json()["detail"]["verdict"]["warnings"]}
    assert client.post(f"/branches/{child}/merge", json={"into": parent, "acknowledge": True}).status_code == 200
    assert {o["outage_id"] for o in client.get(f"/branches/{parent}/outages").json()["outages"]} == {kept, new}
    assert [r["reinforcement_id"] for r in client.get(f"/branches/{parent}/reinforcements").json()["reinforcements"]] == [rid]


def test_branches_with_different_projects_do_not_share_cached_results(project_branch):
    # regression: the cache must key on the candidate set, not just the scenario params
    other = create_branch("Other projects", added_projects=projects(3))["branch_id"]
    ids = lambda bid: {x["request_id"] for x in run(bid)["queue"]}  # noqa: E731
    assert ids(project_branch) != ids(other)  # each branch sees its own projects, never the other's cached run


def test_results_are_cached_durably_and_keyed_by_engine(project_branch):
    from gridforge_api.deps import cache

    first = run(project_branch)
    stats = client.get("/cache").json()
    assert stats["engine"] == cache.engine and any(e["kind"] == "optimize" and e["engine"] == cache.engine for e in stats["entries"])
    cache.clear()  # a "restart": the in-process caches are gone, the stored row is not
    assert run(project_branch)["queue"] == first["queue"]  # read back from the durable cache


# --- jobs -----------------------------------------------------------------------------------------------------------
def test_background_job_runs_a_branch_and_reports_progress(project_branch):
    job = client.post(f"/branches/{project_branch}/optimize/jobs", json={"with_justification": False}).json()
    assert job["status"] in ("queued", "running", "done") and job["job_id"].startswith("job-")
    j = wait_job(job)
    assert j["stage"] == "done" and j["fraction"] == 1.0 and j["elapsed_ms"] >= 0
    assert j["result"]["queue"] == run(project_branch)["queue"]  # the job returns exactly what the sync endpoint does
    assert client.get("/jobs/job-nope").status_code == 404


# --- schedules --------------------------------------------------------------------------------------------------------
def test_a_schedule_persists_changes_no_verdict_and_is_reported_against_the_recommendation(project_branch):
    bid = project_branch
    item = run(bid)["queue"][0]
    rid, status = item["request_id"], item["status"]
    assert item["scheduled_year"] is None
    try:
        for year in (PLAN_START_YEAR, PLAN_END_YEAR):
            assert client.post(f"/branches/{bid}/schedule", json={"request_id": rid, "year": year}).status_code == 200
            it = next(x for x in run(bid)["queue"] if x["request_id"] == rid)
            assert it["scheduled_year"] == year
            assert it["status"] == status  # scheduling never changes the verdict
            assert it["against_recommendation"] == against_recommendation(it["recommended_year"], year)
    finally:
        client.post(f"/branches/{bid}/schedule", json={"request_id": rid, "year": None})
    it = next(x for x in run(bid)["queue"] if x["request_id"] == rid)
    assert it["scheduled_year"] is None and it["against_recommendation"] is False

    # guards: a year outside the plan, a project not on the branch
    assert client.post(f"/branches/{bid}/schedule", json={"request_id": rid, "year": PLAN_END_YEAR + 1}).status_code == 422
    assert client.post(f"/branches/{bid}/schedule", json={"request_id": "NOPE", "year": PLAN_END_YEAR}).status_code == 404


# --- projects on a branch ----------------------------------------------------------------------------------------------
def test_a_project_on_a_branch_can_be_changed_and_is_re_triaged():
    """An agent's approved proposal or the operator's edit: the point of connection, the rating, the import or the year."""
    from gridforge_api import deps, repository

    bid = create_branch("Change", added_projects=[project(applicant="Changer")])["branch_id"]
    with deps.scenarios.cursor() as con:
        rid = repository.candidate_rows(con, bid)[0]["request_id"]
    new_bus = another_bus(stiff_bus())
    r = client.patch(f"/branches/{bid}/candidates/{rid}", json={"bus_id": new_bus, "rating_mw": 7.5})
    assert r.status_code == 200, r.text
    assert r.json()["bus_id"] == new_bus and r.json()["rating_mw"] == 7.5 and r.json()["status"] == "valid" and r.json()["request_id"] == rid
    assert client.patch(f"/branches/{bid}/candidates/{rid}", json={"rating_mw": 0}).json()["status"] == "rejected"  # re-triaged: out of range
    assert client.patch(f"/branches/{bid}/candidates/{rid}", json={"rating_mw": 7.5}).json()["status"] == "valid"
    assert client.patch(f"/branches/{bid}/candidates/CR-nope", json={"bus_id": new_bus}).status_code == 404
    assert client.patch(f"/branches/main/candidates/{rid}", json={"bus_id": new_bus}).status_code == 409
    assert client.patch(f"/branches/{bid}/candidates/{rid}", json={"rating_mw": -1}).status_code == 422


# --- planned works ----------------------------------------------------------------------------------------------------
def test_works_types_are_stored_validated_and_studied():
    """Repowering / replacement windows: the fields round-trip, bad combinations are 422s, and a
    run returns each study's verdict, its combined windows and the repowered element's later years."""
    bid = create_branch("Works")["branch_id"]
    lines = sorted(client.get("/model").json()["lines"], key=lambda ln: (-ln["voltage_kv"], ln["line_id"]))
    line, other = str(lines[0]["line_id"]), str(lines[1]["line_id"])
    base = {"element_kind": "line", "element_id": line, "season": "Summer", "year": MID_YEAR}
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

    res = run_job(bid, view_year=MID_YEAR)
    studies = {s["outage_id"]: s for s in res["years"][str(MID_YEAR)]["outage_studies"]}
    a, b = rp.json()["outage_id"], plain.json()["outage_id"]
    assert studies[a]["with_ids"] == [b] and studies[b]["with_ids"] == [a]  # same season and year: studied together
    assert studies[a]["work"] == "repowering" and studies[a]["after"].startswith(f"from {MID_YEAR + 1}")
    for s in studies.values():
        assert s["verdict"] in _VERDICTS
        assert {"curtailment", "curtailed_mw", "demand_at_risk_mw", "n1_during", "message"} <= s.keys()
    # the uprated line carries the same flow against twice the rating from the following year
    lid = int(line)
    before, after = res["years"][str(MID_YEAR)]["line_loading"][str(lid)], res["years"][str(MID_YEAR + 1)]["line_loading"][str(lid)]
    assert after < before or before == 0


# --- the findings ledger ------------------------------------------------------------------------------------------------
def test_a_run_writes_findings_and_a_rerun_upserts_and_resolves():
    """The ledger, on a finding every grid produces: a project that fails intake is recorded (info), a re-run
    keeps the same row, acknowledging it takes it out of the open list, and fixing the project resolves it."""
    bid = create_branch("Ledger")["branch_id"]
    added = add_project(bid, broken_project())
    assert added["status"] == "rejected"
    rid = added["request_id"]
    run(bid)
    fs = client.get(f"/branches/{bid}/findings").json()
    assert fs["branch_id"] == bid and fs["counts"]["open"] > 0
    f = next(x for x in fs["findings"] if x["kind"] == "rejected" and x["element_id"] == rid)
    assert f["source"] == "engine" and f["status"] == "open" and f["severity"] == "info"
    assert f["evidence_kind"] == "result_cache" and f["evidence"]["years_key"] == f["evidence_ref"] and f["evidence"]["engine"]
    sev = [x["severity"] for x in fs["findings"]]
    assert sev == sorted(sev, key=lambda s: {"breach": 0, "warn": 1, "info": 2}[s])  # breaches first, then warnings
    ids = {x["finding_id"] for x in fs["findings"]}

    run(bid)  # the same run again: the same rows, no duplicates
    assert {x["finding_id"] for x in client.get(f"/branches/{bid}/findings").json()["findings"]} == ids

    acked = client.post(f"/findings/{f['finding_id']}/ack", json={"note": "known: fix the bus"}).json()
    assert acked["status"] == "acknowledged" and acked["acked_at"] and acked["note"]
    assert f["finding_id"] not in {x["finding_id"] for x in client.get(f"/branches/{bid}/findings?status=open").json()["findings"]}
    assert f["finding_id"] in {x["finding_id"] for x in client.get(f"/branches/{bid}/findings?status=acknowledged").json()["findings"]}

    assert client.patch(f"/branches/{bid}/candidates/{rid}", json={"bus_id": stiff_bus()}).json()["status"] == "valid"
    run(bid)  # fixed: the finding is resolved on the next run
    assert f["finding_id"] in {x["finding_id"] for x in client.get(f"/branches/{bid}/findings?status=resolved").json()["findings"]}
    assert client.post("/findings/f-nope/ack", json={}).status_code == 404
    assert client.get(f"/branches/{bid}/findings?status=bogus").status_code == 422
    assert client.get("/branches/nope/findings").status_code == 404


# --- from here on: tests that touch main (merging into it). Keep them last. -------------------------------------
def test_main_is_changed_only_by_merging():
    """Projects, schedules, works and reinforcements go on branches; main takes them through the gate."""
    assert client.post("/optimize/candidates", json={**project(), "branch_id": "main"}).status_code == 409
    reg = client.get("/registry").json()[0]["request_id"]  # the built-in project's registry (an imported grid has none)
    assert client.post("/branches/main/registry", json={"request_id": reg}).status_code == 409
    assert client.post("/branches/main/schedule", json={"request_id": "x", "year": PLAN_END_YEAR}).status_code == 409
    # the demand profile on main stays editable (the profile picker), and must be a proper body
    main = branch("main")
    r = client.post("/branches/main/scenario", json={"scenario": main["scenario"], "growth_2030": main["growth_2030"], "growth_2035": main["growth_2035"]})
    assert r.status_code == 200 and r.json()["branch_id"] == "main"
    assert client.post("/branches/main/scenario", json={"scenario": main["scenario"]}).status_code == 422


def test_merge_check_goes_stale_when_an_input_changes_and_fresh_again_when_it_is_put_back(project_branch):
    """Freshness comes from the cache keys: a branch not solved for its current inputs cannot merge."""
    bid = project_branch
    run(bid)
    run("main")
    mc = client.get(f"/branches/{bid}/merge-check").json()
    assert mc["fresh"] is True and mc["into"] == "main" and mc["branch_status"] == "open"
    assert mc["verdict"]["years_compared"] == list(PLAN_YEARS)
    assert not any(b["kind"] == "stale" for b in mc["verdict"]["blockers"])
    assert mc["evidence"]["engine"] and mc["evidence"]["head_years_key"]

    # a planned works window changes what the years depend on (on any grid): stale until the next run, fresh again once it is removed
    oid = client.post(f"/branches/{bid}/outages", json={"element_kind": "line", "element_id": first_line(), "season": "Summer", "year": MID_YEAR}).json()["outage_id"]
    try:
        mc = client.get(f"/branches/{bid}/merge-check").json()
        assert mc["fresh"] is False and {b["kind"] for b in mc["verdict"]["blockers"]} == {"stale"}
        assert "works windows" in mc["stale_reasons"][0]
    finally:
        client.delete(f"/branches/{bid}/outages/{oid}")
    assert client.get(f"/branches/{bid}/merge-check").json()["fresh"] is True


def test_a_branch_merges_into_main_only_once_run_and_is_history_after():
    # the branch's one change is a project that fails intake: it cannot introduce a problem on any grid, so the gate passes
    bid = create_branch("To merge")["branch_id"]
    rid = add_project(bid, broken_project(applicant="MergeMe"))["request_id"]
    mc = client.get(f"/branches/{bid}/merge-check").json()  # never run: stale, and the merge is refused
    assert mc["fresh"] is False and mc["verdict"]["ok"] is False
    assert mc["verdict"]["blockers"][0]["kind"] == "stale" and mc["stale_reasons"]
    refused = client.post(f"/branches/{bid}/merge", json={"into": "main"})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "blocked" and refused.json()["detail"]["fresh"] is False

    run(bid)
    run("main")
    mc = client.get(f"/branches/{bid}/merge-check").json()
    assert mc["fresh"] is True and mc["verdict"]["ok"] is True, mc["verdict"]["summary"]
    merged = client.post(f"/branches/{bid}/merge", json={"into": "main"})
    assert merged.status_code == 200, merged.text
    assert merged.json()["branch_id"] == "main"
    assert rid in {c["request_id"] for c in client.get("/branches/main/candidates").json()}  # main adopted the branch's projects

    assert branch(bid)["status"] == "merged"
    assert client.post(f"/branches/{bid}/merge", json={"into": "main"}).status_code == 409
    assert client.post(f"/branches/{bid}/discard").status_code == 409  # a merged branch is history


def test_discard_and_main_guard():
    bid = create_branch("To discard")["branch_id"]
    assert client.post(f"/branches/{bid}/discard").json()["status"] == "discarded"
    assert client.post(f"/branches/{bid}/discard").status_code == 409  # not open any more
    assert client.post("/branches/main/discard").status_code == 400
    assert client.post("/branches/main/merge", json={"into": "main"}).status_code == 400


