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
from .roster import SPECIALISTS
from .schemas import HealthBrief, ReviewComment, SpecialistReport, StewardPlan
from .streaming import stage_of
from .tools import merge_summary, proposal_text

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


def _sum_usage(*usages: dict) -> dict:
    """One run's usage from its model calls (the steward's triage and its brief)."""
    costs = [u["cost_credits"] for u in usages if u.get("cost_credits") is not None]
    return {"input_tokens": sum(u.get("input_tokens", 0) for u in usages), "output_tokens": sum(u.get("output_tokens", 0) for u in usages),
            "cost_credits": sum(costs) if costs else None}


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


# --- the steward: triage an event, run specialists, write the brief --------------------------------------------
@DBOS.workflow()
def steward_run(project_id: str, event: dict) -> dict:
    rt = _rt()
    run_id = DBOS.workflow_id or f"steward:{event.get('dedup_id', 'local')}"
    begun = _begin(run_id, project_id, kind="steward", agent="steward", branch_id=event.get("branch_id"), event_id=event.get("event_id"))
    if begun["paused"]:
        return {"run_id": run_id, "status": "skipped_paused", "reason": begun["reason"]}
    skip = events.nothing_to_triage(event)
    if skip:  # a clean run: no specialist to send, so no triage call, no brief (the reviewer still comments)
        _finish(run_id, project_id, status="skipped", summary=skip)
        return {"run_id": run_id, "status": "skipped", "reason": skip}
    allowed = [s for s in event.get("allowed_specialists", []) if s in SPECIALISTS]
    try:
        deps = rt.deps_for(run_id, project_id=project_id, branch_id=event.get("branch_id"))
        prompt = (f"Event: {json.dumps({k: v for k, v in event.items() if k not in ('allowed_specialists',)}, default=str)}\n"
                  f"Allowed specialists now: {', '.join(allowed) or 'none'}. Each studies: {rt.remits()}.\n"
                  "Read the project overview and the open findings, then plan.")
        triage = rt.agents["steward"].run_sync(prompt, deps=deps, usage_limits=_limits())
        plan: StewardPlan = triage.output
        reports = []
        for i, req in enumerate(plan.specialists):
            if req.kind not in allowed:
                continue
            with SetWorkflowID(f"{run_id}:{i}:{req.kind}"):
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

        def store():
            # the brief cites its specialists' steps: every bracket becomes a chip the planner renders, or goes
            cited = [s["step_id"] for s in rt.evidence.steps(run_id)] + [sid for r in reports for sid in (r.get("steps") or [])]
            text = normalize_citations(f"{brief.headline}\n\n{brief.body}", cited)
            # what was not studied and what to check next travel as data (the planner collapses one and offers the other
            # as questions), never as a wall of prose at the end of the brief
            gaps = list(brief.not_studied) + sorted({x for r in reports for x in (r.get("not_studied") or []) if x not in brief.not_studied})
            with rt.harness.store.cursor() as con:
                health = next((t for t in threads.list_threads(con, project_id, kind="health")), None) or threads.create_thread(con, project_id, None, "Project health", kind="health")
                threads.add_message(con, health["thread_id"], "assistant", text, run_id=run_id,
                                    evidence={"event": event.get("type"), "reports": reports, "not_studied": gaps, "next_checks": list(brief.next_checks)})
            return True
        _step(store)
        _finish(run_id, project_id, status="done", summary=strip_citations(brief.headline), usage=_sum_usage(_usage(triage), _usage(res)),
                solves=deps.solves + brief_deps.solves)
        return {"run_id": run_id, "status": "done", "headline": brief.headline, "specialists": [r.get("kind") for r in reports]}
    except Exception as e:
        _finish(run_id, project_id, status="failed", error=f"{type(e).__name__}: {e}")
        raise


