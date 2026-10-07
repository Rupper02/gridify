"""The agents over HTTP: status and the pause switch, events in, operator threads with a streamed
answer, approvals of proposed actions, branch reviews, and the audit trail (runs and their steps)."""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from .. import repository
from ..agents import events, runs, threads
from ..config import log, now
from ..deps import agents, evidence, projects, scenarios
from ..schemas import ApprovalDecision, EventIn, MessageIn, PauseIn, ThreadCreate

router = APIRouter()


def _project(pid: str) -> str:
    projects.row(pid)  # 404 for an unknown project
    return pid


def _on() -> None:
    """The runtime launches at startup; until it has, the routes that need it say so (a transient state)."""
    if not agents.launched:
        raise HTTPException(status_code=503, detail={"agents": "starting", "message": "the agents are still starting; retry in a moment"})


# --- status, pause, events ----------------------------------------------------------------------------------
@router.get("/projects/{pid}/agents")
def agents_status(pid: str) -> dict:
    """Starting, idle, running or paused, with what the agents spent and the last events."""
    _project(pid)
    return agents.status(pid)


@router.post("/projects/{pid}/agents/pause")
def pause_agents(pid: str, body: PauseIn | None = None) -> dict:
    _project(pid)
    _on()
    agents.spend.set_paused(pid, True, (body.reason if body else "") or "operator")
    return agents.status(pid)


@router.post("/projects/{pid}/agents/resume")
def resume_agents(pid: str) -> dict:
    _project(pid)
    _on()
    agents.spend.set_paused(pid, False)
    return agents.status(pid)


@router.post("/projects/{pid}/events")
def post_event(pid: str, body: EventIn) -> dict:
    """An event for the project's agents (what the API emits itself after runs and merges; a pipeline
    can post `project.imported` / `edition.changed`). Deduplicated by its trigger's identity (`events.TRIGGERS`)."""
    _project(pid)
    _on()
    if body.type not in events.TRIGGERS:
        raise HTTPException(status_code=422, detail=f"unknown event type; one of {', '.join(events.TRIGGERS)}")
    try:
        r = events.emit(agents, body.type, {**body.payload, "project_id": pid})
    except KeyError as e:
        raise HTTPException(status_code=422, detail=f"the event payload lacks {e}") from None
    return r or {"event_id": None, "workflow_ids": [], "deduplicated": False, "paused": False}


# --- threads ----------------------------------------------------------------------------------------------------
@router.get("/projects/{pid}/threads")
def list_threads(pid: str, branch_id: str | None = None) -> dict:
    _project(pid)
    with scenarios.cursor() as con:
        return {"threads": threads.list_threads(con, pid, branch_id=branch_id)}


@router.post("/projects/{pid}/threads")
def create_thread(pid: str, body: ThreadCreate) -> dict:
    _project(pid)
    _on()
    with scenarios.cursor() as con:
        if body.branch_id:
            repository.require_branch(con, body.branch_id)
        return threads.create_thread(con, pid, body.branch_id, body.title or "Ask the model")


@router.get("/projects/{pid}/threads/{tid}")
def get_thread(pid: str, tid: str) -> dict:
    _project(pid)
    with scenarios.cursor() as con:
        t = threads.thread_row(con, tid)
        if t is None:
            raise HTTPException(status_code=404, detail=f"thread '{tid}' not found")
        # every proposal of the thread with its status: the planner shows the pending ones as cards and knows what the others became
        return {**t, "messages": threads.messages(con, tid), "approvals": runs.list_approvals(con, pid, status=None, thread_id=tid)}


