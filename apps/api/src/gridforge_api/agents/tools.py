"""The tools the agents may call. Three groups, each a `FunctionToolset` with a stable id:

* `read`: lookups on the project (branches, queue, plan years, diff, merge check, findings, suggestions);
* `studies`: one tool per `studies.STUDIES` entry, run through `PlanService.study` with the solver gate
  taken per chunk (one power flow at a time, operators first) and recorded as evidence; a study outside
  the agent's remit or over its solve budget is refused in the tool's answer, never raised;
* `proposals`: actions that wait for the operator's approval (a branch, a reinforcement, a works window,
  a project or a change to one, a run of the branch).

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
from functools import partial
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from gridforge_optimizer import STUDIES, Control
from gridforge_optimizer.naming import name_payload

from .. import ledger, repository
from . import events
from ..config import AGENT_RUN_BUDGET, now
from ..schemas import NewCandidate, OutageCreate, ReinforcementCreate
from .evidence import EvidenceLedger

TOP_ITEMS = 25  # how many study items a tool returns to the model (the full study stays in the cache)


WAIT_NOTE_S = 5.0  # how often a waiting study tells the trace it is still waiting for the solver


class SolverBusy(Exception):
    """The solver stayed with an operator's work past what this agent run's own time allows."""


GATE_EXAMPLES = 3  # the worst messages an agent reads per group of gate findings


def _badness(f) -> float:
    """Larger is worse, within one kind: a loading or MW figure as it is; a pu voltage by its distance from 1."""
    v = f.value if isinstance(f.value, (int, float)) else 0.0
    return v if v > 2 else abs(1.0 - v)


def _grouped(findings) -> list[dict]:
    """The gate's findings as the agents read them: one item per kind and element across the plan years, carrying
    the worst member's fingerprint (what a review restates and the UI links), the year span, the count, the worst
    figure and the worst few messages. Several hundred single-year N-1 rows are a dozen items (a model handed
    them one by one restated 750 rows over three attempts, $4 of tokens, and its review was superseded meanwhile)."""
    groups: dict[tuple, list] = {}
    for f in findings:
        groups.setdefault((f.kind, f.element_kind, None if f.element_id is None else str(f.element_id)), []).append(f)
    out = []
    for (kind, element_kind, element_id), fs in groups.items():
        worst = sorted(fs, key=lambda f: (-_badness(f), f.finding_fingerprint or ""))
        years = sorted({f.year for f in fs if f.year is not None})
        out.append({"kind": kind, "element_kind": element_kind, "element_id": element_id, "fingerprint": worst[0].finding_fingerprint,
                    "years": (f"{years[0]}-{years[-1]}" if len(years) > 1 else str(years[0])) if years else None, "count": len(fs),
                    "case": worst[0].case, "value": worst[0].value, "limit": worst[0].limit, "message": worst[0].message,
                    "messages": [f.message for f in worst[:GATE_EXAMPLES]]})
    return sorted(out, key=lambda g: (-g["count"], g["kind"], g["element_id"] or ""))


def merge_summary(into: str, verdict, evidence: dict) -> dict:
    """The merge gate's verdict as the agents read it (the `merge_check` tool and the run digest):
    fresh or stale, ok or not, how many blockers and warnings there are, and both grouped by kind and element
    (`_grouped`); the UI reads the gate itself (`GET /branches/{id}/merge-check`), row by row."""
    return {"into": into, "fresh": evidence["fresh"], "stale_reasons": evidence["stale_reasons"], "ok": verdict.ok,
            "n_blockers": len(verdict.blockers), "n_warnings": len(verdict.warnings),
            "blockers": _grouped(verdict.blockers), "warnings": _grouped(verdict.warnings),
            "n_context": len(verdict.context), "summary": verdict.summary,
            "base_years_key": evidence.get("base_years_key")}  # with the run key, the identity of the pair a review judged


class SolverGate:
    """One power flow at a time in the process, operators first: wait while an operator's job is queued or running,
    for as long as the agent run's own time allows (`deadline`, monotonic seconds; None = no limit), telling the trace
    every few seconds (`waiting(seconds)`), then take the lock every power flow runs under. Waiting for the operator
    is the agent's turn coming, not a failure: only a run out of time stops (`SolverBusy`)."""

    def __init__(self, jobs, lock: threading.RLock):
        self._jobs = jobs
        self._lock = lock

    @contextmanager
    def hold(self, waiting: Callable[[float], None] | None = None, deadline: float | None = None):
        t0 = time.monotonic()
        said = -WAIT_NOTE_S
        while self._jobs.busy():
            waited = time.monotonic() - t0
            if deadline is not None and time.monotonic() > deadline:
                raise SolverBusy(f"the operator's run kept the solver for the {waited:.0f} s this run could wait")
            if waiting is not None and waited - said >= WAIT_NOTE_S:
                waiting(waited)
                said = waited
            time.sleep(0.5)
        with self._lock:
            yield


