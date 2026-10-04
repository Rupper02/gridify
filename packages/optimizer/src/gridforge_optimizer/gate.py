"""Merge guardrails: may this branch become the plan of record?

`merge_verdict` is a pure policy over results the engine has already produced: the branch's run with
its plan years, its parent's, and the consequence diff between them. It never solves anything. The
rule it enforces, set by the owner, is NO MERGE WHILE THE GRID WOULD BE BROKEN IN ANY PLAN YEAR, read
against the parent, because the parent is not perfect either:

  * what the branch INTRODUCES or WORSENS in the same year blocks (a new overload or voltage breach,
    the GSP newly over its limit, a new N-1 finding, a new demand-side breach, a works window that
    becomes infeasible, a year that stops converging);
  * what the parent already carries is context, never a blocker;
  * a result that is stale or incomplete blocks on its own: an unstudied year cannot be declared safe;
  * a branch that fell behind its parent blocks, because merging replaces the parent's projects.

Connections are not gated by this (AGENTS.md rule 4: N-1 and planned works are reported, never a
connection gate). Merges are: a supply-security regression is exactly what "the grid will be broken"
means. `MERGE_CHECKS` is the registry, one function per concern; the LEVEL of every kind lives in
`config.MERGE_GATE_LEVELS`, so a policy change is data, not code.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from .config import (
    GATE_GSP_WORSEN_MW,
    GATE_VM_WORSEN_PU,
    GATE_WORSEN_PTS,
    GSP_NEAR_LIMIT_FRACTION,
    LINE_LOADING_MAX_PCT,
    MERGE_GATE_LEVELS,
    PLAN_END_YEAR,
    PLAN_START_YEAR,
    TRAFO_LOADING_MAX_PCT,
)
from .diff import ConsequenceDiff, YearDelta, diff_results, n1_key
from .findings import GRID_REASON_TYPES, SEVERE_VERDICTS, against_recommendation, fingerprint
from .types import Alert, GateFinding, MergeVerdict, OptimizeResult, YearResult

_EPS = 0.05  # movements below this (loading points, MW, pu) are noise, not a change
_PLAN_YEARS = tuple(range(PLAN_START_YEAR, PLAN_END_YEAR + 1))


@dataclass(frozen=True)
class GateContext:
    """Everything a check may read. `fresh` is the API's verdict on whether `head` was solved for the
    branch's current inputs; the checks never second-guess it."""

    head: OptimizeResult | None
    base: OptimizeResult | None
    diff: ConsequenceDiff | None
    fresh: bool = True
    stale_reasons: tuple[str, ...] = ()
    scheduled: Mapping[str, int] = field(default_factory=dict)
    removed_works: tuple[str, ...] = ()
    removed_reinforcements: tuple[str, ...] = ()
    base_label: str = "main"

    @property
    def complete(self) -> bool:
        return self.fresh and self.head is not None and self.base is not None

    def common_years(self) -> list[tuple[int, YearResult, YearResult]]:
        """(year, base, head) for every plan year solved on both sides."""
        if not self.complete:
            return []
        keys = sorted(self.head.years.keys() & self.base.years.keys(), key=int)
        return [(int(k), self.base.years[k], self.head.years[k]) for k in keys]

    def year_delta(self, year: int) -> YearDelta | None:
        return self.diff.years.get(str(year)) if self.diff is not None else None


def _finding(kind: str, message: str, *, year: int | None = None, case: str | None = None,
             element_kind: str | None = None, element_id=None, value: float | None = None,
             base_value: float | None = None, limit: float | None = None, ledger: tuple | None = None) -> GateFinding:
    """A gate finding at the level the policy table gives its kind. `ledger` is the identity of the
    branch-side ledger finding it refers to, as `findings.fingerprint`'s arguments."""
    return GateFinding(
        kind=kind, level=MERGE_GATE_LEVELS[kind], year=year, case=case, element_kind=element_kind,
        element_id=None if element_id is None else str(element_id), value=value, base_value=base_value,
        limit=limit, message=message, finding_fingerprint=fingerprint(*ledger) if ledger else None,
    )


def _years_text(years: list[int]) -> str:
    """Years as runs: [2026, 2027, 2028, 2031] -> '2026 to 2028, 2031'."""
    runs: list[list[int]] = []
    for y in years:
        if runs and y == runs[-1][-1] + 1:
            runs[-1].append(y)
        else:
            runs.append([y])
    return ", ".join(f"{r[0]} to {r[-1]}" if len(r) > 1 else str(r[0]) for r in runs)


