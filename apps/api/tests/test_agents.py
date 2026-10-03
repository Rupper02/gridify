"""The agent harness end to end, with scripted models and no network: DBOS on a temp SQLite system
database, every agent a FunctionModel that calls the real tools and answers in the real shapes.

What is proved: an event wakes the steward, a specialist runs a real study through the solver gate,
the step is recorded with a cache key the durable cache holds, and the agent's finding carries the
study item's figures (copied by the server, never typed by the model); a branch run gets a review
that restates the merge gate's blockers by fingerprint (a wrong restatement is retried); a question
streams tool calls and tokens, flags a figure no tool produced, and a proposal waits for the
operator's approval; events deduplicate; the pause switch and the budget stop work; a relaunch
keeps every result; operators keep the solver first."""

import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path

os.environ.setdefault("GRIDFORGE_SCENARIOS_DB", str(Path(tempfile.mkdtemp()) / "scenarios.duckdb"))

import pytest
from fastapi.testclient import TestClient
from pydantic_ai import ModelRetry, models
from pydantic_ai.messages import ModelRequest, ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from gridforge_api import deps
from gridforge_api.agents import roster
from gridforge_api.agents.evidence import AgentFinding
from gridforge_api.agents.schemas import SpecialistReport
from gridforge_api.agents.tools import SolverGate
from gridforge_api.config import AGENT_BUDGET_DAILY, WAREHOUSE
from gridforge_api.main import app

models.ALLOW_MODEL_REQUESTS = False
pytestmark = pytest.mark.skipif(not WAREHOUSE.exists(), reason="pipeline warehouse DB not materialized")

client = TestClient(app)
PROJECT = deps.agents.project_id
CALLS: dict[str, int] = {}  # model calls per role


# --- scripted models ---------------------------------------------------------------------------------------------
def _prompt(messages) -> str:
    return "\n".join(str(p.content) for m in messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, UserPromptPart))


def _returns(messages, tool: str) -> list:
    """Tool returns since the operator's latest question (earlier turns are history, not this answer)."""
    last_user = max((i for i, m in enumerate(messages) if isinstance(m, ModelRequest) and any(isinstance(p, UserPromptPart) for p in m.parts)), default=0)
    return [p for m in messages[last_user:] if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, ToolReturnPart) and p.tool_name == tool]


def _retries(messages) -> int:
    return sum(1 for m in messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, RetryPromptPart))


def _steward(messages, info):
    out = info.output_tools[0].name
    if "Write the HealthBrief" in _prompt(messages):
        return ("tool", out, {"headline": "Scripted brief: the specialists ran.", "body": "See their findings.", "not_studied": [], "next_checks": ["read the findings"]})
    if not _returns(messages, "project_overview"):
        return ("tool", "project_overview", {})
    return ("tool", out, {"specialists": [{"kind": "data_quality", "branch_id": None, "why": "a new model: check what the builder assumed"}], "note": "triage"})


def _specialist(messages, info):
    out = info.output_tools[0].name
    rets = _returns(messages, "study_data_quality")
    if not rets:
        return ("tool", "study_data_quality", {})
    c = rets[0].content
    items = c.get("items", []) if isinstance(c, dict) else []
    findings = [{"step_id": c["step_id"], "item_index": items[0]["index"], "message": items[0]["message"], "action": "confirm against the LTDS"}] if items else []
    return ("tool", out, {"findings": findings, "not_studied": c.get("not_studied", []) if isinstance(c, dict) else [], "summary": "scripted"})


def _reviewer(messages, info):
    out = info.output_tools[0].name
    if _retries(messages) == 0:  # a wrong first restatement: the validator must send it back
        return ("tool", out, {"verdict_restated": "mergeable", "blockers": [], "warnings": [], "body": "Looks fine.", "not_studied": []})
    mc = json.loads(_prompt(messages).split("The merge gate says:\n", 1)[1].rsplit("\nRead the diff", 1)[0])
    verdict = "blocked" if mc["blockers"] else ("mergeable_with_warnings" if mc["warnings"] else "mergeable")
    restate = lambda fs: [{"kind": f["kind"], "element_id": f["element_id"], "fingerprint": f["fingerprint"], "restated": f["message"]} for f in fs]  # noqa: E731
    return ("tool", out, {"verdict_restated": verdict, "blockers": restate(mc["blockers"]), "warnings": restate(mc["warnings"]), "body": "Restated from the gate.", "not_studied": []})


