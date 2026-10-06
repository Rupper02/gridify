"""The plan year by year: after the greedy run has decided who connects, solve each year of the
plan as it would stand then, so the timeline switches between stored results instead of re-running.

A year's network is today's network with demand grown to that year (interpolated between the 2030
and 2035 anchors) and every accepted project whose energisation year (the operator's scheduled year,
else the optimizer's recommendation) has arrived. It is solved in both study cases, screened N-1 in
each case of config.N1_CASES,
and that year's planned windows are studied in their season (maintenance.study_windows). Works
finished in an earlier year leave their change behind (a repowered element, maintenance.WORKS), so
later years are solved with it; the queue is not re-decided for it. The demand side (demand.py:
regions, firm headroom, P2/8 class, alerts) is read off the same solved net. Nothing here decides who connects:
the queue comes from greedy.optimize, so this is a fixed-plan evaluation (two solves plus the N-1
screen per year), cheap next to the greedy trials.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, MutableMapping

from .config import PLAN_END_YEAR, PLAN_START_YEAR
from .demand import assess_demand
from .greedy import NetFactory, Progress
from .maintenance import WORKS, apply_works_after, study_windows
from .network import (
    apply_reinforcement,
    build_base_net,
    bus_voltages,
    demand_multiplier,
    feasibility,
    grow_for,
    inject_project,
    line_loadings,
    n1_screen,
    n1_screen_cases,
    overloaded_line_ids,
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
    n1_windows: bool | None = None,
    net_factory: NetFactory = build_base_net,
) -> YearResult:
    """Solve one year of the plan (see the module docstring). `n1` runs the year's own N-1 screen;
    `n1_windows` the screen during that year's works windows (the year's setting when None)."""
    screen_windows = n1 if n1_windows is None else n1_windows
    growth = demand_multiplier(params, year)
    net = net_factory()
    grow_for(net, params, growth, _horizon(year))
    for r in reinforcements:
        apply_reinforcement(net, r)
    apply_works_after(net, outages, year)  # repowered elements, from the year after their window
    energised = []
    for c in candidates:
        y = in_service.get(c.request_id)
        if y is not None and y <= year and c.bus_id is not None:
            inject_project(net, c)
            energised.append(c.request_id)

    feasibility(net)  # settles the taps for the intact state
    studies = study_windows(net, [o for o in outages if o.year == year], screen=n1_screen if screen_windows else None)
    screen = n1_screen_cases(net) if n1 else {"cases": [], "screened": 0, "violations": []}
    _, intact_reason, m = feasibility(net)  # the intact envelope the map and readings show
    yr = YearResult(
        year=year,
        growth=round(growth, 4),
        energised=energised,
        accepted=energised,
        converged=intact_reason is None or intact_reason.type != "non_convergent",
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
        n1_cases=screen["cases"],
        n1_screened=screen["screened"],
        n1_violations=screen["violations"],
        outage_studies=studies,
    )
    # the demand side (regions + alerts) reads the intact envelope just solved, so it comes last
    yr.regions, yr.alerts = assess_demand(net, year, screen["violations"])
    return yr


def year_signature(
    year: int,
    candidates: list[Candidate],
    params: OptimizeParams,
    in_service: dict[str, int],
    *,
    outages: list[Outage] = (),
    reinforcements: list[Reinforcement] = (),
) -> str:
    """Everything one year's result depends on, as a stable key: the demand (pathway and anchors),
    the projects in service that year, the reinforcements, that year's windows and the works finished
    before it that leave a change behind. Two plans with the same signature for a year have the same
    result for it, so an edit only re-solves the years whose signature it changes (an outage in 2031
    re-solves 2031, and the later years only if it repowers something)."""
    energised = sorted(
        (c.request_id, c.bus_id, c.rating_mw, c.import_mw, c.technology)
        for c in candidates
        if (y := in_service.get(c.request_id)) is not None and y <= year and c.bus_id is not None
    )
    works = sorted(
        (o.model_dump_json() for o in outages if o.year == year or (o.year < year and WORKS[o.work].after is not None)),
    )
    sig = [year, params.scenario, round(params.growth_2030, 4), round(params.growth_2035, 4), energised,
           sorted(r.model_dump_json() for r in reinforcements), works]
    if params.curve:  # an entered forecast's own figure for the year (the FES path is set by its anchors above)
        sig.append(round(demand_multiplier(params, year), 4))
    return hashlib.sha256(json.dumps(sig, default=str).encode()).hexdigest()[:24]


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
    cache: MutableMapping[str, YearResult] | None = None,
) -> dict[str, YearResult]:
    """Solve every year of the plan in `year_order` (the viewed year first). `on_year` is called as
    each year lands, so a caller can publish partial results; `progress(stage, fraction)` reports
    fractions within this step (0..1).

    `cache` (optional, a mapping the caller keeps) holds year results by `year_signature`, so a
    re-run after a small edit solves only the years the edit touches. Like greedy's trial cache, the
    caller must key the mapping by network snapshot and engine version (and the net factory)."""
    report = progress or (lambda _s, _f: None)
    in_service = energisation_years(result, scheduled)
    order = year_order(view_year, years)
    out: dict[str, YearResult] = {}
    for i, y in enumerate(order):
        n_out = sum(1 for o in outages if o.year == y)
        report(f"year {y}: both cases, N-1" + (f", {n_out} planned outage{'s' if n_out != 1 else ''}" if n_out else ""),
               i / len(order))
        key = year_signature(y, candidates, params, in_service, outages=outages, reinforcements=reinforcements)
        yr = cache.get(key) if cache is not None else None
        if yr is None:
            yr = evaluate_year(y, candidates, params, in_service, outages=outages, reinforcements=reinforcements,
                               net_factory=net_factory)
            if cache is not None:
                cache[key] = yr
        out[str(y)] = yr
        if on_year is not None:
            on_year(yr)
    report("years done", 1.0)
    return {k: out[k] for k in sorted(out)}