@router.post("/projects/{pid}/threads/{tid}/messages")
def post_message(pid: str, tid: str, body: MessageIn) -> dict:
    """Ask the model: stores the question and a queued reply, starts the answer workflow, and returns
    the ids to stream the reply with. 409 while a reply is already streaming in this thread."""
    _project(pid)
    _on()
    if agents.spend.check(pid).paused:
        raise HTTPException(status_code=409, detail={"code": "paused", "message": "the agents are paused for this project"})
    with scenarios.cursor() as con:
        if threads.thread_row(con, tid) is None:
            raise HTTPException(status_code=404, detail=f"thread '{tid}' not found")
        if threads.streaming_in(con, tid):
            raise HTTPException(status_code=409, detail={"code": "streaming", "message": "a reply is already on its way in this thread"})
        user = threads.add_message(con, tid, "user", body.content)
        reply = threads.add_message(con, tid, "assistant", "", status="queued")
    r = events.emit(agents, "operator.asked", {"project_id": pid, "thread_id": tid, "message_id": reply["message_id"]}) or {}
    wid = (r.get("workflow_ids") or [None])[0]
    if wid:  # what the cancel route stops
        with scenarios.cursor() as con:
            threads.set_message(con, reply["message_id"], workflow_id=wid)
    return {"message_id": user["message_id"], "reply_id": reply["message_id"], "workflow_id": wid, "paused": bool(r.get("paused"))}


@router.post("/projects/{pid}/threads/{tid}/cancel")
def cancel_reply(pid: str, tid: str) -> dict:
    """Stop the reply on its way in this thread: the message is marked cancelled at once (the composer
    is free again) and its workflow is cancelled at its next step; what it had already computed stays in
    the cache. 409 when no reply is on its way."""
    _project(pid)
    _on()
    with scenarios.cursor() as con:
        live = next((m for m in threads.messages(con, tid) if m["role"] == "assistant" and m["status"] in ("queued", "streaming")), None)
        if live is None:
            raise HTTPException(status_code=409, detail={"code": "idle", "message": "no reply is on its way in this thread"})
        threads.set_message(con, live["message_id"], status="cancelled", content="Cancelled by the operator.")
        if live.get("run_id") and runs.run_row(con, live["run_id"]):
            runs.finish_run(con, live["run_id"], status="cancelled", summary="cancelled by the operator")
    if live.get("workflow_id"):
        try:
            agents.cancel(live["workflow_id"])
        except Exception:  # it may have just finished: the message above is what the operator sees either way
            log.warning("cancelling workflow %s failed; it may still be running", live["workflow_id"], exc_info=True)
    return {"thread_id": tid, "message_id": live["message_id"], "status": "cancelled", "cancelled_at": now()}


def _sse(workflow_id: str, after: int) -> Iterator[bytes]:
    """The workflow's event stream as server-sent events. A plain generator (Starlette iterates it in a
    worker thread) over DBOS's blocking reader, which follows the stream until the workflow closes it.
    (The async reader is avoided on purpose: DBOS installs its own default executor on the event loop,
    which a closed loop shuts down for every later loop in the process.)"""
    from dbos import DBOS

    yield b": connected\n\n"
    pos = after
    for ev in DBOS.read_stream(workflow_id, "events", offset=after):
        pos += 1  # the id is the stream position: a client resumes with `after=<last id>`
        kind = ev.get("t", "event") if isinstance(ev, dict) else "event"
        yield f"id: {pos}\nevent: {kind}\ndata: {json.dumps(ev, default=str)}\n\n".encode()


