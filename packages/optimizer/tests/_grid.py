"""Grid-agnostic test helpers.

Tests derive their fixtures from whatever `build_base_net()` returns, so the suite passes for any
network (the NGED Bicker Fen region today, any other DNO GSP tomorrow) without hardcoding bus ids.
The idea: a "stiff" bus (top voltage, best-connected) absorbs generation; the weakest buses are where a large
connection overwhelms local capacity first.
"""

import collections

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
