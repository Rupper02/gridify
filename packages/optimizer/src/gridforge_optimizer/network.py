"""pandapower helpers: build the network, grow demand, dispatch generation per study case, inject
projects, test feasibility (statutory voltage bands, thermal limits, the GSP boundary), screen N-1."""

from __future__ import annotations

from collections.abc import Iterable
from typing import NamedTuple

import networkx as nx
import numpy as np
import pandapower as pp
import pandapower.topology as top
import pandas as pd
from pandapower.auxiliary import LoadflowNotConverged

from .config import (
    N1_CASES,
    N1_COLLAPSE_VM_PU,
    GENERATION_FACTOR_DEFAULT,
    GENERATION_FACTORS,
    OLTC_DEADBAND_PU,
    OLTC_MAX_PASSES,
    OLTC_SETPOINT_PU,
    GROWTH_BETA_INDUSTRIAL,
    GROWTH_BETA_RESIDENTIAL,
    GROWTH_EDGE_TILT,
    GROWTH_HETEROGENEITY,
    GROWTH_HOTSPOT_MULT,
    GROWTH_HOTSPOT_QUANTILE,
    LINE_LOADING_MAX_PCT,
    LOAD_TYPE_RESIDENTIAL,
    N1_ISLAND_MIN_MW,
    N1_MIN_KV,
    OUTAGE_DERATE_FACTOR,
    PLAN_START_YEAR,
    TRAFO_LOADING_MAX_PCT,
    VOLTAGE_BANDS,
)
from .dispatch import FLEET_TABLES, _ensure_fleet_columns, merit_order  # noqa: F401  (re-exported)
from .geometry import h01
from .types import Outage, Reason, Reinforcement


def build_base_net():
    """The canonical base network: the default source's (`sources.default_source`: NGED's Bicker Fen
    132 kV GSP region from LTDS open data). Every engine function takes `net_factory=` for any other."""
    from .sources import default_source
    return default_source().build_net()


# --- demand growth ----------------------------------------------------------
def apply_growth(net, factor) -> None:
    """Scale load to model demand growth (keeps original p_mw).

    `factor` may be a scalar (uniform growth) or a per-load Series/dict indexed by
    net.load.index (spatially heterogeneous growth, see per_bus_growth).
    """
    if isinstance(factor, (int, float)):
        net.load["scaling"] = net.load["scaling"] * float(factor)
    else:
        s = factor if isinstance(factor, pd.Series) else pd.Series(factor)
        net.load["scaling"] = net.load["scaling"] * net.load.index.map(s).astype(float)


def _feeder_hops(net) -> tuple[dict[int, int], int]:
    """Electrical hop-distance of every bus from the nearest feeder head (HV/MV trafo LV side)."""
    graph = top.create_nxgraph(net)
    sources = [int(b) for b in net.trafo["lv_bus"].unique() if int(b) in graph]
    if not sources:
        return {}, 1
    # hop count: every branch weighs 1 (networkx has no unweighted multi-source BFS)
    dist = nx.multi_source_dijkstra_path_length(graph, set(sources), weight=lambda u, v, d: 1)
    d_max = max(dist.values()) if dist else 1
    return {int(b): int(d) for b, d in dist.items()}, max(d_max, 1)


def interpolate_growth_for_year(year: int, growth_2030: float, growth_2035: float,
                                base_year: int = PLAN_START_YEAR) -> float:
    """The demand multiplier for one year, linear between the plan's anchors: 1.0 in `base_year`,
    `growth_2030` in 2030 and `growth_2035` in 2035 (held flat outside them)."""
    if year <= base_year:
        return 1.0
    if year <= 2030:
        return 1.0 + (year - base_year) / (2030 - base_year) * (growth_2030 - 1.0)
    if year <= 2035:
        return growth_2030 + (year - 2030) / 5 * (growth_2035 - growth_2030)
    return growth_2035


def demand_multiplier(params, year: int) -> float:
    """The peak-demand multiplier for one plan year: an imported grid's entered forecast as entered, otherwise
    linear between the pathway's 2030 and 2035 anchors (interpolate_growth_for_year)."""
    if params.curve:
        return 1.0 if year <= PLAN_START_YEAR else float(params.curve[min(year, max(params.curve))])
    return interpolate_growth_for_year(year, params.growth_2030, params.growth_2035)


def grow_for(net, params, m: float, horizon: int) -> None:
    """Grow a study net's demand by `m` for a run: uniformly on an entered forecast (a grid's forecast says how much,
    not where), by the FES pathway's per-bus shape otherwise (grow_demand)."""
    if params.curve:
        apply_growth(net, m)
    else:
        grow_demand(net, m, params.scenario, horizon)


def grow_demand(net, m: float, scenario: str, horizon: int) -> None:
    """Apply demand growth: per-bus (DFES pathway) unless scenario is 'custom' (uniform).
    Only demand grows here; no generation is pre-loaded: anything not connected today enters the
    study only as a queue project."""
    if scenario and scenario != "custom":
        apply_growth(net, per_bus_growth(net, m, scenario, horizon))
    else:
        apply_growth(net, m)


