"""The plan year by year: solve each plan year as it would stand then, so the timeline switches between stored
results instead of re-running.

A year's network is today's network with demand grown to that year (per primary on the built-in grid's DFES
projections, or between the `custom` anchors) and every connection whose year has arrived. It is solved in both study
cases (`network.feasibility`) and reported as it stands: every figure, every breach. Nothing here decides who connects:
the operator places each connection and its year.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, MutableMapping

from .config import PLAN_END_YEAR, PLAN_START_YEAR, PLAN_YEARS  # noqa: F401  (PLAN_YEARS re-exported)
from .network import build_base_net, demand_multiplier, feasibility, plan_net, snapshot
from .types import Connection, PlanParams, PlanResult, YearResult

NetFactory = Callable[[], object]
Progress = Callable[[str, float], None]


def year_order(view_year: int | None, years: Iterable[int] = PLAN_YEARS) -> list[int]:
    """The order to solve the years in: the one the operator is looking at first, then the rest chronologically, so
    the result they are waiting for lands first."""
    years = list(years)
    return ([view_year] if view_year in years else []) + [y for y in years if y != view_year]


def in_service(connections: Iterable[Connection], year: int) -> list[Connection]:
    """The connections energised by `year` (each from its own year on)."""
    return [c for c in connections if c.year <= year]


def evaluate_year(year: int, connections: list[Connection], params: PlanParams, *,
                  net_factory: NetFactory = build_base_net) -> YearResult:
    """Solve one year of the plan (see the module docstring)."""
    energised = in_service(connections, year)
    net = plan_net(net_factory, params, year, energised)
    _, breaches, m = feasibility(net)
    converged = not (breaches and breaches[0].type == "non_convergent")
    return YearResult(
        year=year,
        growth=float(net["demand_growth"]),
        energised=[c.request_id for c in energised],
        converged=converged,
        violations=breaches,
        **(snapshot(net, m) if converged else {}),
    )


def year_signature(year: int, connections: list[Connection], params: PlanParams) -> str:
    """Everything one year's result depends on, as a stable key: the demand (pathway and anchors) and the connections
    in service that year. Two plans with the same signature for a year have the same result for it, so an edit only
    re-solves the years it changes (a connection energising in 2031 leaves 2026-2030 as they were)."""
    energised = sorted(json.dumps(c.signature(), default=str) for c in in_service(connections, year))
    sig = [year, params.scenario, round(params.growth_2030, 4), round(params.growth_2035, 4), energised]
    if params.scenario == "custom":
        sig.append(round(demand_multiplier(params, year), 4))
    return hashlib.sha256(json.dumps(sig, default=str).encode()).hexdigest()[:24]


def simulate(
    connections: list[Connection],
    params: PlanParams,
    *,
    view_year: int | None = None,
    years: Iterable[int] = PLAN_YEARS,
    net_factory: NetFactory = build_base_net,
    progress: Progress | None = None,
    on_year: Callable[[YearResult], None] | None = None,
    cache: MutableMapping[str, YearResult] | None = None,
) -> PlanResult:
    """Solve every year of the plan in `year_order` (the viewed year first). `on_year` is called as each year lands, so
    a caller can publish partial results; `progress(stage, fraction)` reports 0..1.

    `cache` (optional, a mapping the caller keeps) holds year results by `year_signature`, so a re-run after a small
    edit solves only the years the edit touches. The caller must key the mapping by network snapshot and engine version
    (and the net factory)."""
    report = progress or (lambda _s, _f: None)
    order = year_order(view_year, years)
    out: dict[str, YearResult] = {}
    for i, y in enumerate(order):
        report(f"year {y}: winter peak and summer minimum", i / len(order))
        key = year_signature(y, connections, params)
        yr = cache.get(key) if cache is not None else None
        if yr is None:
            yr = evaluate_year(y, connections, params, net_factory=net_factory)
            if cache is not None:
                cache[key] = yr
        out[str(y)] = yr
        if on_year is not None:
            on_year(yr)
    report("years done", 1.0)
    return PlanResult(params=params, years={k: out[k] for k in sorted(out)})