def _pct(v: float | None) -> str:
    return "unloaded" if v is None else f"{v:.0f}%"


# --- the checks: each (ctx) -> findings; levels come from MERGE_GATE_LEVELS ---------------------------
def _stale(ctx: GateContext) -> list[GateFinding]:
    if ctx.fresh:
        return []
    why = "; ".join(ctx.stale_reasons) or "its inputs changed since it was last run"
    return [_finding("stale", f"This branch has not been run for its current inputs ({why}). Re-run it before merging.")]


def _no_result(ctx: GateContext) -> list[GateFinding]:
    if not ctx.fresh:
        return []
    return [
        _finding("no_result", f"{label} has no solved plan years to judge the merge on.")
        for label, r in (("This branch", ctx.head), (ctx.base_label, ctx.base))
        if r is None or not r.years
    ]


def _unstudied_years(ctx: GateContext) -> list[GateFinding]:
    out: list[GateFinding] = []
    if not ctx.complete:
        return out
    for label, r in (("This branch", ctx.head), (ctx.base_label, ctx.base)):
        if not r.years:
            continue  # _no_result covers it
        missing = [y for y in _PLAN_YEARS if str(y) not in r.years]
        if missing:
            out.append(_finding("unstudied_years",
                                f"{label} has no result for {_years_text(missing)}: a year that is not solved cannot be declared safe."))
    return out


def _non_convergent(ctx: GateContext) -> list[GateFinding]:
    out: list[GateFinding] = []
    for y, b, h in ctx.common_years():
        if h.converged:
            continue
        if b.converged:
            out.append(_finding("non_convergent", f"The power flow does not converge on this branch in {y}; {ctx.base_label}'s does.",
                                year=y, ledger=("non_convergent", None, None, y, None)))
        else:
            out.append(_finding("preexisting", f"The power flow does not converge in {y} on {ctx.base_label} either.", year=y))
    return out


def _behind_base(ctx: GateContext) -> list[GateFinding]:
    """Merging REPLACES the parent's projects with the branch's: a project on the parent but not on the
    branch (it merged after the branch was opened) would silently disappear."""
    if not ctx.complete or ctx.diff is None:
        return []
    return [
        _finding("behind_base",
                 f"{p.request_id} is on {ctx.base_label} but not on this branch: it merged after the branch was "
                 f"opened, and merging would drop it. Open a new branch from {ctx.base_label}.",
                 element_kind="project", element_id=p.request_id)
        for p in ctx.diff.projects if p.change == "dropped"
    ]


def _thermal(ctx: GateContext) -> list[GateFinding]:
    out: list[GateFinding] = []
    for y, b, h in ctx.common_years():
        d = ctx.year_delta(y)
        for table, label, limit, bl, hl, crossed in (
            ("line", "line", LINE_LOADING_MAX_PCT, b.line_loading, h.line_loading,
             d.newly_overloaded_line_ids if d else None),
            ("trafo", "transformer", TRAFO_LOADING_MAX_PCT, b.trafo_loading, h.trafo_loading,
             d.newly_overloaded_trafo_ids if d else None),
        ):
            h_over = {e for e, v in hl.items() if v is not None and v > limit}
            b_over = {e for e, v in bl.items() if v is not None and v > limit}
            new = set(crossed) if crossed is not None else h_over - b_over
            for eid in sorted(new):
                out.append(_finding("new_overload",
                                    f"{label} {eid} newly over its rating in {y}: {_pct(hl.get(eid))} on this branch, "
                                    f"{_pct(bl.get(eid))} on {ctx.base_label}.",
                                    year=y, element_kind=table, element_id=eid, value=hl.get(eid), base_value=bl.get(eid),
                                    limit=limit, ledger=("overload", table, eid, y, None)))
            for eid in sorted((h_over & b_over) - new):
                bv, hv = bl[eid], hl[eid]
                kind = "overload_worse" if hv - bv > GATE_WORSEN_PTS else "preexisting"
                text = (f"{label} {eid} is over its rating on {ctx.base_label} already ({bv:.0f}%) and loads "
                        f"{hv - bv:.0f} points more on this branch ({hv:.0f}%) in {y}." if kind == "overload_worse" else
                        f"{label} {eid} is over its rating on {ctx.base_label} in {y} ({bv:.0f}%); this branch leaves it at {hv:.0f}%.")
                out.append(_finding(kind, text, year=y, element_kind=table, element_id=eid, value=hv, base_value=bv,
                                    limit=limit, ledger=("overload", table, eid, y, None)))
    return out