def per_bus_growth(net, m: float, scenario: str, horizon: int) -> pd.Series:
    """Per-load growth factors whose load-weighted mean equals the scenario multiplier `m`.

    Shapes demand growth by load type (residential vs industrial), a seeded per-bus
    heterogeneity, distance to the feeder edge, and ~20% adoption hotspots -- so the
    feeder TOTAL grows by exactly `m` while individual buses diverge realistically.
    Fully deterministic in (scenario, horizon, network structure).
    """
    load = net.load
    hops, d_max = _feeder_hops(net)

    weights: dict[int, float] = {}
    for idx, row in load.iterrows():
        bus = int(row["bus"])
        beta = GROWTH_BETA_RESIDENTIAL if str(row.get("type", "")) == LOAD_TYPE_RESIDENTIAL else GROWTH_BETA_INDUSTRIAL
        h = h01(f"{scenario}:{horizon}:{bus}")
        d = hops.get(bus, d_max // 2)
        dist_term = 1.0 + GROWTH_EDGE_TILT * (d / d_max - 0.5)
        hot = GROWTH_HOTSPOT_MULT if h > GROWTH_HOTSPOT_QUANTILE else 1.0
        weights[idx] = beta * (1.0 + GROWTH_HETEROGENEITY * (2.0 * h - 1.0)) * dist_term * hot

    w = pd.Series(weights)
    p = load["p_mw"].reindex(w.index).astype(float)
    wbar = float((w * p).sum() / p.sum()) if float(p.sum()) > 0 else float(w.mean())
    g = m - 1.0
    return 1.0 + g * (w / wbar)


# --- voltage limits ------------------------------------------------------------------------------
def bands_of(net) -> tuple[tuple[float, float, float], ...]:
    """The voltage limits by level, (min kV, vmin, vmax): an imported grid's own, entered at import for each of its
    levels (`net["voltage_bands"]`), otherwise the GB statutory bands (VOLTAGE_BANDS)."""
    return tuple(net.get("voltage_bands") or VOLTAGE_BANDS) if net is not None else VOLTAGE_BANDS


def band_at(kv: float, bands=VOLTAGE_BANDS) -> tuple[float, float]:
    """(vmin, vmax) in pu for one nominal voltage: the band of the highest level it reaches (as `voltage_limits`)."""
    reached = [b for b in bands if kv >= b[0]] or [min(bands, key=lambda b: b[0])]
    _, lo, hi = max(reached, key=lambda b: b[0])
    return lo, hi


def voltage_limits(net) -> tuple[pd.Series, pd.Series]:
    """Per-bus voltage band (vmin, vmax in pu) from the bus's nominal voltage: the band of the highest
    level the bus reaches (`bands_of`: the grid's own limits, or GB's ±10 % at 132 kV and ±6 % below it)."""
    bands = bands_of(net)
    kv = net.bus["vn_kv"].astype(float)
    lowest = min(bands, key=lambda b: b[0])
    vmin = pd.Series(lowest[1], index=net.bus.index, dtype=float)
    vmax = pd.Series(lowest[2], index=net.bus.index, dtype=float)
    for min_kv, lo, hi in sorted(bands, key=lambda b: b[0]):  # ascending: higher levels overwrite
        sel = kv >= min_kv
        vmin[sel] = lo
        vmax[sel] = hi
    return vmin, vmax


def voltage_band(kv: float, net=None) -> tuple[float, float]:
    """The (vmin, vmax) band for one nominal voltage (on `net`'s own limits when it states them)."""
    bands = bands_of(net)
    lo, hi = min(bands, key=lambda b: b[0])[1:]
    for min_kv, lo_b, hi_b in sorted(bands, key=lambda b: b[0]):
        if kv >= min_kv:
            lo, hi = lo_b, hi_b
    return lo, hi


# --- generation + dispatch -----------------------------------------------------------------------


def inject_sgen(
    net, bus: int, p_mw: float, name: str = "", tech: str | None = None, q_mvar: float = 0.0,
    import_mw: float | None = None,
) -> int:
    """Add a static generator (PQ) — DER does not regulate voltage, so violations surface.

    `q_mvar` defaults to 0 (unity power factor); a negative value models the DER ABSORBING
    reactive power, the cheapest lever against voltage rise from export. `import_mw` is the
    project's charging capacity (batteries): the demand it adds in the winter-peak case. Returns
    the new sgen index so a trial injection can be dropped again.
    """
    if int(bus) not in net.bus.index:
        raise ValueError(f"cannot connect at bus {bus}: not in the network model")
    idx = int(pp.create_sgen(net, bus=int(bus), p_mw=float(p_mw), q_mvar=float(q_mvar), name=name, type=tech))
    _ensure_fleet_columns(net)
    net.sgen.at[idx, "p_rated_mw"] = float(p_mw)
    net.sgen.at[idx, "import_mw"] = float(import_mw) if import_mw is not None else float(p_mw)
    return idx


def inject_project(net, c, p_mw: float | None = None, control=None, import_mw: float | None = None) -> tuple[str, int]:
    """Connect a project as its offer runs it (`control`, else `c.control`): a fixed power factor, or unity when it states
    none, is an `sgen` whose reactive power follows its output in every case (`_follow_power_factor`); voltage control
    is a `gen` holding its setpoint within its reactive range, dispatched by the case like any project (no `fleet_id`,
    so never by the merit order). `p_mw` / `import_mw` override the project's own (a probe). Returns (table, index)
    for `drop_project`."""
    control = control or c.control
    p = float(c.rating_mw or 0.0) if p_mw is None else float(p_mw)
    imp = c.import_mw if import_mw is None else import_mw
    if control is not None and control.mode == "voltage":
        if int(c.bus_id) not in net.bus.index:
            raise ValueError(f"cannot connect at bus {c.bus_id}: not in the network model")
        q = control.q_limit(max(p, float(imp or 0.0)))
        idx = int(pp.create_gen(net, bus=int(c.bus_id), p_mw=p, vm_pu=float(control.vm_pu), min_q_mvar=-q, max_q_mvar=q,
                                name=c.request_id, type=c.technology))
        _ensure_fleet_columns(net)
        net.gen.at[idx, "p_rated_mw"] = p
        net.gen.at[idx, "import_mw"] = float(imp) if imp is not None else p
        return "gen", idx
    idx = inject_sgen(net, c.bus_id, p, c.request_id, c.technology, import_mw=imp)
    if control is not None and control.mode == "pf" and (control.pf or 1.0) < 1.0:
        if "q_per_p" not in net.sgen.columns:
            net.sgen["q_per_p"] = pd.Series(dtype=float)
        k = control.q_per_p()
        net.sgen.at[idx, "q_per_p"] = k
        net.sgen.at[idx, "q_mvar"] = abs(p) * k
    return "sgen", idx


def drop_project(net, ref: tuple[str, int]) -> None:
    """Remove a project `inject_project` connected (rolls back a trial or a probe)."""
    table, idx = ref
    net[table] = net[table].drop(index=idx)


def _follow_power_factor(net) -> None:
    """A fixed-power-factor connection's reactive power follows the size of the active power its case dispatches,
    exporting or importing (`q_per_p`, set by `inject_project`); the caller restores `q_mvar` afterwards."""
    if "q_per_p" in net.sgen.columns:
        k = pd.to_numeric(net.sgen["q_per_p"], errors="coerce")
        sel = k.notna()
        if sel.any():
            net.sgen.loc[sel, "q_mvar"] = net.sgen.loc[sel, "p_mw"].astype(float).abs() * k[sel]


def dispatch_for_case(net, case: str, table: str = "sgen") -> pd.Series:
    """The active power of every generator in a table (`sgen` or `gen`) in a study case.

    GENERATION_FACTORS says how much of its rating each technology produces per case: the summer
    minimum (generation) case runs everything at full export; the winter peak (demand) case runs PV
    and wind at nil and batteries CHARGING at their import capacity (a negative factor means import).
    Unknown technologies are treated as firm (GENERATION_FACTOR_DEFAULT). On an imported grid the
    dispatchable units are then set by merit order instead (`dispatch.merit_order`).
    """
    _ensure_fleet_columns(net)
    t = net[table]
    factors = GENERATION_FACTORS.get(case, {})
    default = GENERATION_FACTOR_DEFAULT.get(case, 1.0)
    rated = t["p_rated_mw"].where(t["p_rated_mw"].notna(), t["p_mw"]).astype(float)
    imp = t["import_mw"].where(t["import_mw"].notna(), rated).astype(float)
    out = pd.Series(0.0, index=t.index, dtype=float)
    for idx in t.index:
        tech = str(t.at[idx, "type"] or "").lower()
        f = factors.get(tech, default)
        out[idx] = rated[idx] * f if f >= 0 else -imp[idx] * (-f)
    return out


def _oltc_trafos(net) -> pd.Index:
    """Transformers with a usable on-load tap changer (a tap range and a step)."""
    t = net.trafo
    if "tap_step_percent" not in t.columns:
        return t.index[:0]
    ok = t["tap_step_percent"].fillna(0) > 0
    ok &= t["tap_max"].fillna(0) > t["tap_min"].fillna(0)
    ok &= t["in_service"]
    return t.index[ok]


def _regulate_taps(net) -> int:
    """One AVC pass: move every OLTC transformer's tap so its LV busbar heads back to the setpoint.
    Returns how many taps moved. Needs a solved net (reads net.res_bus). On an HV-tapped transformer
    (GB practice) a LOWER tap means fewer HV turns and a higher LV voltage; on an LV-tapped one it is
    the other way round, so the correction's sign follows `tap_side`."""
    moved = 0
    idx = _oltc_trafos(net)
    if not len(idx):
        return 0
    vm = net.res_bus["vm_pu"]
    for tid in idx:
        lv = int(net.trafo.at[tid, "lv_bus"])
        v = float(vm.get(lv, float("nan")))
        if v != v:  # islanded / not solved
            continue
        err = v - OLTC_SETPOINT_PU
        if abs(err) <= OLTC_DEADBAND_PU:
            continue
        step = float(net.trafo.at[tid, "tap_step_percent"]) / 100.0
        pos = int(net.trafo.at[tid, "tap_pos"])
        delta = round(err / step)  # taps to move, before the winding's sign
        if str(net.trafo.at[tid, "tap_side"]) == "lv":
            delta = -delta
        new = int(min(max(pos + delta, int(net.trafo.at[tid, "tap_min"])), int(net.trafo.at[tid, "tap_max"])))
        if new != pos:
            net.trafo.at[tid, "tap_pos"] = new
            moved += 1
    return moved


def _no_solution(e: Exception) -> bool:
    """Whether an exception from the power flow means the network has no solution as solved (it did not converge, its
    matrix is singular, or nothing is left in service to solve), as opposed to a fault in the code or the data, which
    must surface instead of reading as "does not converge" (a merge-gate blocker, an N-1 finding, an import report)."""
    return (isinstance(e, (LoadflowNotConverged, np.linalg.LinAlgError, FloatingPointError, ZeroDivisionError))
            or (isinstance(e, ValueError) and "ppci is empty" in str(e)))


def _runpp(net) -> None:
    """One Newton-Raphson solve, warm-started from the last solution when there is one (the net
    changes little between trials, so this roughly halves the iterations)."""
    warm = len(net.res_bus) == len(net.bus) and not net.res_bus["vm_pu"].isna().any()
    # a voltage-controlled unit holds its setpoint only within its reactive limits: past them it stops regulating
    q_lims = {"enforce_q_lims": True} if len(net.gen) else {}
    try:
        pp.runpp(net, init="results" if warm else "auto", **q_lims)  # numba when installed
    except Exception as e:
        if not warm or not _no_solution(e):
            raise
        pp.runpp(net, init="auto", **q_lims)  # a bad warm start is retried cold


def _solve(net, regulate: bool = True) -> bool:
    """Run the AC power flow in place, letting the on-load tap changers settle (up to
    OLTC_MAX_PASSES passes; tap positions persist on the net so later solves start settled).
    `regulate=False` keeps the taps where they are. Return False if the power flow fails to converge."""
    try:
        _runpp(net)
        if regulate:
            for _ in range(OLTC_MAX_PASSES - 1):
                if _regulate_taps(net) == 0:
                    break
                _runpp(net)
        return True
    except Exception as e:
        if _no_solution(e):
            return False
        raise


def tap_positions(net) -> tuple:
    """The current tap positions, for saving before a trial and restoring after a rolled-back one
    (a rejected trial must leave no trace, or the greedy path would depend on solve history)."""
    return tuple(int(x) for x in net.trafo["tap_pos"].fillna(0).to_numpy()) if "tap_pos" in net.trafo.columns else ()


def set_tap_positions(net, taps: tuple) -> None:
    if taps and len(taps) == len(net.trafo):
        net.trafo["tap_pos"] = list(taps)


# --- study cases ------------------------------------------------------------------------------
# A connection must be safe in BOTH planning cases a DNO studies, not just at winter peak:
#   * winter_peak — maximum (grown) demand, winter thermal ratings, PV/wind at nil, batteries charging;
#   * summer_min  — minimum demand with summer (lower) thermal ratings, every generator at full
#     output. This is the GENERATION-critical case: little local load soaks up the export, so
#     reverse power flow, voltage rise and the GSP's export to transmission all peak here.
# The summer case needs per-load `min_scale` AND per-line `summer_ratio` (the NGED builder fills them from LTDS; an
# import must state both, `sources.apply_import_meta`): with either missing it would be another case under its name.
class CaseSpec(NamedTuple):
    """A planning study case. Adding one is adding an entry to CASE_SPECS (plus its dispatch factors
    in config.GENERATION_FACTORS): the solver, the reasons and the N-1 screen all read from here."""

    name: str
    label: str  # "at <label>" in reason messages
    rating_label: str  # what a line's loading is a percentage of, in this case
    load_column: str | None = None  # net.load column of per-load scaling (None = demand as grown)
    rating_column: str | None = None  # net.line column of rating multipliers (None = unchanged)


CASE_SPECS: tuple[CaseSpec, ...] = (
    CaseSpec("winter_peak", "winter peak demand", "its rating"),
    CaseSpec("summer_min", "summer minimum demand", "its summer rating",
             load_column="min_scale", rating_column="summer_ratio"),
)
_CASE_BY_NAME = {s.name: s for s in CASE_SPECS}
_CASE_LABEL = {s.name: s.label for s in CASE_SPECS}


class StudyCase(NamedTuple):
    """A case as applied to one network: unpacks as (name, load scaling or None, rating ratio or None)."""

    name: str
    load_scale: pd.Series | None
    rating_ratio: pd.Series | None


def _column(table, column: str | None) -> pd.Series | None:
    """The column if the network carries data in it, else None."""
    if column is not None and column in table.columns and table[column].notna().any():
        return table[column]
    return None


def _study_cases(net) -> list[StudyCase]:
    """The cases this network can be studied in. A case with no data columns always applies (winter
    peak); one with columns applies when the network carries data in every one of them."""
    cases: list[StudyCase] = []
    for spec in CASE_SPECS:
        load_scale, rating_ratio = _column(net.load, spec.load_column), _column(net.line, spec.rating_column)
        if (spec.load_column is None or load_scale is not None) and (spec.rating_column is None or rating_ratio is not None):
            cases.append(StudyCase(spec.name, load_scale, rating_ratio))
    return cases


def _run_case(net, case: str, load_scale: pd.Series | None, rating_ratio: pd.Series | None,
              regulate: bool = True) -> dict | None:
    """Solve one study case in place and return its results, leaving the net's inputs as found.
    None when the power flow does not converge."""
    scaling0, imax0 = net.load["scaling"].copy(), net.line["max_i_ka"].copy()
    p0, q0, gen_p0, gen_on0 = net.sgen["p_mw"].copy(), net.sgen["q_mvar"].copy(), net.gen["p_mw"].copy(), net.gen["in_service"].copy()
    try:
        if load_scale is not None:
            net.load["scaling"] = load_scale.where(load_scale.notna(), scaling0)
        if rating_ratio is not None:
            net.line["max_i_ka"] = imax0 * rating_ratio.fillna(1.0)
        merit_order(net, case)  # the case factors, and an imported grid's power stations by merit order (dispatch.py)
        _follow_power_factor(net)
        ok = _solve(net, regulate=regulate)
    finally:
        net.load["scaling"], net.line["max_i_ka"], net.sgen["p_mw"], net.sgen["q_mvar"] = scaling0, imax0, p0, q0
        net.gen["p_mw"], net.gen["in_service"] = gen_p0, gen_on0
    if not ok:
        return None
    p_ext = float(net.res_ext_grid["p_mw"].sum()) if len(net.res_ext_grid) else 0.0
    return {
        "vm": net.res_bus["vm_pu"].copy(),
        "line_pct": net.res_line["loading_percent"].copy(),
        "trafo_pct": net.res_trafo["loading_percent"].copy(),
        "p_ext_mw": p_ext,
    }


def case_dispatch(net, case: str, load_scale: pd.Series | None = None) -> dict[str, pd.Series]:
    """Each generator table's output in a study case, as `_run_case` sets it (merit order on an imported grid),
    without solving; the net is left as found."""
    saved = {t: (net[t]["p_mw"].copy(), net[t]["in_service"].copy()) for t in FLEET_TABLES}
    scaling0 = net.load["scaling"].copy()
    try:
        if load_scale is not None:
            net.load["scaling"] = load_scale.where(load_scale.notna(), scaling0)
        merit_order(net, case)
        return {t: net[t]["p_mw"].where(net[t]["in_service"].astype(bool), 0.0).astype(float) for t in FLEET_TABLES}
    finally:
        net.load["scaling"] = scaling0
        for t, (p, on) in saved.items():
            net[t]["p_mw"], net[t]["in_service"] = p, on


def _voltage_breaches(net, case: str, vm, line_pct, trafo_pct) -> list[Reason]:
    """Every bus outside its band, furthest outside first."""
    vmin, vmax = voltage_limits(net)
    v = vm.reindex(net.bus.index)
    excess = pd.concat([vmin - v, v - vmax], axis=1).max(axis=1).fillna(0.0)  # islanded buses have no voltage
    out = []
    for b in excess[excess > 1e-9].sort_values(ascending=False, kind="stable").index:
        val, lo, hi = float(v.loc[b]), float(vmin.loc[b]), float(vmax.loc[b])
        kv = float(net.bus.at[b, "vn_kv"])
        out.append(Reason(type="voltage", element_id=int(b), value=round(val, 4), limit=round(hi if val > hi else lo, 2), case=case,
                          message=f"voltage {val:.3f} pu at bus {int(b)} ({kv:g} kV) outside [{lo:.2f}, {hi:.2f}] at {_CASE_LABEL[case]}"))
    return out


def _line_breaches(net, case: str, vm, line_pct, trafo_pct) -> list[Reason]:
    """Every line over its rating, most loaded first."""
    rating = _CASE_BY_NAME[case].rating_label
    return [Reason(type="line", element_id=int(i), value=round(float(val), 1), limit=LINE_LOADING_MAX_PCT, case=case,
                   message=f"line {int(i)} overloaded at {float(val):.1f}% of {rating} at {_CASE_LABEL[case]}")
            for i, val in line_pct[line_pct > LINE_LOADING_MAX_PCT].sort_values(ascending=False, kind="stable").items()]


def _trafo_breaches(net, case: str, vm, line_pct, trafo_pct) -> list[Reason]:
    """Every transformer over its rating, most loaded first."""
    return [Reason(type="trafo", element_id=int(i), value=round(float(val), 1), limit=TRAFO_LOADING_MAX_PCT, case=case,
                   message=f"transformer {int(i)} overloaded at {float(val):.1f}% at {_CASE_LABEL[case]}")
            for i, val in trafo_pct[trafo_pct > TRAFO_LOADING_MAX_PCT].sort_values(ascending=False, kind="stable").items()]


# the per-case limit checks, in the order they bind, each returning every breach worst first: a new local limit is one
# function + one entry here (the GSP boundary is checked after all cases, in feasibility())
LIMIT_CHECKS = (_voltage_breaches, _line_breaches, _trafo_breaches)


def _case_reason(net, case: str, vm, line_pct, trafo_pct) -> Reason | None:
    """The first limit this case breaches (voltage → line → transformer; then the GSP boundary): the worst element of the
    first check that has any. What a connection is judged on."""
    for check in LIMIT_CHECKS:
        breaches = check(net, case, vm, line_pct, trafo_pct)
        if breaches:
            return breaches[0]
    return None


def case_breaches(net, case: str, vm, line_pct, trafo_pct) -> list[Reason]:
    """Every limit this case breaches, each element its own (voltage, then lines, then transformers, worst first within
    each): what an N-1 study lists, so a breach behind a worse one is never hidden."""
    return [r for check in LIMIT_CHECKS for r in check(net, case, vm, line_pct, trafo_pct)]


def gsp_export_limit(net) -> float | None:
    """The GSP's export limit to transmission (MW), or None for an unlimited (infinite) slack."""
    if not hasattr(net, "get") or net.get("gsp_export_limit_mw") is None:
        return None
    return float(net["gsp_export_limit_mw"])


def _gsp_reason(net, export: float, case: str | None) -> Reason | None:
    """The GSP boundary: power pushed UP through the supergrid transformers to transmission, in its
    worst study case, against the GSP's export limit."""
    limit = gsp_export_limit(net)
    if limit is None or export <= limit:
        return None
    name = net.get("gsp_name") or "the GSP"
    return Reason(type="gsp", value=round(export, 1), limit=round(limit, 1), case=case,
                  message=f"{name} would export {export:.0f} MW to the transmission system at "
                          f"{_CASE_LABEL.get(case, 'peak export')}, above its {limit:.0f} MW export limit")


def _by_case(groups: dict[str, tuple[pd.Series, pd.Series]]) -> dict[str, dict[str, list[int]]]:
    """Each study case's elements whose envelope figure it set: case -> {lines, trafos, buses} (ids with a figure).
    What lets a reading say "93% at summer minimum" instead of "93% (worst case)"."""
    out: dict[str, dict[str, list[int]]] = {}
    for kind, (case_of, values) in groups.items():
        for i, c in case_of.items():
            v = values.get(i)
            if v == v:  # a figure, not NaN
                out.setdefault(str(c), {}).setdefault(kind, []).append(int(i))
    return out


def feasibility(net) -> tuple[bool, Reason | None, dict]:
    """Run power flow in every study case; check the statutory voltage band of every bus, line and
    transformer thermal limits, and the GSP export boundary.

    Returns (ok, reason_if_not_ok, metrics). Afterwards net.res_line/res_trafo loading and
    net.res_bus voltage hold the worst-case ENVELOPE across cases (highest loading; the voltage
    furthest from 1.0 pu), so the per-element heat/violation helpers below report the binding case;
    `metrics["envelope_case"]` says which case set each element's figure, `metrics["export_case"]` the export's.
    """
    env_vm = env_line = env_trafo = None
    case_vm = case_line = case_trafo = None  # which study case set each element's envelope figure
    reason: Reason | None = None
    gsp_export = gsp_import = 0.0
    export_case = binding_case = None
    for case, load_scale, rating_ratio in _study_cases(net):
        res = _run_case(net, case, load_scale, rating_ratio)
        if res is None:
            return False, Reason(type="non_convergent", case=case,
                                 message=f"power flow did not converge at {_CASE_LABEL[case]}"), {}
        vm, line_pct, trafo_pct, p = res["vm"], res["line_pct"], res["trafo_pct"], res["p_ext_mw"]
        if -p > gsp_export:
            gsp_export, export_case = -p, case
        gsp_import = max(gsp_import, p)
        if reason is None:
            reason = _case_reason(net, case, vm, line_pct, trafo_pct)
            if reason is not None:
                binding_case = case
        if env_vm is None:
            env_vm, env_line, env_trafo = vm, line_pct, trafo_pct
            case_vm, case_line, case_trafo = (pd.Series(case, index=s.index, dtype=object) for s in (vm, line_pct, trafo_pct))
        else:
            keep = (env_vm - 1.0).abs() >= (vm - 1.0).abs()
            env_vm, case_vm = env_vm.where(keep, vm), case_vm.where(keep, case)
            keep = (env_line >= line_pct) | line_pct.isna()
            env_line, case_line = pd.concat([env_line, line_pct], axis=1).max(axis=1), case_line.where(keep, case)  # NaN-safe max
            keep = (env_trafo >= trafo_pct) | trafo_pct.isna()
            env_trafo, case_trafo = pd.concat([env_trafo, trafo_pct], axis=1).max(axis=1), case_trafo.where(keep, case)

    if reason is None:  # local limits hold — now the boundary, at its worst export case
        reason = _gsp_reason(net, gsp_export, export_case)
        binding_case = export_case if reason is not None else None
    net.res_bus["vm_pu"], net.res_line["loading_percent"] = env_vm, env_line
    net.res_trafo["loading_percent"] = env_trafo
    metrics = {
        "min_vm": float(env_vm.min()),
        "max_vm": float(env_vm.max()),
        "max_line_pct": float(env_line.max()) if len(env_line) else 0.0,
        "max_trafo_pct": float(env_trafo.max()) if len(env_trafo) else 0.0,
        "gsp_export_mw": round(gsp_export, 1),
        "gsp_import_mw": round(gsp_import, 1),
        "gsp_limit_mw": gsp_export_limit(net),
        "binding_case": binding_case,
        "export_case": export_case,
        "envelope_case": _by_case({"lines": (case_line, env_line), "trafos": (case_trafo, env_trafo), "buses": (case_vm, env_vm)}),
    }
    return reason is None, reason, metrics


def plan_net(net_factory, params, growth: float, horizon: int, reinforcements=(), projects=()):
    """A plan's network: a fresh base grown to `horizon`, the simulated reinforcements applied, then `projects`
    connected as their offers run them. The one way the greedy phases, the levers and the plan years build it."""
    net = net_factory()
    grow_for(net, params, growth, horizon)
    for r in reinforcements:
        apply_reinforcement(net, r)
    for c in projects:
        inject_project(net, c)
    return net


def snapshot(net, m: dict) -> dict:
    """The solved intact state a phase or a plan year reports (`m` is `feasibility`'s metrics for the net as it stands)."""
    return dict(
        worst_line_loading_pct=round(m.get("max_line_pct", 0.0), 1),
        worst_trafo_loading_pct=round(m.get("max_trafo_pct", 0.0), 1),
        min_vm_pu=round(m.get("min_vm", 0.0), 4),
        max_vm_pu=round(m.get("max_vm", 0.0), 4),
        overloaded_line_ids=overloaded_line_ids(net),
        line_loading=line_loadings(net),
        bus_vm=bus_voltages(net),
        voltage_violation_bus_ids=voltage_violation_bus_ids(net),
        gsp_export_mw=m.get("gsp_export_mw", 0.0),
        gsp_import_mw=m.get("gsp_import_mw", 0.0),
        gsp_limit_mw=m.get("gsp_limit_mw"),
        gsp_case=m.get("export_case"),
        envelope_case=m.get("envelope_case", {}),
    )


def overloaded_line_ids(net) -> list[int]:
    """Line ids whose loading exceeds the thermal limit in the last solve."""
    lp = net.res_line["loading_percent"]
    return [int(i) for i in lp[lp > LINE_LOADING_MAX_PCT].index]


def line_loadings(net) -> dict[int, float]:
    """Per-line loading_percent from the last solve (for the map heat overlay)."""
    lp = net.res_line["loading_percent"]
    return {int(i): round(float(v), 1) for i, v in lp.items() if v == v}  # a non-convergent solve leaves NaN: no figure, not null


def trafo_loadings(net) -> dict[int, float]:
    """Per-transformer loading_percent from the last solve."""
    tp = net.res_trafo["loading_percent"]
    return {int(i): round(float(v), 1) for i, v in tp.items() if v == v}


def bus_voltages(net) -> dict[int, float]:
    """Per-bus voltage magnitude (pu) from the last solve (for the map voltage overlay)."""
    vm = net.res_bus["vm_pu"]
    return {int(i): round(float(v), 4) for i, v in vm.items() if v == v}


def voltage_violation_bus_ids(net) -> list[int]:
    """Bus ids whose voltage is outside their statutory band in the last solve."""
    vm = net.res_bus["vm_pu"].reindex(net.bus.index)
    vmin, vmax = voltage_limits(net)
    return [int(i) for i in vm[(vm < vmin) | (vm > vmax)].index]


# --- N-1 screen ---------------------------------------------------------------------------------
def _islanded_mw(net, vm: pd.Series) -> tuple[float, list[int]]:
    """Demand stranded on islands in a solve: (MW, the islanded bus ids)."""
    island = islanded_bus_ids(net, vm)
    on = net.load["bus"].isin(island)
    lost = float((net.load.loc[on, "p_mw"] * net.load.loc[on, "scaling"]).sum()) if island else 0.0
    return lost, island


def islanded_bus_ids(net, vm: pd.Series) -> list[int]:
    """The buses left without a voltage (cut off from the infeed) in a solve."""
    v = vm.reindex(net.bus.index)
    return [int(b) for b in v[v.isna()].index]


def solve_case(net, case: str) -> dict | None:
    """Solve one study case on the intact net (taps regulated for it) and return its results
    ({vm, line_pct, trafo_pct, p_ext_mw}), leaving the net's inputs and tap positions as found.
    None if the case does not apply to this net or does not converge."""
    cases = {c.name: c for c in _study_cases(net)}
    if case not in cases:
        return None
    taps = tap_positions(net)
    try:
        return _run_case(net, case, cases[case].load_scale, cases[case].rating_ratio)
    finally:
        set_tap_positions(net, taps)


class OutageResult(NamedTuple):
    """One element taken out: the case's results (None when the power flow fails) and the demand it strands."""

    kind: str
    eid: int
    name: str
    res: dict | None
    lost_mw: float
    island: list[int]


def n1_floor(net) -> float:
    """The lowest voltage the N-1 screen covers: an imported grid's, entered at import, otherwise N1_MIN_KV."""
    return float(net.get("n1_min_kv") or N1_MIN_KV)


def n1_elements(net, min_kv: float | None = None) -> list[tuple[str, int]]:
    """The in-service lines and transformers at or above `min_kv` (by from-bus / HV bus; the grid's N-1 floor,
    `n1_floor`, when None), lines first."""
    min_kv = n1_floor(net) if min_kv is None else min_kv
    kv = net.bus["vn_kv"].astype(float)
    lines = [("line", int(i)) for i in net.line.index if net.line.at[i, "in_service"] and kv.loc[int(net.line.at[i, "from_bus"])] >= min_kv]
    trafos = [("trafo", int(i)) for i in net.trafo.index if net.trafo.at[i, "in_service"] and kv.loc[int(net.trafo.at[i, "hv_bus"])] >= min_kv]
    return lines + trafos


def emergency_ratio(net) -> pd.Series:
    """Each transformer's post-fault rating over its nominal one (LTDS Table 2a's emergency rating;
    1.0 when the net carries none): what the N-1 screen judges post-fault loading against."""
    if "emergency_ratio" in net.trafo.columns:
        return pd.to_numeric(net.trafo["emergency_ratio"], errors="coerce").fillna(1.0).clip(lower=1.0)
    return pd.Series(1.0, index=net.trafo.index)


def outage_results(net, case: str, load_scale, rating_ratio, elements):
    """Each element out in turn, solved as the post-fault steady state: the tap changers re-regulate
    (the AVC relays act within a minute of a fault; the pre-fault taps are restored before the next
    element) and transformer loading is read against the emergency rating (`trafo_pct` is % of it).
    Shared by the N-1 screen and the contingency ranking (studies.py); callers settle the taps for
    the case first."""
    tables = {"line": net.line, "trafo": net.trafo}
    k_emergency = emergency_ratio(net)
    for kind, eid in elements:
        table = tables[kind]
        taps = tap_positions(net)
        table.at[eid, "in_service"] = False
        try:
            res = _run_case(net, case, load_scale, rating_ratio, regulate=True)
        finally:
            table.at[eid, "in_service"] = True
            set_tap_positions(net, taps)
        if res is not None and len(res["trafo_pct"]):
            res["trafo_pct"] = res["trafo_pct"] / k_emergency.reindex(res["trafo_pct"].index).fillna(1.0)
        name = str(table.at[eid, "name"] or f"{kind} {eid}")
        lost, island = _islanded_mw(net, res["vm"]) if res is not None else (0.0, [])
        yield OutageResult(kind, eid, name, res, lost, island)


def n1_screen(net, case: str = "winter_peak", rating_ratio: pd.Series | None = None) -> dict:
    """Single-outage screen of the backbone: take each in-service line and transformer at or
    above the grid's N-1 floor (`n1_floor`: N1_MIN_KV, or an import's own) out of service in turn, solve the study case, and report any thermal, voltage or
    islanding violation, every breached element its own finding, except a post-fault state with a bus below
    `N1_COLLAPSE_VM_PU`: that is no credible steady state and is one "collapse" finding for the outage. Informational
    (not a connection gate); roughly P2/8 security of supply.
    `rating_ratio` overrides the case's line ratings (a maintenance window's season, maintenance.py)."""
    cases = {c: (ls, rr) for c, ls, rr in _study_cases(net)}
    if case not in cases:
        case = "winter_peak"
    load_scale, case_ratio = cases[case]
    rating_ratio = case_ratio if rating_ratio is None else rating_ratio
    # the pre-fault state is the intact network with its taps regulated for THIS case. feasibility()
    # leaves them as the last study case (summer minimum) settled them, so settle them for the screened
    # case first; each outage then starts from those taps and lets the relays re-regulate (outage_results).
    _run_case(net, case, load_scale, rating_ratio, regulate=True)
    elements = n1_elements(net)
    violations: list[dict] = []
    for o in outage_results(net, case, load_scale, rating_ratio, elements):
        head = {"outage_type": o.kind, "outage_id": o.eid, "outage_name": o.name, "case": case}
        if o.res is None:
            violations.append({**head, "type": "non_convergent", "element_id": None, "value": None,
                               "message": f"power flow does not converge with {o.kind} {o.eid} out at {_CASE_LABEL[case]}"})
            continue
        # demand stranded on an island: a supply violation only if it is material (a generator
        # spur or a tee-point with no customers is not)
        if o.lost_mw >= N1_ISLAND_MIN_MW:
            violations.append({**head, "type": "islanded", "element_id": o.island[0], "value": round(o.lost_mw, 2),
                               "islanded_bus_ids": o.island,  # demand.py attributes it to regions
                               "message": f"{o.kind} {o.eid} out islands {o.lost_mw:.1f} MW of demand at {len(o.island)} bus(es) at {_CASE_LABEL[case]}"})
            continue
        # a state the solver settled into with buses far below their band is a collapse, not a list of breaches: the
        # low voltages drive every loading up with them (current ∝ 1/V), so one finding names the outage and the floor
        vm = o.res["vm"].dropna()
        low = vm[vm < N1_COLLAPSE_VM_PU]
        if len(low):
            worst = int(low.idxmin())
            violations.append({**head, "type": "collapse", "element_id": worst, "value": round(float(low.min()), 4), "n_low": int(len(low)),
                               "message": f"{o.kind} {o.eid} out: no credible post-fault steady state at {_CASE_LABEL[case]}: the power flow "
                                          f"settles with {len(low)} bus(es) below {N1_COLLAPSE_VM_PU:.2f} pu (lowest {float(low.min()):.3f} pu at bus {worst})"})
            continue
        # every element the outage breaches, each its own finding: a breach behind a worse one is a finding too
        for r in case_breaches(net, case, o.res["vm"], o.res["line_pct"], o.res["trafo_pct"]):
            msg = f"{o.kind} {o.eid} out: " + r.message + (" (post-fault, of its emergency rating)" if r.type == "trafo" else "")
            violations.append({**head, "type": r.type, "element_id": r.element_id, "value": r.value, "message": msg})
    # the screen leaves res_* from its last outage; callers re-solve for the intact state
    return {"case": case, "screened": len(elements), "violations": violations}


def n1_screen_cases(net, cases: Iterable[str] = N1_CASES) -> dict:
    """The N-1 screen in each of `cases` the network supports (config.N1_CASES), as one list: every
    case's thermal, voltage and convergence findings, each carrying its `case`; islanded demand from the
    first case only (an island is topology, the same in every case; the demand case is where the P2/8-
    style check reads it). `screened` is the elements outaged, the same in each case."""
    supported = {c.name for c in _study_cases(net)}
    run = [c for c in cases if c in supported]
    out: dict = {"cases": run, "screened": 0, "violations": []}
    for i, case in enumerate(run):
        s = n1_screen(net, case)
        out["screened"] = s["screened"]
        out["violations"].extend(v for v in s["violations"] if i == 0 or v["type"] != "islanded")
    return out


# --- planned outages (maintenance windows) ----------------------------------------------------
# a transformer's vk / vkr are percentages of its own rating: scaling the rating alone would also scale
# its impedance in ohms, so they scale with it (a thermal change leaves the impedance as it is)
_RELATIVE_TO_RATING = {"trafo": ("vk_percent", "vkr_percent")}


def _scale_rating(net, table_name: str, eid: int, rating_column: str, k: float):
    """Multiply an element's thermal rating by k, impedance unchanged. Returns an undo."""
    table = getattr(net, table_name)
    cols = [rating_column, *(c for c in _RELATIVE_TO_RATING.get(table_name, ()) if c in table.columns)]
    before = {c: table.at[eid, c] for c in cols}
    for c in cols:
        table.at[eid, c] = float(before[c]) * k

    def undo():
        for c, v in before.items():
            table.at[eid, c] = v
    return undo


def _element_outage(table_name: str, rating_column: str):
    """An outage applier for a line/transformer table: out of service, or derated. Returns an undo."""
    def apply(net, o: Outage):
        table = getattr(net, table_name)
        eid = int(o.element_id)
        if eid not in table.index:
            return None
        if o.kind == "derate":
            return _scale_rating(net, table_name, eid, rating_column, OUTAGE_DERATE_FACTOR)
        before = table.at[eid, "in_service"]
        table.at[eid, "in_service"] = False
        return lambda: table.at.__setitem__((eid, "in_service"), before)
    return apply


def _generator_outage(net, o: Outage):
    """An existing generator out of service (a derate halves its output), in whichever generator table holds it.
    Returns an undo."""
    for table in FLEET_TABLES:
        t = net[table]
        if "fleet_id" not in t.columns:
            continue
        idx = t.index[t["fleet_id"] == o.element_id]
        if not len(idx):
            continue
        col = "p_rated_mw" if o.kind == "derate" else "in_service"
        before = t.loc[idx, col].copy()
        t.loc[idx, col] = before * OUTAGE_DERATE_FACTOR if o.kind == "derate" else False
        return lambda: t.loc.__setitem__((idx, col), before)
    return None


# how each Outage.element_kind changes the net (a new kind of maintenance target is one entry here)
OUTAGE_APPLIERS = {
    "line": _element_outage("line", "max_i_ka"),
    "trafo": _element_outage("trafo", "sn_mva"),
    "gen": _generator_outage,
}


# --- reinforcement (for "what would it take" suggestions) -------------------
def _reinforce_gsp(net, r: Reinforcement) -> None:
    """One more supergrid transformer at the GSP: raises the export limit by one SGT's rating."""
    if hasattr(net, "get") and net.get("gsp_export_limit_mw") is not None and net.get("gsp_sgt_mw"):
        net["gsp_export_limit_mw"] = float(net["gsp_export_limit_mw"]) + float(net["gsp_sgt_mw"])


def _reinforce_element(table_name: str, rating_column: str):
    """A reinforcer for a line/transformer table: add_parallel, or uprate `rating_column` by `factor`."""
    def reinforce(net, r: Reinforcement) -> None:
        table = getattr(net, table_name)
        if r.element_id not in table.index:
            return
        if r.action == "add_parallel":
            table.at[r.element_id, "parallel"] = int(table.at[r.element_id, "parallel"]) + 1
        else:
            _scale_rating(net, table_name, r.element_id, rating_column, r.factor)
    return reinforce


# how each Reinforcement.kind changes the net: a new kind of upgrade is one entry here
REINFORCERS = {
    "gsp": _reinforce_gsp,
    "line": _reinforce_element("line", "max_i_ka"),
    "trafo": _reinforce_element("trafo", "sn_mva"),
}


def apply_reinforcement(net, r: Reinforcement) -> None:
    """Simulate a network reinforcement in place (see REINFORCERS).

    add_parallel bumps the element's `parallel` count -> halves series impedance AND doubles its
    rating, so it relieves BOTH thermal overload and voltage. uprate raises only the thermal
    rating (`max_i_ka` for a line, `sn_mva` for a trafo) by `factor`, leaving impedance (and thus
    voltage) unchanged. kind "gsp" adds one more supergrid transformer at the GSP, raising its
    export limit by one SGT's rating (transmission works). No-op if the element id is unknown.
    """
    REINFORCERS[r.kind](net, r)


def upstream_path_lines(net, bus: int) -> list[int]:
    """Line ids on the shortest path from `bus` up to its nearest feeder head (trafo LV side).

    Used to pick a reinforcement site for a voltage-bound bus. Empty if no path is found.
    """
    graph = top.create_nxgraph(net)
    sources = [int(b) for b in net.trafo["lv_bus"].unique() if int(b) in graph]
    best: list[int] | None = None
    for s in sources:
        if bus in graph and nx.has_path(graph, bus, s):
            p = nx.shortest_path(graph, bus, s)
            if best is None or len(p) < len(best):
                best = p
    if not best:
        return []
    lines: list[int] = []
    for u, v in zip(best[:-1], best[1:]):
        cand = net.line[
            ((net.line["from_bus"] == u) & (net.line["to_bus"] == v))
            | ((net.line["from_bus"] == v) & (net.line["to_bus"] == u))
        ]
        if len(cand):
            lines.append(int(cand.index[0]))
    return lines
