"""The durable workflows: one per kind of agent run. Each is bounded, idempotent by its workflow id,
and does its I/O in steps (`DBOS.run_step`), so a restart resumes it from the last completed step and
a replayed step runs nothing twice. Workflow code reads only its arguments and step outputs.

The runtime that owns the collaborators is looked up through `RUNTIME`, set by `AgentRuntime.launch`
(the composition root), never imported from `deps`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple

from dbos import DBOS, SetWorkflowID
from dbos._error import DBOSWorkflowCancelledError
from gridforge_optimizer.naming import name_payload
from pydantic_ai import DeferredToolRequests, DeferredToolResults, ModelMessagesTypeAdapter, ToolApproved, ToolDenied, UsageLimits
from pydantic_ai.messages import ModelResponse, TextPart

from .. import repository
from ..config import AGENT_RUN_BUDGET, log, now
from . import events, runs, threads
from .citations import normalize_citations, strip_citations
from .evidence import check_numbers
from .streaming import stage_of
from .tools import proposal_text

if TYPE_CHECKING:
    from .runtime import AgentRuntime

RUNTIME: AgentRuntime | None = None


def _rt() -> AgentRuntime:
    assert RUNTIME is not None, "the agent runtime is not launched"
    return RUNTIME


def _step(fn):
    """Run `fn` as a checkpointed step inside a workflow (plainly when called outside one, in tests)."""
    return _rt().harness.durable(fn.__name__, fn)


def _limits() -> UsageLimits:
    """The run's hard stops: its number of model requests, and the tokens its requests and responses add up to
    (`AGENT_RUN_BUDGET["max_tokens"]`: a run that keeps re-reading a huge payload ends as failed, not as a bill). The
    tool-call budget is enforced by `tools._recorded`, which answers past it with a refusal the model writes up from:
    a Pydantic AI `tool_calls_limit` would raise before that refusal ever ran, and end the answer as failed."""
    return UsageLimits(request_limit=AGENT_RUN_BUDGET["max_tool_calls"] + 4, tool_calls_limit=None, total_tokens_limit=AGENT_RUN_BUDGET["max_tokens"])


def _usage(res) -> dict:
    """A run's tokens, and what OpenRouter billed for its own responses (`provider_details["cost"]`, in credits = USD;
    a resumed run's history is not re-counted). Pydantic AI's `usage.cost` is a local price-table estimate that does not
    know every OpenRouter model, so it is not used. None when no response reported a cost."""
    u = res.usage  # a property in Pydantic AI 2.x
    billed = [float(m.provider_details["cost"]) for m in res.new_messages()
              if isinstance(m, ModelResponse) and (m.provider_details or {}).get("cost") is not None]
    return {"input_tokens": int(u.input_tokens or 0), "output_tokens": int(u.output_tokens or 0), "cost_credits": sum(billed) if billed else None}


def _begin(run_id: str, project_id: str, *, kind: str, agent: str, branch_id=None, thread_id=None, event_id=None, parent=None) -> dict:
    """Record the run; a project the operator paused skips it."""
    rt = _rt()

    def do():
        state = rt.spend.check(project_id)
        with rt.harness.store.cursor() as con:
            runs.start_run(con, run_id=run_id, project_id=project_id, kind=kind, agent=agent, workflow_id=DBOS.workflow_id, branch_id=branch_id,
                           thread_id=thread_id, event_id=event_id, parent_run_id=parent, model=rt.model_name(agent),
                           status="skipped_paused" if state.paused else "running")
        return {"paused": state.paused, "reason": state.paused_reason}
    return _step(do)


def _finish(run_id: str, project_id: str, *, status: str, summary: str = "", error: str | None = None, usage: dict | None = None, solves: int = 0) -> None:
    rt = _rt()
    u = usage or {}

    def do():
        with rt.harness.store.cursor() as con:
            runs.finish_run(con, run_id, status=status, summary=summary[:2000], error=error, input_tokens=u.get("input_tokens", 0),
                            output_tokens=u.get("output_tokens", 0), cost_credits=u.get("cost_credits"), solves=solves)
        if usage:
            rt.spend.charge(project_id, tokens=u.get("input_tokens", 0) + u.get("output_tokens", 0), cost_credits=u.get("cost_credits"), solves=solves)
        log.info("agent run %s %s: $%s, %d+%d tokens, %d solves%s", run_id, status, u.get("cost_credits") if u.get("cost_credits") is not None else "-",
                 u.get("input_tokens", 0), u.get("output_tokens", 0), solves, f" ({error[:120]})" if error else "")
        return True
    _step(do)


# --- the note: one model call after a run, from the engine's own digest ------------------------------------------------
@DBOS.workflow()
def digest_run(project_id: str, branch_id: str, run_key: str, event: dict) -> dict:
    """The engineer's note on a run: the engine reduces the run to a digest (`PlanService.digest`: the binding set,
    the deferrals with their chains, what changed, the works, the gate), one model call turns it into at most 150
    words, every figure is checked by value against the digest, and the note is stored for the branch's current run
    (`run_key`) and superseded by the next. Skipped when the branch has moved on or the note exists."""
    rt = _rt()
    run_id = DBOS.workflow_id or f"digest:{branch_id}:{run_key}"

    def current() -> bool:
        return rt.harness.plans.freshness(branch_id).years_key == run_key

    def prepare():
        with rt.harness.store.cursor() as con:
            if runs.note_exists(con, branch_id, run_key) or not current():
                return None
            older = [(rid, wid) for rid, wid in runs.open_runs_of(con, branch_id, "digest") if rid != run_id]
        for _rid, wid in older:  # a note on an earlier run still being written would be superseded at once: stop paying for it
            if wid:
                DBOS.cancel_workflow(wid)
        if older:
            with rt.harness.store.cursor() as con:
                for rid, _wid in older:
                    runs.close_run(con, rid, status="cancelled", error="superseded by a newer run")
        with rt.harness.solver_gate.hold():  # the parent's years may have to be solved for the comparison
            return rt.harness.plans.digest(branch_id)
    digest = _step(prepare)
    if digest is None:
        return {"run_id": run_id, "status": "skipped", "reason": "already noted, or superseded by a newer run"}
    begun = _begin(run_id, project_id, kind="digest", agent="digest", branch_id=branch_id, event_id=event.get("event_id"))
    if begun["paused"]:
        return {"run_id": run_id, "status": "skipped_paused", "reason": begun["reason"]}
    try:
        deps = rt.deps_for(run_id, project_id=project_id, branch_id=branch_id)
        prompt = f"Event: {event.get('type', 'run.finished')}.\nThe digest:\n{json.dumps(digest, default=str)}\nWrite the note."
        res = rt.agents["digest"].run_sync(prompt, deps=deps, usage_limits=_limits())
        body = str(res.output).strip()
        flags = _figure_flags(body, [digest])

        def store():
            if not current():  # a newer run finished while the note was written: it is not the current one
                return None
            with rt.harness.store.cursor() as con:
                runs.supersede_notes(con, branch_id, run_key)
                return runs.insert_note(con, project_id=project_id, branch_id=branch_id, run_key=run_key, run_id=run_id, body=body,
                                        digest=digest, flags=flags)
        row = _step(store)
        if row is None:
            _finish(run_id, project_id, status="skipped", summary="superseded by a newer run before it was stored", usage=_usage(res))
            return {"run_id": run_id, "status": "skipped", "reason": "superseded by a newer run"}
        _finish(run_id, project_id, status="done", summary=body.splitlines()[0][:200] if body else "", usage=_usage(res))
        return {"run_id": run_id, "status": "done", "note_id": row["note_id"], "flags": flags}
    except Exception as e:
        _finish(run_id, project_id, status="failed", error=f"{type(e).__name__}: {e}")
        raise


# --- the answerer: an operator's question, streamed --------------------------------------------------------------------
def _dump_messages(msgs) -> list:
    return ModelMessagesTypeAdapter.dump_python(msgs, mode="json")


FINAL_SEQ = 10_000  # a run's closing event sorts after every step it streamed


def _close(run_id: str, final: dict) -> None:
    rt = _rt()
    try:
        rt.emit_for(run_id)(final)
        if rt.harness.in_workflow():
            DBOS.close_stream("events")
    except DBOSWorkflowCancelledError:  # the operator cancelled: the stream ends with the workflow
        pass


def _cancelled(rt: AgentRuntime, message_id: str) -> bool:
    """The operator cancelled this reply (routers.agents.cancel_reply): its message is final, never overwritten."""
    with rt.harness.store.cursor() as con:
        m = threads.message_row(con, message_id)
    return bool(m and m["status"] == "cancelled")


def _failed(rt: AgentRuntime, run_id: str, project_id: str, message_id: str, e: Exception) -> None:
    """An answer that did not finish: a cancellation keeps the operator's message; any other failure is written up."""
    if isinstance(e, DBOSWorkflowCancelledError) or _step(lambda: _cancelled(rt, message_id)):
        _finish(run_id, project_id, status="cancelled", summary="cancelled by the operator")
        return

    def mark():
        with rt.harness.store.cursor() as con:
            threads.set_message(con, message_id, status="failed", content=f"The answer failed: {type(e).__name__}: {e}")
        return True
    _step(mark)
    _finish(run_id, project_id, status="failed", error=f"{type(e).__name__}: {e}")
    _close(run_id, {"t": "error", "message": str(e), "seq": FINAL_SEQ})


