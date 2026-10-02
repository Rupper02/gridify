"""pandapower helpers: build the network, grow demand, inject generation, test feasibility."""

from __future__ import annotations

import hashlib

import networkx as nx
import pandapower as pp
import pandapower.topology as top
import pandas as pd

from .config import (
    GROWTH_BETA_INDUSTRIAL,
    GROWTH_BETA_RESIDENTIAL,
    GROWTH_EDGE_TILT,
    GROWTH_HETEROGENEITY,
    GROWTH_HOTSPOT_MULT,
    GROWTH_HOTSPOT_QUANTILE,
    LINE_LOADING_MAX_PCT,
    LOAD_TYPE_RESIDENTIAL,
    TRAFO_LOADING_MAX_PCT,
    VOLTAGE_MAX_PU,
    VOLTAGE_MIN_PU,
)
from .types import Reason, Reinforcement


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
    dist = nx.multi_source_shortest_path_length(graph, sources)
    d_max = max(dist.values()) if dist else 1
    return {int(b): int(d) for b, d in dist.items()}, max(d_max, 1)


def per_bus_growth(net, m: float, scenario: str, horizon: int) -> pd.Series:
    """Per-load growth factors whose load-weighted mean equals the scenario multiplier `m`.

    Shapes demand growth by load type (residential vs industrial), a seeded per-bus
    heterogeneity, distance to the feeder edge, and ~20% adoption hotspots -- so the
    feeder TOTAL grows by exactly `m` while individual buses diverge realistically.
    Fully deterministic in (scenario, horizon, network structure).
    """
    load = net.load
    try:
        hops, d_max = _feeder_hops(net)
    except Exception:
        hops, d_max = {}, 1

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


# --- generation + feasibility ----------------------------------------------
def inject_sgen(
    net, bus: int, p_mw: float, name: str = "", tech: str | None = None, q_mvar: float = 0.0
) -> int:
    """Add a static generator (PQ) — DER does not regulate voltage, so violations surface.

    `q_mvar` defaults to 0 (unity power factor); a negative value models the DER ABSORBING
    reactive power, the cheapest lever against voltage rise from export. Returns the new sgen
    index so a trial injection can be dropped again.
    """
    if int(bus) not in net.bus.index:
        raise ValueError(f"cannot connect at bus {bus}: not in the network model")
    return int(pp.create_sgen(net, bus=int(bus), p_mw=float(p_mw), q_mvar=float(q_mvar), name=name, type=tech))


def drop_sgen(net, idx: int) -> None:
    """Remove a previously injected sgen by index (rolls back a rejected trial injection)."""
    net.sgen = net.sgen.drop(index=idx)


def _solve(net) -> bool:
    """Run the AC power flow in place; return False if it fails to converge."""
    try:
        pp.runpp(net)  # uses numba when installed (big speedup over the ~2N solves)
        return True
    except Exception:
        return False


# --- study cases ------------------------------------------------------------------------------
# A connection must be safe in BOTH planning cases a DNO studies, not just at winter peak:
#   * winter_peak — maximum (grown) demand, winter thermal ratings;
#   * summer_min  — minimum demand with summer (lower) thermal ratings, generation still at full
#     output. This is the GENERATION-critical case: little local load soaks up the export, so
#     reverse power flow, voltage rise and the GSP's export to transmission all peak here.
# The summer case needs per-load `min_scale` / per-line `summer_ratio` columns (the NGED builder
# fills them from LTDS); a network without them is studied at winter peak only.
_CASE_LABEL = {"winter_peak": "winter peak demand", "summer_min": "summer minimum demand"}


def _study_cases(net) -> list[tuple[str, pd.Series | None, pd.Series | None]]:
    """(case, load scaling to use or None = as grown, line-rating multiplier or None)."""
    cases: list[tuple[str, pd.Series | None, pd.Series | None]] = [("winter_peak", None, None)]
    has_min = "min_scale" in net.load.columns and net.load["min_scale"].notna().any()
    has_summer = "summer_ratio" in net.line.columns and net.line["summer_ratio"].notna().any()
    if has_min or has_summer:
        cases.append(("summer_min",
                      net.load["min_scale"] if has_min else None,
                      net.line["summer_ratio"] if has_summer else None))
    return cases


def _case_reason(net, case: str, vm, line_pct, trafo_pct) -> Reason | None:
    """The first limit this case breaches (voltage → line → transformer → GSP boundary)."""
    at = _CASE_LABEL[case]
    if not vm.between(VOLTAGE_MIN_PU, VOLTAGE_MAX_PU).all():
        worst = (vm - 1.0).abs().idxmax()
        v = float(vm.loc[worst])
        return Reason(type="voltage", element_id=int(worst), value=round(v, 4), case=case,
                      message=f"voltage {v:.3f} pu at bus {int(worst)} outside "
                              f"[{VOLTAGE_MIN_PU}, {VOLTAGE_MAX_PU}] at {at}")
    if (line_pct > LINE_LOADING_MAX_PCT).any():
        worst = line_pct.idxmax()
        v = float(line_pct.loc[worst])
        rating = "its summer rating" if case == "summer_min" else "its rating"
        return Reason(type="line", element_id=int(worst), value=round(v, 1), case=case,
                      message=f"line {int(worst)} overloaded at {v:.0f}% of {rating} at {at}")
    if (trafo_pct > TRAFO_LOADING_MAX_PCT).any():
        worst = trafo_pct.idxmax()
        v = float(trafo_pct.loc[worst])
        return Reason(type="trafo", element_id=int(worst), value=round(v, 1), case=case,
                      message=f"transformer {int(worst)} overloaded at {v:.0f}% at {at}")
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
    return Reason(type="gsp", value=round(export, 1), case=case,
                  message=f"{name} would export {export:.0f} MW to the transmission system at "
                          f"{_CASE_LABEL.get(case, 'peak export')} — above its {limit:.0f} MW export limit")