def _gate(deps: "AgentDeps", report: Callable[[str, float], None] | None = None):
    """The solver gate for this run: bounded by the run's deadline, and (with `report`) saying it waits."""
    waiting = (lambda s: report(f"waiting for the solver: the operator's run comes first ({s:.0f} s)", 0.0)) if report else None
    return partial(deps.h.solver_gate.hold, waiting=waiting, deadline=deps.deadline)


@dataclass
class Harness:
    """The collaborators the tools work with, handed in once by the runtime (never imported from deps)."""

    plans: Any
    store: Any
    warehouse: Any
    projects: Any  # the grids planned on (baselines, main branches)
    evidence: EvidenceLedger
    solver_gate: SolverGate
    in_workflow: Callable[[], bool] = lambda: False
    durable: Callable[[str, Callable[[], Any]], Any] = lambda name, fn: fn()


@dataclass
class AgentDeps:
    """What one agent run carries: its ids, its scope, its budget counters and its event sink."""

    h: Harness
    run_id: str
    project_id: str = ""
    main_id: str = ""  # the project's plan of record (what a tool reads when no branch is named); set by `deps_for`
    branch_id: str | None = None
    thread_id: str | None = None
    allowed_studies: tuple[str, ...] = tuple(STUDIES)
    emit: Callable[[dict], None] = lambda ev: None
    emit_async: Callable[[dict], Any] | None = None  # set by the runtime (an awaitable sink for the event handler)
    budget: dict = field(default_factory=lambda: dict(AGENT_RUN_BUDGET))
    tool_calls: int = 0
    solves: int = 0
    seq: int = 0
    deadline: float | None = None  # monotonic time after which the run stops waiting for the solver (None = no limit)

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


# --- the recorded step every tool runs through --------------------------------------------------------------
def _recorded(ctx: RunContext[AgentDeps], tool: str, args: dict, work: Callable[..., tuple[dict, str | None, int]], *, reports: bool = False) -> dict:
    """Run `work` (payload, cache key, solves) as a durable step, record it as evidence, and return the
    payload with its step id, the handle the model cites and a finding names. With `reports`, `work` is
    handed a `report(stage, fraction)` that streams the step's progress to the planner's trace (a study's
    chunks landing), so a long study is never a silent chip."""
    deps = ctx.deps
    deps.tool_calls += 1
    if deps.tool_calls > deps.budget["max_tool_calls"]:  # an answer, not a retry: the model must now write up what it has
        return {"refused": "the tool-call budget for this run is spent: answer with what you have, and say what was not studied", "solves": 0}
    step_id = f"{deps.run_id}:{ctx.tool_call_id or uuid.uuid4().hex[:8]}"
    seq = deps.next_seq()

    def report(stage: str, fraction: float) -> None:
        deps.emit({"t": "progress", "tool": tool, "step_id": step_id, "stage": str(stage), "fraction": round(float(fraction), 3), "seq": deps.next_seq()})

    def step() -> dict:
        t0 = now()
        try:
            payload, key, solves = work(report) if reports else work()
            err = None
        except SolverBusy as e:  # the operator's work came first for all this run could wait: an answer, not a failure
            payload, key, solves, err = {"refused": f"Not run yet: {e}. Answer with what you have, say this study is waiting for "
                                                    "the solver while the operator's run finishes, and offer to run it then."}, None, 0, str(e)
        except Exception as e:  # the step records the failure and the model hears it
            payload, key, solves, err = {"error": f"{type(e).__name__}: {e}"}, None, 0, str(e)
        deps.h.evidence.record_step(run_id=deps.run_id, step_id=step_id, seq=seq, tool=tool, args=args, cache_key=key,
                                    result=payload, solves=solves, started_at=t0, finished_at=now(), error=err)
        # the evidence keeps the engine's own words; the model reads every element by its name, the id in brackets
        # for the proposals it may make ("Bicker Fen to Boston 132 kV, circuit 2 (line 1)"), never a bare index
        out = {"step_id": step_id, **name_payload(payload, deps.h.projects.names(deps.project_id)), "solves": solves}
        if "branch_id" in args:  # a tool about a branch says which one, the default it fell back to included
            bid = out.get("branch_id") or args.get("branch_id") or deps.branch_id or deps.main_id
            out["branch_id"], out["branch_name"] = bid, _branch_label(deps.h, bid)
        return out

    out = deps.h.durable(f"tool:{tool}", step)
    deps.solves += int(out.get("solves", 0))
    return out