def _figure_flags(text: str, step_outputs: list) -> list[str]:
    """The soft flags on what the model wrote: digit figures no tool output it read contains (`check_numbers`)."""
    return [f"figure {n:g} appears in no tool output of this conversation" for n in check_numbers(text, step_outputs)]


def _answered(rt: AgentRuntime, project_id: str, thread_id: str, message_id: str, run_id: str, res, deps, earlier_runs: list[str]) -> dict:
    """Store the answerer's result: a text answer, or the proposals that wait for the operator's approval
    with what the model said alongside them; both carry flags for figures no step produced, its own or one
    of the earlier runs whose outputs its history holds (`threads.history_runs`). A reply the operator
    cancelled meanwhile is left as it is."""
    if _cancelled(rt, message_id):
        return {"status": "cancelled", "text": "", "approvals": [], "flags": []}
    out = res.output
    own = rt.evidence.steps(run_id)
    read = [s for rid in earlier_runs for s in rt.evidence.steps(rid)] + own
    # checked against what the model read: the stored engine words named as `tools._recorded` handed them over
    names = rt.harness.projects.names(project_id)
    step_outputs = [name_payload(s["result"], names) for s in read if s.get("result") is not None]
    trace = [{"step_id": s["step_id"], "tool": s["tool"], "stage": stage_of(s["tool"]), "args": s["args"], "solves": s.get("solves", 0)} for s in own]
    cited = [s["step_id"] for s in read]
    evidence = {"steps": cited, "branch_id": deps.branch_id, "snapshot_id": rt.harness.warehouse.baseline_id(), "engine": rt.evidence.engine}
    if isinstance(out, DeferredToolRequests):
        approvals = []
        with rt.harness.store.cursor() as con:
            for call in out.approvals:
                approvals.append(runs.add_approval(con, project_id=project_id, thread_id=thread_id, message_id=message_id, run_id=run_id,
                                                   tool_call_id=call.tool_call_id, tool=call.tool_name, args=call.args_as_dict()))
            # what the model said alongside its proposals (the figures it read, the option it favours), then the proposals
            # themselves, in words (never a tool call as JSON: that is what the Approve card is for)
            last = res.all_messages()[-1]
            said = "\n".join(p.content.strip() for p in last.parts if isinstance(p, TextPart) and p.content.strip()) if isinstance(last, ModelResponse) else ""
            said = normalize_citations(said, cited)
            proposed = "I propose to " + "; ".join(proposal_text(a["tool"], a["args"], names) for a in approvals) + ". Waiting for your approval."
            text = f"{said}\n\n{proposed}" if said else proposed
            flags = _figure_flags(said, step_outputs)  # the model's own words, not the proposals' arguments
            threads.set_message(con, message_id, status="awaiting_approval", content=text, tool_trace=trace, model_messages=_dump_messages(res.all_messages()),
                                usage=_usage(res), cost_credits=_usage(res)["cost_credits"], flags=flags, evidence=evidence)
        return {"status": "awaiting_approval", "approvals": [a["approval_id"] for a in approvals], "text": text, "flags": flags}
    text = normalize_citations(str(out), cited)
    flags = _figure_flags(text, step_outputs)
    with rt.harness.store.cursor() as con:
        threads.set_message(con, message_id, status="done", content=text, tool_trace=trace, model_messages=_dump_messages(res.all_messages()),
                            usage=_usage(res), cost_credits=_usage(res)["cost_credits"], flags=flags, evidence=evidence)
    return {"status": "done", "text": text, "flags": flags}


