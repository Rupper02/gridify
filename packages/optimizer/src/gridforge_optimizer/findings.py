"""Findings: the problems (and the facts worth knowing) a plan carries, as one flat, deterministic
list extracted from an `OptimizeResult` the engine has already produced.

A run reports overloads, voltage breaches, the GSP margin, N-1 findings, demand-side alerts, works
verdicts and the projects it defers, each in its own place on the result. The API's findings ledger
needs them in one shape with a stable identity, so a re-run upserts what is still there and resolves
what is gone. `extract_findings` is that shape. It computes nothing new: every figure is copied from
the result, and every message names elements the way the engine does ("line 12", "bus 7"), so the
planner names them by place.

Pure: no I/O, no pandapower. `EXTRACTORS` is the registry: a new kind of finding is one function and
one entry, like `demand.ALERT_CHECKS`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import NamedTuple

from .config import GSP_NEAR_LIMIT_FRACTION, LINE_LOADING_MAX_PCT, TRAFO_LOADING_MAX_PCT
from .types import SEVERITY_ORDER, VERDICT_SEVERITY, Finding, OptimizeResult, YearResult

# reason types that mean the GRID (not intake or policy) held a project back
GRID_REASON_TYPES = ("line", "trafo", "voltage", "gsp", "non_convergent")
# works verdicts that put supply, not just generation output, at stake
SEVERE_VERDICTS = tuple(v for v, s in VERDICT_SEVERITY.items() if s >= VERDICT_SEVERITY["not_feasible"])
# the N-1 screen's case (network.n1_screen defaults to it; years.evaluate_year calls it that way)
N1_CASE = "winter_peak"


def fingerprint(kind: str, element_kind: str | None = None, element_id=None, year: int | None = None,
                case: str | None = None, extra: tuple = ()) -> str:
    """A finding's stable identity: what kind of problem, on which element, in which year and case.
    Deliberately value-independent, so the same overload at 104% and later at 109% is one finding."""
    sig = "|".join("" if x is None else str(x) for x in (kind, element_kind, element_id, year, case, *extra))
    return hashlib.sha1(sig.encode()).hexdigest()[:16]


def against_recommendation(recommended_year: int | None, scheduled_year: int | None) -> bool:
    """The operator's energisation year goes against the optimizer's: earlier than recommended, or
    scheduled where the grid cannot host the project at all (no recommendation). The one definition
    the API's enrichment, the ledger and the merge gate share."""
    return scheduled_year is not None and (recommended_year is None or scheduled_year < recommended_year)


class _Ctx(NamedTuple):
    result: OptimizeResult
    scheduled: Mapping[str, int]

    def years(self) -> list[YearResult]:
        return sorted(self.result.years.values(), key=lambda y: y.year)


def _finding(kind: str, severity: str, message: str, *, element_kind: str | None = None, element_id=None,
             year: int | None = None, case: str | None = None, value: float | None = None,
             limit: float | None = None, context: dict | None = None, extra: tuple = (),
             fp: str | None = None) -> Finding:
    """Build a Finding; the fingerprint follows the identity fields unless the extractor supplies one."""
    return Finding(
        fingerprint=fp or fingerprint(kind, element_kind, element_id, year, case, extra),
        kind=kind, severity=severity, year=year, case=case, element_kind=element_kind,
        element_id=None if element_id is None else str(element_id), value=value, limit=limit,
        message=message, context=context or {},
    )


def _pct(v: float | None) -> str:
    return "unloaded" if v is None else f"{v:.0f}%"


# --- extractors: one per concern, each (ctx) -> findings ------------------------------------------
def _overloads(ctx: _Ctx) -> list[Finding]:
    """Lines and transformers over their rating in any plan year (the year's worst-case envelope)."""
    out: list[Finding] = []
    for y in ctx.years():
        for table, label, limit, loading in (("line", "line", LINE_LOADING_MAX_PCT, y.line_loading),
                                             ("trafo", "transformer", TRAFO_LOADING_MAX_PCT, y.trafo_loading)):
            for eid, pct in sorted(loading.items()):
                if pct is None or pct <= limit:
                    continue
                out.append(_finding("overload", "breach",
                                    f"{label} {eid} at {pct:.0f}% of its rating in {y.year} (worst case)",
                                    element_kind=table, element_id=eid, year=y.year, value=round(pct, 1), limit=limit))
    return out


def _voltage(ctx: _Ctx) -> list[Finding]:
    """Buses outside their statutory band with the network intact."""
    out: list[Finding] = []
    for y in ctx.years():
        for bus in sorted(y.voltage_violation_bus_ids):
            vm = y.bus_vm.get(bus)
            text = f"{vm:.3f} pu" if vm is not None else "a voltage"
            out.append(_finding("voltage", "breach",
                                f"bus {bus} at {text}, outside its statutory band in {y.year} (worst case)",
                                element_kind="bus", element_id=bus, year=y.year, value=vm))
    return out


