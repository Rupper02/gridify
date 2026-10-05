"""Planned works on a branch: maintenance, repowering and replacement windows, studied the way they
would be run, plus what each work leaves behind.

A window takes an element out (or, for maintenance, derates it) for some weeks of one season of one
year. Windows in the same season of the same year are studied TOGETHER, all applied at once: the
weeks inside a season are not placed in the calendar, so this is the conservative reading. Each group
is solved in its season's case(s) with that season's line ratings (config.SEASON_STUDY) and gets a
verdict:

  feasible        no limit is breached with the element(s) out
  curtailment     a limit is breached, no demand is stranded, and constraining generation near the
                  binding element (the biggest exporters, for the GSP) clears it
  demand_at_risk  demand is stranded on an island, or sits at load buses left outside the voltage
                  band that constraining generation does not clear
  not_feasible    a limit stays breached after the bounded curtailment search (or no convergence)

The curtailment search is a first-order planning estimate, not an optimal dispatch: one generator at
a time, nearest the binding element first, re-solving each time, then a short bisection on the last
one, at most config.CURTAIL_MAX_SOLVES extra solves per case. With an N-1 screen passed in, the
132 kV backbone is also screened with the window in place (informational, like the year's own screen).

After the window: maintenance and replacement (like-for-like) return the element as it was;
repowering returns it with a new capability from the FOLLOWING year on (`apply_works_after`, called
by years.evaluate_year). The queue run (greedy.optimize) does not see repowers: it decides who
connects on the network as it is plus the branch's reinforcements, a stated simplification.
Nothing here decides who connects; every study is reported, never a gate.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import NamedTuple

import networkx as nx
import pandapower.topology as top
import pandas as pd

from .config import (
    CURTAIL_MAX_SOLVES,
    CURTAIL_MIN_RELIEF,
    CURTAIL_REFINE_STEPS,
    N1_ISLAND_MIN_MW,
    OUTAGE_DERATE_FACTOR,
    SEASON_STUDY,
)
from .network import (
    _CASE_LABEL,
    OUTAGE_APPLIERS,
    REINFORCERS,
    _case_reason,
    FLEET_TABLES,
    _column,
    _ensure_fleet_columns,
    _gsp_reason,
    _islanded_mw,
    _run_case,
    _study_cases,
    case_dispatch,
    set_tap_positions,
    tap_positions,
    voltage_limits,
)
from .types import VERDICT_SEVERITY, Curtailment, N1During, Outage, OutageStudy, Reason, Reinforcement

Screen = Callable[..., dict]  # network.n1_screen's shape: (net, case, rating_ratio=...) -> {"screened", "violations"}

_ELEMENT_NOUN = {"line": "line", "trafo": "transformer", "gen": "generator"}


# --- the works -----------------------------------------------------------------------------------
def _as_planned(o: Outage) -> Outage:
    return o


def _fully_out(o: Outage) -> Outage:
    return o.model_copy(update={"kind": "outage"})


def _repower_element(kind: str):
    """A line/transformer comes back uprated (thermal only, impedance in ohms unchanged) or with a
    parallel circuit: the same change a reinforcement makes (network.REINFORCERS)."""
    def repower(net, o: Outage) -> None:
        action = o.repower or "uprate"
        if action == "uprate" and o.factor is None:
            raise ValueError(f"repowering {o.outage_id} by uprate needs a factor")
        REINFORCERS[kind](net, Reinforcement(kind=kind, element_id=int(o.element_id), action=action,
                                             factor=o.factor if action == "uprate" else 2.0))
    return repower


def _repower_generator(net, o: Outage) -> None:
    """An existing generator comes back with a new export rating (its import scales with it); a
    parallel unit is a second identical one (x2)."""
    k = 2.0 if o.repower == "add_parallel" else o.factor
    if k is None:
        raise ValueError(f"repowering {o.outage_id} by uprate needs a factor")
    _ensure_fleet_columns(net)
    for table in FLEET_TABLES:
        t = net[table]
        if "fleet_id" not in t.columns:
            continue
        idx = t.index[t["fleet_id"] == o.element_id]
        for col in ("p_mw", "p_rated_mw", "import_mw"):
            t.loc[idx, col] = t.loc[idx, col].astype(float) * float(k)


# how a repowered element comes back, per Outage.element_kind
REPOWERERS = {
    "line": _repower_element("line"),
    "trafo": _repower_element("trafo"),
    "gen": _repower_generator,
}


def _repower_note(o: Outage) -> str:
    what = f"{_ELEMENT_NOUN.get(o.element_kind, o.element_kind)} {o.element_id}"
    if o.repower == "add_parallel":
        change = "a parallel unit" if o.element_kind == "gen" else "a parallel circuit"
        return f"from {o.year + 1}, {what} comes back with {change}"
    rating = "export rating" if o.element_kind == "gen" else "rating"
    return f"from {o.year + 1}, {what} comes back at {o.factor:g}x its {rating}"


class WorkSpec(NamedTuple):
    """A kind of planned work. Adding one is one entry in WORKS."""

    label: str
    during: Callable[[Outage], Outage]  # the window as applied to the net
    after: Callable | None  # (net, outage) -> None: the change that persists after the window, or None
    note: Callable[[Outage], str]  # what the element is like once the window is over


WORKS: dict[str, WorkSpec] = {
    "maintenance": WorkSpec("maintenance", _as_planned, None, lambda o: "the element returns as it was"),
    "replacement": WorkSpec("like-for-like replacement", _fully_out, None,
                            lambda o: "the element returns like-for-like (recorded only)"),
    "repowering": WorkSpec("repowering", _fully_out,
                           lambda net, o: REPOWERERS[o.element_kind](net, o), _repower_note),
}


def apply_works_after(net, outages, year: int) -> None:
    """Apply what every work finished BEFORE `year` leaves behind (repowering only), in date order."""
    for o in sorted((o for o in outages if o.year < year), key=lambda o: o.year):
        after = WORKS[o.work].after
        if after is not None:
            after(net, o)


# --- curtailment ---------------------------------------------------------------------------------
Row = tuple[str, int]  # (generator table, row)


def _gen_rows(net) -> dict[str, list[Row]]:
    """Generator rows per generator id, across both generator tables: the existing fleet's model id (one
    generator may sit on several buses), else the row's name (a project's request id)."""
    out: dict[str, list[Row]] = {}
    for table in FLEET_TABLES:
        t = net[table]
        fleet = t["fleet_id"] if "fleet_id" in t.columns else pd.Series(None, index=t.index)
        for i in t.index:
            if not bool(t.at[i, "in_service"]):
                continue
            f = fleet.get(i)
            gid = str(f) if isinstance(f, str) and f else str(t.at[i, "name"] or f"{table} {i}")
            out.setdefault(gid, []).append((table, int(i)))
    return out


def _curtailable(r: Reason) -> bool:
    """Less generation relieves a thermal or GSP export breach, and an overvoltage; not an undervoltage."""
    if r.type in ("line", "trafo", "gsp"):
        return True
    return r.type == "voltage" and r.value is not None and r.limit is not None and r.value > r.limit


def _target_buses(net, r: Reason) -> list[int]:
    if r.type == "line" and r.element_id in net.line.index:
        return [int(net.line.at[r.element_id, "from_bus"]), int(net.line.at[r.element_id, "to_bus"])]
    if r.type == "trafo" and r.element_id in net.trafo.index:
        return [int(net.trafo.at[r.element_id, "hv_bus"]), int(net.trafo.at[r.element_id, "lv_bus"])]
    if r.type == "voltage" and r.element_id is not None:
        return [int(r.element_id)]
    return []


def _no_help(before: Reason, after: Reason) -> bool:
    """Did a step fail to relieve the breach it targeted: no convergence, or the same breach eased by
    less than CURTAIL_MIN_RELIEF of its excess over the limit (a generator that does not feed it)?
    A different breach binding next counts as progress."""
    if after.type == "non_convergent":
        return True
    if after.type != before.type or after.element_id != before.element_id:
        return False
    if after.value is None or before.value is None or before.limit is None:
        return False
    # every curtailable breach is an excess ABOVE its limit (thermal, GSP export, overvoltage)
    before_excess = before.value - before.limit
    after_excess = after.value - (after.limit if after.limit is not None else before.limit)
    return after_excess > before_excess * (1 - CURTAIL_MIN_RELIEF)


class _Curtailer:
    """The bounded curtailment search for one case of one window (see the module docstring)."""

    def __init__(self, net, case: str, load_scale, ratio):
        self.net, self.case, self.load_scale, self.ratio = net, case, load_scale, ratio
        _ensure_fleet_columns(net)
        self.rated0 = {t: net[t]["p_rated_mw"].copy() for t in FLEET_TABLES}
        self.base = {t: self.rated0[t].where(self.rated0[t].notna(), net[t]["p_mw"]).astype(float) for t in FLEET_TABLES}
        disp = case_dispatch(net, case, load_scale)
        out = lambda rows: sum(max(float(disp[t][i]), 0.0) for t, i in rows)  # noqa: E731 (its output in this case)
        self.rows = {g: rows for g, rows in _gen_rows(net).items() if out(rows) > 1e-6}
        self.mw0 = {g: out(rows) for g, rows in self.rows.items()}
        self.frac: dict[str, float] = {}
        self.graph = top.create_nxgraph(net)  # the window's topology (out-of-service branches dropped)
        self.solves = 0

    def _set(self, gid: str, frac: float) -> None:
        for t, i in self.rows[gid]:
            self.net[t].at[i, "p_rated_mw"] = self.base[t][i] * (1.0 - frac)
        self.frac[gid] = frac

    def _solve(self) -> Reason | None:
        self.solves += 1
        res = _run_case(self.net, self.case, self.load_scale, self.ratio)
        if res is None:
            return Reason(type="non_convergent", case=self.case, message="no convergence")
        return (_case_reason(self.net, self.case, res["vm"], res["line_pct"], res["trafo_pct"])
                or _gsp_reason(self.net, -res["p_ext_mw"], self.case))

    def _order(self, r: Reason, tried: set[str]) -> list[str]:
        live = [g for g in self.rows if g not in tried and self.frac.get(g, 0.0) < 1.0]
        if r.type == "gsp":
            return sorted(live, key=lambda g: (-self.mw0[g] * (1 - self.frac.get(g, 0.0)), g))
        targets = [b for b in _target_buses(self.net, r) if b in self.graph]
        if not targets:
            return []
        dist = nx.multi_source_dijkstra_path_length(self.graph, set(targets), weight=lambda u, v, d: 1)  # hops
        hops = {g: min((dist[int(self.net[t].at[i, "bus"])] for t, i in self.rows[g]
                        if int(self.net[t].at[i, "bus"]) in dist), default=None) for g in live}
        return sorted((g for g in live if hops[g] is not None), key=lambda g: (hops[g], -self.mw0[g], g))

    def run(self, reason: Reason) -> list[Curtailment] | None:
        """The generation to constrain so every limit holds in this case, or None if the search
        cannot clear it within its budget. Leaves the generators' ratings as found."""
        try:
            return self._search(reason)
        finally:
            for t in FLEET_TABLES:
                self.net[t]["p_rated_mw"] = self.rated0[t]

    def _search(self, r: Reason) -> list[Curtailment] | None:
        tried: set[str] = set()
        while self.solves < CURTAIL_MAX_SOLVES and _curtailable(r):
            order = self._order(r, tried)
            if not order:
                return None
            g = order[0]
            tried.add(g)
            prev = self.frac.get(g, 0.0)
            self._set(g, 1.0)
            r2 = self._solve()
            if r2 is None:
                self._refine(g, prev)
                return self._result()
            if _no_help(r, r2):
                self._set(g, prev)  # constraining it does not help this breach: put it back
                continue
            r = r2
        return None

    def _refine(self, gid: str, lo: float) -> None:
        """Bisect the last generator's constraint between what failed (lo) and full (1.0)."""
        hi = 1.0
        for _ in range(CURTAIL_REFINE_STEPS):
            if self.solves >= CURTAIL_MAX_SOLVES:
                break
            mid = (lo + hi) / 2
            self._set(gid, mid)
            if self._solve() is None:
                hi = mid
            else:
                lo = mid
        self._set(gid, hi)

    def _result(self) -> list[Curtailment]:
        out = []
        for g, f in self.frac.items():
            mw = math.ceil(self.mw0[g] * f * 10 - 1e-9) / 10  # rounded UP, so the reported figure is enough
            if mw > 0:
                t, i = self.rows[g][0]
                tech = str(self.net[t].at[i, "type"] or "generator")
                out.append(Curtailment(id=g, name=tech, mw=mw, case=self.case))
        return out