def _paused_reply(rt: AgentRuntime, run_id: str, message_id: str, reason: str) -> None:
    """The project is paused: the reply says so and its stream ends (a reply left "streaming" would hold the thread)."""
    def mark():
        with rt.harness.store.cursor() as con:
            threads.set_message(con, message_id, status="failed", content=f"The agents are paused ({reason}).")
        return True
    _step(mark)
    _close(run_id, {"t": "final", "status": "failed", "seq": FINAL_SEQ})


@DBOS.workflow()
def answer(project_id: str, thread_id: str, message_id: str) -> dict:
    rt = _rt()
    run_id = DBOS.workflow_id or f"answer:{message_id}"

    def load():
        with rt.harness.store.cursor() as con:
            msgs = threads.messages(con, thread_id)
            reply = threads.message_row(con, message_id)
            question = next((m for m in reversed(msgs) if m["role"] == "user" and m["seq"] < reply["seq"]), None)
            threads.set_message(con, message_id, status="streaming", run_id=run_id)
            t = threads.thread_row(con, thread_id)
            return {"question": question["content"] if question else "", "history": threads.history(con, thread_id, before_seq=reply["seq"]),
                    "earlier_runs": threads.history_runs(con, thread_id, reply["seq"]), "branch_id": t["branch_id"] if t else None}
    loaded = _step(load)
    begun = _begin(run_id, project_id, kind="answer", agent="answerer", branch_id=loaded["branch_id"], thread_id=thread_id)
    if begun["paused"]:
        _paused_reply(rt, run_id, message_id, begun["reason"])
        return {"run_id": run_id, "status": "skipped_paused"}
    try:
        deps = rt.deps_for(run_id, project_id=project_id, branch_id=loaded["branch_id"], thread_id=thread_id, allowed=rt.studies_for("answerer"))
        history = ModelMessagesTypeAdapter.validate_python(loaded["history"]) if loaded["history"] else None
        res = rt.agents["answerer"].run_sync(loaded["question"], deps=deps, message_history=history, usage_limits=_limits())
        done = _step(lambda: _answered(rt, project_id, thread_id, message_id, run_id, res, deps, loaded.get("earlier_runs", [])))
        _finish(run_id, project_id, status=done["status"] if done["status"] == "cancelled" else "done", summary=done.get("text", "")[:200], usage=_usage(res), solves=deps.solves)
        _close(run_id, {"t": "final", "status": done["status"], "text": done.get("text", ""), "approvals": done.get("approvals", []), "flags": done.get("flags", []), "seq": FINAL_SEQ})
        return {"run_id": run_id, **done}
    except Exception as e:
        _failed(rt, run_id, project_id, message_id, e)
        raise


