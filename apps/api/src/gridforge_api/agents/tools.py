"""The tools the agents may call. Three groups, each a `FunctionToolset` with a stable id:

* `read`: lookups on the project (branches, queue, plan years, diff, merge check, findings, suggestions);
* `studies`: one tool per `studies.STUDIES` entry, run through `PlanService.study` with the solver gate
  taken per chunk (one power flow at a time, operators first) and recorded as evidence; a study outside
  the agent's remit or over its solve budget is refused in the tool's answer, never raised;
* `proposals`: actions that wait for the operator's approval (a branch, a reinforcement, a works window).

Every tool body runs as a durable step when it is called inside a DBOS workflow and plainly outside one,
and every call is recorded in `agent_steps` with its arguments and output (or its cache key), so a
figure an agent states can be traced to the call that produced it. Nothing here can merge or discard.
"""

from __future__ import annotations

import inspect
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from gridforge_optimizer import STUDIES

from .. import ledger, repository
from ..config import AGENT_RUN_BUDGET, SOLVER_GATE_MAX_WAIT_S, now
from ..schemas import OutageCreate, ReinforcementCreate
from .evidence import EvidenceLedger

TOP_ITEMS = 25  # how many study items a tool returns to the model (the full study stays in the cache)


class SolverGate:
    """One power flow at a time in the process, operators first: wait while an operator's job is queued
    or running (bounded), then take the lock every power flow runs under."""

    def __init__(self, jobs, lock: threading.RLock, max_wait_s: float = SOLVER_GATE_MAX_WAIT_S):
        self._jobs = jobs
        self._lock = lock
        self.max_wait_s = max_wait_s

    @contextmanager
    def hold(self):
        t0 = time.monotonic()
        while self._jobs.busy():
            if time.monotonic() - t0 > self.max_wait_s:
                raise TimeoutError("an operator's job has had the solver for too long; try again later")
            time.sleep(0.5)
        with self._lock:
            yield


@dataclass
class Harness:
    """The collaborators the tools work with, handed in once by the runtime (never imported from deps)."""

    plans: Any
    store: Any
    warehouse: Any
    projects: Any  # the grids planned on (baselines, main branches)
    evidence: EvidenceLedger
    solver_gate: SolverGate
    project_id: str
    in_workflow: Callable[[], bool] = lambda: False
    durable: Callable[[str, Callable[[], Any]], Any] = lambda name, fn: fn()


@dataclass
class AgentDeps:
    """What one agent run carries: its ids, its scope, its budget counters and its event sink."""

    h: Harness
    run_id: str
    project_id: str = ""
    main_id: str = "main"  # the project's plan of record (what a tool reads when no branch is named)
    branch_id: str | None = None
    thread_id: str | None = None
    allowed_studies: tuple[str, ...] = tuple(STUDIES)
    emit: Callable[[dict], None] = lambda ev: None
    emit_async: Callable[[dict], Any] | None = None  # set by the runtime (an awaitable sink for the event handler)
    budget: dict = field(default_factory=lambda: dict(AGENT_RUN_BUDGET))
    tool_calls: int = 0
    solves: int = 0
    seq: int = 0
    context: dict = field(default_factory=dict)  # what a validator may need (e.g. the merge check)

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


# --- the recorded step every tool runs through --------------------------------------------------------------
def _recorded(ctx: RunContext[AgentDeps], tool: str, args: dict, work: Callable[[], tuple[dict, str | None, int]]) -> dict:
    """Run `work` (payload, cache key, solves) as a durable step, record it as evidence, and return the
    payload with its step id, the handle the model cites and a finding names."""
    deps = ctx.deps
    deps.tool_calls += 1
    if deps.tool_calls > deps.budget["max_tool_calls"]:  # an answer, not a retry: the model must now write up what it has
        return {"refused": "the tool-call budget for this run is spent: answer with what you have, and say what was not studied", "solves": 0}
    step_id = f"{deps.run_id}:{ctx.tool_call_id or uuid.uuid4().hex[:8]}"
    seq = deps.next_seq()

    def step() -> dict:
        t0 = now()
        try:
            payload, key, solves = work()
            err = None
        except Exception as e:  # the step records the failure and the model hears it
            payload, key, solves, err = {"error": f"{type(e).__name__}: {e}"}, None, 0, str(e)
        deps.h.evidence.record_step(run_id=deps.run_id, step_id=step_id, seq=seq, tool=tool, args=args, cache_key=key,
                                    result=payload, solves=solves, started_at=t0, finished_at=now(), error=err)
        return {"step_id": step_id, **payload, "solves": solves}

    out = deps.h.durable(f"tool:{tool}", step)
    deps.solves += int(out.get("solves", 0))
    return out


