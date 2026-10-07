"""The harness's stores and plumbing, without a runtime: the study endpoint and cache, the evidence
ledger that binds an agent's finding to a recorded step, the number guard, the spend meter, and the
job runner's solver lock."""

import threading
import time

import pytest

from gridforge_api import deps
from gridforge_api.agents.spend import SpendMeter
from gridforge_api.agents.evidence import check_numbers, numbers_in
from gridforge_api.config import NGED_PROJECT_ID, now
from gridforge_optimizer.years import PLAN_YEARS
from gridforge_api.jobs import JobRunner
from _support import client, project, requires_warehouse, wait_job

pytestmark = requires_warehouse

PROJECT = NGED_PROJECT_ID


def test_the_study_catalogue_and_a_study_job_cached_by_the_branch_inputs():
    cat = client.get("/studies").json()["studies"]
    assert {s["kind"] for s in cat} >= {"hosting_capacity", "contingency_ranking", "structural_weak_points", "tap_margin", "gsp_margin_by_year", "data_quality"}
    hosting = next(s for s in cat if s["kind"] == "hosting_capacity")
    assert "bus_ids" in hosting["params_schema"]["properties"] and hosting["cost_hint_solves"] > 0 and not hosting["needs_plan"]
    # a branch with its own project, so no earlier run of main can have cached its plan
    bid = client.post("/branches", json={"name": "studies", "from_branch": "main", "added_projects": [project(applicant="Studies")]}).json()["branch_id"]
    assert client.post(f"/branches/{bid}/studies/nope", json={}).status_code == 404
    assert client.post(f"/branches/{bid}/studies/hosting_capacity", json={"step_mw": 0}).status_code == 422
    assert client.post(f"/branches/{bid}/studies/gsp_margin_by_year", json={}).status_code == 422  # reads the plan: run first
    r = wait_job(client.post(f"/branches/{bid}/studies/structural_weak_points", json={}).json())["result"]
    assert r["kind"] == "structural_weak_points" and r["solves"] == 0 and r["not_studied"] and all("fingerprint" in it for it in r["items"])
    assert any(e["kind"] == "study:structural_weak_points" for e in client.get("/cache").json()["entries"])
    t0 = time.perf_counter()
    again = deps.plans.study(bid, "structural_weak_points", {})
    assert again.model_dump() == r and time.perf_counter() - t0 < 2.0  # the cache, not a second study
    # a plan-reading study runs once the branch has a plan: main's, which the suite has solved already
    client.post("/optimize", json={"with_justification": False})
    g = wait_job(client.post("/branches/main/studies/gsp_margin_by_year", json={}).json())["result"]
    assert [it["year"] for it in g["items"]] == list(PLAN_YEARS)


def test_the_number_guard_flags_figures_no_step_produced():
    outputs = [{"items": [{"value": 104.4, "limit": 100.0}], "summary": "line 12 at 104% of its rating"}]
    assert numbers_in("about 104 MW, or 12.5 MW") == [104.0, 12.5]
    assert check_numbers("Line 12 is at 104% of its rating in 2031 (limit 100%).", outputs) == []
    assert check_numbers("It could take 250 MW more.", outputs) == [250.0]
    assert check_numbers("In 2030 two of the three circuits were fine.", outputs) == []  # years and small counts are not figures


def test_the_spend_meter_adds_up_never_pauses_and_the_operator_pauses_and_resumes():
    meter = SpendMeter(deps.scenarios)
    st = meter.check("proj-spend")
    assert st.credits == 0 and not st.paused
    meter.charge("proj-spend", tokens=600, cost_credits=0.4, solves=3)
    st = meter.charge("proj-spend", tokens=5_000_000, cost_credits=50.0)  # no cap: spend is shown, never a stop
    assert (st.tokens, st.solves) == (5_000_600, 3) and st.credits == pytest.approx(50.4) and st.total_credits == pytest.approx(50.4)
    assert not st.paused
    st = meter.set_paused("proj-spend", True, "operator")
    assert st.paused and st.paused_reason == "operator"
    assert meter.set_paused("proj-spend", False).paused is False


def test_the_job_runner_takes_the_solver_lock_and_reports_busy():
    lock = threading.RLock()
    jobs = JobRunner(lock)
    assert not jobs.busy()
    started, release = threading.Event(), threading.Event()

    def slow(progress, _publish):
        started.set()
        release.wait(5)
        return {"ok": True}

    job = jobs.start("test", slow)
    assert started.wait(5) and jobs.busy()
    assert not lock.acquire(blocking=False), "the job holds the solver lock while it runs"
    release.set()
    for _ in range(100):
        if jobs.get(job["job_id"])["status"] == "done":
            break
        time.sleep(0.05)
    assert jobs.get(job["job_id"])["status"] == "done" and not jobs.busy()
    assert lock.acquire(blocking=False)
    lock.release()
    jobs.shutdown()