def feasibility(net) -> tuple[bool, Reason | None, dict]:
    """Run power flow in every study case; check the voltage band, line/transformer thermal limits
    and the GSP export boundary.

    Returns (ok, reason_if_not_ok, metrics). Afterwards net.res_line/res_trafo loading and
    net.res_bus voltage hold the worst-case ENVELOPE across cases (highest loading; the voltage
    furthest from 1.0 pu), so the per-element heat/violation helpers below report the binding case.
    """
    scaling0, imax0 = net.load["scaling"].copy(), net.line["max_i_ka"].copy()
    env_vm = env_line = env_trafo = None
    reason: Reason | None = None
    gsp_export = gsp_import = 0.0
    export_case = binding_case = None
    try:
        for case, load_scale, rating_ratio in _study_cases(net):
            if load_scale is not None:
                net.load["scaling"] = load_scale.where(load_scale.notna(), scaling0)
            if rating_ratio is not None:
                net.line["max_i_ka"] = imax0 * rating_ratio.fillna(1.0)
            ok = _solve(net)
            net.load["scaling"], net.line["max_i_ka"] = scaling0.copy(), imax0.copy()
            if not ok:
                return False, Reason(type="non_convergent", case=case,
                                     message=f"power flow did not converge at {_CASE_LABEL[case]}"), {}
            vm = net.res_bus["vm_pu"].copy()
            line_pct = net.res_line["loading_percent"].copy()
            trafo_pct = net.res_trafo["loading_percent"].copy()
            if len(net.res_ext_grid):
                p = float(net.res_ext_grid["p_mw"].sum())
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
    finally:
        net.load["scaling"], net.line["max_i_ka"] = scaling0, imax0

    if reason is None:  # local limits hold — now the boundary, at its worst export case
        reason = _gsp_reason(net, gsp_export, export_case)
        binding_case = export_case if reason is not None else None
    net.res_bus["vm_pu"], net.res_line["loading_percent"] = env_vm, env_line
    net.res_trafo["loading_percent"] = env_trafo
    metrics = {
        "min_vm": float(env_vm.min()),
        "max_vm": float(env_vm.max()),
        "max_line_pct": float(env_line.max()),
        "max_trafo_pct": float(env_trafo.max()),
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


def bus_voltages(net) -> dict[int, float]:
    """Per-bus voltage magnitude (pu) from the last solve (for the map voltage overlay)."""
    vm = net.res_bus["vm_pu"]
    return {int(i): round(float(v), 4) for i, v in vm.items()}


def voltage_violation_bus_ids(net) -> list[int]:
    """Bus ids whose voltage is outside the [min, max] band in the last solve."""
    vm = net.res_bus["vm_pu"]
    return [int(i) for i in vm[(vm < VOLTAGE_MIN_PU) | (vm > VOLTAGE_MAX_PU)].index]


# --- reinforcement (for "what would it take" suggestions) -------------------
def apply_reinforcement(net, r: Reinforcement) -> None:
    """Simulate a network reinforcement in place.

    add_parallel bumps the element's `parallel` count -> halves series impedance AND doubles its
    rating, so it relieves BOTH thermal overload and voltage. uprate raises only the thermal
    rating (`max_i_ka` for a line, `sn_mva` for a trafo) by `factor`, leaving impedance (and thus
    voltage) unchanged. kind "gsp" adds one more supergrid transformer at the GSP, raising its
    export limit by one SGT's rating (transmission works). No-op if the element id is unknown.
    """
    if r.kind == "gsp":
        if hasattr(net, "get") and net.get("gsp_export_limit_mw") is not None and net.get("gsp_sgt_mw"):
            net["gsp_export_limit_mw"] = float(net["gsp_export_limit_mw"]) + float(net["gsp_sgt_mw"])
        return
    table = net.line if r.kind == "line" else net.trafo
    if r.element_id not in table.index:
        return
    if r.action == "add_parallel":
        table.at[r.element_id, "parallel"] = int(table.at[r.element_id, "parallel"]) + 1
    elif r.kind == "line":
        table.at[r.element_id, "max_i_ka"] = float(table.at[r.element_id, "max_i_ka"]) * r.factor
    else:
        table.at[r.element_id, "sn_mva"] = float(table.at[r.element_id, "sn_mva"]) * r.factor


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