@router.get("/projects/{pid}/threads/{tid}/stream")
async def stream_reply(pid: str, tid: str, message_id: str, request: Request, after: int = 0) -> StreamingResponse:
    """Server-sent events of a reply as it is produced: tokens, tool calls with their step ids and
    planning stage, tool results, and the final message. `after` (or Last-Event-ID, the position of the
    last event received) resumes without replaying."""
    _project(pid)
    _on()
    with scenarios.cursor() as con:
        m = threads.message_row(con, message_id)
    if m is None or m["thread_id"] != tid or not m.get("workflow_id"):
        raise HTTPException(status_code=404, detail="no reply with that id in this thread")
    last = request.headers.get("last-event-id")
    offset = int(last) if last and last.isdigit() else after
    return StreamingResponse(_sse(m["workflow_id"], offset), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# --- approvals ---------------------------------------------------------------------------------------------------
@router.get("/projects/{pid}/approvals")
def list_approvals(pid: str, status: str | None = "pending") -> dict:
    _project(pid)
    with scenarios.cursor() as con:
        return {"approvals": runs.list_approvals(con, pid, status=status)}


@router.post("/projects/{pid}/approvals/{aid}")
def decide_approval(pid: str, aid: str, body: ApprovalDecision) -> dict:
    """Approve or deny a proposed action. The decision is recorded at once; the answer continues (the
    approved tools run on the branch, the denied ones are refused to the model) once every proposal of
    that reply is decided. Until then `waiting_for` lists the proposals still open and `workflow_id` is null."""
    _project(pid)
    _on()
    with scenarios.cursor() as con:
        a = runs.approval_row(con, aid)
        if a is None:
            raise HTTPException(status_code=404, detail=f"approval '{aid}' not found")
        if a["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"approval is '{a['status']}', not pending")
        a = runs.decide_approval(con, aid, "approved" if body.decision == "approve" else "denied", body.note)
        waiting = [s["approval_id"] for s in runs.approvals_for_message(con, a["message_id"]) if s["status"] == "pending"]
    wid = None if waiting else agents.resume_answer(pid, a["thread_id"], a["message_id"])
    return {**a, "workflow_id": wid, "waiting_for": waiting, "checked_at": now()}


# --- the note and the audit trail -----------------------------------------------------------------------------------
@router.get("/branches/{branch_id}/note")
def branch_note(branch_id: str) -> dict:
    """The engineer's note on the branch's current run (`current`), with the digest it was written from; `note: null`
    while none has been written or the run has moved on."""
    with scenarios.cursor() as con:
        repository.require_branch(con, branch_id)
        return {"branch_id": branch_id, "note": runs.current_note(con, branch_id)}


@router.get("/projects/{pid}/agents/runs")
def list_runs(pid: str, kind: str | None = None, limit: int = 50) -> dict:
    _project(pid)
    with scenarios.cursor() as con:
        return {"runs": runs.list_runs(con, pid, kind=kind, limit=limit)}


@router.get("/projects/{pid}/agents/runs/{rid}/steps")
def run_steps(pid: str, rid: str) -> dict:
    """A run's recorded tool steps (its arguments, its cache keys) joined with what DBOS executed."""
    _project(pid)
    with scenarios.cursor() as con:
        run = runs.run_row(con, rid)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run '{rid}' not found")
    steps = evidence.steps(rid)
    dbos_steps: list[dict] = []
    if agents.launched and run.get("workflow_id"):
        try:
            from dbos import DBOS
            dbos_steps = [{"function_id": s["function_id"], "function_name": s["function_name"], "error": str(s["error"]) if s.get("error") else None,
                           "child_workflow_id": s.get("child_workflow_id"), "started_at_epoch_ms": s.get("started_at_epoch_ms"), "completed_at_epoch_ms": s.get("completed_at_epoch_ms")}
                          for s in DBOS.list_workflow_steps(run["workflow_id"], load_output=False)]
        except Exception:  # the audit view must not fail on a runtime hiccup
            log.warning("could not read the DBOS steps of %s", run["workflow_id"], exc_info=True)
            dbos_steps = []
    return {"run": run, "steps": steps, "dbos_steps": dbos_steps}


@router.get("/projects/{pid}/agents/steps/{step_id}")
def step_evidence(pid: str, step_id: str) -> dict:
    """The evidence behind a step: the study it ran (re-fetched from the durable cache), stale if the engine changed."""
    _project(pid)
    r = evidence.replay(step_id)
    if r is None:
        raise HTTPException(status_code=404, detail=f"step '{step_id}' not found")
    return r