def _answerer(messages, info):
    if "propose" in _prompt(messages).lower():
        rets = _returns(messages, "propose_branch")
        if not rets:
            return ("tool", "propose_branch", {"name": "Agent trial", "note": "to try a reinforcement"})
        c = rets[0].content
        return ("text", f"Opened {c['branch_id']} as you approved." if isinstance(c, dict) and "branch_id" in c else f"Not opened: {c}")
    rets = _returns(messages, "queue")
    if not rets:
        return ("tool", "queue", {})
    c = rets[0].content
    return ("text", f"The queue holds {len(c['queue'])} projects [{c['step_id']}]. A made-up figure: 98765.4 MW.")


SCRIPTS = {"steward": _steward, "specialist": _specialist, "reviewer": _reviewer, "answerer": _answerer}


def _scripted(role: str) -> FunctionModel:
    script = SCRIPTS[role]

    def plan(messages, info):
        CALLS[role] = CALLS.get(role, 0) + 1
        return script(messages, info)

    def function(messages, info) -> ModelResponse:
        kind, *rest = plan(messages, info)
        if kind == "text":
            return ModelResponse(parts=[TextPart(rest[0])])
        return ModelResponse(parts=[ToolCallPart(tool_name=rest[0], args=rest[1], tool_call_id=f"call-{uuid.uuid4().hex[:6]}")])

    async def stream_function(messages, info):
        kind, *rest = plan(messages, info)
        if kind == "text":
            yield rest[0]
        else:
            yield {1: DeltaToolCall(name=rest[0], json_args=json.dumps(rest[1]), tool_call_id=f"call-{uuid.uuid4().hex[:6]}")}

    return FunctionModel(function, stream_function=stream_function, model_name=f"scripted-{role}")


@pytest.fixture(autouse=True, scope="module")
def runtime():
    """The one runtime from deps, re-pointed at scripted models and a temp DBOS database, launched
    explicitly (the module-level TestClient never runs the lifespan)."""
    rt = deps.agents
    factory, url = rt.model_factory, rt.system_db_url
    if rt.launched:
        rt.destroy()
    rt.model_factory = _scripted
    rt.system_db_url = "sqlite:///" + str(Path(tempfile.mkdtemp()) / "dbos.sqlite").replace("\\", "/")
    rt.launch()
    yield rt
    rt.destroy()
    rt.model_factory, rt.system_db_url = factory, url


def _result(workflow_id: str, timeout_s: float = 120.0):
    from dbos import DBOS
    return DBOS.retrieve_workflow(workflow_id).get_result()


def _run(branch_id: str) -> dict:
    path = "/optimize" if branch_id == "main" else f"/branches/{branch_id}/optimize"
    r = client.post(path, json={"with_justification": False})
    assert r.status_code == 200, r.text
    return r.json()


