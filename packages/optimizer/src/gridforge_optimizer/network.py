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


def feasibility(net) -> tuple[bool, Reason | None, dict]:
    """Run power flow and check voltage band + line/transformer thermal limits.

    Returns (ok, reason_if_not_ok, metrics).
    """
    if not _solve(net):
        return False, Reason(type="non_convergent", message="power flow did not converge"), {}

    vm = net.res_bus["vm_pu"]
    line_pct = net.res_line["loading_percent"]
    trafo_pct = net.res_trafo["loading_percent"]
    metrics = {
        "min_vm": float(vm.min()),
        "max_vm": float(vm.max()),
        "max_line_pct": float(line_pct.max()),
        "max_trafo_pct": float(trafo_pct.max()),
    }

    if not vm.between(VOLTAGE_MIN_PU, VOLTAGE_MAX_PU).all():
        worst = (vm - 1.0).abs().idxmax()
        v = float(vm.loc[worst])
        return (
            False,
            Reason(type="voltage", element_id=int(worst), value=round(v, 4),
                   message=f"voltage {v:.3f} pu at bus {int(worst)} outside [{VOLTAGE_MIN_PU}, {VOLTAGE_MAX_PU}]"),
            metrics,
        )

    if (line_pct > LINE_LOADING_MAX_PCT).any():
        worst = line_pct.idxmax()
        v = float(line_pct.loc[worst])
        return (
            False,
            Reason(type="line", element_id=int(worst), value=round(v, 1),
                   message=f"line {int(worst)} overloaded at {v:.0f}%"),
            metrics,
        )

    if (trafo_pct > TRAFO_LOADING_MAX_PCT).any():
        worst = trafo_pct.idxmax()
        v = float(trafo_pct.loc[worst])
        return (
            False,
            Reason(type="trafo", element_id=int(worst), value=round(v, 1),
                   message=f"transformer {int(worst)} overloaded at {v:.0f}%"),
            metrics,
        )

    return True, None, metrics


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
    voltage) unchanged. No-op if the element id is unknown.
    """
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
