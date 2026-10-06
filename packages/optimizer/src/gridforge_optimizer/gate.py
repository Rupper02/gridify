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
  * a branch that fell behind its parent blocks, because merging replaces the parent's projects, works,
    reinforcements and demand profile: the parent's changes since the branch was opened (`parent_moved`,
    read by the API from the fork point) are taken in by a rebase, never dropped by a merge.

Connections are not gated by this (AGENTS.md rule 4: N-1 and planned works are reported, never a
connection gate). Merges are: a supply-security regression is exactly what "the grid will be broken"
means. `MERGE_CHECKS` is the registry, one function per concern; the LEVEL of every kind lives in
`config.MERGE_GATE_LEVELS`, so a policy change is data, not code.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from .config import (
    GATE_GSP_WORSEN_MW,
    GATE_NOISE,
    GATE_VM_WORSEN_PU,
    GATE_WORSEN_PTS,
    GSP_NEAR_LIMIT_FRACTION,
    LINE_LOADING_MAX_PCT,
    MERGE_GATE_LEVELS,
    N1_ISLAND_MIN_MW,
    PLAN_YEARS,
    TRAFO_LOADING_MAX_PCT,
)
from .diff import ConsequenceDiff, YearDelta, diff_results
from .findings import (
    GRID_REASON_TYPES,
    SEVERE_VERDICTS,
    _pct,
    against_recommendation,
    alert_id,
    fingerprint,
    gsp_id,
    n1_id,
    n1_key,
    overload_id,
    project_id,
    voltage_id,
    work_id,
    year_id,
)
from .types import Alert, GateFinding, MergeVerdict, OptimizeResult, YearResult



class ParentMove(NamedTuple):
    """One change the parent received after the branch was opened, which the branch does not have."""

    element_kind: str | None  # project | outage | reinforcement | None (the demand profile)
    element_id: str | None
    text: str  # "ECR-AD82A: export rating 4 MW → 3.5 MW"


@dataclass(frozen=True)
class GateContext:
    """Everything a check may read. `fresh` is the API's verdict on whether `head` was solved for the
    branch's current inputs; the checks never second-guess it. `parent_moved` is None when the branch's
    fork point is not known (no common ancestor with its parent, or judged against another branch than
    its parent); `fork_unknown` says the first case, so the gate can say what it cannot tell."""

    head: OptimizeResult | None
    base: OptimizeResult | None
    diff: ConsequenceDiff | None
    fresh: bool = True
    stale_reasons: tuple[str, ...] = ()
    scheduled: Mapping[str, int] = field(default_factory=dict)
    removed_works: tuple[str, ...] = ()
    removed_reinforcements: tuple[str, ...] = ()
    base_label: str = "main"
    parent_moved: tuple[ParentMove, ...] | None = None
    fork_unknown: bool = False
    base_profile: str | None = None  # the base's OWN demand profile when it was solved on the branch's for the comparison

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
        missing = [y for y in PLAN_YEARS if str(y) not in r.years]
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
                                year=y, ledger=year_id("non_convergent", y)))
        else:
            out.append(_finding("preexisting", f"The power flow does not converge in {y} on {ctx.base_label} either.", year=y))
    return out


def _behind_base(ctx: GateContext) -> list[GateFinding]:
    """Merging REPLACES the parent's state with the branch's: whatever the parent received after the
    branch was opened would silently disappear. With the fork point known, each such change blocks until
    the branch is rebased (whatever its run says); without it, only a project missing from the branch can
    be seen, from the diff."""
    if ctx.parent_moved is not None:
        return [_finding("behind_base", f"{ctx.base_label} changed after this branch was opened: {m.text}. Merging would undo it: "
                                        f"rebase this branch onto {ctx.base_label} to take it in.",
                         element_kind=m.element_kind, element_id=m.element_id)
                for m in ctx.parent_moved]
    if not ctx.complete or ctx.diff is None:
        return []
    return [
        _finding("behind_base",
                 f"{p.request_id} is on {ctx.base_label} but not on this branch: it merged after the branch was "
                 f"opened, and merging would drop it. Open a new branch from {ctx.base_label}.",
                 element_kind="project", element_id=p.request_id)
        for p in ctx.diff.projects if p.change == "dropped"
    ]


