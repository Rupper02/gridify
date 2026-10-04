"""The durable workflows: one per kind of agent run. Each is bounded, idempotent by its workflow id,
and does its I/O in steps (`DBOS.run_step`), so a restart resumes it from the last completed step and
a replayed step runs nothing twice. Workflow code reads only its arguments and step outputs.

The runtime that owns the collaborators is looked up through `RUNTIME`, set by `AgentRuntime.launch`
(the composition root), never imported from `deps`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from dbos import DBOS, SetWorkflowID
from pydantic_ai import DeferredToolRequests, DeferredToolResults, ModelMessagesTypeAdapter, ToolApproved, ToolDenied, UsageLimits

from .. import repository
from ..config import AGENT_RUN_BUDGET, now
from . import runs, threads
from .evidence import check_numbers
from .roster import SPECIALISTS
from .schemas import HealthBrief, ReviewComment, SpecialistReport, StewardPlan

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
    return UsageLimits(request_limit=AGENT_RUN_BUDGET["max_tool_calls"] + 4, tool_calls_limit=AGENT_RUN_BUDGET["max_tool_calls"])


def _usage(res) -> dict:
    u = res.usage  # a property in Pydantic AI 2.x
    return {"input_tokens": int(u.input_tokens or 0), "output_tokens": int(u.output_tokens or 0), "cost_credits": float(u.cost) if getattr(u, "cost", None) is not None else None}


def _begin(run_id: str, project_id: str, *, kind: str, agent: str, branch_id=None, thread_id=None, event_id=None, parent=None) -> dict:
    """Record the run and check the day's budget; a paused or exhausted project skips the run."""
    rt = _rt()

    def do():
        state = rt.budget.check(project_id)
        with rt.harness.store.cursor() as con:
            runs.start_run(con, run_id=run_id, project_id=project_id, kind=kind, agent=agent, workflow_id=DBOS.workflow_id, branch_id=branch_id,
                           thread_id=thread_id, event_id=event_id, parent_run_id=parent, model=rt.model_name(agent),
                           status="skipped_budget" if state.paused else "running")
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
            rt.budget.charge(project_id, tokens=u.get("input_tokens", 0) + u.get("output_tokens", 0), cost_credits=u.get("cost_credits"), solves=solves)
        return True
    _step(do)


# --- the steward: triage an event, run specialists, write the brief --------------------------------------------
@DBOS.workflow()
def steward_run(project_id: str, event: dict) -> dict:
    rt = _rt()
    run_id = DBOS.workflow_id or f"steward:{event.get('dedup_id', 'local')}"
    begun = _begin(run_id, project_id, kind="steward", agent="steward", branch_id=event.get("branch_id"), event_id=event.get("event_id"))
    if begun["paused"]:
        return {"run_id": run_id, "status": "skipped_budget", "reason": begun["reason"]}
    allowed = [s for s in event.get("allowed_specialists", []) if s in SPECIALISTS]
    try:
        deps = rt.deps_for(run_id, project_id=project_id, branch_id=event.get("branch_id"))
        prompt = (f"Event: {json.dumps({k: v for k, v in event.items() if k not in ('allowed_specialists',)}, default=str)}\n"
                  f"Allowed specialists now: {', '.join(allowed) or 'none'}. Each studies: {rt.remits()}.\n"
                  "Read the project overview and the open findings, then plan.")
        plan: StewardPlan = rt.agents["steward"].run_sync(prompt, deps=deps, usage_limits=_limits()).output
        reports = []
        for req in plan.specialists:
            if req.kind not in allowed:
                continue
            with SetWorkflowID(f"{run_id}:{req.kind}"):
                handle = DBOS.start_workflow(specialist_run, project_id, req.kind, {"branch_id": req.branch_id or event.get("branch_id"), "why": req.why, "event": event.get("type")}, run_id)
            try:
                reports.append(handle.get_result())
            except Exception as e:  # one specialist failing is a line in the brief, not the end of the sweep
                reports.append({"kind": req.kind, "status": "failed", "error": f"{type(e).__name__}: {e}"[:300]})
        brief_prompt = (f"Event: {event.get('type')}. Your triage note: {plan.note}\n"
                        f"Specialist reports: {json.dumps(reports, default=str)}\nWrite the HealthBrief.")
        brief_deps = rt.deps_for(run_id, project_id=project_id, branch_id=event.get("branch_id"))
        res = rt.agents["steward_brief"].run_sync(brief_prompt, deps=brief_deps, usage_limits=_limits())
        brief: HealthBrief = res.output
        text = f"{brief.headline}\n\n{brief.body}" + (f"\n\nNot studied: {'; '.join(brief.not_studied)}" if brief.not_studied else "") \
            + (f"\n\nNext checks: {'; '.join(brief.next_checks)}" if brief.next_checks else "")

        def store():
            with rt.harness.store.cursor() as con:
                health = next((t for t in threads.list_threads(con, project_id, kind="health")), None) or threads.create_thread(con, project_id, None, "Project health", kind="health")
                threads.add_message(con, health["thread_id"], "assistant", text, run_id=run_id, evidence={"event": event.get("type"), "reports": reports})
            return True
        _step(store)
        _finish(run_id, project_id, status="done", summary=brief.headline, usage=_usage(res), solves=deps.solves + brief_deps.solves)
        return {"run_id": run_id, "status": "done", "headline": brief.headline, "specialists": [r.get("kind") for r in reports]}
    except Exception as e:
        _finish(run_id, project_id, status="failed", error=f"{type(e).__name__}: {e}")
        raise


