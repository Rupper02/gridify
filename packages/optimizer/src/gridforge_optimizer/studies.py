"""Studies: deterministic analyses an agent (or the API) can run on a plan, as a registry.

Where the queue run and the plan years answer "does this plan hold?", a study answers a planner's
sharper question about the network itself: where can new generation or demand connect before a
limit breaks (hosting capacity), which single outage hurts most (contingency ranking), which
elements are structural single points of failure (no power flow needed), which tap changers have run
out of range (tap margin), how the GSP margin evolves year by year, and what the model had to assume
(data quality). Each study is bounded, pure given its `net_factory`, and returns `StudyItem`s whose
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
from pydantic import BaseModel, Field

from .config import (
    CONTINGENCY_MIN_KV,
    CONTINGENCY_SEVERITY_WEIGHTS,
    GSP_MARGIN_WARN_FRACTION,
    HOSTING_MAX_BUSES,
    HOSTING_MIN_KV,
    HOSTING_STEP_MW,
    LINE_LOADING_MAX_PCT,
    MAX_CONNECTION_MW,
    N1_ISLAND_MIN_MW,
    TAP_MARGIN_MIN_STEPS,
    TRAFO_LOADING_MAX_PCT,
)
from .findings import fingerprint
from .greedy import NetFactory, Progress, build_base_net
from .network import (
    _CASE_LABEL,
    _case_reason,
    _gsp_reason,
    _oltc_trafos,
    _run_case,
    _study_cases,
    drop_sgen,
    inject_sgen,
    n1_elements,
    emergency_ratio,
    outage_results,
    set_tap_positions,
    tap_positions,
    voltage_limits,
)
from .types import Candidate, ModelAssumption, OptimizeParams, OptimizeResult, StudyItem, StudyResult

_NOOP: Progress = lambda _s, _f: None  # noqa: E731


class StudyContext(NamedTuple):
    """What a study may read: the plan's network (already reinforced for the branch), its parameters,
    candidates and result (the plan years, for studies that read them), and a progress callback (where
    cancellation lands)."""

    net_factory: NetFactory = build_base_net
    params: OptimizeParams | None = None
    candidates: list[Candidate] = []
    result: OptimizeResult | None = None
    progress: Progress = _NOOP


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
def _probe_buses(net, p: HostingParams) -> list[int]:
    if p.bus_ids:
        return [int(b) for b in p.bus_ids if int(b) in net.bus.index]
    deg = _degree(net)
    buses = [int(b) for b in net.bus.index if float(net.bus.at[b, "vn_kv"]) >= p.min_kv]
    buses.sort(key=lambda b: (-float(net.bus.at[b, "vn_kv"]), -deg.get(b, 0), b))
    return buses[:p.max_buses]


def _hosting_probe(net, case, bus: int, mw: float, direction: str) -> tuple[bool, Any, int]:
    """Inject `mw` at `bus` (firm export, or a demand connection importing it), solve the case with the
    taps regulated, then leave the net exactly as found. Returns (within limits, the binding reason, solves)."""
    taps = tap_positions(net)
    idx = (inject_sgen(net, bus, mw, "hosting-probe", "other") if direction == "export"
           else inject_sgen(net, bus, 0.0, "hosting-probe", "demand", import_mw=mw))
    try:
        res = _run_case(net, case.name, case.load_scale, case.rating_ratio, regulate=True)
    finally:
        drop_sgen(net, idx)
        set_tap_positions(net, taps)
    if res is None:
        from .types import Reason
        return False, Reason(type="non_convergent", case=case.name, message=f"power flow does not converge at {_CASE_LABEL[case.name]}"), 1
    r = _case_reason(net, case.name, res["vm"], res["line_pct"], res["trafo_pct"]) or _gsp_reason(net, -res["p_ext_mw"], case.name)
    return r is None, r, 1


def _hosting_capacity(ctx: StudyContext, p: HostingParams) -> StudyResult:
    net = ctx.net_factory()
    cases = _cases_for(net, p.cases)
    buses = _probe_buses(net, p)
    items: list[StudyItem] = []
    solves = 0
    cap = MAX_CONNECTION_MW
    for i, bus in enumerate(buses):
        ctx.progress(f"hosting capacity: bus {bus} ({i + 1}/{len(buses)})", i / max(len(buses), 1))
        for case in cases.values():
            ok_cap, reason_cap, n = _hosting_probe(net, case, bus, cap, p.direction)
            solves += n
            if ok_cap:
                value, binding = cap, None
            else:
                lo, hi, binding = 0.0, cap, reason_cap
                ok0, reason0, n = _hosting_probe(net, case, bus, 0.0, p.direction)  # the network as it is
                solves += n
                if not ok0:
                    value, binding = 0.0, reason0
                else:
                    while hi - lo > p.step_mw:
                        mid = (lo + hi) / 2
                        ok, reason, n = _hosting_probe(net, case, bus, mid, p.direction)
                        solves += n
                        if ok:
                            lo = mid
                        else:
                            hi, binding = mid, reason
                    value = math.floor(lo / p.step_mw) * p.step_mw
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
                   "fault levels", "the 400 kV network beyond the GSP export limit"]
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
    sg = net.sgen[net.sgen["bus"].isin(lost)] if len(net.sgen) else None
    gen = float(sg["p_rated_mw"].fillna(sg["p_mw"]).sum()) if sg is not None and len(sg) else 0.0
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
    not_studied = ["line-drop compensation and site-specific AVC targets (1.02 pu assumed everywhere)",
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
                       not_studied=["the GSP import limit (the network carries no import limit yet)", "the 400 kV network"], summary=summary)


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