@DBOS.workflow()
def specialist_run(project_id: str, kind: str, scope: dict, parent_run_id: str) -> dict:
    rt = _rt()
    run_id = DBOS.workflow_id or f"{parent_run_id}:{kind}"
    branch_id = scope.get("branch_id") or rt.harness.projects.main_id(project_id)  # the project's own main, never NGED's
    begun = _begin(run_id, project_id, kind="specialist", agent=kind, branch_id=branch_id, parent=parent_run_id)
    if begun["paused"]:
        return {"kind": kind, "run_id": run_id, "status": "skipped_paused"}
    try:
        deps = rt.deps_for(run_id, project_id=project_id, branch_id=branch_id, allowed=rt.studies_for(kind))
        prompt = (f"Study branch '{branch_id}'. Why you were asked: {scope.get('why', '')} (event: {scope.get('event', '')}).\n"
                  f"Your studies: {', '.join(rt.studies_for(kind))}. Keep the scope small enough for the run budget.")
        res = rt.agents[kind].run_sync(prompt, deps=deps, usage_limits=_limits())
        report: SpecialistReport = res.output
        # what the report still lists is bound here; what the specialist filed as it went (`file_finding`) is already in the ledger
        fps = _step(lambda: rt.evidence.bind_findings(run_id, branch_id, report.findings, snapshot_id=rt.harness.warehouse.baseline_id(), at=now()))
        fps = list(dict.fromkeys([*deps.context.get("filed", []), *fps]))
        _finish(run_id, project_id, status="done", summary=strip_citations(report.summary), usage=_usage(res), solves=deps.solves)

        def recorded():
            """The run's steps, and what was not studied as the harness computes it: the model's few items plus the
            studies in this specialist's remit it did not run (or that were refused)."""
            steps = rt.evidence.steps(run_id)
            ran = {s["tool"].removeprefix("study_") for s in steps
                   if s["tool"].startswith("study_") and not (isinstance(s.get("result"), dict) and s["result"].get("refused"))}
            not_run = [f"{k} was not run" for k in rt.studies_for(kind) if k not in ran]
            return {"steps": [s["step_id"] for s in steps], "not_studied": list(report.not_studied) + not_run}
        rec = _step(recorded)
        return {"kind": kind, "run_id": run_id, "status": "done", "summary": report.summary, "n_findings": len(fps), "not_studied": rec["not_studied"],
                "steps": rec["steps"]}
    except Exception as e:
        _finish(run_id, project_id, status="failed", error=f"{type(e).__name__}: {e}")
        raise


