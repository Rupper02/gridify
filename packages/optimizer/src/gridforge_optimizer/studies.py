"""Studies: deterministic analyses an agent (or the API) can run on a plan, as a registry.

Where the queue run and the plan years answer "does this plan hold?", a study answers a planner's
sharper question about the network itself: where can new generation or demand connect before a
limit breaks (hosting capacity), which single outage hurts most (contingency ranking), which
elements are structural single points of failure (no power flow needed), which tap changers have run
out of range (tap margin), how the GSP margin evolves year by year, what the model had to assume
(data quality), how one project could connect when its busbar cannot take it (connection options: a
firm size or a flexible connection, the parallel-circuit chain, the higher-voltage busbars that take
it) and the best window for a planned work. Each study is bounded, pure given its `net_factory`, and returns `StudyItem`s whose
figures are the engine's and whose fingerprints are stable, so a finding filed against an item keeps
its identity across runs. Every study also says what it did NOT study.

`STUDIES` is the registry: a new study is one function, one params model and one entry. The API
caches a study by its params under `ResultCache.key`; the agents see the catalogue as tools.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, Literal, NamedTuple

import networkx as nx
from pydantic import BaseModel, Field, model_validator

from .config import (
    BEST_WINDOW_N1_SHORTLIST,
    CONNECTION_OPTION_BUSES,
    CONTINGENCY_MIN_KV,
    CONTINGENCY_SEVERITY_WEIGHTS,
    GENERATION_FACTORS,
    GENERATION_FACTOR_DEFAULT,
    GSP_MARGIN_WARN_FRACTION,
    HOSTING_MAX_BUSES,
    HOSTING_MIN_KV,
    HOSTING_STEP_MW,
    IMPORT_ONLY_TECHS,
    LINE_LOADING_MAX_PCT,
    MAX_CONNECTION_MW,
    MAX_REINFORCE_STEPS,
    N1_ISLAND_MIN_MW,
    OLTC_SETPOINT_PU,
    PLAN_END_YEAR,
    PLAN_START_YEAR,
    TAP_MARGIN_MIN_STEPS,
    TRAFO_LOADING_MAX_PCT,
)
from .dispatch import FLEET_TABLES
from .findings import fingerprint
from .greedy import NetFactory, Progress, build_base_net
from .sensitivity import rank_buses
from .network import (
    _CASE_LABEL,
    Baseline,
    _case_reason,
    _gsp_reason,
    _oltc_trafos,
    _run_case,
    _study_cases,
    drop_project,
    inject_project,
    inject_sgen,
    limit_baseline,
    n1_elements,
    emergency_ratio,
    outage_results,
    set_tap_positions,
    tap_positions,
    voltage_limits,
    solve_case,
)
from .suggest import discover_chain, phase_baseline, phase_net
from .types import REASON_SPECS, Candidate, ModelAssumption, OptimizeParams, OptimizeResult, Outage, Reason, StudyItem, StudyResult
from .windows import SEASONS, best_windows

_NOOP: Progress = lambda _s, _f: None  # noqa: E731


class StudyContext(NamedTuple):
    """What a study may read: the plan's network (already reinforced for the branch), its parameters,
    candidates and result (the plan years, for studies that read them), the branch's planned works and
    the operator's schedule (for studies that study the plan year by year), and a progress callback
    (where cancellation lands)."""

    net_factory: NetFactory = build_base_net
    params: OptimizeParams | None = None
    candidates: list[Candidate] = []
    result: OptimizeResult | None = None
    progress: Progress = _NOOP
    schedule: dict[str, int | None] = {}
    outages: list[Outage] = []


# --- parameters (the tool schemas the agents see) ---------------------------------------------------------
class HostingParams(BaseModel):
    """Hosting capacity per bus: new export (a firm generator) or import (a demand connection)."""

    bus_ids: list[int] | None = Field(default=None, description="buses to probe; default: every bus at or above min_kv, best-connected first")
    direction: Literal["export", "import"] = "export"
    cases: list[str] | None = Field(default=None, description="study cases; default: every case the network supports")
    step_mw: float = Field(default=HOSTING_STEP_MW, ge=1.0, description="resolution of the answer in MW")
    min_kv: float = Field(default=HOSTING_MIN_KV, ge=0.0)
    max_buses: int = Field(default=HOSTING_MAX_BUSES, ge=1, le=200)


class ContingencyParams(BaseModel):
    """Every single outage at or above min_kv, scored and ranked."""

    cases: list[str] | None = None
    min_kv: float = Field(default=CONTINGENCY_MIN_KV, ge=0.0)
    top: int = Field(default=25, ge=1, le=500, description="how many contingencies to report, worst first")


class StructuralParams(BaseModel):
    """Bridges and articulation points of the network graph (no power flow)."""


class TapMarginParams(BaseModel):
    cases: list[str] | None = None


class GspMarginParams(BaseModel):
    """The GSP export margin in every solved plan year (needs the plan)."""


class DataQualityParams(BaseModel):
    """What the model had to assume (the builder's fallbacks) and other data gaps."""


class ConnectionOptionsParams(BaseModel):
    """How one project could connect: what its own busbar takes of it (a firm size, or a flexible
    connection firm to that MW), how far a chain of parallel circuits gets it, and which higher-voltage
    busbars nearby take its full MW (needs the plan)."""

    request_id: str = Field(description="the project, as the queue names it")
    step_mw: float = Field(default=HOSTING_STEP_MW, ge=1.0, description="resolution of the MW answers")
    max_buses: int = Field(default=CONNECTION_OPTION_BUSES, ge=0, le=12, description="higher-voltage busbars to probe: the ones with the most first-order room (DC sensitivity), the AC solve confirming")
    part: Literal["all", "site", "bus"] = Field(default="all", description="a chunk: the project's own site (its busbar and the chain), one higher-voltage busbar (bus_ids), or everything")
    bus_ids: list[int] | None = Field(default=None, description="the higher-voltage busbars to probe instead of the nearest ones")


class BestWindowParams(BaseModel):
    """The windows for a planned work on one element, every season of every year in the range, studied
    against the plan as it stands that year (windows.best_windows; needs the plan)."""

    element_kind: Literal["line", "trafo", "gen"]
    element_id: str = Field(description="the element as the model names it: a line or transformer index, or a generator's id")
    work: str = Field(default="maintenance", description="maintenance | replacement | repowering (maintenance.WORKS)")
    kind: str = Field(default="outage", description="outage | derate (maintenance only)")
    repower: str | None = Field(default=None, description="repowering only: uprate | add_parallel")
    factor: float | None = Field(default=None, gt=1.0, le=4.0, description="repowering uprate only: the rating multiplier")
    weeks: int = Field(default=4, ge=1, le=52)
    years: tuple[int, int] = Field(default=(PLAN_START_YEAR, PLAN_END_YEAR), description="[from, to] within the plan")
    seasons: list[str] | None = Field(default=None, description="the seasons to probe; default: all four")
    n1: bool = Field(default=True, description="screen second faults (N-1) during the shortlisted windows; roughly doubles their cost")

    @model_validator(mode="after")
    def _range(self):
        lo, hi = self.years
        if not (PLAN_START_YEAR <= lo <= hi <= PLAN_END_YEAR):
            raise ValueError(f"years must be [from, to] within {PLAN_START_YEAR}..{PLAN_END_YEAR}")
        if self.seasons is not None and not self.seasons:
            raise ValueError("seasons, when given, must not be empty")
        return self


class StudySpec(NamedTuple):
    run: Callable[[StudyContext, Any], StudyResult]
    params_model: type[BaseModel]
    cost_hint: Callable[[Any], int]  # estimated power-flow solves (budgets and the UI)
    description: str  # what it measures and what it does not
    needs_plan: bool = False  # True: ctx.result (with years) is required
    chunk: Callable[[StudyContext, Any], list[BaseModel]] | None = None  # split into independent sub-studies


# --- helpers ------------------------------------------------------------------------------------------------
def _item(index: int, kind: str, *, element_kind: str | None, element_id, message: str, fp_extra: tuple = (),
          case: str | None = None, year: int | None = None, value: float | None = None, limit: float | None = None,
          unit: str = "", severity: str = "info", element_name: str = "", extra: dict | None = None) -> StudyItem:
    return StudyItem(index=index, element_kind=element_kind, element_id=element_id, element_name=element_name, case=case,
                     year=year, value=value, limit=limit, unit=unit, severity=severity, message=message,
                     fingerprint=fingerprint(kind, element_kind, element_id, year, case, fp_extra), extra=extra or {})


def _cases_for(net, wanted: list[str] | None) -> dict:
    """The study cases to run: the ones asked for that the network supports, else all it supports."""
    specs = {c.name: c for c in _study_cases(net)}
    if wanted:
        return {k: specs[k] for k in wanted if k in specs}
    return specs


def _bus_name(net, bus: int) -> str:
    name = str(net.bus.at[bus, "name"] or "")
    return f"{name} ({net.bus.at[bus, 'vn_kv']:g} kV)" if name else f"bus {bus} ({net.bus.at[bus, 'vn_kv']:g} kV)"


def _degree(net) -> dict[int, int]:
    d: dict[int, int] = {}
    for b in list(net.line["from_bus"]) + list(net.line["to_bus"]) + list(net.trafo["hv_bus"]) + list(net.trafo["lv_bus"]):
        d[int(b)] = d.get(int(b), 0) + 1
    return d


def _line_mva(net, lid: int) -> float:
    kv = float(net.bus.at[int(net.line.at[lid, "from_bus"]), "vn_kv"])
    return math.sqrt(3) * kv * float(net.line.at[lid, "max_i_ka"]) * float(net.line.at[lid, "parallel"])


def _slack_buses(net) -> set[int]:
    return {int(b) for b in net.ext_grid["bus"]} if len(net.ext_grid) else set()


# --- hosting capacity ----------------------------------------------------------------------------------------
def _ranked(net, buses: list[int], direction: str, limit: int) -> list[int]:
    """The `limit` buses with the most first-order headroom for `direction` (`sensitivity.rank_buses` on the winter-peak
    operating point: one DC factor matrix instead of a bisection per bus), so the AC probes go where the room is. The
    given order stands when there are no more buses than `limit`, or when the factors are not available."""
    if len(buses) <= limit:
        return buses[:limit]
    solve_case(net, "winter_peak")
    return rank_buses(net, buses, direction=direction)[:limit]


def _probe_buses(net, p: HostingParams) -> list[int]:
    if p.bus_ids:
        return [int(b) for b in p.bus_ids if int(b) in net.bus.index]
    deg = _degree(net)
    buses = [int(b) for b in net.bus.index if float(net.bus.at[b, "vn_kv"]) >= p.min_kv]
    buses.sort(key=lambda b: (-float(net.bus.at[b, "vn_kv"]), -deg.get(b, 0), b))
    return _ranked(net, buses, p.direction, p.max_buses)


def _probe(net, case, inject: Callable[[], int], baseline: Baseline | None = None) -> tuple[bool, Any, int]:
    """Inject something (`inject` connects it and returns its (table, index)), solve the case with the taps
    regulated, then leave the net exactly as found. Returns (within limits, the binding reason, solves): with a
    `baseline`, a breach it already carries binds only once the injection worsens it, as a connection is judged."""
    taps = tap_positions(net)
    ref = inject()
    try:
        res = _run_case(net, case.name, case.load_scale, case.rating_ratio, regulate=True)
    finally:
        drop_project(net, ref)
        set_tap_positions(net, taps)
    if res is None:
        return False, Reason(type="non_convergent", case=case.name, message=f"power flow does not converge at {_CASE_LABEL[case.name]}"), 1
    excused = baseline.breaches.get(case.name) if baseline else None
    r = (_case_reason(net, case.name, res["vm"], res["line_pct"], res["trafo_pct"], excused)
         or _gsp_reason(net, -res["p_ext_mw"], case.name, baseline.gsp_export_mw if baseline else None))
    return r is None, r, 1


def _hosting_probe(net, case, bus: int, mw: float, direction: str, baseline: Baseline) -> tuple[bool, Any, int]:
    """Probe `mw` of new firm export (or a demand connection importing it) at `bus`."""
    return _probe(net, case, lambda: ("sgen", inject_sgen(net, bus, mw, "hosting-probe", "other") if direction == "export"
                                              else inject_sgen(net, bus, 0.0, "hosting-probe", "demand", import_mw=mw)), baseline)


def _bisect_mw(probe: Callable[[float], tuple[bool, Any, int]], cap: float, step: float,
               at_cap: tuple[bool, Any] | None = None) -> tuple[float, Any, int]:
    """The most MW `probe` accepts between 0 and `cap`, to `step`: (value, the binding reason or None
    when nothing binds within the cap, solves). The cap is probed first (often nothing binds; `at_cap`
    hands in that answer when the caller already has it), then 0 (the network as it is), then by bisection."""
    solves = 0
    if at_cap is None:
        ok_cap, reason_cap, n = probe(cap)
        solves += n
    else:
        ok_cap, reason_cap = at_cap
    if ok_cap:
        return cap, None, solves
    ok0, reason0, n = probe(0.0)
    solves += n
    if not ok0:
        return 0.0, reason0, solves
    lo, hi, binding = 0.0, cap, reason_cap
    while hi - lo > step:
        mid = (lo + hi) / 2
        ok, reason, n = probe(mid)
        solves += n
        if ok:
            lo = mid
        else:
            hi, binding = mid, reason
    return math.floor(lo / step) * step, binding, solves


def _hosting_capacity(ctx: StudyContext, p: HostingParams) -> StudyResult:
    net = ctx.net_factory()
    cases = _cases_for(net, p.cases)
    buses = _probe_buses(net, p)
    baseline = limit_baseline(net)
    items: list[StudyItem] = []
    solves = 0
    cap = MAX_CONNECTION_MW
    for i, bus in enumerate(buses):
        ctx.progress(f"hosting capacity: bus {bus} ({i + 1}/{len(buses)})", i / max(len(buses), 1))
        for case in cases.values():
            value, binding, n = _bisect_mw(lambda mw: _hosting_probe(net, case, bus, mw, p.direction, baseline), cap, p.step_mw)
            solves += n
            label = _CASE_LABEL[case.name]
            where = _bus_name(net, bus)
            if binding is None:
                msg = f"at least {cap:.0f} MW of new {p.direction} at {where} at {label}: no limit reached within the {cap:.0f} MW intake cap"
            else:
                msg = f"about {value:.0f} MW of new {p.direction} at {where} at {label}, then {binding.message}"
            items.append(_item(len(items), "hosting_capacity", element_kind="bus", element_id=bus, element_name=where, case=case.name,
                               value=round(value, 1), limit=cap if binding is None else None, unit="MW",
                               severity="warn" if value < p.step_mw else "info", message=msg, fp_extra=(p.direction,),
                               extra={"direction": p.direction, "binding": binding.model_dump() if binding else None,
                                      "step_mw": p.step_mw}))
    not_studied = ["demand growth and the plan's projects: today's network, as the branch reinforces it",
                   "fault levels", "the transmission network beyond the export limit"]
    if p.direction == "export":
        not_studied.append("the probe is a firm generator (full output in both cases); PV or wind would host more at winter peak")
    worst = min(items, key=lambda x: x.value or 0.0) if items else None
    summary = (f"{len(buses)} buses probed in {len(cases)} case(s) at {p.step_mw:g} MW resolution; the least room is "
               f"{worst.value:.0f} MW at {worst.element_name} ({_CASE_LABEL[worst.case]})." if worst else "No bus probed.")
    return StudyResult(kind="hosting_capacity", params=p.model_dump(), items=items, solves=solves, not_studied=not_studied, summary=summary)


def _hosting_chunks(ctx: StudyContext, p: HostingParams, size: int = 4) -> list[BaseModel]:
    buses = _probe_buses(ctx.net_factory(), p)
    return [p.model_copy(update={"bus_ids": buses[i:i + size]}) for i in range(0, len(buses), size)] or [p]


# --- contingency ranking -----------------------------------------------------------------------------------------
def _contingency_ranking(ctx: StudyContext, p: ContingencyParams) -> StudyResult:
    net = ctx.net_factory()
    cases = _cases_for(net, p.cases)
    vmin, vmax = voltage_limits(net)
    w = CONTINGENCY_SEVERITY_WEIGHTS
    rows: list[dict] = []
    solves = 0
    taps0 = tap_positions(net)
    try:
        for ci, case in enumerate(cases.values()):
            ctx.progress(f"contingency ranking: {_CASE_LABEL[case.name]}", ci / max(len(cases), 1))
            _run_case(net, case.name, case.load_scale, case.rating_ratio, regulate=True)  # pre-fault taps for this case
            solves += 1
            elements = n1_elements(net, p.min_kv)
            k_emergency = emergency_ratio(net)
            for o in outage_results(net, case.name, case.load_scale, case.rating_ratio, elements):
                solves += 1
                if o.res is None:
                    rows.append({"kind": o.kind, "eid": o.eid, "name": o.name, "case": case.name, "non_convergent": True,
                                 "islanded_mw": 0.0, "thermal_excess_mva": 0.0, "voltage_shortfall_pu": 0.0, "binding": None})
                    continue
                lp, tp, vm = o.res["line_pct"], o.res["trafo_pct"], o.res["vm"]
                excess = 0.0
                for lid, pct in lp.items():
                    if pct > LINE_LOADING_MAX_PCT:
                        excess += (pct - LINE_LOADING_MAX_PCT) / 100.0 * _line_mva(net, int(lid))
                for tid, pct in tp.items():
                    if pct == pct and pct > TRAFO_LOADING_MAX_PCT:
                        excess += (pct - TRAFO_LOADING_MAX_PCT) / 100.0 * float(net.trafo.at[tid, "sn_mva"]) * float(net.trafo.at[tid, "parallel"]) * float(k_emergency.loc[tid])  # pct is of the emergency rating
                v = vm.reindex(net.bus.index)
                short = float(max((vmin - v).max(), (v - vmax).max(), 0.0)) if v.notna().any() else 0.0
                lost = o.lost_mw if o.lost_mw >= N1_ISLAND_MIN_MW else 0.0
                if lost == 0.0 and excess == 0.0 and short <= 1e-9:
                    continue  # a contingency that breaks nothing is not reported
                r = _case_reason(net, case.name, vm, lp, tp)
                rows.append({"kind": o.kind, "eid": o.eid, "name": o.name, "case": case.name, "non_convergent": False,
                             "islanded_mw": round(lost, 2), "thermal_excess_mva": round(excess, 2),
                             "voltage_shortfall_pu": round(short, 4), "binding": r.model_dump() if r else None,
                             "island": o.island})
    finally:
        set_tap_positions(net, taps0)
    for row in rows:
        row["index"] = None if row["non_convergent"] else round(
            w["islanded_mw"] * row["islanded_mw"] + w["thermal_excess_mva"] * row["thermal_excess_mva"]
            + w["voltage_shortfall_pu"] * row["voltage_shortfall_pu"], 3)
    rows.sort(key=lambda r: (not r["non_convergent"], -r["islanded_mw"], -r["thermal_excess_mva"], -r["voltage_shortfall_pu"], r["kind"], r["eid"]))
    items: list[StudyItem] = []
    for row in rows[:p.top]:
        noun = "transformer" if row["kind"] == "trafo" else "line"
        if row["non_convergent"]:
            msg = f"losing {noun} {row['eid']} at {_CASE_LABEL[row['case']]}: the power flow does not converge (the network cannot be solved without it)"
            sev = "breach"
        else:
            parts = []
            if row["islanded_mw"]:
                parts.append(f"cuts off {row['islanded_mw']:.1f} MW of demand")
            if row["thermal_excess_mva"]:
                parts.append(f"overloads elements by {row['thermal_excess_mva']:.1f} MVA in total")
            if row["voltage_shortfall_pu"]:
                parts.append(f"pushes a bus {row['voltage_shortfall_pu']:.3f} pu outside its band")
            msg = f"losing {noun} {row['eid']} at {_CASE_LABEL[row['case']]} {'; '.join(parts)}"
            if row["binding"]:
                msg += f" ({row['binding']['message']})"
            sev = "breach" if row["islanded_mw"] or row["thermal_excess_mva"] else "warn"
        items.append(_item(len(items), "contingency", element_kind=row["kind"], element_id=row["eid"], element_name=row["name"],
                           case=row["case"], value=row["index"], unit="index", severity=sev, message=msg,
                           extra={k: row[k] for k in ("non_convergent", "islanded_mw", "thermal_excess_mva", "voltage_shortfall_pu", "binding") if k in row}
                           | ({"island": row["island"]} if row.get("island") else {})))
    screened = sum(len(n1_elements(net, p.min_kv)) for _ in cases)
    not_studied = ["second outages (N-2) and switching after the fault", "fault levels", "elements below "
                   f"{p.min_kv:g} kV", "demand growth and the plan's projects: today's network, as the branch reinforces it"]
    summary = (f"{screened} single outages screened in {len(cases)} case(s); {len(rows)} break a limit or strand demand"
               + (f"; worst: {items[0].message}" if items else "") + ".")
    return StudyResult(kind="contingency_ranking", params=p.model_dump(), items=items, solves=solves, not_studied=not_studied, summary=summary)


def _contingency_chunks(ctx: StudyContext, p: ContingencyParams) -> list[BaseModel]:
    cases = _cases_for(ctx.net_factory(), p.cases)
    return [p.model_copy(update={"cases": [c]}) for c in cases] or [p]


# --- structural weak points -------------------------------------------------------------------------------------
def _simple_graph(net) -> tuple[nx.Graph, dict[tuple[int, int], list[tuple[str, int, int]]]]:
    """The network as a simple graph with, per bus pair, the elements joining them and their parallel count."""
    g = nx.Graph()
    g.add_nodes_from(int(b) for b in net.bus.index)
    by_pair: dict[tuple[int, int], list[tuple[str, int, int]]] = {}
    for kind, table, a, b in (("line", net.line, "from_bus", "to_bus"), ("trafo", net.trafo, "hv_bus", "lv_bus")):
        for eid, row in table.iterrows():
            if not bool(row["in_service"]):
                continue
            u, v = int(row[a]), int(row[b])
            key = (min(u, v), max(u, v))
            g.add_edge(*key)
            by_pair.setdefault(key, []).append((kind, int(eid), int(row.get("parallel", 1) or 1)))
    return g, by_pair


def _islanded_by(net, g: nx.Graph, slack: set[int]) -> tuple[float, float, list[int]]:
    """Demand and generation on the components of `g` that no longer reach a slack bus."""
    lost: list[int] = []
    for comp in nx.connected_components(g):
        if not comp & slack:
            lost.extend(int(b) for b in comp)
    if not lost:
        return 0.0, 0.0, []
    on = net.load["bus"].isin(lost)
    demand = float((net.load.loc[on, "p_mw"] * net.load.loc[on, "scaling"]).sum())
    gen = 0.0
    for t in (net[name] for name in FLEET_TABLES):  # fixed-power-factor and voltage-controlled generation alike
        if len(t):
            on = t[t["bus"].isin(lost)]
            if len(on):
                rated = on["p_rated_mw"] if "p_rated_mw" in on.columns else on["p_mw"]
                gen += float(rated.fillna(on["p_mw"]).sum())
    return demand, gen, sorted(lost)


def _structural_weak_points(ctx: StudyContext, p: StructuralParams) -> StudyResult:
    net = ctx.net_factory()
    g, by_pair = _simple_graph(net)
    slack = _slack_buses(net)
    items: list[StudyItem] = []
    # bridges: one circuit (no parallel, nothing else on the route) whose loss islands part of the network
    for u, v in sorted(nx.bridges(g)):
        els = by_pair[(min(u, v), max(u, v))]
        if len(els) != 1 or els[0][2] > 1:
            continue
        kind, eid, _ = els[0]
        h = g.copy()
        h.remove_edge(u, v)
        demand, gen, lost = _islanded_by(net, h, slack)
        if demand < N1_ISLAND_MIN_MW and gen < 1.0:
            continue
        noun = "transformer" if kind == "trafo" else "line"
        items.append(_item(len(items), "structural", element_kind=kind, element_id=eid, value=round(demand, 2), unit="MW",
                           severity="warn" if demand >= N1_ISLAND_MIN_MW else "info",
                           message=f"{noun} {eid} is the only route to {len(lost)} bus(es): losing it cuts off {demand:.1f} MW of demand and {gen:.1f} MW of generation",
                           extra={"generation_mw": round(gen, 2), "island_bus_ids": lost[:50]}))
    # articulation points: a busbar whose loss (a busbar fault) splits the network
    for bus in sorted(nx.articulation_points(g)):
        if bus in slack:
            continue
        h = g.copy()
        h.remove_node(bus)
        demand, gen, lost = _islanded_by(net, h, slack)
        own = net.load[net.load["bus"] == bus]
        demand += float((own["p_mw"] * own["scaling"]).sum())
        if demand < N1_ISLAND_MIN_MW and gen < 1.0:
            continue
        items.append(_item(len(items), "structural", element_kind="bus", element_id=bus, element_name=_bus_name(net, bus),
                           value=round(demand, 2), unit="MW", severity="warn" if demand >= N1_ISLAND_MIN_MW else "info",
                           message=f"a fault clearing {_bus_name(net, bus)} cuts off {demand:.1f} MW of demand and {gen:.1f} MW of generation at {len(lost) + 1} bus(es)",
                           extra={"generation_mw": round(gen, 2), "island_bus_ids": lost[:50]}))
    not_studied = ["power flow: this is topology only (what the N-1 screen and the contingency ranking solve)",
                   "normally-open points and switching that could restore supply"]
    summary = f"{sum(1 for x in items if x.element_kind != 'bus')} single-route circuits and {sum(1 for x in items if x.element_kind == 'bus')} busbars whose loss islands demand or generation."
    return StudyResult(kind="structural_weak_points", params=p.model_dump(), items=items, solves=0, not_studied=not_studied, summary=summary)


# --- tap margin ------------------------------------------------------------------------------------------------
def _tap_margin(ctx: StudyContext, p: TapMarginParams) -> StudyResult:
    net = ctx.net_factory()
    cases = _cases_for(net, p.cases)
    items: list[StudyItem] = []
    solves = 0
    taps0 = tap_positions(net)
    try:
        for case in cases.values():
            res = _run_case(net, case.name, case.load_scale, case.rating_ratio, regulate=True)
            solves += 1
            if res is None:
                continue
            for tid in _oltc_trafos(net):
                pos, tmin, tmax = (int(net.trafo.at[tid, c]) for c in ("tap_pos", "tap_min", "tap_max"))
                to_min, to_max = pos - tmin, tmax - pos
                steps = min(to_min, to_max)
                if steps > TAP_MARGIN_MIN_STEPS:
                    continue
                side = "its lowest tap (no more voltage lift)" if to_min <= to_max else "its highest tap (no more voltage cut)"
                lv = int(net.trafo.at[tid, "lv_bus"])
                vm = float(res["vm"].get(lv, float("nan")))
                items.append(_item(len(items), "tap_margin", element_kind="trafo", element_id=int(tid), case=case.name,
                                   value=float(steps), limit=float(TAP_MARGIN_MIN_STEPS), unit="steps",
                                   severity="breach" if steps <= 0 else "warn",
                                   message=(f"transformer {tid} sits {'at' if steps <= 0 else f'{steps} step from'} {side} at {_CASE_LABEL[case.name]}"
                                            f" (tap {pos} in {tmin}..{tmax}; LV busbar at {vm:.3f} pu)"),
                                   extra={"tap_pos": pos, "tap_min": tmin, "tap_max": tmax, "lv_vm_pu": round(vm, 4) if vm == vm else None}))
    finally:
        set_tap_positions(net, taps0)
    not_studied = [f"line-drop compensation and site-specific AVC targets ({OLTC_SETPOINT_PU:g} pu assumed everywhere)",
                   "demand growth and the plan's projects: today's network, as the branch reinforces it"]
    summary = f"{len(items)} regulated transformer(s) at or within {TAP_MARGIN_MIN_STEPS} step of a tap stop across {len(cases)} case(s)."
    return StudyResult(kind="tap_margin", params=p.model_dump(), items=items, solves=solves, not_studied=not_studied, summary=summary)


# --- GSP margin by year --------------------------------------------------------------------------------------------
def _gsp_margin_by_year(ctx: StudyContext, p: GspMarginParams) -> StudyResult:
    years = sorted(ctx.result.years.values(), key=lambda y: y.year) if ctx.result else []
    items: list[StudyItem] = []
    for y in years:
        if y.gsp_limit_mw is None or y.gsp_limit_mw <= 0:
            continue
        margin = y.gsp_limit_mw - y.gsp_export_mw
        sev = "breach" if margin < 0 else "warn" if margin < GSP_MARGIN_WARN_FRACTION * y.gsp_limit_mw else "info"
        items.append(_item(len(items), "gsp_margin", element_kind="gsp", element_id="gsp", year=y.year, value=round(margin, 1),
                           limit=round(y.gsp_limit_mw, 1), unit="MW", severity=sev,
                           message=f"in {y.year} the GSP exports {y.gsp_export_mw:.0f} of its {y.gsp_limit_mw:.0f} MW limit: {margin:.0f} MW of margin ({y.gsp_export_mw / y.gsp_limit_mw:.0%} used)",
                           extra={"export_mw": y.gsp_export_mw, "import_mw": y.gsp_import_mw}))
    tight = min(items, key=lambda x: x.value or 0.0) if items else None
    summary = (f"{len(items)} plan years; the tightest is {tight.year} with {tight.value:.0f} MW of export margin." if tight
               else "No plan year with a GSP limit.")
    return StudyResult(kind="gsp_margin_by_year", params=p.model_dump(), items=items, solves=0,
                       not_studied=["the GSP import limit (the network carries no import limit yet)", "the transmission network beyond the boundary"], summary=summary)


# --- data quality ------------------------------------------------------------------------------------------------
def _data_quality(ctx: StudyContext, p: DataQualityParams) -> StudyResult:
    net = ctx.net_factory()
    recorded = net.get("assumptions", {}) if hasattr(net, "get") else {}
    items: list[StudyItem] = []
    for key in sorted(recorded):
        a = ModelAssumption.model_validate({**recorded[key], "count": len(recorded[key].get("element_ids", []))})
        items.append(_item(len(items), "data_quality", element_kind="assumption", element_id=a.key, value=float(a.count or 0), unit="count",
                           severity="warn" if a.key == "rating_fallback" else "info",
                           message=f"{a.count} {a.element_kind or 'element'}(s): {a.message}",
                           extra={"source": a.source, "element_kind": a.element_kind, "element_ids": a.element_ids[:50]}))
    fixed = len(net.trafo) - len(_oltc_trafos(net))
    if fixed and "no_oltc" not in recorded:
        items.append(_item(len(items), "data_quality", element_kind="assumption", element_id="fixed_tap", value=float(fixed), unit="count",
                           message=f"{fixed} transformer(s) have no usable tap changer in the model"))
    not_studied = ["coordinates (the map model records their source separately)", "fault levels (published, units undocumented, not used)"]
    summary = f"{len(items)} kinds of assumption in the model, touching {sum(int(x.value or 0) for x in items)} elements."
    return StudyResult(kind="data_quality", params=p.model_dump(), items=items, solves=0, not_studied=not_studied, summary=summary)


# --- connection options ---------------------------------------------------------------------------------------------


def _bisect_solves(step: float) -> int:
    return 2 + math.ceil(math.log2(MAX_CONNECTION_MW / step))


def _candidate_of(ctx: StudyContext, request_id: str) -> Candidate:
    c = next((c for c in ctx.candidates if c.request_id == request_id), None)
    if c is None:
        raise ValueError(f"{request_id} is not a project on this branch")
    if c.bus_id is None:
        raise ValueError(f"{request_id} has no connection point (bus) in the model")
    return c


def _asks(c: Candidate) -> tuple[str, float]:
    """What the project asks of the network: its export, or its import for a demand connection."""
    if (c.technology or "").lower() in IMPORT_ONLY_TECHS:
        return "import", float(c.import_mw or 0.0)
    return "export", float(c.rating_mw or 0.0)


def _project_probe(net, case, bus: int, c: Candidate, mw: float, direction: str, baseline: Baseline) -> tuple[bool, Any, int]:
    """Probe `mw` of THIS project at `bus`: its own technology and control, so the case dispatch applies (PV at nil
    at winter peak, a battery charging, its reactive power as its offer runs it), with its import scaled along."""
    probe = c.model_copy(update={"bus_id": bus, "request_id": "connection-probe"})
    if direction == "import":
        return _probe(net, case, lambda: inject_project(net, probe, p_mw=0.0, import_mw=mw), baseline)
    return _probe(net, case, lambda: inject_project(net, probe, p_mw=mw, import_mw=c.import_at(mw)), baseline)


def _probed_cases(cases: dict, c: Candidate, direction: str) -> dict:
    """The cases where the project does something: an export project is not probed in a case its
    technology dispatches at nil (PV or wind at winter peak), where any MW would trivially fit."""
    if direction != "export":
        return cases
    tech = (c.technology or "").lower()
    return {k: v for k, v in cases.items() if GENERATION_FACTORS.get(k, {}).get(tech, GENERATION_FACTOR_DEFAULT.get(k, 1.0)) != 0.0}


def _higher_buses(net, bus: int) -> list[tuple[int, int]]:
    """Every busbar at a higher voltage than `bus`, nearest first by network steps (then the lower voltage
    level, the better connected, the id), as (bus, steps)."""
    g, _ = _simple_graph(net)
    if bus not in g:
        return []
    kv0 = float(net.bus.at[bus, "vn_kv"])
    deg = _degree(net)
    steps = nx.single_source_shortest_path_length(g, bus)
    higher = [(int(b), int(d)) for b, d in steps.items() if int(b) != bus and float(net.bus.at[int(b), "vn_kv"]) > kv0]
    higher.sort(key=lambda bd: (bd[1], float(net.bus.at[bd[0], "vn_kv"]), -deg.get(bd[0], 0), bd[0]))
    return higher


def _plan_net(ctx: StudyContext, exclude: str) -> tuple[Any, str]:
    """The network the options are probed on: the plan's hardest phase (demand grown to it, the projects
    accepted by then energised, the branch's reinforcements applied), without `exclude` itself."""
    phase = max(ctx.result.phases, key=int) if ctx.result and ctx.result.phases else None
    if phase is None:
        return ctx.net_factory(), "today"
    return phase_net(ctx.candidates, ctx.params or OptimizeParams(), ctx.result, phase, net_factory=ctx.net_factory, exclude=exclude), phase


def _plan_baseline(ctx: StudyContext, phase: str, exclude: str) -> Baseline:
    """What the probed phase breaches before its own projects (the earlier phases' connected, without `exclude`): a probe
    is judged against it, as the queue run judges a connection in that phase."""
    if phase == "today":
        return limit_baseline(ctx.net_factory())
    return phase_baseline(ctx.candidates, ctx.params or OptimizeParams(), ctx.result, phase, net_factory=ctx.net_factory, exclude=exclude)


def _size_items(p: ConnectionOptionsParams, c: Candidate, net, cases: dict, phase: str, items: list[StudyItem],
                baseline: Baseline) -> int:
    """What the project's own busbar takes of it, per case: a firm size, or a flexible connection firm to that MW."""
    direction, asked = _asks(c)
    rid, bus = c.request_id, int(c.bus_id)
    where = _bus_name(net, bus)
    solves = 0
    for case in cases.values():
        value, binding, n = _bisect_mw(lambda mw: _project_probe(net, case, bus, c, mw, direction, baseline), MAX_CONNECTION_MW, p.step_mw)
        solves += n
        label = _CASE_LABEL[case.name]
        fits = value >= asked
        if binding is None:
            msg = f"{where} takes at least {MAX_CONNECTION_MW:.0f} MW of {rid} at {label}: no limit reached within the intake cap"
        else:
            msg = f"{where} takes about {value:.0f} MW of {rid}'s {asked:.0f} MW at {label}, then {binding.message}"
            if not fits:
                msg += f"; as a firm connection size it to about {value:.0f} MW, or connect it flexibly, firm to {value:.0f} MW and curtailed above"
        items.append(_item(len(items), "connection_options", element_kind="bus", element_id=bus, element_name=where, case=case.name,
                           value=round(value, 1), limit=round(asked, 1), unit="MW", severity="info" if fits else "warn", message=msg,
                           fp_extra=("size", rid),
                           extra={"option": "size", "request_id": rid, "direction": direction, "asked_mw": asked, "fits": fits, "phase": phase,
                                  "binding": binding.model_dump() if binding else None}))
    return solves


def _chain_item(ctx: StudyContext, c: Candidate, where: str, phase: str, items: list[StudyItem]) -> int:
    """How far a chain of parallel circuits (suggest.discover_chain) gets the project at its own busbar."""
    rid = c.request_id
    accepted = ctx.result.phases[phase].accepted if ctx.result and phase in ctx.result.phases else []
    if rid in accepted:
        items.append(_item(len(items), "connection_options", element_kind="project", element_id=rid, element_name=where, severity="info",
                           message=f"{rid} already connects at {where} in the plan's {phase} phase", fp_extra=("reinforce",),
                           extra={"option": "reinforce", "request_id": rid, "connects": True, "reinforcements": [], "binding": None}))
        return 0
    reinf, connected, last, solves = discover_chain(ctx.candidates, ctx.params or OptimizeParams(), ctx.result, rid, net_factory=ctx.net_factory)
    noun = {"line": "line", "trafo": "transformer"}
    parts = ", ".join(f"{noun.get(r.kind, r.kind)} {r.element_id}" for r in reinf)
    circuits = f"{len(reinf)} parallel circuit{'s' if len(reinf) != 1 else ''}"
    if connected and not reinf:
        msg = f"{rid} connects at {where} as the plan stands: no reinforcement needed"
    elif connected:
        msg = f"{rid} connects at {where} after {circuits} ({parts})"
    elif reinf:
        msg = (f"after {circuits} ({parts}) {rid} is still held at {where}: {last.message}; "
               "the chain adds one circuit per element and stops when one of them binds again")
    else:
        msg = f"no parallel-circuit chain applies to {rid} at {where}" + (f": {last.message}" if last else "")
    items.append(_item(len(items), "connection_options", element_kind="project", element_id=rid, element_name=where,
                       case=last.case if last else None, value=last.value if last else None, limit=last.limit if last else None,
                       unit=REASON_SPECS[last.type].unit if last and last.type in REASON_SPECS else "", severity="info" if connected else "warn", message=msg,
                       fp_extra=("reinforce",),
                       extra={"option": "reinforce", "request_id": rid, "connects": connected, "reinforcements": [r.model_dump() for r in reinf],
                              "binding": last.model_dump() if last else None}))
    return solves


def _move_items(p: ConnectionOptionsParams, c: Candidate, net, cases: dict, phase: str, items: list[StudyItem],
                baseline: Baseline) -> int:
    """The project's full MW probed at higher-voltage busbars, nearest first; where it does not fit, how much does."""
    direction, asked = _asks(c)
    rid, home = c.request_id, int(c.bus_id)
    where = _bus_name(net, home)
    tech = c.technology or "project"
    higher = dict(_higher_buses(net, home))
    buses = [int(b) for b in p.bus_ids if int(b) in net.bus.index] if p.bus_ids else _ranked(net, list(higher), direction, p.max_buses)
    solves = 0
    for b in buses:
        there, steps = _bus_name(net, b), higher.get(b)
        for case in cases.values():
            label = _CASE_LABEL[case.name]
            ok, reason, n = _project_probe(net, case, b, c, asked, direction, baseline)
            solves += n
            if ok:
                value, binding, fits = asked, None, True
                msg = f"{rid} ({asked:.0f} MW {tech}) connects at {there} at {label} within every limit"
            else:
                value, binding, n = _bisect_mw(lambda mw: _project_probe(net, case, b, c, mw, direction, baseline), asked, p.step_mw,
                                               at_cap=(ok, reason))
                solves += n
                fits = False
                msg = f"{there} takes about {value:.0f} MW of {rid}'s {asked:.0f} MW at {label}, then {binding.message}"
            if steps is not None:
                msg += f" ({steps} step{'s' if steps != 1 else ''} from {where})"
            items.append(_item(len(items), "connection_options", element_kind="bus", element_id=b, element_name=there, case=case.name,
                               value=round(value, 1), limit=round(asked, 1), unit="MW", severity="info" if fits else "warn", message=msg,
                               fp_extra=("move", rid),
                               extra={"option": "move", "request_id": rid, "direction": direction, "vn_kv": float(net.bus.at[b, "vn_kv"]), "steps": steps,
                                      "asked_mw": asked, "fits": fits, "phase": phase, "binding": binding.model_dump() if binding else None}))
    return solves


def _connection_options(ctx: StudyContext, p: ConnectionOptionsParams) -> StudyResult:
    c = _candidate_of(ctx, p.request_id)
    direction, asked = _asks(c)
    net, phase = _plan_net(ctx, exclude=c.request_id)
    baseline = _plan_baseline(ctx, phase, c.request_id)
    every_case = _cases_for(net, None)
    cases = _probed_cases(every_case, c, direction)
    skipped = [k for k in every_case if k not in cases]
    where = _bus_name(net, int(c.bus_id))
    items: list[StudyItem] = []
    solves = 0
    if p.part in ("all", "site"):
        ctx.progress(f"connection options: {c.request_id} at its own busbar", 0.0)
        solves += _size_items(p, c, net, cases, phase, items, baseline)
        ctx.progress(f"connection options: the parallel-circuit chain for {c.request_id}", 0.3)
        solves += _chain_item(ctx, c, where, phase, items)
    if p.part in ("all", "bus"):
        ctx.progress(f"connection options: higher-voltage busbars for {c.request_id}", 0.5)
        solves += _move_items(p, c, net, cases, phase, items, baseline)
    sizes = [it for it in items if it.extra.get("option") == "size"]
    chain = next((it for it in items if it.extra.get("option") == "reinforce"), None)
    moves = [it for it in items if it.extra.get("option") == "move"]
    bits = [f"{c.request_id}: {asked:.0f} MW {c.technology or 'project'} ({direction}) at {where}"]
    if sizes:
        least = min(sizes, key=lambda it: it.value or 0.0)
        bits.append(f"its busbar takes about {least.value:.0f} MW of it ({_CASE_LABEL[least.case]})")
    if chain is not None:
        bits.append("the parallel-circuit chain connects it" if chain.extra.get("connects") else "the parallel-circuit chain does not reach it")
    if moves:
        by_bus: dict[str, list[StudyItem]] = {}
        for it in moves:
            by_bus.setdefault(it.element_name, []).append(it)
        for name, its in by_bus.items():
            if all(it.extra.get("fits") for it in its):
                bits.append(f"{name} takes its full MW in every case")
            else:
                worst = min(its, key=lambda it: it.value or 0.0)
                binding = (worst.extra.get("binding") or {}).get("message", "")
                bits.append(f"{name} takes about {worst.value:.0f} MW of it ({_CASE_LABEL[worst.case]}{', then ' + binding if binding else ''})")
    where_probed = (f"the other plan years: probed in the {phase} phase (demand grown to it, the projects accepted by then energised, "
                    "the branch's reinforcements applied)" if phase != "today"
                    else "demand growth and the plan's projects: today's network, as the branch reinforces it")
    not_studied = [where_probed,
                   *[f"{_CASE_LABEL[k]}: {c.technology or 'the project'} dispatches at nil in that case, so any MW fits there" for k in skipped],
                   "the works a new point of connection needs (a bay, a transformer, the circuit to it) and their cost",
                   "transmission works and the wider transmission queue",
                   "the hours a flexible connection would be curtailed (no time series)",
                   "fault levels"]
    return StudyResult(kind="connection_options", params=p.model_dump(), items=items, solves=solves, not_studied=not_studied, summary="; ".join(bits) + ".")


def _connection_chunks(ctx: StudyContext, p: ConnectionOptionsParams) -> list[BaseModel]:
    """The project's own site as one part, then one part per higher-voltage busbar."""
    if p.part != "all":
        return [p]
    try:
        c = _candidate_of(ctx, p.request_id)
    except ValueError:
        return [p]  # the run itself says why
    net, _ = _plan_net(ctx, exclude=p.request_id)  # ranked on the operating point the run itself probes, so the parts come in its order
    buses = p.bus_ids or _ranked(net, [b for b, _ in _higher_buses(net, int(c.bus_id))], _asks(c)[0], p.max_buses)
    return [p.model_copy(update={"part": "site"})] + [p.model_copy(update={"part": "bus", "bus_ids": [b]}) for b in buses]


def _connection_cost(p: ConnectionOptionsParams) -> int:
    b = _bisect_solves(p.step_mw)
    site = (MAX_REINFORCE_STEPS + 1 + 2 * b) if p.part in ("all", "site") else 0
    n_buses = len(p.bus_ids) if p.bus_ids else p.max_buses
    bus = n_buses * 2 * (1 + b) if p.part in ("all", "bus") else 0
    return site + bus


# --- the best window for a planned work ------------------------------------------------------------------------------
_VERDICT_SEVERITY = {"feasible": "info", "curtailment": "warn", "demand_at_risk": "breach", "not_feasible": "breach", "unstudied": "warn"}
_ELEMENT_NOUN = {"line": "line", "trafo": "transformer", "gen": "generator"}


def _best_window(ctx: StudyContext, p: BestWindowParams) -> StudyResult:
    lo, hi = p.years
    options = best_windows(ctx.result, ctx.candidates, ctx.params or OptimizeParams(), (p.element_kind, p.element_id), range(lo, hi + 1),
                           p.seasons or SEASONS, work=p.work, kind=p.kind, repower=p.repower, factor=p.factor, weeks=p.weeks,
                           scheduled=ctx.schedule, reinforcements=(), outages=ctx.outages, n1=p.n1, net_factory=ctx.net_factory,
                           progress=ctx.progress)
    noun = _ELEMENT_NOUN.get(p.element_kind, p.element_kind)
    name = f"{noun} {p.element_id}"
    items = [_item(i, "best_window", element_kind=p.element_kind, element_id=p.element_id, element_name=name, case=o.season, year=o.year,
                   value=round(o.curtailed_mw, 1), unit="MW", severity=_VERDICT_SEVERITY.get(o.verdict, "warn"),
                   message=f"{o.season} {o.year}, {p.work} ({p.kind}, {p.weeks} weeks) of {name}: {o.verdict}; {o.message}",
                   fp_extra=(p.work, p.kind, p.repower or "", str(p.weeks)),
                   extra={"rank": o.rank, "verdict": o.verdict, "curtailed_mw": o.curtailed_mw, "demand_at_risk_mw": o.demand_at_risk_mw,
                          "n1_findings": o.n1_findings, "worst_line_loading_pct": o.worst_line_loading_pct,
                          "worst_trafo_loading_pct": o.worst_trafo_loading_pct})
             for i, o in enumerate(options)]
    best = options[0] if options else None
    summary = (f"{len(options)} window(s) for {name} ({p.work}) in {lo}..{hi}; the best is {best.season} {best.year}: {best.verdict}"
               + (f", {best.curtailed_mw:.0f} MW curtailed" if best.curtailed_mw else "") + "." if best else f"No window for {name} in {lo}..{hi}.")
    not_studied = ["where in the season the weeks fall (a window is studied in its season's case(s), not placed in the calendar)",
                   "second faults during the windows outside the N-1 shortlist" if p.n1 else "second faults during the window (N-1 not screened)",
                   "the curtailment as an optimal re-dispatch (a bounded first-order search)",
                   "fault levels"]
    return StudyResult(kind="best_window", params=p.model_dump(), items=items, solves=_window_cost(p), not_studied=not_studied,
                       summary=summary)


def _window_chunks(ctx: StudyContext, p: BestWindowParams) -> list[BaseModel]:
    """One part per year when no N-1 screen is asked for (the shortlist is picked over the whole ranking)."""
    if p.n1:
        return [p]
    lo, hi = p.years
    return [p.model_copy(update={"years": (y, y)}) for y in range(lo, hi + 1)]


def _window_cost(p: BestWindowParams) -> int:
    lo, hi = p.years
    n_seasons = len(p.seasons) if p.seasons else len(SEASONS)
    return (hi - lo + 1) * n_seasons * 3 + (BEST_WINDOW_N1_SHORTLIST * 60 if p.n1 else 0)


# --- the registry ----------------------------------------------------------------------------------------------------
STUDIES: dict[str, StudySpec] = {
    "hosting_capacity": StudySpec(
        _hosting_capacity, HostingParams,
        cost_hint=lambda p: (len(p.bus_ids) if p.bus_ids else p.max_buses) * (len(p.cases) if p.cases else 2) * (2 + math.ceil(math.log2(MAX_CONNECTION_MW / p.step_mw))),
        description=("Per bus, the MW of new export (a firm generator) or import (a demand connection) that today's network, as the branch "
                     "reinforces it, can take before the first statutory voltage, thermal or GSP limit breaks, by bisection in each study case. "
                     "Not studied: demand growth, the plan's projects, fault levels."),
        chunk=_hosting_chunks),
    "contingency_ranking": StudySpec(
        _contingency_ranking, ContingencyParams,
        cost_hint=lambda p: 160 * (len(p.cases) if p.cases else 2),
        description=("Every single circuit or transformer outage at or above min_kv in each study case, scored by the demand it cuts off, the "
                     "thermal excess it causes and the worst voltage shortfall, ranked worst first. The N-1 screen's mechanics, wider. "
                     "Not studied: second outages, switching, fault levels."),
        chunk=_contingency_chunks),
    "structural_weak_points": StudySpec(
        _structural_weak_points, StructuralParams, cost_hint=lambda p: 0,
        description="Single-route circuits and busbars whose loss islands demand or generation, from the network graph alone (no power flow)."),
    "tap_margin": StudySpec(
        _tap_margin, TapMarginParams, cost_hint=lambda p: len(p.cases) if p.cases else 2,
        description="Regulated transformers at or within one step of a tap stop after the taps settle in each case: no voltage control left there."),
    "gsp_margin_by_year": StudySpec(
        _gsp_margin_by_year, GspMarginParams, cost_hint=lambda p: 0, needs_plan=True,
        description="The GSP's export margin in every solved plan year of the branch's result (reads the plan, solves nothing)."),
    "data_quality": StudySpec(
        _data_quality, DataQualityParams, cost_hint=lambda p: 0,
        description="What the model had to assume: blank ratings filled, lengths defaulted, tap steps assumed, power factors defaulted, and which elements."),
    "connection_options": StudySpec(
        _connection_options, ConnectionOptionsParams, cost_hint=_connection_cost, needs_plan=True,
        description=("How one project (request_id) could connect, probed in the plan's hardest phase on the branch's reinforced network: "
                     "what its own busbar takes of it (a firm size, or a flexible connection firm to that MW), how far a chain of parallel "
                     "circuits gets it, and which higher-voltage busbars nearby (nearest first) take its full MW and what binds there. "
                     "Not studied: the works and cost of a new point of connection, transmission works, curtailment hours, fault levels."),
        chunk=_connection_chunks),
    "best_window": StudySpec(
        _best_window, BestWindowParams, cost_hint=_window_cost, needs_plan=True,
        description=("The windows for a planned work on one element (maintenance, replacement or repowering; an outage or a derate): every "
                     "season of every year in the range, studied against the plan as it stands that year together with the branch's other "
                     "windows, with the verdict, the curtailment and the demand at risk of each; with n1 the shortlist is also screened for "
                     "second faults. Not studied: where the weeks fall in the season, the curtailment as an optimal re-dispatch, fault levels."),
        chunk=_window_chunks),
}


def run_study(kind: str, ctx: StudyContext, params: BaseModel | dict | None = None) -> StudyResult:
    """Run one study from the registry on a plan. `params` may be a dict (an agent's tool call) or the
    study's params model. Raises KeyError for an unknown study and ValueError when a study that needs
    the plan is run without one."""
    spec = STUDIES[kind]
    p = params if isinstance(params, BaseModel) else spec.params_model.model_validate(params or {})
    if spec.needs_plan and (ctx.result is None or not ctx.result.years):
        raise ValueError(f"{kind} reads the plan years: run the branch first")
    return spec.run(ctx, p)


def chunk_study(kind: str, ctx: StudyContext, params: BaseModel | dict | None = None) -> list[BaseModel]:
    """The independent sub-studies a study splits into (one per DBOS step), or the study itself."""
    spec = STUDIES[kind]
    p = params if isinstance(params, BaseModel) else spec.params_model.model_validate(params or {})
    return spec.chunk(ctx, p) if spec.chunk else [p]


def merge_chunks(kind: str, params: BaseModel | dict, parts: list[StudyResult]) -> StudyResult:
    """One result from a study's chunks: the items re-indexed in order, the costs summed, the caveats united."""
    spec = STUDIES[kind]
    p = params if isinstance(params, BaseModel) else spec.params_model.model_validate(params or {})
    items = [it.model_copy(update={"index": i}) for i, it in enumerate(x for part in parts for x in part.items)]
    not_studied: list[str] = []
    for part in parts:
        for n in part.not_studied:
            if n not in not_studied:
                not_studied.append(n)
    summary = parts[-1].summary if len(parts) == 1 else f"{len(items)} items from {len(parts)} parts; " + "; ".join(part.summary for part in parts)
    return StudyResult(kind=kind, params=p.model_dump(), items=items, solves=sum(x.solves for x in parts), not_studied=not_studied, summary=summary)