# --- the window study ----------------------------------------------------------------------------
def _out_of_band_demand(net, vm: pd.Series) -> float:
    """Demand at buses outside their statutory voltage band (islanded buses have no voltage and are
    counted by _islanded_mw instead). On the same basis as _islanded_mw (grown demand)."""
    v = vm.reindex(net.bus.index)
    vmin, vmax = voltage_limits(net)
    bad = v[(v < vmin) | (v > vmax)].index
    on = net.load["bus"].isin(bad) & net.load["in_service"]
    return float((net.load.loc[on, "p_mw"] * net.load.loc[on, "scaling"]).sum())


_SEVERITY = VERDICT_SEVERITY




class _CaseState(NamedTuple):
    """What the window does on its own in one case, so the N-1 screen reports only what a SECOND
    fault adds: the breach it already causes, and the demand it already strands."""

    ratio: pd.Series | None
    breaches: set
    stranded_mw: float


class _GroupResult:
    def __init__(self):
        self.cases: list[str] = []
        self.violations: list[Reason] = []
        self.worst_line = self.worst_trafo = self.export = 0.0
        self.verdict = "feasible"
        self.at_risk = 0.0
        self.curtailment: list[Curtailment] = []
        self.n1: N1During | None = None
        self.solved: dict[str, _CaseState] = {}  # converged cases only

    def judge(self, verdict: str) -> None:
        if _SEVERITY[verdict] > _SEVERITY[self.verdict]:
            self.verdict = verdict

    @property
    def curtailed_mw(self) -> float:
        per_case: dict[str, float] = {}
        for c in self.curtailment:
            per_case[c.case] = per_case.get(c.case, 0.0) + c.mw
        return round(max(per_case.values(), default=0.0), 1)