def _branch(ctx: RunContext[AgentDeps], branch_id: str | None) -> str:
    return branch_id or ctx.deps.branch_id or ctx.deps.main_id


def _branch_label(h: Harness, branch_id: str) -> str:
    """A branch as the operator knows it: its name, quoted, with its id ("qa-resize-fix" (br-d08cb74c))."""
    with h.store.cursor() as con:
        row = repository.branch_row(con, branch_id)
    return f'"{row["name"]}" ({branch_id})' if row and row.get("name") and row["name"] != branch_id else branch_id


def scope_instructions(ctx: RunContext[AgentDeps]) -> str:
    """Where the run is working, told to the model every run (an agent that is not told guesses "main"): the
    branch in view, what it was opened from, and that a tool reads it unless another branch_id is passed."""
    d = ctx.deps
    here = d.branch_id or d.main_id
    with d.h.store.cursor() as con:
        row = repository.branch_row(con, here)
        base = repository.base_of(con, row) if row else None
        parent = base["branch_id"] if base else None
    this = _branch_label(d.h, here)
    where = (f"branch {this}, opened from {_branch_label(d.h, parent)}" if parent
             else f"{this}, the plan of record (what physically exists today)")
    return (f"Where you are working: {where}. Every tool reads this branch unless you pass another branch_id, and "
            f"every result says which branch it is about (branch_id, branch_name). Answer about this branch unless "
            f"the operator names another; when a figure comes from another branch (main's, to compare), say which.")


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
    def limits(ctx: RunContext[AgentDeps], branch_id: str | None = None) -> dict:
        """What limits the branch's plan, as the engine reduces the whole run: the binding set (which elements bind or come near their limit, from which plan year, in which study case, with the MW of headroom left at the worst year, the projects deferred on each and how many N-1 outages breach it), the deferred projects' chains (the reason's element, case, figure against the limit, and what a connection_options study measured when one has run), the N-1 rows folded into clusters by cause, and the works verdicts. Read this before any study: most questions are answered here."""
        bid = _branch(ctx, branch_id)

        def work():
            h = ctx.deps.h
            with _gate(ctx.deps)():
                lim = h.plans.limits(bid, solve=True, wait=True)
            out = lim.model_dump(exclude_none=True)
            for b in out["binding"]:
                b["trajectory"] = [p for p in b["trajectory"] if p["year"] in (lim.years[0], lim.years[-1]) or p["year"] == b["worst"]["year"]]
            out["binding"] = out["binding"][:TOP_ITEMS]
            out["clusters"] = out["clusters"][:TOP_ITEMS]
            out["summary"] = (f"{len(lim.binding)} elements bind or come near a limit; {len(lim.chains)} projects deferred; "
                              f"{lim.n1_rows} N-1 rows in {lim.n1_pairs} outage/case pairs, {len(lim.clusters)} causes; {len(lim.works)} works windows")
            return ({"branch_id": bid, **out}, None, 0)
        return _recorded(ctx, "limits", {"branch_id": bid}, work)

    @ts.tool
    def plan_year(ctx: RunContext[AgentDeps], year: int, branch_id: str | None = None) -> dict:
        """One plan year of a branch as solved: worst loadings, voltage range, GSP export against its limit, N-1 findings, demand alerts and works verdicts. Solves the years if they are not cached."""
        bid = _branch(ctx, branch_id)

        def work():
            h = ctx.deps.h
            with _gate(ctx.deps)():
                res = h.plans.result_with_years(h.plans.inputs(bid))
            y = res.years.get(str(year))
            if y is None:
                return ({"branch_id": bid, "year": year, "error": "that year is not in the plan"}, None, 0)
            # which element carries the worst figure: the year's per-element loadings are the same worst-of-every-case
            # envelope the worst figure is the maximum of (named by `_recorded` like every element)
            worst_line = max(y.line_loading.items(), key=lambda kv: kv[1], default=None)
            worst_trafo = max(y.trafo_loading.items(), key=lambda kv: kv[1], default=None)
            most = lambda kind, w: f"the most loaded {kind} is {kind} {w[0]} at {w[1]:.0f}%" if w else f"no {kind} loading (not solved)"  # noqa: E731
            return ({"branch_id": bid, "year": year, "worst_line_loading_pct": y.worst_line_loading_pct, "worst_trafo_loading_pct": y.worst_trafo_loading_pct,
                     "worst_line": f"line {worst_line[0]}" if worst_line else None, "worst_transformer": f"transformer {worst_trafo[0]}" if worst_trafo else None,
                     "min_vm_pu": y.min_vm_pu, "max_vm_pu": y.max_vm_pu, "overloaded_line_ids": y.overloaded_line_ids,
                     "voltage_violation_bus_ids": y.voltage_violation_bus_ids, "gsp_export_mw": y.gsp_export_mw, "gsp_limit_mw": y.gsp_limit_mw,
                     "n1_findings": [v.get("message") for v in y.n1_violations][:TOP_ITEMS], "alerts": [a.message for a in y.alerts][:TOP_ITEMS],
                     "works": [{"outage_id": s.outage_id, "verdict": s.verdict, "message": s.message,
                                "second_faults": [f"{v.get('outage_type')} {v.get('outage_id')} out as well: {v.get('message')}" for v in s.n1_during.violations][:TOP_ITEMS]
                                if s.n1_during else None}
                               for s in y.outage_studies],
                     "energised": y.energised, "converged": y.converged,
                     "summary": f"{year}: {most('line', worst_line)}, {most('transformer', worst_trafo)}, "
                                f"voltage {y.min_vm_pu:.3f}-{y.max_vm_pu:.3f} pu, GSP export {y.gsp_export_mw:.0f} of {y.gsp_limit_mw or 0:.0f} MW, "
                                f"{len(y.n1_violations)} N-1 breaches from {len({(v.get('outage_type'), v.get('outage_id')) for v in y.n1_violations})} single outages, "
                                f"{len(y.alerts)} customer alerts"}, None, 0)
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
            if base is None:
                return ({"branch_id": bid, "summary": "This is the project's main, the plan of record: branches merge into it and it merges "
                                                      "nowhere, so it has no merge check. Check a branch instead."}, None, 0)
            with _gate(ctx.deps)():
                verdict, evidence = h.plans.merge_check(bid, base["branch_id"])
            return ({"branch_id": bid, **merge_summary(base["branch_id"], verdict, evidence)}, None, 0)
        return _recorded(ctx, "merge_check", {"branch_id": bid}, work)

    @ts.tool
    def diff(ctx: RunContext[AgentDeps], branch_id: str | None = None) -> dict:
        """The consequence diff of a branch against its parent: MW connected by 2030 and 2035, who moved, and per plan year what newly overloads, clears, or changes at the GSP and in the N-1 screen."""
        bid = _branch(ctx, branch_id)

        def work():
            h = ctx.deps.h
            with h.store.cursor() as con:
                base = repository.base_of(con, repository.require_branch(con, bid))
            if base is None:
                return ({"branch_id": bid, "summary": "This is the project's main, the plan of record: it has no parent to diff against. "
                                                      "Diff a branch instead."}, None, 0)
            with _gate(ctx.deps)():
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
    def findings(ctx: RunContext[AgentDeps], branch_id: str | None = None, status: str = "open", kind: str | None = None,
                 severity: str | None = None, source: str | None = None, limit: int = 40) -> dict:
        """The findings ledger of a branch: what its last run (and earlier agents) found, breaches first. Narrow it by status (open | acknowledged | resolved), kind (overload | voltage | n1 | alert | work | deferred | gsp_near_limit | …), severity (breach | warn | info) and source (engine | agent | operator); a ledger has hundreds of warnings, so read the breaches first."""
        bid = _branch(ctx, branch_id)

        def work():
            with ctx.deps.h.store.cursor() as con:
                rows = ledger.list_findings(con, bid, status=status if status in ledger.STATUSES else None)
                counts = ledger.counts(con, bid)
            rows = [r for r in rows if (not kind or r["kind"] == kind) and (not severity or r["severity"] == severity) and (not source or r["source"] == source)]
            out = [{k: r[k] for k in ("finding_id", "fingerprint", "kind", "severity", "year", "element_kind", "element_id", "value", "limit", "message", "source")}
                   for r in rows[:int(limit)]]
            return ({"branch_id": bid, "counts": counts, "findings": out, "shown": f"{len(out)} of {len(rows)} matching, breaches first",
                     "summary": f"{counts['open']} open ({counts['breach_open']} breaches, {counts['warn_open']} warnings); {len(out)} of {len(rows)} returned"}, None, 0)
        return _recorded(ctx, "findings", {"branch_id": bid, "status": status, "kind": kind, "severity": severity, "source": source, "limit": limit}, work)

    @ts.tool
    def suggestions(ctx: RunContext[AgentDeps], branch_id: str | None = None, request_id: str | None = None) -> dict:
        """The engine's "what would it take" levers for the projects a branch defers on the grid (or for one project): the reinforcement chain, the MW it frees and who connects. Measured by re-solving; costs solves."""
        bid = _branch(ctx, branch_id)

        def work():
            h = ctx.deps.h
            with _gate(ctx.deps)():
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
    shown = min(len(items), TOP_ITEMS)
    return {"kind": result.kind, "summary": result.summary, "not_studied": result.not_studied, "n_items": len(items),
            "shown": f"{shown} of {len(items)}, worst first; the full study is cached under this step (a display cap, not a gap)",
            "items": worst_first[:TOP_ITEMS]}