def _voltage(ctx: GateContext) -> list[GateFinding]:
    out: list[GateFinding] = []
    for y, b, h in ctx.common_years():
        b_bad, h_bad = set(b.voltage_violation_bus_ids), set(h.voltage_violation_bus_ids)
        for bus in sorted(h_bad - b_bad):
            hv = h.bus_vm.get(bus)
            text = f"{hv:.3f} pu" if hv is not None else "a voltage"
            out.append(_finding("new_voltage_violation",
                                f"bus {bus} newly outside its statutory band in {y}: {text} on this branch.",
                                year=y, element_kind="bus", element_id=bus, value=hv, base_value=b.bus_vm.get(bus),
                                ledger=("voltage", "bus", bus, y, None)))
        for bus in sorted(h_bad & b_bad):
            hv, bv = h.bus_vm.get(bus), b.bus_vm.get(bus)
            if hv is None or bv is None:
                continue
            worse = abs(hv - 1.0) - abs(bv - 1.0) > GATE_VM_WORSEN_PU
            kind = "voltage_worse" if worse else "preexisting"
            text = (f"bus {bus} is outside its band on {ctx.base_label} ({bv:.3f} pu) and drifts further on this branch "
                    f"({hv:.3f} pu) in {y}." if worse else
                    f"bus {bus} is outside its band on {ctx.base_label} in {y} ({bv:.3f} pu); this branch leaves it at {hv:.3f} pu.")
            out.append(_finding(kind, text, year=y, element_kind="bus", element_id=bus, value=hv, base_value=bv,
                                ledger=("voltage", "bus", bus, y, None)))
    return out


def _gsp(ctx: GateContext) -> list[GateFinding]:
    out: list[GateFinding] = []
    for y, b, h in ctx.common_years():
        limit = h.gsp_limit_mw
        if limit is None or limit <= 0:
            continue
        he, be = h.gsp_export_mw, b.gsp_export_mw
        b_limit = b.gsp_limit_mw if b.gsp_limit_mw else limit
        common = dict(year=y, element_kind="gsp", element_id="gsp", value=round(he, 1), base_value=round(be, 1), limit=limit)
        if he > limit and be <= b_limit:
            out.append(_finding("gsp_over_limit", f"GSP export {he:.0f} MW is above its {limit:.0f} MW limit in {y} on this "
                                                  f"branch ({be:.0f} MW on {ctx.base_label}).",
                                ledger=("gsp_over_limit", "gsp", "gsp", y, None), **common))
        elif he > limit:
            kind = "gsp_worse" if he - be > GATE_GSP_WORSEN_MW else "preexisting"
            text = (f"GSP export is above its {limit:.0f} MW limit on {ctx.base_label} already ({be:.0f} MW) and this branch "
                    f"adds {he - be:.0f} MW ({he:.0f} MW) in {y}." if kind == "gsp_worse" else
                    f"GSP export is above its {limit:.0f} MW limit on {ctx.base_label} in {y} ({be:.0f} MW); this branch leaves it at {he:.0f} MW.")
            out.append(_finding(kind, text, ledger=("gsp_over_limit", "gsp", "gsp", y, None), **common))
        elif he > GSP_NEAR_LIMIT_FRACTION * limit:
            kind = "gsp_near_limit" if he > be + _EPS else "preexisting"
            text = (f"GSP export {he:.0f} MW is {he / limit:.0%} of its {limit:.0f} MW limit in {y} on this branch "
                    f"({be:.0f} MW on {ctx.base_label})." if kind == "gsp_near_limit" else
                    f"GSP export is within {1 - GSP_NEAR_LIMIT_FRACTION:.0%} of its limit on {ctx.base_label} in {y}; this branch does not add to it.")
            out.append(_finding(kind, text, ledger=("gsp_near_limit", "gsp", "gsp", y, None), **common))
    return out