def _study_case(net, name: str, load_scale, ratio, out: _GroupResult) -> None:
    """Solve one case with the group applied and fold its verdict into `out`."""
    res = _run_case(net, name, load_scale, ratio)
    out.cases.append(name)
    if res is None:
        out.violations.append(Reason(type="non_convergent", case=name,
                                     message=f"power flow does not converge at {_CASE_LABEL[name]}"))
        out.judge("not_feasible")
        return
    out.worst_line = max(out.worst_line, float(res["line_pct"].max()) if len(res["line_pct"]) else 0.0)
    out.worst_trafo = max(out.worst_trafo, float(res["trafo_pct"].max()) if len(res["trafo_pct"]) else 0.0)
    out.export = max(out.export, -res["p_ext_mw"])
    lost, island = _islanded_mw(net, res["vm"])
    n_buses = len(island)
    oob = _out_of_band_demand(net, res["vm"])
    r = _case_reason(net, name, res["vm"], res["line_pct"], res["trafo_pct"]) or _gsp_reason(net, -res["p_ext_mw"], name)
    out.solved[name] = _CaseState(ratio, {(r.type, r.element_id)} if r is not None else set(), lost)
    if lost >= N1_ISLAND_MIN_MW:
        out.violations.append(Reason(type="islanded", value=round(lost, 2), case=name,
                                     message=f"{lost:.1f} MW of demand at {n_buses} bus(es) is cut off at {_CASE_LABEL[name]}"))
        out.at_risk = max(out.at_risk, lost + oob)
        out.judge("demand_at_risk")
        return
    if r is None:
        return
    out.violations.append(r)
    cut = _Curtailer(net, name, load_scale, ratio).run(r)
    if cut is not None:
        out.curtailment.extend(cut)
        out.judge("curtailment")
    elif oob >= N1_ISLAND_MIN_MW:
        out.at_risk = max(out.at_risk, oob)
        out.judge("demand_at_risk")
    else:
        out.judge("not_feasible")