def _study_tool(kind: str):
    spec = STUDIES[kind]
    params_model = spec.params_model

    def run(ctx: RunContext[AgentDeps], branch_id: str | None = None, params: BaseModel | None = None) -> dict:
        bid = _branch(ctx, branch_id)
        deps = ctx.deps
        refusal, p = None, None
        if kind not in deps.allowed_studies:  # refusals are answers the model reads, not retries that end the run
            refusal = f"{kind} is not in your remit; you may run: {', '.join(deps.allowed_studies)}"
        else:
            try:
                p = params if params is not None else params_model()
            except ValidationError as e:  # a study about one project or element: the model must say which
                missing = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())
                refusal = f"{kind} needs its parameters: {missing}"
        if p is not None and spec.cost_hint(p) > (left := deps.budget["max_solves"] - deps.solves):
            refusal = (f"{kind} with these parameters would cost about {spec.cost_hint(p)} solves; this run has {left} left. "
                       "Narrow it (fewer buses or elements) or say it was not studied.")
        h = deps.h

        def work(report):
            if refusal is not None:  # recorded like any step: an audit row, a step id, a call against the run's budget
                return ({"refused": refusal}, None, 0)
            # the solver per chunk (operators get it between chunks); each chunk and the study's own stages stream to the trace
            res = h.plans.study(bid, kind, p, progress=report, chunked=True, hold=_gate(deps, report))
            return (_compact(res), h.plans.study_key(bid, kind, p), res.solves)

        args = {"branch_id": bid, "params": (p.model_dump() if p is not None else params.model_dump() if params is not None else {})}
        return _recorded(ctx, f"study_{kind}", args, work, reports=True)

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
def _element_ids(h: Harness, branch_id: str) -> dict[str, set]:
    """The ids a proposal on a branch may name: its own project's (a model read, so never under the store lock)."""
    with h.store.cursor() as con:
        pid = repository.require_branch(con, branch_id)["project_id"]
    return h.projects.element_ids(pid)


