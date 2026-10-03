"""The best window for a planned work: study one element out in every (year, season) of a range,
against the plan as it stands that year, and rank the windows.

Each year is solved by years.evaluate_year (its network built once, with that year's demand,
energised projects, reinforcements, works finished earlier and the branch's other windows), and the
element's window is probed in every requested season of that year on the same net. A probe in a
season the branch already has windows in is studied TOGETHER with them, as the real window would be
(maintenance.study_windows). Probes of different years never see each other: a repowering probed in
one year does not change the next year's study.

Two passes keep the cost bounded. The first studies every window without the N-1 screen; the second
screens N-1 during the window for a shortlist of config.BEST_WINDOW_N1_SHORTLIST only (re-studied
with the screen; the screen roughly doubles a window's cost): the best window of each season, then
the next best overall. Windows outside the shortlist report `n1_findings = None` (not screened), so
a window with fewer second-fault findings can exist among them: a stated limit of the bounded search.

Ranking (deterministic): verdict (feasible < curtailment < demand_at_risk < not_feasible), then the
generation curtailed, the demand at risk, the second-fault findings during the window (shortlist
first, so a screened window ranks above an unscreened one it ties with), the worst line and
transformer loadings, then the earliest year and the season order. Nothing here schedules the work
or decides who connects; it only reports what each window does.
"""

from __future__ import annotations

from collections.abc import Iterable

from .config import BEST_WINDOW_N1_SHORTLIST, SEASON_STUDY
from .greedy import NetFactory, Progress
from .maintenance import WORKS
from .network import build_base_net
from .types import Candidate, OptimizeParams, OptimizeResult, Outage, OutageStudy, Reinforcement, WindowOption
from .years import PLAN_YEARS, energisation_years, evaluate_year

SEASONS = tuple(SEASON_STUDY)
VERDICT_RANK = {"feasible": 0, "curtailment": 1, "demand_at_risk": 2, "not_feasible": 3}
PROBE_ID = "best-window"


def _option(year: int, season: str, s: OutageStudy) -> WindowOption:
    return WindowOption(
        rank=0, year=year, season=season, verdict=s.verdict, curtailed_mw=s.curtailed_mw,
        demand_at_risk_mw=s.demand_at_risk_mw, n1_findings=s.n1_during.findings if s.n1_during else None,
        worst_line_loading_pct=s.worst_line_loading_pct, worst_trafo_loading_pct=s.worst_trafo_loading_pct,
        message=s.message, study=s,
    )


def rank_key(o: WindowOption) -> tuple:
    """Lower is better (see the module docstring); an unscreened window counts after any screened one."""
    n1 = o.n1_findings if o.n1_findings is not None else float("inf")
    return (VERDICT_RANK.get(o.verdict, len(VERDICT_RANK)), o.curtailed_mw, o.demand_at_risk_mw, n1,
            o.worst_line_loading_pct, o.worst_trafo_loading_pct, o.year, SEASONS.index(o.season))


def _shortlist(ranked: list[WindowOption], n: int) -> list[WindowOption]:
    """The windows to screen N-1 for: the best of each season first (a second fault's effect
    depends mostly on the season's case and ratings, so the best of one season must not crowd out
    the others), then the next best overall, up to `n`. `ranked` is in pass-1 order."""
    firsts = [o for i, o in enumerate(ranked) if all(p.season != o.season for p in ranked[:i])][:n]
    taken = {(o.year, o.season) for o in firsts}
    return firsts + [o for o in ranked if (o.year, o.season) not in taken][: n - len(firsts)]


