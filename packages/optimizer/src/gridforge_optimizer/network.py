"""pandapower helpers: build the network, grow demand, inject generation, test feasibility."""

from __future__ import annotations

import hashlib

import networkx as nx
import pandapower as pp
import pandapower.networks as nw
import pandapower.topology as top
import pandas as pd

from .config import (
    LINE_LOADING_MAX_PCT,
    TRAFO_LOADING_MAX_PCT,
    VOLTAGE_MAX_PU,
    VOLTAGE_MIN_PU,
)
from .types import Reason


def build_base_net():
    """A fresh mv_oberrhein network (the validated canonical grid)."""
    return nw.mv_oberrhein()


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


# residential LV networks electrify fast (EVs + heat pumps); directly-connected MV
# industrial load grows slowly. This is the FES residential-vs-industrial sector split,
# and it is already encoded in the network's load types.
_RESI_BETA = 1.0      # "MV/LV Station" -> LV residential/commercial
_INDU_BETA = 0.25     # "MV Load" -> directly-connected MV industrial
_ALPHA = 0.6          # amplitude of per-bus EV/heat-pump heterogeneity
_GAMMA = 0.3          # tilt growth toward the rural feeder edge
_HOTSPOT_CUT = 0.8    # top ~20% of buses become adoption hotspots (DFES street-clustering)
_HOTSPOT_MULT = 1.8


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
        beta = _RESI_BETA if str(row.get("type", "")) == "MV/LV Station" else _INDU_BETA
        h = _hash01(f"{scenario}:{horizon}:{bus}")
        d = hops.get(bus, d_max // 2)
        dist_term = 1.0 + _GAMMA * (d / d_max - 0.5)
        hot = _HOTSPOT_MULT if h > _HOTSPOT_CUT else 1.0
        weights[idx] = beta * (1.0 + _ALPHA * (2.0 * h - 1.0)) * dist_term * hot

    w = pd.Series(weights)
    p = load["p_mw"].reindex(w.index).astype(float)
    wbar = float((w * p).sum() / p.sum()) if float(p.sum()) > 0 else float(w.mean())
    g = m - 1.0
    return 1.0 + g * (w / wbar)


# --- generation + feasibility ----------------------------------------------
def inject_sgen(net, bus: int, p_mw: float, name: str = "", tech: str | None = None) -> int:
    """Add a static generator (PQ) — DER does not regulate voltage, so violations surface.

    Returns the new sgen index so a trial injection can be dropped again.
    """
    return int(pp.create_sgen(net, bus=int(bus), p_mw=float(p_mw), q_mvar=0.0, name=name, type=tech))


def drop_sgen(net, idx: int) -> None:
    net.sgen = net.sgen.drop(index=idx)


def _solve(net) -> bool:
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
    lp = net.res_line["loading_percent"]
    return [int(i) for i in lp[lp > LINE_LOADING_MAX_PCT].index]


def line_loadings(net) -> dict[int, float]:
    """Per-line loading_percent from the last solve (for the map heat overlay)."""
    lp = net.res_line["loading_percent"]
    return {int(i): round(float(v), 1) for i, v in lp.items()}