# what the same N-1 screen finds WITHOUT the window, per case: {(outage, problem, element): MW stranded}
Baseline = dict[str, dict[tuple, float]]


def _finding_key(v: dict) -> tuple:
    return (v.get("outage_type"), v.get("outage_id"), v.get("case"), v.get("type"), None if v.get("type") == "islanded" else v.get("element_id"))


def _baseline_screen(net, screen: Screen, season_name: str) -> Baseline:
    """The N-1 screen of the year as it is (no window), in the season's cases and ratings: what a
    window's own screen is compared with, so only what the window adds is reported. Taps as found."""
    season = SEASON_STUDY.get(season_name, SEASON_STUDY["Summer"])
    cases = {c.name: c for c in _study_cases(net)}
    taps = tap_positions(net)
    out: Baseline = {}
    try:
        for name in season["cases"]:
            if name not in cases:
                continue
            ratio = _column(net.line, season["rating_column"]) if season["rating_column"] else cases[name].rating_ratio
            found = screen(net, name, rating_ratio=ratio).get("violations", [])
            out[name] = {_finding_key(v): float(v.get("value") or 0.0) for v in found}
    finally:
        set_tap_positions(net, taps)
    return out


_N1_ORDER = {"non_convergent": 0, "islanded": 1, "line": 2, "trafo": 2, "voltage": 3}