def _gsp(ctx: _Ctx) -> list[Finding]:
    """The GSP's export to transmission against its limit: over it, or within the warning band."""
    out: list[Finding] = []
    for y in ctx.years():
        limit, export = y.gsp_limit_mw, y.gsp_export_mw
        if limit is None or limit <= 0:
            continue
        if export > limit:
            out.append(_finding("gsp_over_limit", "breach",
                                f"GSP export {export:.0f} MW is above its {limit:.0f} MW limit in {y.year}",
                                element_kind="gsp", element_id="gsp", year=y.year, value=round(export, 1), limit=limit))
        elif export > GSP_NEAR_LIMIT_FRACTION * limit:
            out.append(_finding("gsp_near_limit", "warn",
                                f"GSP export {export:.0f} MW is {export / limit:.0%} of its {limit:.0f} MW limit in {y.year}",
                                element_kind="gsp", element_id="gsp", year=y.year, value=round(export, 1), limit=limit))
    return out


def _n1(ctx: _Ctx) -> list[Finding]:
    """Every single-outage finding of the N-1 screen (reported, never a connection gate)."""
    out: list[Finding] = []
    for y in ctx.years():
        for v in y.n1_violations:
            out.append(_finding("n1", "warn", f"{v.get('message', 'N-1 finding')} in {y.year}",
                                element_kind=v.get("outage_type"), element_id=v.get("outage_id"), year=y.year,
                                case=N1_CASE, value=v.get("value"),
                                context={"breach_type": v.get("type"), "breach_element_id": v.get("element_id"),
                                         "outage_name": v.get("outage_name")},
                                extra=(v.get("type"), v.get("element_id"))))
    return out


def _alerts(ctx: _Ctx) -> list[Finding]:
    """The demand-side alerts (demand.ALERT_CHECKS), at their own level."""
    return [
        _finding("alert", a.level, a.message, element_kind="region", element_id=a.region_id, year=a.year,
                 value=a.value, limit=a.limit, context={"alert_kind": a.kind}, extra=(a.kind,))
        for y in ctx.years() for a in y.alerts
    ]


def _works(ctx: _Ctx) -> list[Finding]:
    """Planned works windows that are not simply feasible: curtailment warns, supply at stake breaches."""
    out: list[Finding] = []
    for y in ctx.years():
        for s in y.outage_studies:
            if s.verdict == "feasible":
                continue
            severe = s.verdict in SEVERE_VERDICTS
            value = s.demand_at_risk_mw if s.verdict == "demand_at_risk" else s.curtailed_mw
            out.append(_finding("work", "breach" if severe else "warn", s.message, element_kind="outage",
                                element_id=s.outage_id, year=s.year, value=round(value, 1),
                                context={"verdict": s.verdict, "work": s.work, "cases": list(s.cases),
                                         "with_ids": list(s.with_ids)}))
    return out


def _queue(ctx: _Ctx) -> list[Finding]:
    """Projects the run holds back: deferred ones (with the binding reason) warn, rejected ones inform.
    Identity is the project alone: a project that stays deferred is one finding whatever binds it."""
    out: list[Finding] = []
    for q in ctx.result.queue:
        r = q.reason
        if q.status == "Deferred" and r is not None:
            out.append(_finding("deferred", "warn", f"{q.request_id} deferred: {r.message}", element_kind="project",
                                element_id=q.request_id, case=r.case, value=r.value, limit=r.limit,
                                context={"reason_type": r.type, "binding_element_id": r.element_id,
                                         "grid": r.type in GRID_REASON_TYPES},
                                fp=fingerprint("deferred", "project", q.request_id)))
        elif q.status == "Rejected":
            why = r.message if r is not None else "did not pass intake"
            out.append(_finding("rejected", "info", f"{q.request_id} rejected: {why}", element_kind="project",
                                element_id=q.request_id, context={"reason_type": r.type if r else None}))
    return out


def _schedule(ctx: _Ctx) -> list[Finding]:
    """Accepted projects the operator scheduled against the optimizer's recommendation."""
    out: list[Finding] = []
    for q in ctx.result.queue:
        if q.status not in ("Phase1", "Phase2"):
            continue
        scheduled = ctx.scheduled.get(q.request_id)
        if not against_recommendation(q.recommended_year, scheduled):
            continue
        if q.recommended_year is None:
            text = f"{q.request_id} is scheduled for {scheduled}, but the grid has no year it can host it"
        else:
            text = f"{q.request_id} is scheduled for {scheduled}, earlier than the {q.recommended_year} the grid supports"
        out.append(_finding("against_recommendation", "warn", text, element_kind="project", element_id=q.request_id,
                            value=scheduled, limit=q.recommended_year))
    return out


def _non_convergent(ctx: _Ctx) -> list[Finding]:
    """Years whose intact power flow did not converge: their figures cannot be trusted."""
    return [
        _finding("non_convergent", "breach",
                 f"the power flow did not converge in {y.year}: that year's figures are not trustworthy", year=y.year)
        for y in ctx.years() if not y.converged
    ]


# the extractors, in the order their findings read best; a new kind of finding is one function + one entry
EXTRACTORS: tuple[Callable[[_Ctx], list[Finding]], ...] = (
    _overloads, _voltage, _gsp, _n1, _alerts, _works, _queue, _schedule, _non_convergent,
)


def extract_findings(result: OptimizeResult, scheduled: Mapping[str, int] | None = None) -> list[Finding]:
    """Every finding in a result (its queue and its solved plan years), breaches first, then by year."""
    ctx = _Ctx(result, dict(scheduled or {}))
    out = [f for extract in EXTRACTORS for f in extract(ctx)]
    out.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.year or 0, f.kind, f.element_kind or "",
                            f.element_id or "", f.fingerprint))
    return out