def _branch(ctx: RunContext[AgentDeps], branch_id: str | None) -> str:
    return branch_id or ctx.deps.branch_id or ctx.deps.main_id


# --- read tools -------------------------------------------------------------------------------------------------
def build_read_tools() -> FunctionToolset[AgentDeps]:
    ts: FunctionToolset[AgentDeps] = FunctionToolset(id="read")

    @ts.tool
    def project_overview(ctx: RunContext[AgentDeps]) -> dict:
        """The project at a glance: its branches, its main's open findings by severity, the budget left for this run."""
        def work():
            h, d = ctx.deps.h, ctx.deps
            with h.store.cursor() as con:
                ids = repository.branch_ids(con, d.project_id)
                branches = [b for b in (repository.branch_to_client(con, repository.branch_row(con, i)) for i in ids) if b["status"] == "open"]
                counts = ledger.counts(con, d.main_id)
            return ({"project_id": d.project_id, "main_branch": d.main_id, "branches": [{k: b[k] for k in ("branch_id", "name", "scenario", "n_added", "status")} for b in branches],
                     "main_findings": counts, "snapshot_id": h.projects.baseline(d.project_id),
                     "run_budget_left": {"tool_calls": ctx.deps.budget["max_tool_calls"] - ctx.deps.tool_calls,
                                         "solves": ctx.deps.budget["max_solves"] - ctx.deps.solves}}, None, 0)
        return _recorded(ctx, "project_overview", {}, work)

    @ts.tool
    def queue(ctx: RunContext[AgentDeps], branch_id: str | None = None) -> dict:
        """A branch's connection queue as the last run left it: each project's status, phase, recommended year and binding reason; plus the 2030 and 2035 phase figures."""
        bid = _branch(ctx, branch_id)

        def work():
            r = ctx.deps.h.plans.branch_result(bid)
            q = [{"request_id": x.request_id, "status": x.status, "technology": x.technology, "rating_mw": x.rating_mw, "bus_id": x.bus_id,
                  "recommended_year": x.recommended_year, "reason": x.reason.message if x.reason else None} for x in r.queue]
            phases = {k: {"accepted": len(p.accepted), "worst_line_loading_pct": p.worst_line_loading_pct, "worst_trafo_loading_pct": p.worst_trafo_loading_pct,
                          "min_vm_pu": p.min_vm_pu, "max_vm_pu": p.max_vm_pu, "gsp_export_mw": p.gsp_export_mw, "gsp_limit_mw": p.gsp_limit_mw,
                          "n1_findings": len(p.n1_violations)} for k, p in r.phases.items()}
            return ({"branch_id": bid, "queue": q, "phases": phases, "summary": f"{len(q)} projects: " + ", ".join(
                f"{s} {sum(1 for x in q if x['status'] == s)}" for s in ("Phase1", "Phase2", "Deferred", "Rejected"))}, None, 0)
        return _recorded(ctx, "queue", {"branch_id": bid}, work)

    @ts.tool
    def plan_year(ctx: RunContext[AgentDeps], year: int, branch_id: str | None = None) -> dict:
        """One plan year of a branch as solved: worst loadings, voltage range, GSP export against its limit, N-1 findings, demand alerts and works verdicts. Solves the years if they are not cached."""
        bid = _branch(ctx, branch_id)

        def work():
            h = ctx.deps.h
            with h.solver_gate.hold():
                res = h.plans.result_with_years(h.plans.inputs(bid))
            y = res.years.get(str(year))
            if y is None:
                return ({"branch_id": bid, "year": year, "error": "that year is not in the plan"}, None, 0)
            return ({"branch_id": bid, "year": year, "worst_line_loading_pct": y.worst_line_loading_pct, "worst_trafo_loading_pct": y.worst_trafo_loading_pct,
                     "min_vm_pu": y.min_vm_pu, "max_vm_pu": y.max_vm_pu, "overloaded_line_ids": y.overloaded_line_ids,
                     "voltage_violation_bus_ids": y.voltage_violation_bus_ids, "gsp_export_mw": y.gsp_export_mw, "gsp_limit_mw": y.gsp_limit_mw,
                     "n1_findings": [v.get("message") for v in y.n1_violations][:TOP_ITEMS], "alerts": [a.message for a in y.alerts][:TOP_ITEMS],
                     "works": [{"outage_id": s.outage_id, "verdict": s.verdict, "message": s.message} for s in y.outage_studies],
                     "energised": y.energised, "converged": y.converged,
                     "summary": f"{year}: worst line {y.worst_line_loading_pct:.0f}%, worst transformer {y.worst_trafo_loading_pct:.0f}%, "
                                f"voltage {y.min_vm_pu:.3f}-{y.max_vm_pu:.3f} pu, GSP export {y.gsp_export_mw:.0f} of {y.gsp_limit_mw or 0:.0f} MW, "
                                f"{len(y.n1_violations)} N-1 findings, {len(y.alerts)} customer alerts"}, None, 0)
        return _recorded(ctx, "plan_year", {"branch_id": bid, "year": year}, work)

    @ts.tool
    def merge_check(ctx: RunContext[AgentDeps], branch_id: str | None = None) -> dict:
        """The merge gate's verdict for a branch against its parent: fresh or stale, blockers, warnings, context. Solves the parent's years if they are not cached."""
        bid = _branch(ctx, branch_id)

        def work():
            h = ctx.deps.h
            with h.store.cursor() as con:
                head = repository.require_branch(con, bid)
                base = repository.base_of(con, head)
            with h.solver_gate.hold():
                verdict, evidence = h.plans.merge_check(bid, base["branch_id"])
            short = lambda f: {"kind": f.kind, "year": f.year, "element_kind": f.element_kind, "element_id": f.element_id, "value": f.value,  # noqa: E731
                               "limit": f.limit, "fingerprint": f.finding_fingerprint, "message": f.message}
            return ({"branch_id": bid, "into": base["branch_id"], "fresh": evidence["fresh"], "stale_reasons": evidence["stale_reasons"],
                     "ok": verdict.ok, "blockers": [short(f) for f in verdict.blockers], "warnings": [short(f) for f in verdict.warnings],
                     "n_context": len(verdict.context), "summary": verdict.summary}, None, 0)
        return _recorded(ctx, "merge_check", {"branch_id": bid}, work)

    @ts.tool
    def diff(ctx: RunContext[AgentDeps], branch_id: str | None = None) -> dict:
        """The consequence diff of a branch against its parent: MW connected by 2030 and 2035, who moved, and per plan year what newly overloads, clears, or changes at the GSP and in the N-1 screen."""
        bid = _branch(ctx, branch_id)

        def work():
            h = ctx.deps.h
            with h.store.cursor() as con:
                base = repository.base_of(con, repository.require_branch(con, bid))
            with h.solver_gate.hold():
                d = h.plans.diff(bid, base["branch_id"])
            years = {k: {"newly_overloaded_line_ids": y.newly_overloaded_line_ids, "newly_overloaded_trafo_ids": y.newly_overloaded_trafo_ids,
                         "cleared_line_ids": y.cleared_line_ids, "worst_line_delta": y.worst_line_delta, "gsp_export_head": y.gsp_export_head,
                         "gsp_export_delta": y.gsp_export_delta, "n1_findings_delta": y.n1_findings_delta} for k, y in d.years.items()}
            movers = [{"request_id": p.request_id, "change": p.change, "base_status": p.base_status, "head_status": p.head_status} for p in d.projects if p.change != "unchanged"]
            return ({"branch_id": bid, "into": base["branch_id"], "headline": d.headline, "movers": movers[:TOP_ITEMS], "years": years,
                     "works": [{"outage_id": w.outage_id, "year": w.year, "change": w.change, "consequence": w.consequence} for w in d.works],
                     "summary": f"MW by 2035 {d.headline.get('mw_2035_base')} -> {d.headline.get('mw_2035_head')}; {len(movers)} projects moved"}, None, 0)
        return _recorded(ctx, "diff", {"branch_id": bid}, work)

    @ts.tool
    def findings(ctx: RunContext[AgentDeps], branch_id: str | None = None, status: str = "open", kind: str | None = None, limit: int = 40) -> dict:
        """The findings ledger of a branch: what its last run (and earlier agents) found, breaches first. Filter by status (open | acknowledged | resolved) and kind."""
        bid = _branch(ctx, branch_id)

        def work():
            with ctx.deps.h.store.cursor() as con:
                rows = ledger.list_findings(con, bid, status=status if status in ledger.STATUSES else None)
                counts = ledger.counts(con, bid)
            if kind:
                rows = [r for r in rows if r["kind"] == kind]
            out = [{k: r[k] for k in ("finding_id", "fingerprint", "kind", "severity", "year", "element_kind", "element_id", "value", "limit", "message", "source")}
                   for r in rows[:int(limit)]]
            return ({"branch_id": bid, "counts": counts, "findings": out, "summary": f"{counts['open']} open ({counts['breach_open']} breaches, {counts['warn_open']} warnings); {len(out)} returned"}, None, 0)
        return _recorded(ctx, "findings", {"branch_id": bid, "status": status, "kind": kind, "limit": limit}, work)

    @ts.tool
    def suggestions(ctx: RunContext[AgentDeps], branch_id: str | None = None, request_id: str | None = None) -> dict:
        """The engine's "what would it take" levers for the projects a branch defers on the grid (or for one project): the reinforcement chain, the MW it frees and who connects. Measured by re-solving; costs solves."""
        bid = _branch(ctx, branch_id)

        def work():
            h = ctx.deps.h
            with h.solver_gate.hold():
                sugs = h.plans.suggestions(bid, 5, request_id)
            out = [{"target": f"{s.target_type} {s.target_element_id}", "action": s.action, "connects_target": s.connects_target,
                    "freed_mw_2030": s.freed_mw_2030, "freed_mw_2035": s.freed_mw_2035, "newly_connected": s.newly_connected_project_ids,
                    "blocked": s.blocked_project_ids, "caveat": s.caveat} for s in sugs]
            return ({"branch_id": bid, "suggestions": out, "summary": f"{len(out)} levers"}, None, sum(s.extra_solves for s in sugs))
        return _recorded(ctx, "suggestions", {"branch_id": bid, "request_id": request_id}, work)

    return ts