@DBOS.workflow()
def specialist_run(project_id: str, kind: str, scope: dict, parent_run_id: str) -> dict:
    rt = _rt()
    run_id = DBOS.workflow_id or f"{parent_run_id}:{kind}"
    branch_id = scope.get("branch_id") or "main"
    begun = _begin(run_id, project_id, kind="specialist", agent=kind, branch_id=branch_id, parent=parent_run_id)
    if begun["paused"]:
        return {"kind": kind, "run_id": run_id, "status": "skipped_budget"}
    try:
        deps = rt.deps_for(run_id, project_id=project_id, branch_id=branch_id, allowed=rt.studies_for(kind))
        prompt = (f"Study branch '{branch_id}'. Why you were asked: {scope.get('why', '')} (event: {scope.get('event', '')}).\n"
                  f"Your studies: {', '.join(rt.studies_for(kind))}. Keep the scope small enough for the run budget.")
        res = rt.agents[kind].run_sync(prompt, deps=deps, usage_limits=_limits())
        report: SpecialistReport = res.output
        fps = _step(lambda: rt.evidence.bind_findings(run_id, branch_id, report.findings, snapshot_id=rt.harness.warehouse.baseline_id(), at=now()))
        _finish(run_id, project_id, status="done", summary=report.summary, usage=_usage(res), solves=deps.solves)
        return {"kind": kind, "run_id": run_id, "status": "done", "summary": report.summary, "n_findings": len(fps), "not_studied": report.not_studied,
                "steps": [s["step_id"] for s in rt.evidence.steps(run_id)]}
    except Exception as e:
        _finish(run_id, project_id, status="failed", error=f"{type(e).__name__}: {e}")
        raise


# --- the reviewer: a comment on every branch run, like a PR bot --------------------------------------------------------
@DBOS.workflow()
def review_branch(project_id: str, branch_id: str, run_key: str) -> dict:
    rt = _rt()
    run_id = DBOS.workflow_id or f"review:{branch_id}:{run_key}"
    if branch_id == "main":
        return {"run_id": run_id, "status": "skipped", "reason": "main is not reviewed; branches are"}

    def superseded() -> bool:
        """The branch has moved on (a newer run, or new inputs) since this run: its review is not current."""
        return rt.harness.plans.freshness(branch_id).years_key != run_key

    def gate():
        with rt.harness.store.cursor() as con:
            if runs.review_exists(con, branch_id, run_key) or superseded():
                return None
            runs.supersede_reviews(con, branch_id, run_key)
            head = repository.require_branch(con, branch_id)
            base = repository.base_of(con, head)
        with rt.harness.solver_gate.hold():
            verdict, evidence = rt.harness.plans.merge_check(branch_id, base["branch_id"])
        short = lambda f: {"kind": f.kind, "year": f.year, "element_kind": f.element_kind, "element_id": f.element_id, "value": f.value, "limit": f.limit,  # noqa: E731
                           "fingerprint": f.finding_fingerprint, "message": f.message}
        return {"into": base["branch_id"], "fresh": evidence["fresh"], "ok": verdict.ok, "summary": verdict.summary,
                "blockers": [short(f) for f in verdict.blockers], "warnings": [short(f) for f in verdict.warnings], "n_context": len(verdict.context)}
    mc = _step(gate)
    if mc is None:
        return {"run_id": run_id, "status": "skipped", "reason": "already reviewed, or superseded by a newer run"}
    begun = _begin(run_id, project_id, kind="review", agent="reviewer", branch_id=branch_id)
    if begun["paused"]:
        return {"run_id": run_id, "status": "skipped_budget"}
    try:
        deps = rt.deps_for(run_id, project_id=project_id, branch_id=branch_id, allowed=rt.studies_for("reviewer"))
        deps.context["merge_check"] = mc
        prompt = (f"Review branch '{branch_id}' against '{mc['into']}'. The merge gate says:\n{json.dumps(mc, default=str)}\n"
                  "Read the diff and the findings if you need context, then write the ReviewComment.")
        res = rt.agents["reviewer"].run_sync(prompt, deps=deps, usage_limits=_limits())
        review: ReviewComment = res.output

        def store():
            if superseded():  # a newer run finished while this review was written: it is not the current one
                return None
            with rt.harness.store.cursor() as con:
                return runs.insert_review(con, project_id=project_id, branch_id=branch_id, run_key=run_key, run_id=run_id, verdict=review.verdict_restated,
                                          verdict_json=mc, body=review.body, blockers=[b.model_dump() for b in review.blockers],
                                          warnings=[w.model_dump() for w in review.warnings], not_studied=review.not_studied)
        row = _step(store)
        if row is None:
            _finish(run_id, project_id, status="skipped", summary="superseded by a newer run before it was stored", usage=_usage(res), solves=deps.solves)
            return {"run_id": run_id, "status": "skipped", "reason": "superseded by a newer run"}
        _finish(run_id, project_id, status="done", summary=review.body[:200], usage=_usage(res), solves=deps.solves)
        return {"run_id": run_id, "status": "done", "review_id": row["review_id"], "verdict": review.verdict_restated}
    except Exception as e:
        _finish(run_id, project_id, status="failed", error=f"{type(e).__name__}: {e}")
        raise


