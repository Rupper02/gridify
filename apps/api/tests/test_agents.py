"""The agent harness end to end, with scripted models and no network: DBOS on a temp SQLite system
database, every agent a FunctionModel that calls the real tools and answers in the real shapes.

What is proved: a finished run wakes the note once (one model call on the engine's digest, the note
stored for the run and served for the branch, a figure the digest does not hold flagged, the same run
again deduplicated); a branch behind main is refused by the gate; a question streams tool calls and
tokens, flags a figure no tool produced, and a proposal waits for the operator's approval; the pause
switch stops work; a relaunch keeps every result; operators keep the solver first."""

import json
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_ai import models
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from gridforge_api import deps
from gridforge_api.agents.tools import SolverBusy, SolverGate
from gridforge_api.main import app
from _support import add_project, broken_project, client, create_branch as _create, project as _project, requires_warehouse, run as _run

models.ALLOW_MODEL_REQUESTS = False
pytestmark = requires_warehouse

PROJECT = deps.agents.project_id
CALLS: dict[str, int] = {}  # model calls per role


# --- scripted models ---------------------------------------------------------------------------------------------
def _prompt(messages) -> str:
    return "\n".join(str(p.content) for m in messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, UserPromptPart))


def _returns(messages, tool: str) -> list:
    """Tool returns since the operator's latest question (earlier turns are history, not this answer)."""
    last_user = max((i for i, m in enumerate(messages) if isinstance(m, ModelRequest) and any(isinstance(p, UserPromptPart) for p in m.parts)), default=0)
    return [p for m in messages[last_user:] if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, ToolReturnPart) and p.tool_name == tool]


def _digest(messages, info):
    """The note writer: the digest is in the prompt; the note quotes one of its figures and makes one up (to be flagged)."""
    digest = json.loads(_prompt(messages).split("The digest:\n", 1)[1].rsplit("\nWrite the note.", 1)[0])
    return ("text", f"Scripted note: {digest['queue']['connected']} projects connect by {digest['years'][-1]}. A made-up figure: 98765.4 MW.")


def _answerer(messages, info):
    p = _prompt(messages)
    low = p.lower()
    rid = re.search(r"CR-\d+", p)
    if low.startswith("move "):  # "Move CR-2056 on br-xxxx to bus 12 and run at once": a change and a run in one reply
        bid = re.search(r"br-[0-9a-f]+", p).group(0)
        change = {"branch_id": bid, "request_id": rid.group(0), "bus_id": int(re.search(r"bus (\d+)", p).group(1))}
        if not _returns(messages, "propose_candidate_change"):
            return ("tools", [("propose_candidate_change", change), ("propose_run", {"branch_id": bid})])
        outcomes = [r.content.get("summary", r.content) if isinstance(r.content, dict) else r.content for r in _returns(messages, "propose_candidate_change") + _returns(messages, "propose_run")]
        return ("text", "Done: " + "; ".join(str(o) for o in outcomes))
    if "propose" in low:
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


SCRIPTS = {"digest": _digest, "answerer": _answerer}


def _scripted(role: str) -> FunctionModel:
    script = SCRIPTS[role]

    def plan(messages, info):
        CALLS[role] = CALLS.get(role, 0) + 1
        return script(messages, info)

    def calls(kind, rest):  # ("tool", name, args) or ("tools", [(name, args), ...]): one response, one or several tool calls
        return rest[0] if kind == "tools" else [(rest[0], rest[1])]

    def function(messages, info) -> ModelResponse:
        kind, *rest = plan(messages, info)
        if kind == "text":
            return ModelResponse(parts=[TextPart(rest[0])])
        return ModelResponse(parts=[ToolCallPart(tool_name=n, args=a, tool_call_id=f"call-{uuid.uuid4().hex[:6]}") for n, a in calls(kind, rest)])

    async def stream_function(messages, info):
        kind, *rest = plan(messages, info)
        if kind == "text":
            yield rest[0]
        else:
            for i, (n, a) in enumerate(calls(kind, rest)):
                yield {i + 1: DeltaToolCall(name=n, json_args=json.dumps(a), tool_call_id=f"call-{uuid.uuid4().hex[:6]}")}

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


def _result(workflow_id: str):
    from dbos import DBOS
    return DBOS.retrieve_workflow(workflow_id).get_result()