def _n1(ctx: GateContext) -> list[GateFinding]:
    """New or worsened N-1 findings. Keyed by `diff.n1_key`, never by the diff's capped lists."""
    out: list[GateFinding] = []
    for y, b, h in ctx.common_years():
        bk = {n1_key(v): v for v in b.n1_violations}
        hk = {n1_key(v): v for v in h.n1_violations}
        for k in sorted(hk.keys() - bk.keys(), key=str):
            v = hk[k]
            kind = "n1_new_islanded" if v.get("type") == "islanded" else "n1_new_limit"
            out.append(_finding(kind, f"New N-1 finding in {y}: {v.get('message', '')}", year=y, case=v.get("case"),
                                element_kind=v.get("outage_type"), element_id=v.get("outage_id"), value=v.get("value"),
                                ledger=("n1", v.get("outage_type"), v.get("outage_id"), y, v.get("case"),
                                        (v.get("type"), v.get("element_id")))))
        same = 0
        for k in sorted(hk.keys() & bk.keys(), key=str):
            hv, bv = hk[k].get("value"), bk[k].get("value")
            if hv is not None and bv is not None and hv - bv > _EPS:
                v = hk[k]
                out.append(_finding("n1_worse", f"N-1 finding worse in {y}: {v.get('message', '')} ({bv:g} on {ctx.base_label}).",
                                    year=y, case=v.get("case"), element_kind=v.get("outage_type"), element_id=v.get("outage_id"),
                                    value=hv, base_value=bv,
                                    ledger=("n1", v.get("outage_type"), v.get("outage_id"), y, v.get("case"),
                                            (v.get("type"), v.get("element_id")))))
            else:
                same += 1
        if same:
            out.append(_finding("preexisting", f"{same} N-1 finding{'s' if same != 1 else ''} in {y} already on "
                                               f"{ctx.base_label}; this branch leaves {'them' if same != 1 else 'it'} as {'they are' if same != 1 else 'it is'}.",
                                year=y))
    return out


def _excess(a: Alert) -> float:
    """How far past its threshold an alert is (every demand-side check reads worse as further away)."""
    return 0.0 if a.value is None or a.limit is None else abs(a.value - a.limit)


def _alerts(ctx: GateContext) -> list[GateFinding]:
    out: list[GateFinding] = []
    for y, b, h in ctx.common_years():
        bk = {(a.kind, a.region_id): a for a in b.alerts}
        for a in sorted(h.alerts, key=lambda a: (a.kind, a.region_id)):
            ba = bk.get((a.kind, a.region_id))
            if ba is None:
                kind = "alert_new_breach" if a.level == "breach" else "alert_new_warn"
            elif a.level == "breach" and ba.level != "breach":
                kind = "alert_new_breach"
            elif _excess(a) - _excess(ba) > _EPS:
                kind = "alert_worse"
            else:
                kind = "preexisting"
            text = a.message if kind != "preexisting" else f"{a.message} (already so on {ctx.base_label})"
            out.append(_finding(kind, text, year=y, element_kind="region", element_id=a.region_id, value=a.value,
                                base_value=ba.value if ba else None, limit=a.limit,
                                ledger=("alert", "region", a.region_id, y, None, (a.kind,))))
    return out


def _works(ctx: GateContext) -> list[GateFinding]:
    out: list[GateFinding] = []
    if ctx.diff is None or not ctx.complete:
        return out
    for w in ctx.diff.works:
        severe = w.verdict_on_branch in SEVERE_VERDICTS
        if w.change == "worse":
            kind = "work_worse_severe" if severe else "work_worse"
        elif severe:
            kind = "work_infeasible"
        else:
            continue
        value = w.demand_at_risk_mw_branch if w.verdict_on_branch == "demand_at_risk" else w.curtailed_mw_branch
        base_value = (w.demand_at_risk_mw_main if w.verdict_on_main == "demand_at_risk" else w.curtailed_mw_main)
        out.append(_finding(kind, w.consequence or w.message, year=w.year, element_kind="outage", element_id=w.outage_id,
                            value=value, base_value=base_value, ledger=("work", "outage", w.outage_id, w.year, None)))
    return out


def _schedule(ctx: GateContext) -> list[GateFinding]:
    if not ctx.complete:
        return []
    out: list[GateFinding] = []
    for q in ctx.head.queue:
        if q.status not in ("Phase1", "Phase2"):
            continue
        s = ctx.scheduled.get(q.request_id)
        if not against_recommendation(q.recommended_year, s):
            continue
        text = (f"{q.request_id} is scheduled for {s}, earlier than the {q.recommended_year} the grid supports."
                if q.recommended_year is not None else
                f"{q.request_id} is scheduled for {s}, but the grid has no year it can host it.")
        out.append(_finding("against_recommendation", text, element_kind="project", element_id=q.request_id,
                            value=s, limit=q.recommended_year,
                            ledger=("against_recommendation", "project", q.request_id, None, None)))
    return out