def _n1_rank(v: dict, extra_mw: float) -> tuple:
    """Worst first: no convergence, then demand stranded (most first), then thermal (highest first), then voltage."""
    return (_N1_ORDER.get(v.get("type"), 4), -(extra_mw if v.get("type") == "islanded" else float(v.get("value") or 0.0)))


def _n1_words(v: dict, extra_mw: float) -> str:
    """One second-fault finding in words, naming the fault and what it does (ids; the planner names them)."""
    fault = f"{v.get('outage_type')} {v.get('outage_id')} out as well"
    if v.get("type") == "islanded":
        return f"{fault} cuts off another {extra_mw:.1f} MW at {_CASE_LABEL.get(v.get('case'), v.get('case'))}"
    return f"{fault}: {v.get('message', '')}"


def _screen_during(net, screen: Screen, solved: dict[str, _CaseState], baseline: Baseline) -> N1During:
    """The N-1 screen with the window in place, in each of the window's cases (seasonal ratings).
    A finding counts only when the window adds it: not already found without the window (`baseline`),
    not a breach the window causes on its own, and for an island at least N1_ISLAND_MIN_MW of demand
    beyond what the window or the same fault without the window strands. The findings are listed
    worst first (`violations`, the screen's own dicts) and the worst is said in words."""
    n1 = N1During()
    found: list[tuple[tuple, float, dict]] = []
    for name, own in solved.items():
        s = screen(net, name, rating_ratio=own.ratio)
        base = baseline.get(name, {})
        n1.cases.append(name)
        n1.screened += int(s.get("screened", 0))
        for v in s.get("violations", []):
            key = _finding_key(v)
            extra = 0.0
            if v.get("type") == "islanded":
                extra = float(v.get("value") or 0.0) - max(own.stranded_mw, base.get(key, 0.0))
                if extra < N1_ISLAND_MIN_MW:
                    continue
            elif key in base or (v.get("type"), v.get("element_id")) in own.breaches:
                continue
            found.append((_n1_rank(v, extra), extra, {**v, "case": v.get("case") or name}))
    found.sort(key=lambda t: t[0])
    n1.violations = [v for _, _, v in found]
    n1.findings = len(n1.violations)
    n1.second_fault_at_risk_mw = round(max((extra for _, extra, _ in found), default=0.0), 1)
    n1.worst = _n1_words(found[0][2], found[0][1]) if found else ""
    return n1


def _study_group(net, season_name: str, screen: Screen | None, baseline: Baseline) -> _GroupResult:
    season = SEASON_STUDY.get(season_name, SEASON_STUDY["Summer"])
    cases = {c.name: c for c in _study_cases(net)}
    out = _GroupResult()
    for name in season["cases"]:
        if name not in cases:
            continue
        case = cases[name]
        ratio = _column(net.line, season["rating_column"]) if season["rating_column"] else case.rating_ratio
        _study_case(net, name, case.load_scale, ratio, out)
    if screen is not None:
        out.n1 = _screen_during(net, screen, out.solved, baseline)
    return out