def build_proposal_tools() -> FunctionToolset[AgentDeps]:
    ts: FunctionToolset[AgentDeps] = FunctionToolset(id="proposals", requires_approval=True)

    @ts.tool
    def propose_branch(ctx: RunContext[AgentDeps], name: str, note: str) -> dict:
        """Propose opening a branch off the project's main to try something (the operator approves; nothing changes on main)."""
        def work():
            h, main = ctx.deps.h, ctx.deps.main_id
            with h.store.cursor() as con:
                bid = repository.open_branch(con, repository.require_branch(con, main), name, created_by="agent:answerer")
            h.plans.edited()
            return ({"branch_id": bid, "name": name, "note": note, "summary": f"opened {name} ({bid}) off {main}"}, None, 0)
        return _recorded(ctx, "propose_branch", {"name": name, "note": note}, work)

    @ts.tool
    def propose_reinforcement(ctx: RunContext[AgentDeps], branch_id: str, kind: str, element_id: int, action: str = "add_parallel", factor: float = 2.0, label: str = "") -> dict:
        """Propose a simulated reinforcement on a branch (kind line | trafo | gsp; action add_parallel | uprate) for the next run to measure. The operator approves; main is never edited."""
        def work():
            h = ctx.deps.h
            body = ReinforcementCreate(kind=kind, element_id=element_id, action=action, factor=factor, label=label)
            ids = _element_ids(h, branch_id)
            with h.store.cursor() as con:
                repository.require_open(con, branch_id, allow_main=False)
                row = repository.insert_reinforcement(con, branch_id, body, ids)
            h.plans.edited()
            return ({**row, "summary": f"reinforcement {row['reinforcement_id']} on {branch_id}"}, None, 0)
        return _recorded(ctx, "propose_reinforcement", {"branch_id": branch_id, "kind": kind, "element_id": element_id, "action": action, "factor": factor, "label": label}, work)

    @ts.tool
    def propose_works_window(ctx: RunContext[AgentDeps], branch_id: str, element_kind: str, element_id: str, season: str, year: int, weeks: int = 4, work: str = "maintenance") -> dict:
        """Propose a planned works window on a branch (element_kind line | trafo | gen; season Winter | Spring | Summer | Autumn) for the next run to study. The operator approves."""
        def do():
            h = ctx.deps.h
            body = OutageCreate(element_kind=element_kind, element_id=element_id, season=season, year=year, weeks=weeks, work=work)
            ids = _element_ids(h, branch_id)
            with h.store.cursor() as con:
                repository.require_open(con, branch_id, allow_main=False)
                row = repository.insert_outage(con, branch_id, body, ids)
            return ({**row, "summary": f"window {row['outage_id']} on {branch_id}"}, None, 0)
        return _recorded(ctx, "propose_works_window", {"branch_id": branch_id, "element_kind": element_kind, "element_id": element_id, "season": season, "year": year, "weeks": weeks, "work": work}, do)

    @ts.tool
    def propose_candidate(ctx: RunContext[AgentDeps], branch_id: str, applicant: str, technology: str, bus_id: int, rating_mw: float,
                          import_mw: float | None = None, commissioning_year: int | None = None, readiness_rationale: str = "",
                          control: Control | None = None) -> dict:
        """Propose adding a connection project to a branch: technology solar | wind | battery | hybrid | demand | electrolyser | other, rating_mw its export (0 for a demand connection), import_mw its import (batteries, demand), commissioning_year the year asked for. control: how its connection offer runs it, as the operator states it: {mode: pf, pf, absorbing} (a fixed power factor) or {mode: voltage, vm_pu, q_range_pf} (voltage control within a reactive range); never assume one: ask, and leave it out when not known (the project then runs at unity power factor, marked not stated). Intake-triaged like the operator's own entry; the next run ranks it. The operator approves; main is never edited."""
        def work():
            h = ctx.deps.h
            body = NewCandidate(applicant=applicant, technology=technology, bus_id=bus_id, rating_mw=rating_mw, import_mw=import_mw,
                                commissioning_year=commissioning_year, readiness_rationale=readiness_rationale, control=control, branch_id=branch_id)
            valid = _element_ids(h, branch_id)["buses"]
            with h.store.cursor() as con:
                repository.require_open(con, branch_id, allow_main=False)
                row = repository.insert_candidate(con, branch_id, body, valid)
            h.plans.edited()
            client = repository.to_client(row)
            return ({**client, "summary": f"{row['request_id']} ({client['status']}) added to {branch_id}"}, None, 0)
        return _recorded(ctx, "propose_candidate", {"branch_id": branch_id, "applicant": applicant, "technology": technology, "bus_id": bus_id, "rating_mw": rating_mw,
                                                    "import_mw": import_mw, "commissioning_year": commissioning_year, "readiness_rationale": readiness_rationale,
                                                    "control": control.model_dump() if control else None}, work)

    @ts.tool
    def propose_candidate_change(ctx: RunContext[AgentDeps], branch_id: str, request_id: str, bus_id: int | None = None, rating_mw: float | None = None,
                                 import_mw: float | None = None, commissioning_year: int | None = None, control: Control | None = None) -> dict:
        """Propose changing a project on a branch: its point of connection (bus_id, e.g. the higher-voltage busbar connection_options found), its export rating (a firm size; a battery's import scales with it unless import_mw is given, as connection_options probed it), its import capacity, its requested year or its control mode (as for propose_candidate: only what the operator states); omitted fields keep their value. Re-triaged; the next run measures it. The operator approves."""
        def work():
            h = ctx.deps.h
            changes = {k: v for k, v in {"bus_id": bus_id, "rating_mw": rating_mw, "import_mw": import_mw, "commissioning_year": commissioning_year,
                                         "control": control.model_dump() if control else None}.items() if v is not None}
            valid = _element_ids(h, branch_id)["buses"]
            with h.store.cursor() as con:
                repository.require_open(con, branch_id, allow_main=False)
                row = repository.update_candidate(con, branch_id, request_id, changes, valid)
            h.plans.edited()
            applied = {k: row.get(k) for k in ("bus_id", "rating_mw", "import_mw", "commissioning_year", "control") if k in changes or (k == "import_mw" and "rating_mw" in changes and row.get(k) is not None)}
            return ({**row, "summary": f"{request_id} on {branch_id}: " + ", ".join(f"{k} -> {v}" for k, v in applied.items())}, None, 0)
        return _recorded(ctx, "propose_candidate_change", {"branch_id": branch_id, "request_id": request_id, "bus_id": bus_id, "rating_mw": rating_mw,
                                                           "import_mw": import_mw, "commissioning_year": commissioning_year,
                                                           "control": control.model_dump() if control else None}, work)

    @ts.tool
    def propose_rebase(ctx: RunContext[AgentDeps], branch_id: str) -> dict:
        """Propose rebasing a branch onto its parent as it is now (when the merge check says it is behind main): the parent's
        current state plus the branch's own changes. Only a rebase without conflicts is applied: where both sides changed the
        same thing the operator picks in the Review tab, never an agent. The branch's result is then out of date until it runs
        (propose_run). The operator approves."""
        def work():
            h = ctx.deps.h
            valid = _element_ids(h, branch_id)["buses"]
            with h.store.cursor() as con:
                head = repository.require_open(con, branch_id, allow_main=False)
                p = repository.rebase_plan(con, head)
                if p is None:
                    return ({"branch_id": branch_id, "refused": "the branch it was opened from is gone: nothing to rebase onto"}, None, 0)
                if p.conflicts:
                    return ({"branch_id": branch_id, "refused": f"{len(p.conflicts)} conflict(s): both sides changed the same thing, and only the "
                                                                "operator picks a side, in the Review tab. Tell them which.",
                             "conflicts": [c.text for c in p.conflicts]}, None, 0)
                n = repository.apply_rebase(con, head, p, {}, valid)
            h.plans.edited()
            return ({"branch_id": branch_id, "taken": n, "summary": f"rebased {branch_id} onto {head['parent_id']}: {n} of its changes taken in; "
                                                                     "the branch's result is out of date until it runs"}, None, 0)
        return _recorded(ctx, "propose_rebase", {"branch_id": branch_id}, work)

    @ts.tool
    def propose_run(ctx: RunContext[AgentDeps], branch_id: str) -> dict:
        """Propose running the branch now (the queue, then every plan year) so what was proposed is measured and reviewed. A full run: operators' own jobs wait for it. The operator approves."""
        def work():
            h = ctx.deps.h
            with h.store.cursor() as con:
                row = repository.require_branch(con, branch_id)
            with _gate(ctx.deps)():
                out = h.plans.optimize_payload(repository.branch_request(row), branch_id)
            queue = out.get("queue", [])
            by: dict[str, int] = {}
            for q in queue:
                by[q["status"]] = by.get(q["status"], 0) + 1
            deferred = [{"request_id": q["request_id"], "reason": (q.get("reason") or {}).get("message")} for q in queue if q["status"] == "Deferred"]
            event = events.run_finished(branch_id, out, is_main=repository.is_main(row),  # what the workflow announces
                                        parent_run_key=events.parent_run_key(h.plans, h.store, branch_id))
            return ({"branch_id": branch_id, "run_key": out.get("run_key"), "statuses": by, "deferred": deferred, "event": event,
                     "summary": f"ran {branch_id}: " + (", ".join(f"{n} {s}" for s, n in sorted(by.items())) or "an empty queue")}, out.get("run_key"), 0)
        return _recorded(ctx, "propose_run", {"branch_id": branch_id}, work)

    return ts