def _fork_unknown(ctx: GateContext) -> list[GateFinding]:
    if not ctx.fork_unknown:
        return []
    return [_finding("fork_unknown", f"Where this branch started from {ctx.base_label} is not known (it was opened from a branch "
                                     f"before fork points were recorded), so a change {ctx.base_label} received since cannot be told "
                                     f"from this branch's own, and merging replaces {ctx.base_label}'s projects, works, reinforcements "
                                     f"and demand profile with this branch's. Rebase it onto {ctx.base_label} first: every difference "
                                     f"between the two is then yours to pick.")]


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
                                    limit=limit, ledger=overload_id(table, eid, y)))
            for eid in sorted((h_over & b_over) - new):
                bv, hv = bl[eid], hl[eid]
                kind = "overload_worse" if hv - bv > GATE_WORSEN_PTS else "preexisting"
                text = (f"{label} {eid} is over its rating on {ctx.base_label} already ({bv:.0f}%) and loads "
                        f"{hv - bv:.0f} points more on this branch ({hv:.0f}%) in {y}." if kind == "overload_worse" else
                        f"{label} {eid} is over its rating on {ctx.base_label} in {y} ({bv:.0f}%); this branch leaves it at {hv:.0f}%.")
                out.append(_finding(kind, text, year=y, element_kind=table, element_id=eid, value=hv, base_value=bv,
                                    limit=limit, ledger=overload_id(table, eid, y)))
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
                                ledger=voltage_id(bus, y)))
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
                                ledger=voltage_id(bus, y)))
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
                                ledger=gsp_id("gsp_over_limit", y), **common))
        elif he > limit:
            kind = "gsp_worse" if he - be > GATE_GSP_WORSEN_MW else "preexisting"
            text = (f"GSP export is above its {limit:.0f} MW limit on {ctx.base_label} already ({be:.0f} MW) and this branch "
                    f"adds {he - be:.0f} MW ({he:.0f} MW) in {y}." if kind == "gsp_worse" else
                    f"GSP export is above its {limit:.0f} MW limit on {ctx.base_label} in {y} ({be:.0f} MW); this branch leaves it at {he:.0f} MW.")
            out.append(_finding(kind, text, ledger=gsp_id("gsp_over_limit", y), **common))
        elif he > GSP_NEAR_LIMIT_FRACTION * limit:
            kind = "gsp_near_limit" if he > be + GATE_NOISE else "preexisting"
            text = (f"GSP export {he:.0f} MW is {he / limit:.0%} of its {limit:.0f} MW limit in {y} on this branch "
                    f"({be:.0f} MW on {ctx.base_label})." if kind == "gsp_near_limit" else
                    f"GSP export is within {1 - GSP_NEAR_LIMIT_FRACTION:.0%} of its limit on {ctx.base_label} in {y}; this branch does not add to it.")
            out.append(_finding(kind, text, ledger=gsp_id("gsp_near_limit", y), **common))
    return out


# when the same N-1 finding (same outage, case and breached element) counts as WORSE on the branch, per kind of breach,
# with the planning tolerances the intact checks use, and how its figure reads: (moved beyond the tolerance, figure)
_N1_WORSE: dict[str, tuple[Callable[[float, float], bool], Callable[[float], str]]] = {
    "line": (lambda h, b: h - b > GATE_WORSEN_PTS, lambda v: f"{v:.1f}%"),
    "trafo": (lambda h, b: h - b > GATE_WORSEN_PTS, lambda v: f"{v:.1f}%"),
    # further outside its band: further from 1.0 pu, in either direction (as `_voltage`)
    "voltage": (lambda h, b: abs(h - 1.0) - abs(b - 1.0) > GATE_VM_WORSEN_PU, lambda v: f"{v:.3f} pu"),
    "islanded": (lambda h, b: h - b > N1_ISLAND_MIN_MW, lambda v: f"{v:.1f} MW"),
    # a collapse deeper: its lowest voltage lower (network.N1_COLLAPSE_VM_PU)
    "collapse": (lambda h, b: b - h > GATE_VM_WORSEN_PU, lambda v: f"{v:.3f} pu"),
}
_N1_NEW_KIND = {"islanded": "n1_new_islanded", "collapse": "n1_new_collapse"}  # by the kind of breach; a limit otherwise
_CASE_TEXT = {"winter_peak": "winter peak", "summer_min": "summer minimum"}  # the study cases as the gate names them


