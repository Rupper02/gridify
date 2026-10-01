"""Grid-agnostic test helpers.

Tests derive their fixtures from whatever `build_base_net()` returns, so the suite passes for any
network (mv_oberrhein, the NGED Bicker Fen region, a future DNO GSP) without hardcoding bus ids.
The idea: a "stiff" bus (top voltage, best-connected) absorbs generation; saturating the weakest
buses with capped projects overwhelms local capacity on any finite grid, forcing grid deferrals.
"""

import collections

from gridforge_optimizer import Candidate, OptimizeParams, optimize
from gridforge_optimizer.config import MAX_CONNECTION_MW
from gridforge_optimizer.network import build_base_net


def base_net():
    return build_base_net()


def _degree(net):
    d = collections.Counter()
    for _, ln in net.line.iterrows():
        d[int(ln.from_bus)] += 1
        d[int(ln.to_bus)] += 1
    return d


def stiff_bus(net):
    """Highest-voltage, best-connected bus — near the grid infeed, so it absorbs generation."""
    hv = net.bus.vn_kv.max()
    deg = _degree(net)
    return max((int(b) for b in net.bus.index if net.bus.at[b, "vn_kv"] == hv), key=lambda b: deg.get(b, 0))


def weak_buses(net, k=12):
    """The k lowest-voltage buses — local connection points where generation overwhelms soonest."""
    order = sorted((int(b) for b in net.bus.index), key=lambda b: (net.bus.at[b, "vn_kv"], b))
    return order[:k]


def invalid_bus(net):
    return int(max(int(b) for b in net.bus.index)) + 10_000


def saturating_candidates(net, n=10, mw=None):
    """`n` generation projects spread over the weakest buses, each at ~half the connection cap.

    On any finite grid the cumulative reverse flow exceeds local capacity, so some projects are
    deferred on a grid constraint (kept below the cap so they pass intake, and moderate so a low-
    voltage bus overloads a line rather than failing to converge)."""
    mw = mw if mw is not None else round(MAX_CONNECTION_MW * 0.5, 1)
    wb = weak_buses(net, n)
    return [
        Candidate(request_id=f"SAT-{i}", bus_id=wb[i % len(wb)], technology="wind",
                  rating_mw=mw, readiness_score=0.9, strategic_fit=0.8)
        for i in range(n)
    ]


def grid_deferred(queue):
    """Queue items deferred on a network constraint (line/trafo/voltage), not intake/non-convergence."""
    return [q for q in queue if q.status == "Deferred" and q.reason and q.reason.type in ("line", "trafo", "voltage")]


def optimize_saturated(net=None, params=None):
    net = net or base_net()
    return optimize(saturating_candidates(net), params or OptimizeParams())