def _wait_for(pred, timeout_s=60.0, what="condition"):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        v = pred()
        if v:
            return v
        time.sleep(0.25)
    raise AssertionError(f"timed out waiting for {what}")


# --- the note on a run ------------------------------------------------------------------------------------------------
def test_a_finished_run_gets_its_note_once_from_the_engines_digest():
    s = client.get(f"/projects/{PROJECT}/agents").json()
    assert s["launched"] and s["status"] in ("idle", "running")
    bid = _create("Noted", added_projects=[_project(applicant="Noted")])["branch_id"]
    out = _run(bid)
    note = _wait_for(lambda: client.get(f"/branches/{bid}/note").json()["note"], 120, "the note")
    assert note["run_key"] == out["run_key"] and note["status"] == "current"
    assert note["body"].startswith("Scripted note:") and "projects connect" in note["body"]
    assert note["flags"] and "98765.4" in note["flags"][0]  # the made-up figure is flagged; the digest's own figure is not
    assert note["digest"]["queue"]["connected"] >= 0 and note["digest"]["binding"] is not None
    run = next(x for x in client.get(f"/projects/{PROJECT}/agents/runs?kind=digest").json()["runs"] if x["branch_id"] == bid)
    assert run["status"] == "done" and run["model"] and run["summary"].startswith("Scripted note")
    # the same run again: deduplicated by run key, no second model call, the note stands
    before = dict(CALLS)
    _run(bid)
    time.sleep(1.0)
    assert CALLS == before and client.get(f"/branches/{bid}/note").json()["note"]["note_id"] == note["note_id"]
    # the status read knows about it
    s = client.get(f"/projects/{PROJECT}/agents").json()
    assert s["last_events"] and s["spend"]["tokens"] >= 0


# --- the gate on a branch behind main --------------------------------------------------------------------------------
def test_a_branch_behind_main_is_refused_by_the_gate():
    behind = _create("Behind main")["branch_id"]
    ahead = _create("Ahead of it")["branch_id"]
    add_project(ahead, broken_project(applicant="Ahead"))  # a change that cannot introduce a problem on any grid
    _run(ahead)
    _run("main")
    assert client.post(f"/branches/{ahead}/merge", json={"into": "main", "acknowledge": True}).status_code == 200
    _run("main")
    _run(behind)
    gate = client.get(f"/branches/{behind}/merge-check").json()["verdict"]
    assert gate["ok"] is False and gate["blockers"] and all(b["kind"] == "behind_base" for b in gate["blockers"])
    refused = client.post(f"/branches/{behind}/merge", json={"into": "main", "acknowledge": True})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "blocked"
    assert "rebase this branch onto main" in refused.json()["detail"]["message"]
    from gridforge_api import ledger  # the refused attempt is on record
    with deps.scenarios.cursor() as con:
        rows = ledger.merge_rows(con, behind)
    assert rows and rows[-1]["outcome"] == "refused" and rows[-1]["n_blockers"] >= 1


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


def test_two_proposals_in_one_reply_resume_once_both_are_decided():
    from gridforge_api import repository

    bid = _create("Both", added_projects=[_project(applicant="Both")])["branch_id"]
    with deps.scenarios.cursor() as con:
        row = repository.candidate_rows(con, bid)[0]
    rid, old_bus = row["request_id"], int(row["bus_id"])
    new_bus = next(b["bus_id"] for b in sorted(client.get("/model").json()["buses"], key=lambda b: -b["vn_kv"]) if b["bus_id"] != old_bus)
    tid = client.post(f"/projects/{PROJECT}/threads", json={"branch_id": bid, "title": "Both"}).json()["thread_id"]
    sent = _ask(tid, f"Move {rid} on {bid} to bus {new_bus} and run at once")
    first = _result(sent["workflow_id"])
    assert first["status"] == "awaiting_approval" and len(first["approvals"]) == 2, first
    a_change, a_run = first["approvals"]
    view = client.get(f"/projects/{PROJECT}/threads/{tid}").json()
    assert {a["approval_id"] for a in view["approvals"]} == {a_change, a_run} and all(a["status"] == "pending" for a in view["approvals"])
    # the first decision is recorded and waits for the second: nothing runs yet
    r1 = client.post(f"/projects/{PROJECT}/approvals/{a_change}", json={"decision": "approve"}).json()
    assert r1["workflow_id"] is None and r1["waiting_for"] == [a_run]
    with deps.scenarios.cursor() as con:
        assert int(repository.candidate_rows(con, bid)[0]["bus_id"]) == old_bus
    assert client.post(f"/projects/{PROJECT}/approvals/{a_change}", json={"decision": "approve"}).status_code == 409  # decided once
    # the second decision resumes the reply with both: the approved change is applied, the denied run never runs
    r2 = client.post(f"/projects/{PROJECT}/approvals/{a_run}", json={"decision": "deny", "note": "not now"}).json()
    assert r2["workflow_id"] and r2["waiting_for"] == []
    done = _result(r2["workflow_id"])
    assert done["status"] == "done" and done["text"].startswith("Done:"), done
    with deps.scenarios.cursor() as con:
        assert int(repository.candidate_rows(con, bid)[0]["bus_id"]) == new_bus
    by = {a["approval_id"]: a["status"] for a in client.get(f"/projects/{PROJECT}/threads/{tid}").json()["approvals"]}
    assert by == {a_change: "applied", a_run: "denied"}
    assert not any(e["type"] == "run.finished" and e["dedup_id"].startswith(f"run:{bid}:") for e in client.get(f"/projects/{PROJECT}/agents").json()["last_events"])