# --- the reviewer: a comment on every branch run, like a PR bot --------------------------------------------------------
@DBOS.workflow()
def review_branch(project_id: str, branch_id: str, run_key: str) -> dict:
    rt = _rt()
    run_id = DBOS.workflow_id or f"review:{branch_id}:{run_key}"
    def superseded() -> bool:
        """The branch has moved on (a newer run, or new inputs) since this run: its review is not current."""
        return rt.harness.plans.freshness(branch_id).years_key != run_key

    def gate():
        with rt.harness.store.cursor() as con:
            if runs.review_exists(con, branch_id, run_key) or superseded():
                return None
            runs.supersede_reviews(con, branch_id, run_key)
            older = [(rid, wid) for rid, wid in runs.open_runs_of(con, branch_id, "review") if rid != run_id]
            head = repository.require_branch(con, branch_id)
            base = repository.base_of(con, head)
        for rid, wid in older:  # a review of an earlier run still being written: `store` would throw it away, so stop paying for it
            if wid:
                DBOS.cancel_workflow(wid)
        if older:
            with rt.harness.store.cursor() as con:
                for rid, _wid in older:
                    runs.close_run(con, rid, status="cancelled", error="superseded by a newer run")
        if base is None:  # a project's main merges nowhere: nothing to review
            return None
        with rt.harness.solver_gate.hold():
            verdict, evidence = rt.harness.plans.merge_check(branch_id, base["branch_id"])
        mc = merge_summary(base["branch_id"], verdict, evidence)
        # the same plan (run key) judged against the same parent plan (base key) on another branch of the project has
        # a current review already: its words hold here too, so it is copied, not bought again
        prior = None
        if mc.get("base_years_key"):
            with rt.harness.store.cursor() as con:
                prior = runs.review_for_run(con, project_id, run_key, mc["base_years_key"])
        return {"mc": mc, "inherit": prior if prior and prior["branch_id"] != branch_id else None}
    gated = _step(gate)
    if gated is None:
        return {"run_id": run_id, "status": "skipped", "reason": "already reviewed, superseded by a newer run, or a main (it merges nowhere)"}
    mc, prior = gated["mc"], gated["inherit"]
    begun = _begin(run_id, project_id, kind="review", agent="reviewer", branch_id=branch_id)
    if begun["paused"]:
        return {"run_id": run_id, "status": "skipped_paused"}
    if prior is not None:
        def copy():
            if superseded():
                return None
            with rt.harness.store.cursor() as con:
                return runs.insert_review(con, project_id=project_id, branch_id=branch_id, run_key=run_key, run_id=run_id, verdict=prior["verdict"],
                                          verdict_json=mc, body=prior["body"] + f"\n\nThe same plan against the same parent was reviewed on branch "
                                          f"{prior['branch_id']} (review {prior['review_id']}); this is that comment, inherited.",
                                          blockers=prior.get("blockers") or [], warnings=prior.get("warnings") or [], not_studied=prior.get("not_studied") or [])
        row = _step(copy)
        _finish(run_id, project_id, status="done" if row else "skipped",
                summary=f"inherited the review of the same plan from {prior['branch_id']}" if row else "superseded by a newer run before it was stored")
        return {"run_id": run_id, "status": "done" if row else "skipped", "inherited_from": prior["review_id"]}
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
            body = normalize_citations(review.body, [s["step_id"] for s in rt.evidence.steps(run_id)])
            with rt.harness.store.cursor() as con:
                return runs.insert_review(con, project_id=project_id, branch_id=branch_id, run_key=run_key, run_id=run_id, verdict=review.verdict_restated,
                                          verdict_json=mc, body=body, blockers=[b.model_dump() for b in review.blockers],
                                          warnings=[w.model_dump() for w in review.warnings], not_studied=review.not_studied)
        row = _step(store)
        if row is None:
            _finish(run_id, project_id, status="skipped", summary="superseded by a newer run before it was stored", usage=_usage(res), solves=deps.solves)
            return {"run_id": run_id, "status": "skipped", "reason": "superseded by a newer run"}
        _finish(run_id, project_id, status="done", summary=strip_citations(review.body)[:200], usage=_usage(res), solves=deps.solves)
        return {"run_id": run_id, "status": "done", "review_id": row["review_id"], "verdict": review.verdict_restated}
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
        if settled["ran"]:  # an approved run is a run like any other: the reviewer (and the steward) hear about it, alike
            # workflow code, not a step: `emit` enqueues workflows, which DBOS refuses from inside a step (the event
            # row it writes is idempotent by its dedup id, so a replay of this line wakes nobody twice)
            events.emit(rt, "run.finished", {**settled["ran"]["event"], "project_id": project_id})
        _finish(run_id, project_id, status=done["status"] if done["status"] == "cancelled" else "done", summary=done.get("text", "")[:200], usage=_usage(res), solves=deps.solves)
        _close(run_id, {"t": "final", "status": done["status"], "text": done.get("text", ""), "approvals": done.get("approvals", []), "flags": done.get("flags", []), "seq": FINAL_SEQ})
        return {"run_id": run_id, "reply_id": loaded["reply_id"], **done}
    except Exception as e:
        _failed(rt, run_id, project_id, loaded["reply_id"], e)
        raise


STEWARD_QUEUE = "steward"  # partitioned by project: one steward activity per project at a time
CHAT_QUEUE = "chat"  # reviews and answers: a few at once


class WorkflowSpec(NamedTuple):
    fn: Callable
    args_of: Callable[[str, dict], tuple]  # (project id, event) -> the workflow's arguments
    queue: str
    timeout_runs: float  # the workflow's time limit, in agent-run budgets (`AGENT_RUN_BUDGET["timeout_s"]`)


# the registry `AgentRuntime.start` enqueues from (events.emit by trigger, the approvals route by name)
WORKFLOWS: dict[str, WorkflowSpec] = {
    "steward_run": WorkflowSpec(steward_run, lambda pid, ev: (pid, ev), STEWARD_QUEUE, 3),  # the triage, its specialists and the brief
    "review_branch": WorkflowSpec(review_branch, lambda pid, ev: (pid, ev["branch_id"], ev["run_key"]), CHAT_QUEUE, 3),
    "answer": WorkflowSpec(answer, lambda pid, ev: (pid, ev["thread_id"], ev["message_id"]), CHAT_QUEUE, 3),
    "answer_resume": WorkflowSpec(answer_resume, lambda pid, ev: (pid, ev["thread_id"], ev["message_id"]), CHAT_QUEUE, 1),
}