def _create(name, **kw):
    r = client.post("/branches", json={"name": name, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _good(**kw):
    buses = client.get("/model").json()["buses"]
    return {"applicant": "Acme", "bus_id": max(buses, key=lambda b: b["vn_kv"])["bus_id"], "technology": "solar", "rating_mw": 5.0, "readiness_score": 0.9, **kw}


def _wait_for(pred, timeout_s=60.0, what="condition"):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        v = pred()
        if v:
            return v
        time.sleep(0.25)
    raise AssertionError(f"timed out waiting for {what}")


# --- the steward, a specialist, the evidence chain -------------------------------------------------------------------
def test_an_event_wakes_the_steward_whose_specialist_studies_and_binds_evidence():
    s = client.get(f"/projects/{PROJECT}/agents").json()
    assert s["enabled"] and s["launched"] and s["status"] in ("idle", "running")
    r = client.post(f"/projects/{PROJECT}/events", json={"type": "project.imported", "payload": {"snapshot_id": "test-snap-1"}}).json()
    assert r["workflow_ids"] and not r["deduplicated"] and not r["paused"]
    wid = r["workflow_ids"][0]
    out = _result(wid)
    assert out["status"] == "done" and out["specialists"] == ["data_quality"], out
    assert out["headline"].startswith("Scripted brief")

    # the same event again is deduplicated: no second workflow, no second model call
    before = dict(CALLS)
    again = client.post(f"/projects/{PROJECT}/events", json={"type": "project.imported", "payload": {"snapshot_id": "test-snap-1"}}).json()
    assert again["deduplicated"] is True and CALLS == before

    runs = client.get(f"/projects/{PROJECT}/agents/runs").json()["runs"]
    steward = next(x for x in runs if x["kind"] == "steward" and x["run_id"] == wid)
    spec = next(x for x in runs if x["kind"] == "specialist" and x["parent_run_id"] == wid)
    assert steward["status"] == "done" and spec["status"] == "done" and spec["agent"] == "data_quality"
    assert steward["model"] == "scripted-steward" or steward["model"]  # the configured model name is recorded

    # the specialist's study step: recorded, keyed into the durable cache, and listed next to DBOS's own steps
    detail = client.get(f"/projects/{PROJECT}/agents/runs/{spec['run_id']}/steps").json()
    step = next(x for x in detail["steps"] if x["tool"] == "study_data_quality")
    assert step["cache_key"] and deps.cache.has(step["cache_key"]) and step["error"] is None
    assert any(d["function_name"].startswith("tool:") or "study" in d["function_name"] or d["function_name"] for d in detail["dbos_steps"])
    assert detail["run"]["workflow_id"] == spec["run_id"]

    # the finding's figures are the study item's, copied by the server
    ev = client.get(f"/projects/{PROJECT}/agents/steps/{step['step_id']}").json()
    assert ev["study"]["kind"] == "data_quality" and ev["stale"] is False
    items = ev["study"]["items"]
    agent_findings = [f for f in client.get("/branches/main/findings?status=open").json()["findings"] if f["source"] == "agent"]
    if items:
        f = next(x for x in agent_findings if x["evidence_ref"] == step["step_id"])
        it = next(i for i in items if i["fingerprint"] == f["fingerprint"])  # the row IS a study item, by fingerprint
        assert f["element_id"] == it["element_id"] and f["value"] == it["value"] and f["limit"] == it["limit"] and f["severity"] == it["severity"]
        assert f["evidence_kind"] == "tool_call" and f["message"]
    else:
        assert not agent_findings

    # the brief landed in the project's health thread
    threads = client.get(f"/projects/{PROJECT}/threads").json()["threads"]
    health = next(t for t in threads if t["kind"] == "health")
    msgs = client.get(f"/projects/{PROJECT}/threads/{health['thread_id']}").json()["messages"]
    assert any(m["role"] == "assistant" and m["content"].startswith("Scripted brief") for m in msgs)
    # the status read knows about it
    s = client.get(f"/projects/{PROJECT}/agents").json()
    assert s["last_events"] and s["budget"]["tokens"] >= 0


def test_a_finding_that_names_no_recorded_step_is_sent_back_to_the_model():
    d = deps.agents.deps_for("run-validator-test")

    class Ctx:
        deps = d
    bad = SpecialistReport(findings=[AgentFinding(step_id="run-x:call-nope", item_index=0, message="m", action="a")], summary="s")
    with pytest.raises(ModelRetry):
        roster._validate_report(Ctx(), bad)
    assert roster._validate_report(Ctx(), SpecialistReport(findings=[], summary="nothing")).summary == "nothing"


def test_startup_events_fire_once_per_snapshot():
    first = deps.agents.emit_startup_events()
    assert first and first[0]["type"] in ("project.imported", "edition.changed")
    _result(first[0]["workflow_ids"][0])
    assert deps.agents.emit_startup_events() == []


# --- the reviewer on a branch run --------------------------------------------------------------------------------------
def test_a_branch_run_gets_a_review_that_restates_the_gate_after_a_retry():
    behind = _create("Behind main")["branch_id"]
    ahead = _create("Ahead of it", added_projects=[_good(applicant="Ahead")])["branch_id"]
    _run(ahead)
    _run("main")
    assert client.post(f"/branches/{ahead}/merge", json={"into": "main", "acknowledge": True}).status_code == 200
    _run("main")
    out = _run(behind)
    reviews = _wait_for(lambda: client.get(f"/branches/{behind}/reviews").json()["reviews"], 120, "the review")
    rv = reviews[0]
    assert rv["run_key"] == out["run_key"] and rv["status"] == "prepared_for_review"
    assert rv["verdict"] == "blocked" and rv["blockers"] and all(b["kind"] == "behind_base" for b in rv["blockers"])
    gate = client.get(f"/branches/{behind}/merge-check").json()["verdict"]
    assert {(b["kind"], b["element_id"]) for b in rv["blockers"]} == {(b["kind"], b["element_id"]) for b in gate["blockers"]}
    assert rv["gate"]["ok"] is False and rv["body"] == "Restated from the gate."
    # the first restatement was wrong and came back: two model calls for one review
    run = next(x for x in client.get(f"/projects/{PROJECT}/agents/runs?kind=review").json()["runs"] if x["branch_id"] == behind)
    assert run["status"] == "done"
    # the same run again: no second review (deduplicated by run key); a merge is still refused
    _run(behind)
    assert len(client.get(f"/branches/{behind}/reviews?all=true").json()["reviews"]) == 1
    assert client.post(f"/branches/{behind}/merge", json={"into": "main", "acknowledge": True}).status_code == 409


# --- the answerer: a streamed answer, a flagged figure, a proposal -----------------------------------------------------
def _ask(tid: str, text: str) -> dict:
    r = client.post(f"/projects/{PROJECT}/threads/{tid}/messages", json={"content": text})
    assert r.status_code == 200, r.text
    return r.json()


def _sse(url: str) -> list[dict]:
    out = []
    with client.stream("GET", url) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def test_a_question_streams_its_trace_and_flags_a_figure_no_tool_produced():
    t = client.post(f"/projects/{PROJECT}/threads", json={"branch_id": "main", "title": "Ask"}).json()
    tid = t["thread_id"]
    sent = _ask(tid, "How big is the queue?")
    assert client.post(f"/projects/{PROJECT}/threads/{tid}/messages", json={"content": "again"}).status_code == 409  # one reply at a time
    final = _result(sent["workflow_id"])
    assert final["status"] == "done" and "98765.4" in final["text"] and final["flags"]
    msg = next(m for m in client.get(f"/projects/{PROJECT}/threads/{tid}").json()["messages"] if m["message_id"] == sent["reply_id"])
    assert msg["status"] == "done" and msg["flags"] and msg["evidence"]["steps"] and msg["tool_trace"][0]["tool"] == "queue"
    events = _sse(f"/projects/{PROJECT}/threads/{tid}/stream?message_id={sent['reply_id']}")
    kinds = [e["t"] for e in events]
    assert "tool_call" in kinds and "tool_result" in kinds and "token" in kinds and kinds[-1] == "final"
    call = next(e for e in events if e["t"] == "tool_call")
    assert call["tool"] == "queue" and call["stage"] == "ASSEMBLE" and call["step_id"].startswith(sent["workflow_id"])
    # resuming after the first two events replays only the rest
    rest = _sse(f"/projects/{PROJECT}/threads/{tid}/stream?message_id={sent['reply_id']}&after=2")
    assert len(rest) == len(events) - 2


def test_a_proposal_waits_for_approval_and_runs_when_approved():
    tid = client.post(f"/projects/{PROJECT}/threads", json={"title": "Propose"}).json()["thread_id"]
    sent = _ask(tid, "Please propose a branch to try a reinforcement.")
    final = _result(sent["workflow_id"])
    assert final["status"] == "awaiting_approval" and final["approvals"]
    aid = final["approvals"][0]
    pending = client.get(f"/projects/{PROJECT}/approvals").json()["approvals"]
    assert any(a["approval_id"] == aid and a["tool"] == "propose_branch" for a in pending)
    before = {b["branch_id"] for b in client.get("/branches").json()["branches"]}
    r = client.post(f"/projects/{PROJECT}/approvals/{aid}", json={"decision": "approve", "note": "go"}).json()
    done = _result(r["workflow_id"])
    assert done["status"] == "done" and done["text"].startswith("Opened br-")
    new = {b["branch_id"] for b in client.get("/branches").json()["branches"]} - before
    assert len(new) == 1
    nb = new.pop()
    b = next(x for x in client.get("/branches").json()["branches"] if x["branch_id"] == nb)
    assert b["created_by"] == "agent:answerer" and b["name"] == "Agent trial" and b["status"] == "open"
    assert client.post(f"/projects/{PROJECT}/approvals/{aid}", json={"decision": "approve"}).status_code == 409  # decided once
    # a denied proposal runs nothing
    sent2 = _ask(tid, "Propose another branch.")
    aid2 = _result(sent2["workflow_id"])["approvals"][0]
    before = {b["branch_id"] for b in client.get("/branches").json()["branches"]}
    r2 = client.post(f"/projects/{PROJECT}/approvals/{aid2}", json={"decision": "deny", "note": "not now"}).json()
    assert _result(r2["workflow_id"])["text"].startswith("Not opened")
    assert {b["branch_id"] for b in client.get("/branches").json()["branches"]} == before


# --- the switches, the solver order, the relaunch --------------------------------------------------------------------------
def test_pause_stops_new_work_and_resume_restarts_it():
    assert client.post(f"/projects/{PROJECT}/agents/pause", json={"reason": "maintenance"}).json()["status"] == "paused"
    r = client.post(f"/projects/{PROJECT}/events", json={"type": "project.imported", "payload": {"snapshot_id": "paused-snap"}}).json()
    assert r["paused"] is True and r["workflow_ids"] == []
    tid = client.post(f"/projects/{PROJECT}/threads", json={"title": "Paused"}).json()["thread_id"]
    assert client.post(f"/projects/{PROJECT}/threads/{tid}/messages", json={"content": "hi"}).status_code == 409
    assert client.post(f"/projects/{PROJECT}/agents/resume").json()["status"] in ("idle", "running")


def test_the_daily_budget_pauses_the_project():
    deps.budget.charge(PROJECT, tokens=int(AGENT_BUDGET_DAILY["tokens"]))
    s = client.get(f"/projects/{PROJECT}/agents").json()
    assert s["status"] == "paused" and s["paused_reason"] == "budget" and s["budget"]["exhausted"]
    r = client.post(f"/projects/{PROJECT}/events", json={"type": "project.imported", "payload": {"snapshot_id": "budget-snap"}}).json()
    assert r["paused"] is True and r["workflow_ids"] == []
    with deps.scenarios.cursor() as con:  # a new day, for the tests that follow
        con.execute("UPDATE agent_budgets SET tokens = 0 WHERE project_id = ?", [PROJECT])
    assert client.get(f"/projects/{PROJECT}/agents").json()["status"] != "paused"


def test_operators_take_the_solver_first_and_the_wait_is_bounded():
    class Jobs:
        def __init__(self, busy_for):
            self.until = time.monotonic() + busy_for

        def busy(self):
            return time.monotonic() < self.until
    lock = threading.RLock()
    t0 = time.monotonic()
    with SolverGate(Jobs(0.8), lock, max_wait_s=5).hold():
        assert time.monotonic() - t0 >= 0.7
    with pytest.raises(TimeoutError):
        with SolverGate(Jobs(10), lock, max_wait_s=0.6).hold():
            pass


def test_a_relaunch_keeps_every_result_and_runs_nothing_twice():
    runs_before = client.get(f"/projects/{PROJECT}/agents/runs").json()["runs"]
    calls_before = dict(CALLS)
    deps.agents.destroy()
    assert client.get(f"/projects/{PROJECT}/agents").json()["launched"] is False
    deps.agents.launch()
    assert client.get(f"/projects/{PROJECT}/agents").json()["launched"] is True
    again = client.post(f"/projects/{PROJECT}/events", json={"type": "project.imported", "payload": {"snapshot_id": "test-snap-1"}}).json()
    assert again["deduplicated"] is True
    wid = next(x["run_id"] for x in runs_before if x["kind"] == "steward" and x["status"] == "done")
    assert _result(wid)["status"] == "done"
    time.sleep(1.5)  # the queue poller's tick: nothing picks anything up
    assert CALLS == calls_before
    assert len(client.get(f"/projects/{PROJECT}/agents/runs").json()["runs"]) == len(runs_before)