# --- the answerer: an operator's question, streamed --------------------------------------------------------------------
def _dump_messages(msgs) -> list:
    return ModelMessagesTypeAdapter.dump_python(msgs, mode="json")


def _close(run_id: str, final: dict) -> None:
    rt = _rt()
    rt.emit_for(run_id)(final)
    if rt.harness.in_workflow():
        DBOS.close_stream("events")


def _answered(rt: AgentRuntime, project_id: str, thread_id: str, message_id: str, run_id: str, res, deps) -> dict:
    """Store the answerer's result: a text answer (flags for figures no step produced), or the
    proposals that wait for the operator's approval."""
    out = res.output
    step_outputs = [s.get("result") for s in rt.evidence.steps(run_id) if s.get("result") is not None]
    trace = [{"step_id": s["step_id"], "tool": s["tool"], "args": s["args"], "solves": s.get("solves", 0)} for s in rt.evidence.steps(run_id)]
    evidence = {"steps": [t["step_id"] for t in trace], "branch_id": deps.branch_id, "snapshot_id": rt.harness.warehouse.baseline_id(), "engine": rt.evidence.engine}
    if isinstance(out, DeferredToolRequests):
        approvals = []
        with rt.harness.store.cursor() as con:
            for call in out.approvals:
                approvals.append(runs.add_approval(con, project_id=project_id, thread_id=thread_id, message_id=message_id, run_id=run_id,
                                                   tool_call_id=call.tool_call_id, tool=call.tool_name, args=call.args_as_dict()))
            text = "I propose: " + "; ".join(f"{a['tool']} {json.dumps(a['args'])}" for a in approvals) + ". Waiting for your approval."
            threads.set_message(con, message_id, status="awaiting_approval", content=text, tool_trace=trace, model_messages=_dump_messages(res.all_messages()),
                                usage=_usage(res), cost_credits=_usage(res)["cost_credits"], evidence=evidence)
        return {"status": "awaiting_approval", "approvals": [a["approval_id"] for a in approvals], "text": text}
    text = str(out)
    flags = [f"figure {n:g} appears in no tool output of this run" for n in check_numbers(text, step_outputs)]
    with rt.harness.store.cursor() as con:
        threads.set_message(con, message_id, status="done", content=text, tool_trace=trace, model_messages=_dump_messages(res.all_messages()),
                            usage=_usage(res), cost_credits=_usage(res)["cost_credits"], flags=flags, evidence=evidence)
    return {"status": "done", "text": text, "flags": flags}


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
            return {"question": question["content"] if question else "", "history": threads.history(con, thread_id, before_seq=reply["seq"]), "branch_id": t["branch_id"] if t else None}
    loaded = _step(load)
    begun = _begin(run_id, project_id, kind="answer", agent="answerer", branch_id=loaded["branch_id"], thread_id=thread_id)
    if begun["paused"]:
        with rt.harness.store.cursor() as con:
            threads.set_message(con, message_id, status="failed", content=f"The agents are paused ({begun['reason']}).")
        _close(run_id, {"t": "final", "status": "failed", "seq": 10_000})
        return {"run_id": run_id, "status": "skipped_budget"}
    try:
        deps = rt.deps_for(run_id, project_id=project_id, branch_id=loaded["branch_id"], thread_id=thread_id, allowed=rt.studies_for("answerer"))
        history = ModelMessagesTypeAdapter.validate_python(loaded["history"]) if loaded["history"] else None
        res = rt.agents["answerer"].run_sync(loaded["question"], deps=deps, message_history=history, usage_limits=_limits())
        done = _step(lambda: _answered(rt, project_id, thread_id, message_id, run_id, res, deps))
        _finish(run_id, project_id, status="done", summary=done.get("text", "")[:200], usage=_usage(res), solves=deps.solves)
        _close(run_id, {"t": "final", "status": done["status"], "text": done.get("text", ""), "approvals": done.get("approvals", []), "flags": done.get("flags", []), "seq": 10_000})
        return {"run_id": run_id, **done}
    except Exception as e:
        with rt.harness.store.cursor() as con:
            threads.set_message(con, message_id, status="failed", content=f"The answer failed: {type(e).__name__}: {e}")
        _finish(run_id, project_id, status="failed", error=f"{type(e).__name__}: {e}")
        _close(run_id, {"t": "error", "message": str(e), "seq": 10_000})
        raise