def _n1_badness(v: dict) -> float:
    """Larger is worse, within one outage's findings: a loading or MW figure as it is, a voltage by its distance from 1 pu."""
    x = v.get("value")
    if not isinstance(x, (int, float)):
        return 0.0
    return abs(1.0 - float(x)) if v.get("type") in ("voltage", "collapse") else float(x)


def _n1_detail(v: dict) -> str:
    """An N-1 record's message without its "<element> out" head: the grouped finding names the outage once."""
    msg = str(v.get("message") or "")
    head = f"{v.get('outage_type')} {v.get('outage_id')} out"
    return msg[len(head):].lstrip(": ").strip() if msg.startswith(head) else msg


def _n1(ctx: GateContext) -> list[GateFinding]:
    """New or worsened N-1 findings, each outage once per case: what one outage adds across the plan years is one gate
    item with its count, its years and the worst of them (the summer-minimum screen is not grown, so it repeats every
    year: an outage that breaches five elements in nine years is one blocker, not forty-five). Keyed by `findings.n1_key`,
    never by the diff's capped lists; worse per kind of breach (`_N1_WORSE`), a smaller move is context, per year."""
    new: dict[tuple, list[tuple[int, dict]]] = {}
    worse: dict[tuple, list[tuple[int, dict, dict]]] = {}
    out: list[GateFinding] = []
    for y, b, h in ctx.common_years():
        bk = {n1_key(v): v for v in b.n1_violations}
        hk = {n1_key(v): v for v in h.n1_violations}
        for k in sorted(hk.keys() - bk.keys(), key=str):
            v = hk[k]
            kind = _N1_NEW_KIND.get(v.get("type"), "n1_new_limit")
            new.setdefault((v.get("outage_type"), str(v.get("outage_id")), v.get("case"), kind), []).append((y, v))
        same = 0
        for k in sorted(hk.keys() & bk.keys(), key=str):
            hv, bv = hk[k].get("value"), bk[k].get("value")
            is_worse, _figure = _N1_WORSE.get(hk[k].get("type"), (lambda h, b: False, str))
            if hv is not None and bv is not None and is_worse(hv, bv):
                v = hk[k]
                worse.setdefault((v.get("outage_type"), str(v.get("outage_id")), v.get("case")), []).append((y, v, bk[k]))
            else:
                same += 1
        if same:
            out.append(_finding("preexisting", f"{same} N-1 finding{'s' if same != 1 else ''} in {y} already on "
                                               f"{ctx.base_label}; this branch leaves {'them' if same != 1 else 'it'} as {'they are' if same != 1 else 'it is'}.",
                                year=y))
    for (otype, oid, case, kind), members in new.items():
        years = sorted({y for y, _ in members})
        wy, wv = max(members, key=lambda m: (_n1_badness(m[1]), -m[0]))
        n = len({n1_key(v) for _, v in members})
        where = f"{otype} {oid} out at {_CASE_TEXT.get(case, case)}, {_years_text(years)}"
        text = (f"{where}: {n} element{'s' if n != 1 else ''} newly breach{'' if n != 1 else 'es'} a limit; worst: {_n1_detail(wv)}." if kind == "n1_new_limit"
                else f"{where}: {_n1_detail(wv)}.")
        out.append(_finding(kind, text, year=years[0], case=case, element_kind=otype, element_id=oid, value=wv.get("value"),
                            ledger=n1_id(wv, wy)))
    for (otype, oid, case), members in worse.items():
        years = sorted({y for y, _, _ in members})
        wy, wv, wb = max(members, key=lambda m: (_n1_badness(m[1]) - _n1_badness(m[2]), -m[0]))
        _is_worse, figure = _N1_WORSE[wv.get("type")]
        n = len({n1_key(v) for _, v, _ in members})
        out.append(_finding("n1_worse", f"{otype} {oid} out at {_CASE_TEXT.get(case, case)}, {_years_text(years)}: {n} finding{'s' if n != 1 else ''} "
                                        f"worse than on {ctx.base_label}; worst: {_n1_detail(wv)} (now {figure(wv.get('value'))}, "
                                        f"{figure(wb.get('value'))} on {ctx.base_label}).",
                            year=years[0], case=case, element_kind=otype, element_id=oid, value=wv.get("value"), base_value=wb.get("value"),
                            ledger=n1_id(wv, wy)))
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
            elif _excess(a) - _excess(ba) > GATE_NOISE:
                kind = "alert_worse"
            else:
                kind = "preexisting"
            text = a.message if kind != "preexisting" else f"{a.message} (already so on {ctx.base_label})"
            out.append(_finding(kind, text, year=y, element_kind="region", element_id=a.region_id, value=a.value,
                                base_value=ba.value if ba else None, limit=a.limit,
                                ledger=alert_id(a.region_id, y, a.kind)))
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
        elif not w.on_base and (w.verdict_on_branch != "feasible" or (w.n1_findings_branch or 0) > 0):
            kind = "work_new"  # a window the branch adds, with a cost main does not carry (curtailment, second faults)
        else:
            continue
        value = w.demand_at_risk_mw_branch if w.verdict_on_branch == "demand_at_risk" else w.curtailed_mw_branch
        base_value = (w.demand_at_risk_mw_main if w.verdict_on_main == "demand_at_risk" else w.curtailed_mw_main)
        out.append(_finding(kind, w.consequence or w.message, year=w.year, element_kind="outage", element_id=w.outage_id,
                            value=value, base_value=base_value, ledger=work_id(w.outage_id, w.year)))
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
                            ledger=project_id("against_recommendation", q.request_id)))
    return out