@DBOS.workflow()
def answer_resume(project_id: str, thread_id: str, message_id: str) -> dict:
    """Continue an answer once the operator has decided every proposal it made: the approved deferred
    tools run, the denied ones are refused to the model, and it writes the rest of the answer (or proposes
    again). One resume per reply, so a reply that made two proposals waits for both decisions."""
    rt = _rt()
    run_id = DBOS.workflow_id or f"resume:{message_id}"

    def load():
        with rt.harness.store.cursor() as con:
            approvals = runs.approvals_for_message(con, message_id)
            prior = threads.message_row(con, message_id)
            reply = threads.add_message(con, thread_id, "assistant", "", status="streaming", run_id=run_id, workflow_id=DBOS.workflow_id)
            t = threads.thread_row(con, thread_id)
            return {"approvals": approvals, "history": prior["model_messages"] or [], "reply_id": reply["message_id"],
                    "earlier_runs": threads.history_runs(con, thread_id, reply["seq"]), "branch_id": t["branch_id"] if t else None}
    loaded = _step(load)
    approvals = loaded["approvals"]
    begun = _begin(run_id, project_id, kind="answer", agent="answerer", branch_id=loaded["branch_id"], thread_id=thread_id,
                   parent=approvals[0]["run_id"] if approvals else None)
    if begun["paused"]:
        _paused_reply(rt, run_id, loaded["reply_id"], begun["reason"])
        return {"run_id": run_id, "status": "skipped_paused"}
    try:
        deps = rt.deps_for(run_id, project_id=project_id, branch_id=loaded["branch_id"], thread_id=thread_id, allowed=rt.studies_for("answerer"))
        decisions: dict[str, Any] = {
            a["tool_call_id"]: ToolApproved() if a["status"] == "approved" else ToolDenied(message=f"The operator declined: {a.get('note') or 'no reason given'}")
            for a in approvals
        }
        res = rt.agents["answerer"].run_sync(None, deps=deps, message_history=ModelMessagesTypeAdapter.validate_python(loaded["history"]),
                                             deferred_tool_results=DeferredToolResults(approvals=decisions), usage_limits=_limits())
        done = _step(lambda: _answered(rt, project_id, thread_id, loaded["reply_id"], run_id, res, deps, loaded.get("earlier_runs", [])))

        def settle():
            steps = {s["step_id"]: s for s in rt.evidence.steps(run_id)}
            with rt.harness.store.cursor() as con:
                for a in approvals:
                    if a["status"] != "approved":
                        runs.set_approval_result(con, a["approval_id"], "denied", {"status": done["status"]})
                        continue
                    step = steps.get(f"{run_id}:{a['tool_call_id']}") or {}
                    out = step.get("result") or {}
                    why = step.get("error") or out.get("error") or out.get("refused")  # a tool answers its failures as payloads
                    runs.set_approval_result(con, a["approval_id"], "failed" if why else "applied",
                                             {"status": done["status"], **({"error": why} if why else {})})
            ran = next((s["result"] for s in steps.values() if s["tool"] == "propose_run" and (s.get("result") or {}).get("event")), None)
            return {"ran": ran}
        settled = _step(settle)
        if settled["ran"]:  # an approved run is a run like any other: its note is written, alike
            # workflow code, not a step: `emit` enqueues workflows, which DBOS refuses from inside a step (the event
            # row it writes is idempotent by its dedup id, so a replay of this line wakes nobody twice)
            events.emit(rt, "run.finished", {**settled["ran"]["event"], "project_id": project_id})
        _finish(run_id, project_id, status=done["status"] if done["status"] == "cancelled" else "done", summary=done.get("text", "")[:200], usage=_usage(res), solves=deps.solves)
        _close(run_id, {"t": "final", "status": done["status"], "text": done.get("text", ""), "approvals": done.get("approvals", []), "flags": done.get("flags", []), "seq": FINAL_SEQ})
        return {"run_id": run_id, "reply_id": loaded["reply_id"], **done}
    except Exception as e:
        _failed(rt, run_id, project_id, loaded["reply_id"], e)
        raise


DIGEST_QUEUE = "digest"  # partitioned by project: notes land one at a time, in order
CHAT_QUEUE = "chat"  # answers: a few at once


class WorkflowSpec(NamedTuple):
    fn: Callable
    args_of: Callable[[str, dict], tuple]  # (project id, event) -> the workflow's arguments
    queue: str
    timeout_runs: float  # the workflow's time limit, in agent-run budgets (`AGENT_RUN_BUDGET["timeout_s"]`)


# the registry `AgentRuntime.start` enqueues from (events.emit by trigger, the approvals route by name)
WORKFLOWS: dict[str, WorkflowSpec] = {
    "digest_run": WorkflowSpec(digest_run, lambda pid, ev: (pid, ev["branch_id"], ev["run_key"], ev), DIGEST_QUEUE, 1),
    "answer": WorkflowSpec(answer, lambda pid, ev: (pid, ev["thread_id"], ev["message_id"]), CHAT_QUEUE, 3),
    "answer_resume": WorkflowSpec(answer_resume, lambda pid, ev: (pid, ev["thread_id"], ev["message_id"]), CHAT_QUEUE, 1),
}