TOOL_GROUPS: dict[str, Callable[[], FunctionToolset[AgentDeps]]] = {
    "read": build_read_tools,
    "studies": build_study_tools,
    "proposals": build_proposal_tools,
}


# --- proposals in words: what the operator reads next to the Approve button --------------------------------------------
def _element(names, kind: str, eid) -> str:
    """An element as the operator knows it, the id in brackets ("Sleaford 132 kV, circuit 1 (line 16)")."""
    k = "transformer" if kind == "trafo" else kind
    try:
        i = int(eid)
    except (TypeError, ValueError):
        return f"{k} {eid}"
    name = names.of(k, i) if names is not None else ""
    return f"{name} ({k} {i})" if name else f"{k} {i}"


def _mw(x) -> str:
    return f"{float(x):g} MW"


def _change_text(a: dict, names) -> str:
    rid = a.get("request_id", "the project")
    parts = []
    if a.get("rating_mw") is not None:
        parts.append(f"resize {rid} to {_mw(a['rating_mw'])}" + ("" if a.get("import_mw") is not None else " (its import follows)"))
    if a.get("import_mw") is not None:
        parts.append(f"set {rid}'s import to {_mw(a['import_mw'])}")
    if a.get("bus_id") is not None:
        parts.append(f"move {rid} to {_element(names, 'bus', a['bus_id'])}")
    if a.get("commissioning_year") is not None:
        parts.append(f"ask {a['commissioning_year']} for {rid}")
    if a.get("control") is not None:
        parts.append(f"set {rid}'s control mode as stated")
    return ", ".join(parts) or f"change {rid}"


