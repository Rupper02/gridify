"""The harness's stores and plumbing, without a runtime: the study endpoint and cache, the evidence
ledger that binds an agent's finding to a recorded step, the number guard, the budget meter, the
threads store, and the job runner's solver lock."""

import os
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("GRIDFORGE_SCENARIOS_DB", str(Path(tempfile.mkdtemp()) / "scenarios.duckdb"))

import pytest
from fastapi.testclient import TestClient

from gridforge_api import deps
from gridforge_api.agents import threads
from gridforge_api.agents.budget import BudgetMeter
from gridforge_api.agents.evidence import AgentFinding, check_numbers, numbers_in
from gridforge_api.config import WAREHOUSE, now
from gridforge_api.jobs import JobRunner
from gridforge_api.main import app

pytestmark = pytest.mark.skipif(not WAREHOUSE.exists(), reason="pipeline warehouse DB not materialized")

client = TestClient(app)
PROJECT = "nged-bickerfen"


def _wait(job):
    for _ in range(1200):
        if job["status"] not in ("queued", "running"):
            break
        time.sleep(0.25)
        job = client.get(f"/jobs/{job['job_id']}").json()
    assert job["status"] == "done", job.get("error")
    return job["result"]


def test_the_study_catalogue_and_a_study_job_cached_by_the_branch_inputs():
    cat = client.get("/studies").json()["studies"]
    assert {s["kind"] for s in cat} >= {"hosting_capacity", "contingency_ranking", "structural_weak_points", "tap_margin", "gsp_margin_by_year", "data_quality"}
    hosting = next(s for s in cat if s["kind"] == "hosting_capacity")
    assert "bus_ids" in hosting["params_schema"]["properties"] and hosting["cost_hint_solves"] > 0 and not hosting["needs_plan"]
    bid = client.post("/branches", json={"name": "studies"}).json()["branch_id"]
    assert client.post(f"/branches/{bid}/studies/nope", json={}).status_code == 404
    assert client.post(f"/branches/{bid}/studies/hosting_capacity", json={"step_mw": 0}).status_code == 422
    assert client.post(f"/branches/{bid}/studies/gsp_margin_by_year", json={}).status_code == 422  # reads the plan: run first
    r = _wait(client.post(f"/branches/{bid}/studies/structural_weak_points", json={}).json())
    assert r["kind"] == "structural_weak_points" and r["solves"] == 0 and r["not_studied"] and all("fingerprint" in it for it in r["items"])
    assert any(e["kind"] == "study:structural_weak_points" for e in client.get("/cache").json()["entries"])
    t0 = time.perf_counter()
    again = deps.plans.study(bid, "structural_weak_points", {})
    assert again.model_dump() == r and time.perf_counter() - t0 < 2.0  # the cache, not a second study
    # a plan-reading study runs once the branch has
    client.post(f"/branches/{bid}/optimize", json={"with_justification": False})
    g = _wait(client.post(f"/branches/{bid}/studies/gsp_margin_by_year", json={}).json())
    assert [it["year"] for it in g["items"]] == list(range(2026, 2036))