# --- study tools: one per registry entry --------------------------------------------------------------------------
def _compact(result) -> dict:
    items = [{"index": it.index, "element_kind": it.element_kind, "element_id": it.element_id, "element_name": it.element_name, "case": it.case,
              "year": it.year, "value": it.value, "limit": it.limit, "unit": it.unit, "severity": it.severity, "message": it.message}
             for it in result.items]
    worst_first = sorted(items, key=lambda x: ({"breach": 0, "warn": 1, "info": 2}.get(x["severity"], 3), x["index"]))
    return {"kind": result.kind, "summary": result.summary, "not_studied": result.not_studied, "n_items": len(items), "items": worst_first[:TOP_ITEMS]}


def _study_tool(kind: str):
    spec = STUDIES[kind]
    params_model = spec.params_model

    def run(ctx: RunContext[AgentDeps], branch_id: str | None = None, params: BaseModel | None = None) -> dict:
        bid = _branch(ctx, branch_id)
        deps = ctx.deps
        if kind not in deps.allowed_studies:  # refusals are answers the model reads, not retries that end the run
            return {"refused": f"{kind} is not in your remit; you may run: {', '.join(deps.allowed_studies)}", "solves": 0}
        p = params if params is not None else params_model()
        left = deps.budget["max_solves"] - deps.solves
        if spec.cost_hint(p) > left:
            return {"refused": f"{kind} with these parameters would cost about {spec.cost_hint(p)} solves; this run has {left} left. Narrow it (fewer buses or elements) or say it was not studied.", "solves": 0}
        h = deps.h

        def work():
            res = h.plans.study(bid, kind, p, chunked=True, hold=h.solver_gate.hold)  # the solver per chunk: operators get it between chunks
            return (_compact(res), h.plans.study_key(bid, kind, p), res.solves)

        return _recorded(ctx, f"study_{kind}", {"branch_id": bid, "params": p.model_dump()}, work)

    run.__name__ = f"study_{kind}"
    run.__doc__ = spec.description + " `params` are the study's parameters (all optional)."
    run.__signature__ = inspect.Signature([
        inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=RunContext[AgentDeps]),
        inspect.Parameter("branch_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None, annotation=str | None),
        inspect.Parameter("params", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None, annotation=params_model | None),
    ], return_annotation=dict)
    run.__annotations__ = {"ctx": RunContext[AgentDeps], "branch_id": str | None, "params": params_model | None, "return": dict}
    return run


