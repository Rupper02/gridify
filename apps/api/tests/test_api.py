"""API tests: the branch workflow through the FastAPI TestClient, limited to what must never break: the cache keys,
the job path, the diff, and "main changes only by merging".

Grid-agnostic: bus ids and years come from the live /model and the plan config, and no test asserts what a connection
does to the grid. The tests that merge into main come last: main is shared state."""

from gridify_optimizer.years import PLAN_YEARS

from _support import add_connection, branch, client, connection, create_branch, requires_warehouse, run, wait_job

pytestmark = requires_warehouse


def test_branches_with_different_connections_do_not_share_cached_results(solved_branch):
    other = create_branch("Other connections")["branch_id"]
    add_connection(other, connection(name="Other", rating_mw=2.0))
    a, b = run(solved_branch), run(other)
    assert a["run_key"] != b["run_key"]
    assert list(a["years"]) == [str(y) for y in PLAN_YEARS]


def test_a_job_returns_what_the_sync_run_does_and_the_diff_reads_it(solved_branch):
    job = client.post(f"/branches/{solved_branch}/run", json={}).json()
    assert job["job_id"].startswith("job-")
    j = wait_job(job)
    assert j["stage"] == "done" and j["fraction"] == 1.0
    assert j["result"]["years"] == run(solved_branch)["years"]
    d = client.get(f"/branches/{solved_branch}/diff").json()
    assert d["base"] == "main" and list(d["years"]) == [str(y) for y in PLAN_YEARS]
    assert client.get("/jobs/job-nope").status_code == 404


def test_an_edit_makes_the_result_unsolved_until_the_next_run():
    bid = create_branch("Edit me")["branch_id"]
    rid = add_connection(bid, connection())["request_id"]
    assert client.get(f"/branches/{bid}/result").status_code == 409  # never run
    run(bid)
    assert client.get(f"/branches/{bid}/result").status_code == 200
    assert client.patch(f"/branches/{bid}/connections/{rid}", json={"year": max(PLAN_YEARS)}).status_code == 200
    r = client.get(f"/branches/{bid}/result")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_solved"


def test_a_connection_is_validated():
    bid = create_branch("Validation")["branch_id"]
    bad_bus = max(b["bus_id"] for b in client.get("/model").json()["buses"]) + 10_000
    assert client.post(f"/branches/{bid}/connections", json=connection(bus_id=bad_bus)).status_code == 422
    assert client.post(f"/branches/{bid}/connections", json=connection(year=None)).status_code == 422
    assert client.post(f"/branches/{bid}/connections", json=connection(year=max(PLAN_YEARS) + 1)).status_code == 422


def test_a_registry_project_is_placed_with_its_own_year():
    """Regression: the request's year was required, so pulling a project from the registry (which sends only its id)
    was refused with 422 and the planner's "+" did nothing."""
    project = next(r for r in client.get("/registry").json() if r["bus_id"] is not None and r["year"] is not None)
    bid = create_branch("Registry")["branch_id"]
    placed = add_connection(bid, {"from_registry": project["request_id"]})
    assert placed["request_id"] == project["request_id"] and placed["year"] == project["year"]


def test_a_technology_is_stored_as_the_engine_reads_it():
    """Regression: " Solar " was stored as sent and ran as firm generation at winter peak."""
    bid = create_branch("Technology case")["branch_id"]
    assert add_connection(bid, connection(technology=" Solar "))["technology"] == "solar"


def test_a_run_and_a_year_run_refuse_a_year_outside_the_plan():
    bid = create_branch("Years")["branch_id"]
    assert client.post(f"/branches/{bid}/run", json={"view_year": max(PLAN_YEARS) + 1}).status_code == 422
    assert client.post(f"/branches/{bid}/year-run", json={"year": min(PLAN_YEARS) - 1, "pathway": "ht"}).status_code == 422


def test_main_is_changed_only_by_merging():
    assert client.post("/branches/main/connections", json=connection()).status_code == 409
    # the demand profile on main stays editable (the profile picker)
    main = branch("main")
    assert client.post("/branches/main/profile", json={"scenario": main["scenario"]}).status_code == 200
    assert client.post("/branches/main/profile", json={"scenario": "nope"}).status_code == 422


def test_a_branch_merges_into_main_and_is_history_after():
    bid = create_branch("To merge")["branch_id"]
    rid = add_connection(bid, connection(name="MergeMe"))["request_id"]
    merged = client.post(f"/branches/{bid}/merge")
    assert merged.status_code == 200, merged.text
    assert rid in {c["request_id"] for c in client.get("/branches/main/connections").json()}  # main adopted the branch's connections
    assert branch(bid)["status"] == "merged"
    assert client.post(f"/branches/{bid}/merge").status_code == 409
    assert client.post(f"/branches/{bid}/discard").status_code == 409  # a merged branch is history


def test_discard_and_main_guard():
    bid = create_branch("To discard")["branch_id"]
    assert client.post(f"/branches/{bid}/discard").json()["discarded"] == bid
    assert client.post(f"/branches/{bid}/discard").status_code == 409  # not open any more
    assert client.post("/branches/main/discard").status_code == 409
    assert client.post("/branches/main/merge").status_code == 409


def test_a_branch_opened_before_another_merge_cannot_undo_it():
    """Regression: merging a branch whose parent had changed since it was opened replaced the parent's connections
    with its own, silently dropping what the other branch had merged."""
    first = create_branch("First")["branch_id"]
    second = create_branch("Second")["branch_id"]
    rid_first = add_connection(first, connection(name="First"))["request_id"]
    rid_second = add_connection(second, connection(name="Second"))["request_id"]
    assert client.post(f"/branches/{first}/merge").status_code == 200
    refused = client.post(f"/branches/{second}/merge")
    assert refused.status_code == 409, refused.text
    on_main = {c["request_id"] for c in client.get("/branches/main/connections").json()}
    assert rid_first in on_main and rid_second not in on_main
    assert branch(second)["status"] == "open"  # nothing changed: it can be redone on a fresh branch
