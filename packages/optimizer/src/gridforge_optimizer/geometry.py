"""Where buses sit on the map, grid-agnostically. A network may carry positions for some buses (a
substation join table, a CGMES GL profile, pandapower `bus.geo`): the rest are placed between their
neighbours by harmonic interpolation, so a tee-point sits on the route between real substations. A
network with no positions at all gets a deterministic synthetic layout (Kamada-Kawai), which the
model marks `crs="synthetic"` so the UI shows no basemap under it. Pure: no I/O."""

from __future__ import annotations

import hashlib
import math

import networkx as nx

SYNTHETIC_CENTER = (0.0, 0.0)  # a synthetic layout is drawn in a small box here; the UI hides the basemap
SYNTHETIC_SPAN_DEG = 0.6  # the box's width in degrees of longitude


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


def synthetic_positions(net) -> dict[int, tuple[float, float]]:
    """A deterministic layout for a network with no coordinates: Kamada-Kawai per connected
    component, components side by side, scaled into a small box around SYNTHETIC_CENTER."""
    adj = adjacency(net)
    g = nx.Graph()
    g.add_nodes_from(adj)
    g.add_edges_from((a, b) for a, nbs in adj.items() for b in nbs if a < b)
    pos: dict[int, tuple[float, float]] = {}
    offset = 0.0
    for comp in sorted(nx.connected_components(g), key=lambda c: (-len(c), min(c))):
        sub = g.subgraph(comp)
        if len(comp) == 1:
            lay = {next(iter(comp)): (0.0, 0.0)}
        else:
            lay = nx.kamada_kawai_layout(sub, pos={n: (math.cos(i), math.sin(i)) for i, n in enumerate(sorted(comp))})
        xs = [float(p[0]) for p in lay.values()]
        width = (max(xs) - min(xs)) or 1.0
        for n, p in lay.items():
            pos[int(n)] = (float(p[0]) - min(xs) + offset, float(p[1]))
        offset += width + 0.6
    xs = [p[0] for p in pos.values()] or [0.0]
    ys = [p[1] for p in pos.values()] or [0.0]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    k = SYNTHETIC_SPAN_DEG / span
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return {b: (round(SYNTHETIC_CENTER[0] + (x - cx) * k, 6), round(SYNTHETIC_CENTER[1] + (y - cy) * k, 6)) for b, (x, y) in pos.items()}