def build_study_tools() -> FunctionToolset[AgentDeps]:
    ts: FunctionToolset[AgentDeps] = FunctionToolset(id="studies")
    for kind in STUDIES:
        ts.add_function(_study_tool(kind), takes_ctx=True, name=f"study_{kind}")
    return ts


# --- proposals: deferred tools the operator approves -----------------------------------------------------------------
def build_proposal_tools() -> FunctionToolset[AgentDeps]:
    ts: FunctionToolset[AgentDeps] = FunctionToolset(id="proposals", requires_approval=True)

    @ts.tool
    def propose_branch(ctx: RunContext[AgentDeps], name: str, note: str) -> dict:
        """Propose opening a branch off the project's main to try something (the operator approves; nothing changes on main)."""
        def work():
            h, main = ctx.deps.h, ctx.deps.main_id
            with h.store.cursor() as con:
                bid = repository.open_branch(con, repository.require_branch(con, main), name, created_by="agent:answerer")
            h.plans.invalidate("plan")
            return ({"branch_id": bid, "name": name, "note": note, "summary": f"opened {name} ({bid}) off {main}"}, None, 0)
        return _recorded(ctx, "propose_branch", {"name": name, "note": note}, work)

    @ts.tool
    def propose_reinforcement(ctx: RunContext[AgentDeps], branch_id: str, kind: str, element_id: int, action: str = "add_parallel", factor: float = 2.0, label: str = "") -> dict:
        """Propose a simulated reinforcement on a branch (kind line | trafo | gsp; action add_parallel | uprate) for the next run to measure. The operator approves; main is never edited."""
        def work():
            h = ctx.deps.h
            body = ReinforcementCreate(kind=kind, element_id=element_id, action=action, factor=factor, label=label)
            with h.store.cursor() as con:
                repository.require_open(con, branch_id, allow_main=False)
                row = repository.insert_reinforcement(con, branch_id, body)
            h.plans.invalidate("plan")
            return ({**row, "summary": f"reinforcement {row['reinforcement_id']} on {branch_id}"}, None, 0)
        return _recorded(ctx, "propose_reinforcement", {"branch_id": branch_id, "kind": kind, "element_id": element_id, "action": action, "factor": factor, "label": label}, work)

    @ts.tool
    def propose_works_window(ctx: RunContext[AgentDeps], branch_id: str, element_kind: str, element_id: str, season: str, year: int, weeks: int = 4, work: str = "maintenance") -> dict:
        """Propose a planned works window on a branch (element_kind line | trafo | gen; season Winter | Spring | Summer | Autumn) for the next run to study. The operator approves."""
        def do():
            h = ctx.deps.h
            body = OutageCreate(element_kind=element_kind, element_id=element_id, season=season, year=year, weeks=weeks, work=work)
            with h.store.cursor() as con:
                repository.require_open(con, branch_id, allow_main=False)
                row = repository.insert_outage(con, branch_id, body)
            return ({**row, "summary": f"window {row['outage_id']} on {branch_id}"}, None, 0)
        return _recorded(ctx, "propose_works_window", {"branch_id": branch_id, "element_kind": element_kind, "element_id": element_id, "season": season, "year": year, "weeks": weeks, "work": work}, do)

    return ts


TOOL_GROUPS: dict[str, Callable[[], FunctionToolset[AgentDeps]]] = {
    "read": build_read_tools,
    "studies": build_study_tools,
    "proposals": build_proposal_tools,
}
