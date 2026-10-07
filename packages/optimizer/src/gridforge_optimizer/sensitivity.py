"""First-order sensitivities on a solved case: where new MW can go before a branch binds, for every bus at once.

A DC power transfer distribution factor (PTDF) matrix says how much of one MW injected at a bus flows on each branch
(lines and transformers, taps and in-service state honoured). From the solved case's flows and the branch ratings it
gives a thermal headroom per bus in one pass: on this grid (139 buses, 172 branches) the matrix takes about 0.1 s
and predicts the AC flow shift within a few per cent, so the studies use it to **rank** buses and let the AC solve
confirm only the few that matter, instead of bisecting every bus blind.

What it is not: a verdict. It knows no voltage and no reactive power (the summer-minimum case on a weak 33 kV mesh
is voltage-bound), and a loading percentage is current-based while this is MW. Every figure it produces is labelled
first-order; nothing it says reaches a result without an AC solve behind it.
"""

from __future__ import annotations

import math

import numpy as np
from pandapower.pypower.idx_brch import PF
from pandapower.pypower.makePTDF import makePTDF


def _ratings_mva(net) -> dict[int, float]:
    """MVA rating per ppc branch row (lines first, then transformers, in table order): √3·kV·I·parallel for a line,
    sn·parallel for a transformer; the case's summer ratio applied where the net carries one on the line."""
    out: dict[int, float] = {}
    lk = net._pd2ppc_lookups["branch"]
    if "line" in lk:
        start = lk["line"][0]
        for k, lid in enumerate(net.line.index):
            kv = float(net.bus.at[int(net.line.at[lid, "from_bus"]), "vn_kv"])
            i_ka = net.line.at[lid, "max_i_ka"]
            if i_ka == i_ka and i_ka is not None:
                par = float(net.line.at[lid, "parallel"]) if "parallel" in net.line.columns else 1.0
                out[start + k] = math.sqrt(3) * kv * float(i_ka) * par
    if "trafo" in lk:
        start = lk["trafo"][0]
        for k, tid in enumerate(net.trafo.index):
            par = float(net.trafo.at[tid, "parallel"]) if "parallel" in net.trafo.columns else 1.0
            out[start + k] = float(net.trafo.at[tid, "sn_mva"]) * par
    return out


def thermal_headroom(net, buses: list[int], *, direction: str = "export", rating_ratio: dict[int, float] | None = None) -> dict[int, float]:
    """First-order MW each bus can take as new export (or as new demand, `direction="import"`) before the most
    constrained branch reaches its rating, on the case `net` was last solved for. Branches already over their rating
    give a headroom of 0. A bus the solve left islanded (no row in the reduced ppc) gets no entry. `rating_ratio`
    scales a line's rating by its pandapower index (the summer ratio of the solved case)."""
    ppc = net._ppc
    if ppc is None or "internal" not in ppc:
        return {}
    internal = ppc["internal"]
    bus, branch, base_mva = internal["bus"], internal["branch"], float(internal["baseMVA"])
    lookup = net._pd2ppc_lookups["bus"]
    slack_bus = int(net.ext_grid.bus.iloc[0]) if len(net.ext_grid) else None
    slack = int(lookup[slack_bus]) if slack_bus is not None and lookup[slack_bus] < len(bus) else None
    try:
        H = makePTDF(base_mva, bus, branch, slack=slack, result_side=0)  # from-side flows per MW injected
    except Exception:  # a singular reduction: no sensitivity rather than a wrong one
        return {}
    flows = np.real(branch[:, PF]) * base_mva  # MW on the from side at the operating point
    is_mask = internal.get("branch_is")
    full_ratings = _ratings_mva(net)
    # ppc rows kept in the reduced ppci, in order; their ratings follow them
    kept = [i for i, on in enumerate(is_mask)] if is_mask is None else [i for i, on in enumerate(is_mask) if on]
    ratings = np.array([full_ratings.get(i, np.inf) for i in kept], dtype=float)
    if rating_ratio:
        lk = net._pd2ppc_lookups["branch"].get("line")
        if lk is not None:
            for k, lid in enumerate(net.line.index):
                row = lk[0] + k
                if row in kept and lid in rating_ratio:
                    ratings[kept.index(row)] *= float(rating_ratio[lid])
    sign = 1.0 if direction == "export" else -1.0
    out: dict[int, float] = {}
    for b in buses:
        col = lookup[b] if b in lookup else None
        if col is None or col >= H.shape[1]:
            continue
        s = sign * H[:, col]
        with np.errstate(divide="ignore", invalid="ignore"):
            room = np.where(s > 0, (ratings - flows) / s, np.where(s < 0, (ratings + flows) / (-s), np.inf))
        room = np.where(np.isfinite(ratings), room, np.inf)
        h = float(np.nanmin(room)) if room.size else math.inf
        out[int(b)] = max(0.0, h) if math.isfinite(h) else math.inf
    return out


def rank_buses(net, buses: list[int], *, direction: str = "export", rating_ratio: dict[int, float] | None = None) -> list[int]:
    """`buses` ordered by first-order thermal headroom, most first; buses without a sensitivity keep their given order
    at the end. Equal headrooms keep the given order (a higher voltage level first, as the callers sort them)."""
    room = thermal_headroom(net, buses, direction=direction, rating_ratio=rating_ratio)
    known = [b for b in buses if b in room]
    known.sort(key=lambda b: -room[b])
    return known + [b for b in buses if b not in room]