def _profile(ctx: GateContext) -> list[GateFinding]:
    """Merging adopts the branch's demand profile. The comparison itself is like for like (the API solves the base on the
    branch's profile), so the base's own profile comes in as `base_profile`; the results' labels then agree."""
    if not ctx.complete:
        return []
    base_profile = ctx.base_profile or ctx.base.params.scenario
    if ctx.head.params.scenario == base_profile:
        return []
    return [_finding("profile_differs", f"Merging changes {ctx.base_label}'s demand profile from "
                                        f"{base_profile} to {ctx.head.params.scenario}.")]


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
                 ledger=project_id("deferred", q.request_id))
        for q in ctx.head.queue
        if q.status == "Deferred" and q.reason is not None and q.reason.type in GRID_REASON_TYPES
    ]


# the checks, one per concern; a new rule is one function + one entry here + its kinds in MERGE_GATE_LEVELS
MERGE_CHECKS: tuple[Callable[[GateContext], list[GateFinding]], ...] = (
    _stale, _no_result, _unstudied_years, _non_convergent, _behind_base, _fork_unknown,
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
    parent_moved: Sequence[ParentMove] | None = None,
    fork_unknown: bool = False,
    base_profile: str | None = None,
) -> MergeVerdict:
    """Run every check in MERGE_CHECKS on the branch (`head`) against its parent (`base`) and bucket
    the findings by level. `diff` is `diff_results(base, head)` when not given; `base_profile` is the base's own
    demand profile when `base` was solved on the branch's (`_profile`). Pure and deterministic."""
    if diff is None and head is not None and base is not None:
        diff = diff_results(base, head)
    ctx = GateContext(head=head, base=base, diff=diff, fresh=fresh, stale_reasons=tuple(stale_reasons),
                      scheduled=dict(scheduled or {}), removed_works=tuple(removed_works),
                      removed_reinforcements=tuple(removed_reinforcements), base_label=base_label,
                      parent_moved=None if parent_moved is None else tuple(parent_moved), fork_unknown=fork_unknown,
                      base_profile=base_profile)
    found = [f for check in MERGE_CHECKS for f in check(ctx)]

    def order(f: GateFinding):
        return (f.year or 0, f.kind, f.element_kind or "", f.element_id or "")

    blockers = sorted((f for f in found if f.level == "blocker"), key=order)
    warnings = sorted((f for f in found if f.level == "warning"), key=order)
    context = sorted((f for f in found if f.level == "info"), key=order)
    years = sorted(int(k) for k in diff.years) if diff is not None else []
    return MergeVerdict(ok=not blockers, blockers=blockers, warnings=warnings, context=context,
                        years_compared=years, summary=_summary(blockers, warnings))