class _Prober:
    """Study the element's windows year by year on the branch's plan (one evaluate_year per year)."""

    def __init__(self, result, candidates, params, element, work_fields: dict, *, scheduled, reinforcements,
                 outages, net_factory):
        self.candidates, self.params, self.element, self.work = candidates, params, element, work_fields
        self.in_service = energisation_years(result, scheduled)
        self.reinforcements, self.outages, self.net_factory = list(reinforcements), list(outages), net_factory

    def year(self, y: int, seasons: list[str], n1: bool) -> list[WindowOption]:
        probes = [Outage(outage_id=f"{PROBE_ID}:{y}:{s}", element_kind=self.element[0], element_id=str(self.element[1]),
                         season=s, year=y, **self.work) for s in seasons]
        yr = evaluate_year(y, self.candidates, self.params, self.in_service, outages=self.outages + probes,
                           reinforcements=self.reinforcements, n1=n1, net_factory=self.net_factory)
        by_id = {s.outage_id: s for s in yr.outage_studies}
        out = []
        for p in probes:
            s = by_id[p.outage_id]
            if not s.cases:  # maintenance._missing: the element is not in the model
                raise ValueError(s.message)
            out.append(_option(y, p.season, s))
        return out


def best_windows(
    result: OptimizeResult,
    candidates: list[Candidate],
    params: OptimizeParams,
    element: tuple[str, str],
    years: Iterable[int] = PLAN_YEARS,
    seasons: Iterable[str] = SEASONS,
    *,
    work: str = "maintenance",
    kind: str = "outage",
    repower: str | None = None,
    factor: float | None = None,
    weeks: int = 4,
    scheduled: dict[str, int | None] | None = None,
    reinforcements: list[Reinforcement] = (),
    outages: list[Outage] = (),
    n1: bool = True,
    n1_shortlist: int = BEST_WINDOW_N1_SHORTLIST,
    net_factory: NetFactory = build_base_net,
    progress: Progress | None = None,
) -> list[WindowOption]:
    """Every (year, season) window for `element` = (element_kind, element_id), best first.

    `result` is the branch's queue run (who energises when, with `scheduled` overrides); `outages`
    are the branch's other planned windows, studied with the probe when they share its season and
    year. With `n1`, the best `n1_shortlist` windows are re-studied with the N-1 screen. Raises
    ValueError for an unknown work or season, or an element not in the network model."""
    if work not in WORKS:
        raise ValueError(f"unknown work '{work}' (one of {', '.join(WORKS)})")
    asked = set(seasons)
    if not asked or asked - set(SEASONS):
        raise ValueError("seasons must be a non-empty subset of " + ", ".join(SEASONS))
    seasons = [s for s in SEASONS if s in asked]  # in season order
    years = sorted(set(int(y) for y in years))
    if not years:
        raise ValueError("years must not be empty")
    report = progress or (lambda _s, _f: None)
    prober = _Prober(result, candidates, params, element,
                     {"work": work, "kind": kind, "repower": repower, "factor": factor, "weeks": weeks},
                     scheduled=scheduled, reinforcements=reinforcements, outages=outages, net_factory=net_factory)
    screen_share = 0.25 if n1 and n1_shortlist > 0 else 0.0

    options: list[WindowOption] = []
    for i, y in enumerate(years):
        report(f"year {y}: {len(seasons)} season(s)", (1 - screen_share) * i / len(years))
        options.extend(prober.year(y, seasons, n1=False))
    options.sort(key=rank_key)

    if screen_share:
        short = _shortlist(options, n1_shortlist)
        picked = {(o.year, o.season) for o in short}
        rest = [o for o in options if (o.year, o.season) not in picked]
        by_year: dict[int, list[str]] = {}
        for o in short:
            by_year.setdefault(o.year, []).append(o.season)
        screened: dict[tuple[int, str], WindowOption] = {}
        for j, (y, ss) in enumerate(sorted(by_year.items())):
            report(f"N-1 during the best windows: {y}", (1 - screen_share) + screen_share * j / len(by_year))
            screened.update({(o.year, o.season): o for o in prober.year(y, [s for s in SEASONS if s in ss], n1=True)})
        options = sorted([*screened.values(), *rest], key=rank_key)
    report("windows ranked", 1.0)
    return [o.model_copy(update={"rank": i + 1}) for i, o in enumerate(options)]