@DBOS.workflow()
def answer_resume(project_id: str, thread_id: str, message_id: str, approval_id: str, approved: bool, note: str) -> dict:
    """Continue an answer whose proposal the operator decided: the deferred tool runs (or is denied)."""
    rt = _rt()
    run_id = DBOS.workflow_id or f"resume:{approval_id}"

    def load():
        with rt.harness.store.cursor() as con:
            a = runs.approval_row(con, approval_id)
            prior = threads.message_row(con, message_id)
            reply = threads.add_message(con, thread_id, "assistant", "", status="streaming", run_id=run_id, workflow_id=DBOS.workflow_id)
            t = threads.thread_row(con, thread_id)
            return {"approval": a, "history": prior["model_messages"] or [], "reply_id": reply["message_id"], "branch_id": t["branch_id"] if t else None}
    loaded = _step(load)
    a = loaded["approval"]
    begun = _begin(run_id, project_id, kind="answer", agent="answerer", branch_id=loaded["branch_id"], thread_id=thread_id, parent=a["run_id"])
    if begun["paused"]:
        return {"run_id": run_id, "status": "skipped_budget"}
    try:
        deps = rt.deps_for(run_id, project_id=project_id, branch_id=loaded["branch_id"], thread_id=thread_id, allowed=rt.studies_for("answerer"))
        decision: Any = ToolApproved() if approved else ToolDenied(message=f"The operator declined: {note or 'no reason given'}")
        results = DeferredToolResults(approvals={a["tool_call_id"]: decision})
        res = rt.agents["answerer"].run_sync(None, deps=deps, message_history=ModelMessagesTypeAdapter.validate_python(loaded["history"]),
                                             deferred_tool_results=results, usage_limits=_limits())
        done = _step(lambda: _answered(rt, project_id, thread_id, loaded["reply_id"], run_id, res, deps))

        def settle():
            with rt.harness.store.cursor() as con:
                runs.set_approval_result(con, approval_id, "applied" if approved else "denied", {"status": done["status"]})
            return True
        _step(settle)
        _finish(run_id, project_id, status="done", summary=done.get("text", "")[:200], usage=_usage(res), solves=deps.solves)
        _close(run_id, {"t": "final", "status": done["status"], "text": done.get("text", ""), "seq": 10_000})
        return {"run_id": run_id, "reply_id": loaded["reply_id"], **done}
    except Exception as e:
        with rt.harness.store.cursor() as con:
            threads.set_message(con, loaded["reply_id"], status="failed", content=f"The answer failed: {type(e).__name__}: {e}")
        _finish(run_id, project_id, status="failed", error=f"{type(e).__name__}: {e}")
        _close(run_id, {"t": "error", "message": str(e), "seq": 10_000})
        raise


# the registry events.emit starts workflows from: name -> (workflow, how to build its arguments from the event)
WORKFLOWS = {
    "steward_run": (steward_run, lambda pid, ev: (pid, ev)),
    "review_branch": (review_branch, lambda pid, ev: (pid, ev["branch_id"], ev["run_key"])),
    "answer": (answer, lambda pid, ev: (pid, ev["thread_id"], ev["message_id"])),
}