PROPOSAL_TEXT: dict[str, Callable[[dict, Any], str]] = {
    "propose_candidate_change": _change_text,
    "propose_candidate": lambda a, n: f"add {a.get('applicant') or 'a project'} ({a.get('technology')}, {_mw(a.get('rating_mw') or 0)}) at "
                                      f"{_element(n, 'bus', a.get('bus_id'))}" + (f", asking for {a['commissioning_year']}" if a.get("commissioning_year") else ""),
    "propose_run": lambda a, n: "run the branch now",
    "propose_branch": lambda a, n: f"open a branch '{a.get('name')}' off main" + (f": {a['note']}" if a.get("note") else ""),
    "propose_reinforcement": lambda a, n: (f"add a parallel circuit on {_element(n, a.get('kind', 'line'), a.get('element_id'))}" if a.get("action") == "add_parallel"
                                           else f"uprate {_element(n, a.get('kind', 'line'), a.get('element_id'))} ×{float(a.get('factor') or 2):g}"),
    "propose_works_window": lambda a, n: f"schedule {a.get('weeks', 4)} weeks of {a.get('work', 'maintenance')} on "
                                         f"{_element(n, a.get('element_kind', 'line'), a.get('element_id'))} in {str(a.get('season', '')).lower()} {a.get('year')}",
    "propose_rebase": lambda a, n: "rebase the branch onto its parent as it is now",
}


def proposal_text(tool: str, args: dict, names) -> str:
    """A proposal in words ("resize ECR-83EF2 to 55 MW (its import follows)"), never its tool call as JSON; an unknown
    tool falls back to its name and arguments."""
    fn = PROPOSAL_TEXT.get(tool)
    try:
        return fn(args or {}, names) if fn else f"{tool} {args}"
    except Exception:  # a phrasing must never fail a reply
        return f"{tool} {args}"
