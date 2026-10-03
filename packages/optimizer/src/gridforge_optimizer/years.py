"""The plan year by year: after the greedy run has decided who connects, solve each year of the
plan as it would stand then, so the timeline switches between stored results instead of re-running.

A year's network is today's network with demand grown to that year (interpolated between the 2030
and 2035 anchors) and every accepted project whose energisation year (the operator's scheduled year,
else the optimizer's recommendation) has arrived. It is solved in both study cases, screened N-1,
and each planned outage in that year is studied in its season; the demand side (demand.py: regions,
firm headroom, P2/8 class, alerts) is read off the same solved net. Nothing here decides who connects:
the queue comes from greedy.optimize, so this is a fixed-plan evaluation (two solves plus the N-1
screen per year), cheap next to the greedy trials.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .config import PLAN_END_YEAR, PLAN_START_YEAR
from .demand import assess_demand
from .greedy import NetFactory, Progress
from .network import (
    apply_reinforcement,
    build_base_net,
    bus_voltages,
    feasibility,
    grow_demand,
    inject_sgen,
    interpolate_growth_for_year,
    line_loadings,
    n1_screen,
    overloaded_line_ids,
    study_outage,
    trafo_loadings,
    voltage_violation_bus_ids,
)
from .types import Candidate, OptimizeParams, OptimizeResult, Outage, Reinforcement, YearResult

PLAN_YEARS = tuple(range(PLAN_START_YEAR, PLAN_END_YEAR + 1))


def year_order(view_year: int | None, years: Iterable[int] = PLAN_YEARS) -> list[int]:
    """The order to solve the years in: the one the operator is looking at first, then the two
    policy horizons, then the rest chronologically, so the most useful results land first."""
    years = list(years)
    first = [y for y in (view_year, 2030, 2035) if y in years]
    seen: list[int] = []
    for y in first + years:
        if y not in seen:
            seen.append(y)
    return seen


def _horizon(year: int) -> int:
    """The planning horizon whose per-bus growth shape a year takes (2030 up to it, 2035 after)."""
    return 2030 if year <= 2030 else 2035


def energisation_years(result: OptimizeResult, scheduled: dict[str, int | None] | None = None) -> dict[str, int]:
    """Each accepted project's year in service: the operator's scheduled year if set, else the
    optimizer's recommendation. Deferred and rejected projects never energise."""
    scheduled = scheduled or {}
    out: dict[str, int] = {}
    for q in result.queue:
        if q.status not in ("Phase1", "Phase2"):
            continue
        y = scheduled.get(q.request_id) or q.recommended_year
        if y is not None:
            out[q.request_id] = int(y)
    return out


def evaluate_year(
    year: int,
    candidates: list[Candidate],
    params: OptimizeParams,
    in_service: dict[str, int],
    *,
    outages: list[Outage] = (),
    reinforcements: list[Reinforcement] = (),
    n1: bool = True,
    net_factory: NetFactory = build_base_net,
) -> YearResult:
    """Solve one year of the plan (see the module docstring)."""
    growth = interpolate_growth_for_year(year, params.growth_2030, params.growth_2035)
    net = net_factory()
    grow_demand(net, growth, params.scenario, _horizon(year))
    for r in reinforcements:
        apply_reinforcement(net, r)
    energised = []
    for c in candidates:
        y = in_service.get(c.request_id)
        if y is not None and y <= year and c.bus_id is not None:
            inject_sgen(net, c.bus_id, c.rating_mw or 0.0, c.request_id, c.technology, import_mw=c.import_mw)
            energised.append(c.request_id)

    feasibility(net)  # settles the taps for the intact state
    studies = [study_outage(net, o) for o in outages if o.year == year]
    screen = n1_screen(net) if n1 else {"screened": 0, "violations": []}
    _, _, m = feasibility(net)  # the intact envelope the map and readings show
    yr = YearResult(
        year=year,
        growth=round(growth, 4),
        energised=energised,
        accepted=energised,
        worst_line_loading_pct=round(m.get("max_line_pct", 0.0), 1),
        worst_trafo_loading_pct=round(m.get("max_trafo_pct", 0.0), 1),
        min_vm_pu=round(m.get("min_vm", 0.0), 4),
        max_vm_pu=round(m.get("max_vm", 0.0), 4),
        overloaded_line_ids=overloaded_line_ids(net),
        line_loading=line_loadings(net),
        trafo_loading=trafo_loadings(net),
        bus_vm=bus_voltages(net),
        voltage_violation_bus_ids=voltage_violation_bus_ids(net),
        gsp_export_mw=m.get("gsp_export_mw", 0.0),
        gsp_import_mw=m.get("gsp_import_mw", 0.0),
        gsp_limit_mw=m.get("gsp_limit_mw"),
        n1_screened=screen["screened"],
        n1_violations=screen["violations"],
        outage_studies=studies,
    )
    # the demand side (regions + alerts) reads the intact envelope just solved, so it comes last
    yr.regions, yr.alerts = assess_demand(net, year, screen["violations"])
    return yr


def evaluate_years(
    result: OptimizeResult,
    candidates: list[Candidate],
    params: OptimizeParams,
    *,
    scheduled: dict[str, int | None] | None = None,
    outages: list[Outage] = (),
    reinforcements: list[Reinforcement] = (),
    view_year: int | None = None,
    years: Iterable[int] = PLAN_YEARS,
    net_factory: NetFactory = build_base_net,
    progress: Progress | None = None,
    on_year: Callable[[YearResult], None] | None = None,
) -> dict[str, YearResult]:
    """Solve every year of the plan in `year_order` (the viewed year first). `on_year` is called as
    each year lands, so a caller can publish partial results; `progress(stage, fraction)` reports
    fractions within this step (0..1)."""
    report = progress or (lambda _s, _f: None)
    in_service = energisation_years(result, scheduled)
    order = year_order(view_year, years)
    out: dict[str, YearResult] = {}
    for i, y in enumerate(order):
        n_out = sum(1 for o in outages if o.year == y)
        report(f"year {y}: both cases, N-1" + (f", {n_out} planned outage{'s' if n_out != 1 else ''}" if n_out else ""),
               i / len(order))
        yr = evaluate_year(y, candidates, params, in_service, outages=outages, reinforcements=reinforcements,
                           net_factory=net_factory)
        out[str(y)] = yr
        if on_year is not None:
            on_year(yr)
    report("years done", 1.0)
    return {k: out[k] for k in sorted(out)}
