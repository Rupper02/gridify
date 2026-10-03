"""pandapower helpers: build the network, grow demand, dispatch generation per study case, inject
projects, test feasibility (statutory voltage bands, thermal limits, the GSP boundary), screen N-1."""

from __future__ import annotations

import hashlib
from typing import NamedTuple

import networkx as nx
import pandapower as pp
import pandapower.topology as top
import pandas as pd

from .config import (
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
from .types import Outage, Reason, Reinforcement


def build_base_net():
    """The canonical base network: the real NGED Bicker Fen 132 kV GSP region (from LTDS open data)."""
    from .nged import build_nged_net
    return build_nged_net()


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


def _hash01(key: str) -> float:
    """Deterministic pseudo-random value in [0,1) from a string (seeded by scenario+bus)."""
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


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
        h = _hash01(f"{scenario}:{horizon}:{bus}")
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
def voltage_limits(net) -> tuple[pd.Series, pd.Series]:
    """Per-bus statutory voltage band (vmin, vmax in pu) from the bus's nominal voltage: the first
    band in VOLTAGE_BANDS whose minimum kV the bus reaches (±10 % at 132 kV, ±6 % below it)."""
    kv = net.bus["vn_kv"].astype(float)
    vmin = pd.Series(VOLTAGE_BANDS[-1][1], index=net.bus.index, dtype=float)
    vmax = pd.Series(VOLTAGE_BANDS[-1][2], index=net.bus.index, dtype=float)
    for min_kv, lo, hi in sorted(VOLTAGE_BANDS, key=lambda b: b[0]):  # ascending: higher levels overwrite
        sel = kv >= min_kv
        vmin[sel] = lo
        vmax[sel] = hi
    return vmin, vmax


def voltage_band(kv: float) -> tuple[float, float]:
    """The (vmin, vmax) band for one nominal voltage."""
    lo, hi = VOLTAGE_BANDS[-1][1], VOLTAGE_BANDS[-1][2]
    for min_kv, lo_b, hi_b in sorted(VOLTAGE_BANDS, key=lambda b: b[0]):
        if kv >= min_kv:
            lo, hi = lo_b, hi_b
    return lo, hi


# --- generation + dispatch -----------------------------------------------------------------------
def _ensure_sgen_columns(net) -> None:
    if "import_mw" not in net.sgen.columns:
        net.sgen["import_mw"] = pd.Series(dtype=float)
    if "p_rated_mw" not in net.sgen.columns:
        net.sgen["p_rated_mw"] = pd.Series(dtype=float)


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
    _ensure_sgen_columns(net)
    net.sgen.at[idx, "p_rated_mw"] = float(p_mw)
    net.sgen.at[idx, "import_mw"] = float(import_mw) if import_mw is not None else float(p_mw)
    return idx


def drop_sgen(net, idx: int) -> None:
    """Remove a previously injected sgen by index (rolls back a rejected trial injection)."""
    net.sgen = net.sgen.drop(index=idx)


def dispatch_for_case(net, case: str) -> pd.Series:
    """The active power of every sgen in a study case.

    GENERATION_FACTORS says how much of its rating each technology produces per case: the summer
    minimum (generation) case runs everything at full export; the winter peak (demand) case runs PV
    and wind at nil and batteries CHARGING at their import capacity (a negative factor means import).
    Unknown technologies are treated as firm (GENERATION_FACTOR_DEFAULT).
    """
    _ensure_sgen_columns(net)
    factors = GENERATION_FACTORS.get(case, {})
    default = GENERATION_FACTOR_DEFAULT.get(case, 1.0)
    rated = net.sgen["p_rated_mw"].where(net.sgen["p_rated_mw"].notna(), net.sgen["p_mw"]).astype(float)
    imp = net.sgen["import_mw"].where(net.sgen["import_mw"].notna(), rated).astype(float)
    out = pd.Series(0.0, index=net.sgen.index, dtype=float)
    for idx in net.sgen.index:
        tech = str(net.sgen.at[idx, "type"] or "").lower()
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


def _runpp(net) -> None:
    """One Newton-Raphson solve, warm-started from the last solution when there is one (the net
    changes little between trials, so this roughly halves the iterations)."""
    warm = len(net.res_bus) == len(net.bus) and not net.res_bus["vm_pu"].isna().any()
    try:
        pp.runpp(net, init="results" if warm else "auto")  # numba when installed
    except Exception:
        if not warm:
            raise
        pp.runpp(net, init="auto")  # a bad warm start is retried cold


def _solve(net, regulate: bool = True) -> bool:
    """Run the AC power flow in place, letting the on-load tap changers settle (up to
    OLTC_MAX_PASSES passes; tap positions persist on the net so later solves start settled).
    `regulate=False` keeps the taps where they are (used by the N-1 screen, where the intact
    settings are the honest pre-fault state). Return False if the power flow fails to converge."""
    try:
        _runpp(net)
        if regulate:
            for _ in range(OLTC_MAX_PASSES - 1):
                if _regulate_taps(net) == 0:
                    break
                _runpp(net)
        return True
    except Exception:
        return False


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
# The summer case needs per-load `min_scale` / per-line `summer_ratio` columns (the NGED builder
# fills them from LTDS); a network without them is studied at winter peak only.
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
    peak); one with columns applies when the network carries data in at least one of them."""
    cases: list[StudyCase] = []
    for spec in CASE_SPECS:
        load_scale, rating_ratio = _column(net.load, spec.load_column), _column(net.line, spec.rating_column)
        if spec.load_column is None and spec.rating_column is None or load_scale is not None or rating_ratio is not None:
            cases.append(StudyCase(spec.name, load_scale, rating_ratio))
    return cases


def _run_case(net, case: str, load_scale: pd.Series | None, rating_ratio: pd.Series | None,
              regulate: bool = True) -> dict | None:
    """Solve one study case in place and return its results, leaving the net's inputs as found.
    None when the power flow does not converge."""
    scaling0, imax0 = net.load["scaling"].copy(), net.line["max_i_ka"].copy()
    p0 = net.sgen["p_mw"].copy()
    try:
        if load_scale is not None:
            net.load["scaling"] = load_scale.where(load_scale.notna(), scaling0)
        if rating_ratio is not None:
            net.line["max_i_ka"] = imax0 * rating_ratio.fillna(1.0)
        if len(net.sgen):
            net.sgen["p_mw"] = dispatch_for_case(net, case)
        ok = _solve(net, regulate=regulate)
    finally:
        net.load["scaling"], net.line["max_i_ka"], net.sgen["p_mw"] = scaling0, imax0, p0
    if not ok:
        return None
    p_ext = float(net.res_ext_grid["p_mw"].sum()) if len(net.res_ext_grid) else 0.0
    return {
        "vm": net.res_bus["vm_pu"].copy(),
        "line_pct": net.res_line["loading_percent"].copy(),
        "trafo_pct": net.res_trafo["loading_percent"].copy(),
        "p_ext_mw": p_ext,
    }


def _voltage_reason(net, case: str, vm, line_pct, trafo_pct) -> Reason | None:
    vmin, vmax = voltage_limits(net)
    v = vm.reindex(net.bus.index)
    excess = pd.concat([vmin - v, v - vmax], axis=1).max(axis=1).fillna(0.0)  # islanded buses have no voltage
    if not (excess > 1e-9).any():
        return None
    worst = int(excess.idxmax())
    val = float(v.loc[worst])
    lo, hi = float(vmin.loc[worst]), float(vmax.loc[worst])
    kv = float(net.bus.at[worst, "vn_kv"])
    return Reason(type="voltage", element_id=worst, value=round(val, 4), limit=round(hi if val > hi else lo, 2), case=case,
                  message=f"voltage {val:.3f} pu at bus {worst} ({kv:g} kV) outside [{lo:.2f}, {hi:.2f}] at {_CASE_LABEL[case]}")


def _line_reason(net, case: str, vm, line_pct, trafo_pct) -> Reason | None:
    if not (line_pct > LINE_LOADING_MAX_PCT).any():
        return None
    worst = line_pct.idxmax()
    val = float(line_pct.loc[worst])
    rating = _CASE_BY_NAME[case].rating_label
    return Reason(type="line", element_id=int(worst), value=round(val, 1), limit=LINE_LOADING_MAX_PCT, case=case,
                  message=f"line {int(worst)} overloaded at {val:.0f}% of {rating} at {_CASE_LABEL[case]}")


def _trafo_reason(net, case: str, vm, line_pct, trafo_pct) -> Reason | None:
    if not (trafo_pct > TRAFO_LOADING_MAX_PCT).any():
        return None
    worst = trafo_pct.idxmax()
    val = float(trafo_pct.loc[worst])
    return Reason(type="trafo", element_id=int(worst), value=round(val, 1), limit=TRAFO_LOADING_MAX_PCT, case=case,
                  message=f"transformer {int(worst)} overloaded at {val:.0f}% at {_CASE_LABEL[case]}")


# the per-case limit checks, in the order they bind: a new local limit is one function + one entry here
# (the GSP boundary is checked after all cases, in feasibility())
LIMIT_CHECKS = (_voltage_reason, _line_reason, _trafo_reason)


def _case_reason(net, case: str, vm, line_pct, trafo_pct) -> Reason | None:
    """The first limit this case breaches (voltage → line → transformer; then the GSP boundary)."""
    for check in LIMIT_CHECKS:
        reason = check(net, case, vm, line_pct, trafo_pct)
        if reason is not None:
            return reason
    return None


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


def feasibility(net) -> tuple[bool, Reason | None, dict]:
    """Run power flow in every study case; check the statutory voltage band of every bus, line and
    transformer thermal limits, and the GSP export boundary.

    Returns (ok, reason_if_not_ok, metrics). Afterwards net.res_line/res_trafo loading and
    net.res_bus voltage hold the worst-case ENVELOPE across cases (highest loading; the voltage
    furthest from 1.0 pu), so the per-element heat/violation helpers below report the binding case.
    """
    env_vm = env_line = env_trafo = None
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
        else:
            env_vm = env_vm.where((env_vm - 1.0).abs() >= (vm - 1.0).abs(), vm)
            env_line = pd.concat([env_line, line_pct], axis=1).max(axis=1)  # NaN-safe max
            env_trafo = pd.concat([env_trafo, trafo_pct], axis=1).max(axis=1)

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
    }
    return reason is None, reason, metrics


def overloaded_line_ids(net) -> list[int]:
    """Line ids whose loading exceeds the thermal limit in the last solve."""
    lp = net.res_line["loading_percent"]
    return [int(i) for i in lp[lp > LINE_LOADING_MAX_PCT].index]


def line_loadings(net) -> dict[int, float]:
    """Per-line loading_percent from the last solve (for the map heat overlay)."""
    lp = net.res_line["loading_percent"]
    return {int(i): round(float(v), 1) for i, v in lp.items()}


def trafo_loadings(net) -> dict[int, float]:
    """Per-transformer loading_percent from the last solve."""
    tp = net.res_trafo["loading_percent"]
    return {int(i): round(float(v), 1) for i, v in tp.items() if v == v}


def bus_voltages(net) -> dict[int, float]:
    """Per-bus voltage magnitude (pu) from the last solve (for the map voltage overlay)."""
    vm = net.res_bus["vm_pu"]
    return {int(i): round(float(v), 4) for i, v in vm.items()}


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


def n1_elements(net, min_kv: float = N1_MIN_KV) -> list[tuple[str, int]]:
    """The in-service lines and transformers at or above `min_kv` (by from-bus / HV bus), lines first."""
    kv = net.bus["vn_kv"].astype(float)
    lines = [("line", int(i)) for i in net.line.index if net.line.at[i, "in_service"] and kv.loc[int(net.line.at[i, "from_bus"])] >= min_kv]
    trafos = [("trafo", int(i)) for i in net.trafo.index if net.trafo.at[i, "in_service"] and kv.loc[int(net.trafo.at[i, "hv_bus"])] >= min_kv]
    return lines + trafos


def outage_results(net, case: str, load_scale, rating_ratio, elements):
    """Each element out in turn, solved with the taps as they are (the pre-fault settings: a tap
    changer does not move in the instant after a fault), restored before the next. Shared by the N-1
    screen and the contingency ranking (studies.py); callers settle the taps for the case first."""
    tables = {"line": net.line, "trafo": net.trafo}
    for kind, eid in elements:
        table = tables[kind]
        table.at[eid, "in_service"] = False
        try:
            res = _run_case(net, case, load_scale, rating_ratio, regulate=False)
        finally:
            table.at[eid, "in_service"] = True
        name = str(table.at[eid, "name"] or f"{kind} {eid}")
        lost, island = _islanded_mw(net, res["vm"]) if res is not None else (0.0, [])
        yield OutageResult(kind, eid, name, res, lost, island)


def n1_screen(net, case: str = "winter_peak", rating_ratio: pd.Series | None = None) -> dict:
    """Single-outage screen of the EHV backbone: take each in-service line and transformer at or
    above N1_MIN_KV out of service in turn, solve the study case, and report any thermal, voltage or
    islanding violation. Informational (not a connection gate); roughly P2/8 security of supply.
    `rating_ratio` overrides the case's line ratings (a maintenance window's season, maintenance.py)."""
    cases = {c: (ls, rr) for c, ls, rr in _study_cases(net)}
    if case not in cases:
        case = "winter_peak"
    load_scale, case_ratio = cases[case]
    rating_ratio = case_ratio if rating_ratio is None else rating_ratio
    # the pre-fault state is the intact network with its taps regulated for THIS case. feasibility()
    # leaves them as the last study case (summer minimum) settled them, which would make every winter
    # outage look like a voltage breach, so settle them for the screened case first; each outage then
    # runs with those taps frozen (outage_results).
    _run_case(net, case, load_scale, rating_ratio, regulate=True)
    elements = n1_elements(net)
    violations: list[dict] = []
    for o in outage_results(net, case, load_scale, rating_ratio, elements):
        head = {"outage_type": o.kind, "outage_id": o.eid, "outage_name": o.name}
        if o.res is None:
            violations.append({**head, "type": "non_convergent", "element_id": None, "value": None,
                               "message": f"power flow does not converge with {o.kind} {o.eid} out"})
            continue
        # demand stranded on an island: a supply violation only if it is material (a generator
        # spur or a tee-point with no customers is not)
        if o.lost_mw >= N1_ISLAND_MIN_MW:
            violations.append({**head, "type": "islanded", "element_id": o.island[0], "value": round(o.lost_mw, 2),
                               "islanded_bus_ids": o.island,  # demand.py attributes it to regions
                               "message": f"{o.kind} {o.eid} out islands {o.lost_mw:.1f} MW of demand at {len(o.island)} bus(es)"})
            continue
        r = _case_reason(net, case, o.res["vm"], o.res["line_pct"], o.res["trafo_pct"])
        if r is not None:
            violations.append({**head, "type": r.type, "element_id": r.element_id, "value": r.value, "message": r.message})
    # the screen leaves res_* from its last outage; callers re-solve for the intact state
    return {"case": case, "screened": len(elements), "violations": violations}


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
    """An existing generator out of service (a derate halves its output). Returns an undo."""
    if "fleet_id" not in net.sgen.columns:
        return None
    idx = net.sgen.index[net.sgen["fleet_id"] == o.element_id]
    if not len(idx):
        return None
    col = "p_rated_mw" if o.kind == "derate" else "in_service"
    before = net.sgen.loc[idx, col].copy()
    net.sgen.loc[idx, col] = before * OUTAGE_DERATE_FACTOR if o.kind == "derate" else False
    return lambda: net.sgen.loc.__setitem__((idx, col), before)


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
