"""Compare two plans: turn two `PlanResult`s into what changed, year by year.

For every plan year both runs solved: the worst line and transformer loadings, the voltage range, the GSP export,
which lines and transformers newly overload or clear, the biggest movers, the breaches each side carries, and which
connections are in service on one side only. Pure and deterministic: no I/O, no pandapower; it only reshapes fields
already on the two results.
"""

from __future__ import annotations

from pydantic import BaseModel

from .config import DIFF_NOISE, LINE_LOADING_MAX_PCT, TRAFO_LOADING_MAX_PCT
from .types import PlanResult, Reason, YearResult

_TOP = 8  # the biggest loading movers listed per kind (every crossing of the limit is listed besides)


class LoadingDelta(BaseModel):
    """One line's or transformer's loading in a year, base vs head (the kind is the list it sits in)."""

    element_id: int
    base_pct: float | None = None
    head_pct: float | None = None
    delta: float = 0.0
    crossed: str = "unchanged"  # newly_overloaded|cleared|worsened|eased|unchanged


class YearDelta(BaseModel):
    """The network effect of head against base in one plan year."""

    year: int
    worst_line_base: float = 0.0
    worst_line_head: float = 0.0
    worst_line_delta: float = 0.0
    worst_trafo_base: float = 0.0
    worst_trafo_head: float = 0.0
    worst_trafo_delta: float = 0.0
    min_vm_delta: float = 0.0
    max_vm_delta: float = 0.0
    gsp_export_base: float = 0.0
    gsp_export_head: float = 0.0
    gsp_export_delta: float = 0.0
    gsp_limit_mw: float | None = None
    violations_base: int = 0
    violations_head: int = 0
    new_violations: list[Reason] = []  # breaches head carries that base does not (by type, element and case)
    cleared_violations: list[Reason] = []  # breaches base carries that head does not
    newly_overloaded_line_ids: list[int] = []
    cleared_line_ids: list[int] = []
    newly_overloaded_trafo_ids: list[int] = []
    cleared_trafo_ids: list[int] = []
    top_line_deltas: list[LoadingDelta] = []
    top_trafo_deltas: list[LoadingDelta] = []
    energised_only_head: list[str] = []  # in service this year on head but not on base
    energised_only_base: list[str] = []


class PlanDiff(BaseModel):
    headline: dict
    years: dict[str, YearDelta] = {}  # plan year -> its network delta (years solved on both runs)


def _crossed(base_pct: float | None, head_pct: float | None, delta: float, limit: float) -> str:
    b_over = base_pct is not None and base_pct > limit
    h_over = head_pct is not None and head_pct > limit
    if h_over and not b_over:
        return "newly_overloaded"
    if b_over and not h_over:
        return "cleared"
    if delta > DIFF_NOISE:
        return "worsened"
    if delta < -DIFF_NOISE:
        return "eased"
    return "unchanged"


def _loading_deltas(base: dict[int, float], head: dict[int, float], limit: float) -> list[LoadingDelta]:
    """The biggest movers between two loading maps (top _TOP by |delta|), plus every element that crosses the limit
    either way, so no new overload is ever cut off the list. Unmoved elements are left out."""
    out: list[LoadingDelta] = []
    for eid in base.keys() | head.keys():
        bp, hp = base.get(eid), head.get(eid)
        delta = round((hp or 0.0) - (bp or 0.0), 1)
        out.append(LoadingDelta(element_id=int(eid), base_pct=bp, head_pct=hp, delta=delta, crossed=_crossed(bp, hp, delta, limit)))
    out = [d for d in out if d.crossed != "unchanged"]
    out.sort(key=lambda d: (-abs(d.delta), d.element_id))
    return out[:_TOP] + [d for d in out[_TOP:] if d.crossed in ("newly_overloaded", "cleared")]


def _over(loading: dict[int, float], limit: float) -> set[int]:
    return {int(i) for i, v in loading.items() if v is not None and v > limit}


def _key(r: Reason) -> tuple:
    return (r.type, r.element_id, r.case)


def diff_year(base: YearResult, head: YearResult) -> YearDelta:
    """The network delta of one plan year, head against base (pure)."""
    b_over, h_over = _over(base.line_loading, LINE_LOADING_MAX_PCT), _over(head.line_loading, LINE_LOADING_MAX_PCT)
    bt_over, ht_over = _over(base.trafo_loading, TRAFO_LOADING_MAX_PCT), _over(head.trafo_loading, TRAFO_LOADING_MAX_PCT)
    b_v, h_v = {_key(r): r for r in base.violations}, {_key(r): r for r in head.violations}
    return YearDelta(
        year=head.year,
        worst_line_base=base.worst_line_loading_pct,
        worst_line_head=head.worst_line_loading_pct,
        worst_line_delta=round(head.worst_line_loading_pct - base.worst_line_loading_pct, 1),
        worst_trafo_base=base.worst_trafo_loading_pct,
        worst_trafo_head=head.worst_trafo_loading_pct,
        worst_trafo_delta=round(head.worst_trafo_loading_pct - base.worst_trafo_loading_pct, 1),
        min_vm_delta=round(head.min_vm_pu - base.min_vm_pu, 4),
        max_vm_delta=round(head.max_vm_pu - base.max_vm_pu, 4),
        gsp_export_base=round(base.gsp_export_mw, 1),
        gsp_export_head=round(head.gsp_export_mw, 1),
        gsp_export_delta=round(head.gsp_export_mw - base.gsp_export_mw, 1),
        gsp_limit_mw=head.gsp_limit_mw,
        violations_base=len(base.violations),
        violations_head=len(head.violations),
        new_violations=[h_v[k] for k in h_v if k not in b_v],
        cleared_violations=[b_v[k] for k in b_v if k not in h_v],
        newly_overloaded_line_ids=sorted(h_over - b_over),
        cleared_line_ids=sorted(b_over - h_over),
        newly_overloaded_trafo_ids=sorted(ht_over - bt_over),
        cleared_trafo_ids=sorted(bt_over - ht_over),
        top_line_deltas=_loading_deltas(base.line_loading, head.line_loading, LINE_LOADING_MAX_PCT),
        top_trafo_deltas=_loading_deltas(base.trafo_loading, head.trafo_loading, TRAFO_LOADING_MAX_PCT),
        energised_only_head=sorted(set(head.energised) - set(base.energised)),
        energised_only_base=sorted(set(base.energised) - set(head.energised)),
    )


def diff_plans(base: PlanResult, head: PlanResult) -> PlanDiff:
    """`diff_year` for every plan year solved on both runs, and a headline across them."""
    years = {k: diff_year(base.years[k], head.years[k]) for k in sorted(base.years.keys() & head.years.keys())}
    first_new = next((int(k) for k, d in years.items() if d.new_violations), None)
    headline = {
        "years_compared": len(years),
        "years_with_new_violations": sum(1 for d in years.values() if d.new_violations),
        "years_with_cleared_violations": sum(1 for d in years.values() if d.cleared_violations),
        "first_year_with_new_violations": first_new,
        "worst_line_delta": max((d.worst_line_delta for d in years.values()), default=0.0),
        "gsp_export_delta": max((d.gsp_export_delta for d in years.values()), default=0.0),
    }
    return PlanDiff(headline=headline, years=years)