def _profile(ctx: GateContext) -> list[GateFinding]:
    if not ctx.complete or ctx.head.params.scenario == ctx.base.params.scenario:
        return []
    return [_finding("profile_differs", f"Merging changes {ctx.base_label}'s demand profile from "
                                        f"{ctx.base.params.scenario} to {ctx.head.params.scenario}.")]


def _proposals(ctx: GateContext) -> list[GateFinding]:
    out: list[GateFinding] = []
    if ctx.removed_works:
        out.append(_finding("proposals_removed", f"Merging removes {len(ctx.removed_works)} planned works window"
                                                 f"{'s' if len(ctx.removed_works) != 1 else ''} from {ctx.base_label}: "
                                                 f"{', '.join(ctx.removed_works)}.", element_kind="outage"))
    if ctx.removed_reinforcements:
        out.append(_finding("proposals_removed", f"Merging removes {len(ctx.removed_reinforcements)} reinforcement"
                                                 f"{'s' if len(ctx.removed_reinforcements) != 1 else ''} from {ctx.base_label}: "
                                                 f"{', '.join(ctx.removed_reinforcements)}.", element_kind="reinforcement"))
    return out


def _deferred(ctx: GateContext) -> list[GateFinding]:
    if not ctx.complete:
        return []
    return [
        _finding("deferred_on_grid", f"{q.request_id} stays deferred: {q.reason.message}", case=q.reason.case,
                 element_kind="project", element_id=q.request_id, value=q.reason.value, limit=q.reason.limit,
                 ledger=("deferred", "project", q.request_id))
        for q in ctx.head.queue
        if q.status == "Deferred" and q.reason is not None and q.reason.type in GRID_REASON_TYPES
    ]


# the checks, one per concern; a new rule is one function + one entry here + its kinds in MERGE_GATE_LEVELS
MERGE_CHECKS: tuple[Callable[[GateContext], list[GateFinding]], ...] = (
    _stale, _no_result, _unstudied_years, _non_convergent, _behind_base,
    _thermal, _voltage, _gsp, _n1, _alerts, _works,
    _schedule, _profile, _proposals, _deferred,
)


def _summary(blockers: list[GateFinding], warnings: list[GateFinding]) -> str:
    def n(xs, word):
        return f"{len(xs)} {word}{'s' if len(xs) != 1 else ''}"
    if blockers:
        return f"{n(blockers, 'blocker')}, {n(warnings, 'warning')}: {blockers[0].message}"
    if warnings:
        return f"Ready to merge with {n(warnings, 'warning')}: {warnings[0].message}"
    return "Ready to merge: this branch introduces no new problem in any plan year."


def merge_verdict(
    head: OptimizeResult | None,
    base: OptimizeResult | None,
    diff: ConsequenceDiff | None = None,
    *,
    fresh: bool = True,
    stale_reasons: tuple[str, ...] | list[str] = (),
    scheduled: Mapping[str, int] | None = None,
    removed_works: tuple[str, ...] | list[str] = (),
    removed_reinforcements: tuple[str, ...] | list[str] = (),
    base_label: str = "main",
) -> MergeVerdict:
    """Run every check in MERGE_CHECKS on the branch (`head`) against its parent (`base`) and bucket
    the findings by level. `diff` is `diff_results(base, head)` when not given. Pure and deterministic."""
    if diff is None and head is not None and base is not None:
        diff = diff_results(base, head)
    ctx = GateContext(head=head, base=base, diff=diff, fresh=fresh, stale_reasons=tuple(stale_reasons),
                      scheduled=dict(scheduled or {}), removed_works=tuple(removed_works),
                      removed_reinforcements=tuple(removed_reinforcements), base_label=base_label)
    found = [f for check in MERGE_CHECKS for f in check(ctx)]

    def order(f: GateFinding):
        return (f.year or 0, f.kind, f.element_kind or "", f.element_id or "")

    blockers = sorted((f for f in found if f.level == "blocker"), key=order)
    warnings = sorted((f for f in found if f.level == "warning"), key=order)
    context = sorted((f for f in found if f.level == "info"), key=order)
    years = sorted(int(k) for k in diff.years) if diff is not None else []
    return MergeVerdict(ok=not blockers, blockers=blockers, warnings=warnings, context=context,
                        years_compared=years, summary=_summary(blockers, warnings))
