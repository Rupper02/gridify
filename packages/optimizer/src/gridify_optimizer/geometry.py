"""Where buses sit on the map, grid-agnostically. A network may carry positions for some buses (a
substation join table, a CGMES GL profile, pandapower `bus.geo`): the rest are placed between their
neighbours by harmonic interpolation, so a tee-point sits on the route between real substations. Pure: no I/O."""

from __future__ import annotations

import hashlib


def h01(s: str) -> float:
    """A deterministic pseudo-random value in [0, 1) from a string (jitter and fallback spots)."""
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def adjacency(net) -> dict[int, set[int]]:
    """Bus -> neighbouring buses over lines and transformers."""
    adj: dict[int, set[int]] = {int(b): set() for b in net.bus.index}
    for a, c in list(zip(net.line.from_bus, net.line.to_bus)) + list(zip(net.trafo.hv_bus, net.trafo.lv_bus)):
        adj[int(a)].add(int(c))
        adj[int(c)].add(int(a))
    return adj


def interpolate_positions(net, fixed: dict[int, tuple[float, float]], fallback_center: tuple[float, float]) -> dict[int, tuple[float, float]]:
    """(lon, lat) per bus. Buses in `fixed` stay where they are (already jittered by the caller when
    several share a substation); every other bus is placed at the mean of its placed neighbours,
    iterated to a fixed point; a bus with no placed neighbour falls back to a deterministic spot
    near `fallback_center` so the map still renders."""
    jit = lambda b: ((h01(str(b) + "jx") - 0.5) * 0.006, (h01(str(b) + "jy") - 0.5) * 0.004)  # noqa: E731
    pos: dict[int, tuple[float, float]] = dict(fixed)
    adj = adjacency(net)
    for _ in range(200):  # harmonic interpolation: each free bus -> mean of its placed neighbours
        moved = 0.0
        for b in adj:
            if b in fixed:
                continue
            nb = [pos[n] for n in adj[b] if n in pos]
            if nb:
                new = (sum(p[0] for p in nb) / len(nb), sum(p[1] for p in nb) / len(nb))
                old = pos.get(b)
                moved = max(moved, 1.0 if old is None else abs(new[0] - old[0]) + abs(new[1] - old[1]))
                pos[b] = new
        if moved < 1e-7:
            break
    out = {}
    for b in net.bus.index:
        b = int(b)
        lon, lat = pos.get(b) or (fallback_center[0] + (h01(str(b) + "x") - 0.5) * 0.5,
                                  fallback_center[1] + (h01(str(b) + "y") - 0.5) * 0.32)
        if b not in fixed:  # keep interpolated buses from stacking exactly on each other
            dx, dy = jit(b)
            lon, lat = lon + dx * 0.5, lat + dy * 0.5
        out[b] = (round(lon, 6), round(lat, 6))
    return out