def _describe(o: Outage) -> str:
    noun = f"{_ELEMENT_NOUN.get(o.element_kind, o.element_kind)} {o.element_id}"
    if o.work == "maintenance" and o.kind == "derate":
        return f"{noun} derated to {OUTAGE_DERATE_FACTOR:.0%}"
    return f"{noun} out"


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _curtailment_text(cuts: list[Curtailment]) -> str:
    by_case: dict[str, list[str]] = {}
    for c in cuts:
        by_case.setdefault(c.case, []).append(f"{c.id} by {c.mw:.1f} MW")
    text = "; ".join(f"at {_CASE_LABEL[case]}, constraining {_and(items)}" for case, items in by_case.items())
    return text[:1].upper() + text[1:]


def _message(o: Outage, with_ids: list[str], g: _GroupResult) -> str:
    """A plain-English summary, naming elements by id (the planner resolves their names)."""
    head = f"{_describe(o)} for {WORKS[o.work].label} ({o.season} {o.year})"
    if with_ids:
        head += f", studied together with {_and(with_ids)}"
    found = "; ".join(v.message for v in g.violations)
    if g.verdict == "feasible":
        body = (f"Feasible: no limit breached; worst line {g.worst_line:.0f}%, worst transformer "
                f"{g.worst_trafo:.0f}% at {' and '.join(_CASE_LABEL[c] for c in g.cases)}.")
    elif g.verdict == "curtailment":
        body = (f"Feasible with curtailment: {found}. {_curtailment_text(g.curtailment)} holds every "
                f"limit (a first-order estimate, not an optimal dispatch).")
    elif g.verdict == "demand_at_risk":
        body = f"Demand at risk: {g.at_risk:.1f} MW. {found}."
    else:
        body = f"Not feasible: {found}. Constraining nearby generation does not clear it."
    text = f"{head}. {body}"
    if g.n1 is not None and g.n1.findings:
        text += f" During the window the N-1 screen finds {g.n1.findings} more second-fault problem(s); the worst: {g.n1.worst}."
    return text + f" After the window, {WORKS[o.work].note(o)}."


def _missing(o: Outage) -> OutageStudy:
    noun = _ELEMENT_NOUN.get(o.element_kind, o.element_kind)
    return OutageStudy(outage_id=o.outage_id, year=o.year, cases=[], ok=True, work=o.work,
                       message=f"{noun} {o.element_id} is not in the network model", after=WORKS[o.work].note(o))


def study_windows(net, windows: list[Outage], *, screen: Screen | None = None) -> list[OutageStudy]:
    """Study one year's windows (see the module docstring): grouped by season, each group applied at
    once. Returns one OutageStudy per window, in the order given. Leaves the net as found: the
    elements, the generators' ratings and the tap positions (the year's own results must not depend
    on whether a window was studied in it)."""
    by_season: dict[str, list[Outage]] = {}
    for o in windows:
        by_season.setdefault(o.season, []).append(o)
    studies: dict[int, OutageStudy] = {}
    pos = {id(o): i for i, o in enumerate(windows)}
    for season, group in by_season.items():
        baseline = _baseline_screen(net, screen, season) if screen is not None else {}
        taps = tap_positions(net)
        undos, applied = [], []
        try:
            for o in group:
                undo = OUTAGE_APPLIERS[o.element_kind](net, WORKS[o.work].during(o))
                if undo is None:
                    studies[pos[id(o)]] = _missing(o)
                else:
                    undos.append(undo)
                    applied.append(o)
            g = _study_group(net, season, screen, baseline) if applied else None
        finally:
            for undo in reversed(undos):
                undo()
            set_tap_positions(net, taps)
        for o in applied:
            with_ids = [x.outage_id for x in applied if x is not o]
            studies[pos[id(o)]] = OutageStudy(
                outage_id=o.outage_id, year=o.year, cases=g.cases, ok=not g.violations, violations=g.violations,
                worst_line_loading_pct=round(g.worst_line, 1), worst_trafo_loading_pct=round(g.worst_trafo, 1),
                gsp_export_mw=round(g.export, 1), message=_message(o, with_ids, g), work=o.work,
                with_ids=with_ids, verdict=g.verdict, demand_at_risk_mw=round(g.at_risk, 1),
                curtailment=g.curtailment, curtailed_mw=g.curtailed_mw, n1_during=g.n1,
                after=WORKS[o.work].note(o),
            )
    return [studies[i] for i in range(len(windows))]