def test_an_agent_finding_is_bound_to_a_recorded_step_and_its_figures_are_the_engines():
    bid = client.post("/branches", json={"name": "evidence"}).json()["branch_id"]
    study = deps.plans.study(bid, "data_quality", {})
    assert study.items, "the builder records assumptions, so the data-quality study has items"
    key = next(k for k, v in deps.plans.cache.compute.items() if v is study)
    run_id, step_id = "run-test-1", "run-test-1:call_1"
    deps.evidence.record_step(run_id=run_id, step_id=step_id, seq=1, tool="study_data_quality", args={"branch_id": bid}, cache_key=key,
                              result={"summary": study.summary, "items": [it.model_dump() for it in study.items[:3]]}, solves=0,
                              started_at=now(), finished_at=now())
    deps.evidence.record_step(run_id=run_id, step_id=step_id, seq=1, tool="study_data_quality", args={"branch_id": bid}, cache_key=key,
                              solves=0, started_at=now(), finished_at=now())  # a replayed step is idempotent
    assert len(deps.evidence.steps(run_id)) == 1
    loaded = deps.evidence.load_step(step_id)
    assert loaded is not None and loaded.study is not None and loaded.study.kind == "data_quality"

    fps = deps.evidence.bind_findings(run_id, bid, [AgentFinding(step_id=step_id, item_index=0, message="The model guesses some ratings; check them.", action="verify the LTDS rows")],
                                      snapshot_id="snap", at=now())
    item = study.items[0]
    assert fps == [item.fingerprint]
    rows = client.get(f"/branches/{bid}/findings").json()["findings"]
    f = next(x for x in rows if x["fingerprint"] == item.fingerprint)
    assert f["source"] == "agent" and f["evidence_kind"] == "tool_call" and f["evidence_ref"] == step_id
    # the figures are the study item's, not the model's words
    assert f["value"] == item.value and f["element_id"] == str(item.element_id) and f["kind"] == "data_quality"
    assert f["message"].startswith("The model guesses") and f["context"]["engine_message"] == item.message
    assert f["evidence"]["cache_key"] == key and f["evidence"]["item_index"] == 0
    # a bad reference is refused, loudly
    with pytest.raises(ValueError):
        deps.evidence.bind_findings(run_id, bid, [AgentFinding(step_id=step_id, item_index=999, message="x")], snapshot_id="s", at=now())
    with pytest.raises(ValueError):
        deps.evidence.bind_findings(run_id, bid, [AgentFinding(step_id="run-test-1:nope", item_index=0, message="x")], snapshot_id="s", at=now())
    with pytest.raises(ValueError):
        deps.evidence.bind_findings("another-run", bid, [AgentFinding(step_id=step_id, item_index=0, message="x")], snapshot_id="s", at=now())
    replay = deps.evidence.replay(step_id)
    assert replay["study"]["kind"] == "data_quality" and replay["stale"] is False and replay["step"]["tool"] == "study_data_quality"


def test_the_number_guard_flags_figures_no_step_produced():
    outputs = [{"items": [{"value": 104.4, "limit": 100.0}], "summary": "line 12 at 104% of its rating"}]
    assert numbers_in("about 104 MW, or 12.5 MW") == [104.0, 12.5]
    assert check_numbers("Line 12 is at 104% of its rating in 2031 (limit 100%).", outputs) == []
    assert check_numbers("It could take 250 MW more.", outputs) == [250.0]
    assert check_numbers("In 2030 two of the three circuits were fine.", outputs) == []  # years and small counts are not figures


def test_the_budget_meter_charges_pauses_and_resumes():
    meter = BudgetMeter(deps.scenarios, daily={"credits": 1.0, "tokens": 1000, "solves": 10})
    st = meter.check("proj-budget")
    assert st.credits == 0 and not st.paused and not st.exhausted
    st = meter.charge("proj-budget", tokens=600, cost_credits=0.4, solves=3)
    assert (st.tokens, st.solves) == (600, 3) and st.credits == pytest.approx(0.4) and not st.exhausted
    st = meter.charge("proj-budget", tokens=500)
    assert st.exhausted and st.paused and st.paused_reason == "budget"
    st = meter.set_paused("proj-budget", True, "operator")
    assert st.paused and st.paused_reason == "operator"
    st = meter.set_paused("proj-budget", False)
    assert st.paused and st.paused_reason == "budget"  # resuming cannot override an exhausted budget
    fresh = meter.set_paused("proj-other", True, "operator")
    assert fresh.paused and not fresh.exhausted and meter.set_paused("proj-other", False).paused is False


def test_threads_and_messages_keep_the_model_history_in_order():
    with deps.scenarios.cursor() as con:
        t = threads.create_thread(con, PROJECT, "main", "hosting at Boston")
        assert t["kind"] == "ask" and threads.list_threads(con, PROJECT)[0]["thread_id"] == t["thread_id"]
        u = threads.add_message(con, t["thread_id"], "user", "Where can 20 MW connect?")
        a = threads.add_message(con, t["thread_id"], "assistant", "", status="queued")
        assert threads.streaming_in(con, t["thread_id"])
        a2 = threads.set_message(con, a["message_id"], status="done", content="At Boston: about 20 MW.", tool_trace=[{"t": "tool_call", "tool": "study_hosting_capacity"}],
                                 model_messages=[{"kind": "request"}, {"kind": "response"}], usage={"input_tokens": 10}, evidence={"steps": ["s1"]})
        assert a2["status"] == "done" and a2["tool_trace"][0]["tool"] == "study_hosting_capacity" and a2["evidence"] == {"steps": ["s1"]}
        assert [m["seq"] for m in threads.messages(con, t["thread_id"])] == [1, 2] and u["seq"] == 1
        assert threads.history(con, t["thread_id"]) == [{"kind": "request"}, {"kind": "response"}]
        assert threads.history(con, t["thread_id"], before_seq=2) == []
        assert not threads.streaming_in(con, t["thread_id"])


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