# --- the switches, the solver order, the relaunch --------------------------------------------------------------------------
def test_pause_stops_new_work_and_resume_restarts_it():
    assert client.post(f"/projects/{PROJECT}/agents/pause", json={"reason": "maintenance"}).json()["status"] == "paused"
    r = client.post(f"/projects/{PROJECT}/events", json={"type": "project.imported", "payload": {"snapshot_id": "paused-snap"}}).json()
    assert r["paused"] is True and r["workflow_ids"] == []
    tid = client.post(f"/projects/{PROJECT}/threads", json={"title": "Paused"}).json()["thread_id"]
    assert client.post(f"/projects/{PROJECT}/threads/{tid}/messages", json={"content": "hi"}).status_code == 409
    assert client.post(f"/projects/{PROJECT}/agents/resume").json()["status"] in ("idle", "running")


def test_operators_take_the_solver_first_and_the_wait_is_bounded_by_the_run():
    class Jobs:
        def __init__(self, busy_for):
            self.until = time.monotonic() + busy_for

        def busy(self):
            return time.monotonic() < self.until
    lock = threading.RLock()
    t0 = time.monotonic()
    said: list[float] = []
    with SolverGate(Jobs(0.8), lock).hold(waiting=said.append, deadline=time.monotonic() + 5):
        assert time.monotonic() - t0 >= 0.7
    assert said, "a waiting study tells the trace it waits"
    with pytest.raises(SolverBusy):  # only the run's own deadline stops the wait
        with SolverGate(Jobs(10), lock).hold(deadline=time.monotonic() + 0.6):
            pass


def test_a_relaunch_keeps_every_result_and_runs_nothing_twice():
    runs_before = client.get(f"/projects/{PROJECT}/agents/runs").json()["runs"]
    calls_before = dict(CALLS)
    deps.agents.destroy()
    assert client.get(f"/projects/{PROJECT}/agents").json()["launched"] is False
    deps.agents.launch()
    assert client.get(f"/projects/{PROJECT}/agents").json()["launched"] is True
    again = client.post(f"/projects/{PROJECT}/events", json={"type": "project.imported", "payload": {"snapshot_id": "paused-snap"}}).json()
    assert again["deduplicated"] is True
    wid = next(x["run_id"] for x in runs_before if x["kind"] == "digest" and x["status"] == "done")
    assert _result(wid)["status"] == "done"
    time.sleep(1.5)  # the queue poller's tick: nothing picks anything up
    assert CALLS == calls_before
    assert len(client.get(f"/projects/{PROJECT}/agents/runs").json()["runs"]) == len(runs_before)


def test_the_app_lifespan_launches_and_stops_the_runtime_off_the_event_loop(monkeypatch):
    """What `uvicorn` does: the lifespan starts the agents while the loop is running (DBOS's sync calls
    refuse that thread, so the lifespan moves them off it) and destroys them on shutdown. The job worker
    is kept alive for the modules that follow."""
    monkeypatch.setattr(deps.jobs, "shutdown", lambda: None)
    deps.agents.destroy()
    assert not deps.agents.launched
    with TestClient(app) as c:
        assert deps.agents.launched
        assert c.get(f"/projects/{PROJECT}/agents").json()["launched"] is True
    assert not deps.agents.launched

