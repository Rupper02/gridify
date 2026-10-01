"""Build a real National Grid Electricity Distribution (NGED) network from open LTDS data.

Source: NGED Connected Data Portal — Long Term Development Statement (LTDS) tabular model,
Bicker Fen 132 kV GSP region (Lincolnshire). Raw tables are bundled under data/nged/ as pulled
from the CKAN API. This module reduces them to a solvable pandapower network + a geolocated
canonical model + a connection queue, so the optimizer and the API serve a real DNO network.

Reduction: nodes joined by switches/zero-impedance connectors are union-find merged into one bus;
real circuits (with R1/X1 and a rating) become lines; Table 2a → transformers; Table 3 → loads;
the 132 kV GSP busbar is the external-grid infeed. %Z on a 100 MVA base is converted to ohms /
pandapower vk%. Coordinates come from NGED's Primary Substation Location CSV when present, else a
deterministic placeholder layout around the GSP (so the map still renders during setup).
"""

from __future__ import annotations

import csv
import json
import math
from functools import lru_cache
from pathlib import Path

import pandapower as pp

_DATA = Path(__file__).resolve().parent / "data" / "nged"
GSP_CENTER = (-0.20, 52.88)  # Bicker Fen, Lincolnshire (lon, lat) — placeholder-layout anchor
# After-diversity factor on LTDS winter-peak demand: peaks don't coincide, so planners assess an
# after-diversity maximum demand. This sets a feasible present-day base; growth scenarios push it up.
DEMAND_DIVERSITY = 0.55
# Fallback thermal rating (kA) by operating voltage when LTDS leaves a circuit's rating blank.
_RATING_FALLBACK_KA = {132: 1.0, 66: 0.7, 33: 0.6, 20: 0.5, 11: 0.4}


def _load(name: str) -> list[dict]:
    p = _DATA / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _is_line(c: dict) -> bool:
    return (
        _num(c["R1"]) is not None
        and _num(c["X1"]) is not None
        and (_num(c["X1"]) or _num(c["R1"]))
        and _num(c["Winter"]) is not None
    )


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def _build():
    """Construct the pandapower net + bookkeeping (node->bus map, names). Returns a dict."""
    circ, t2a, dem, nodes = _load("circuit"), _load("t2a"), _load("demand"), _load("node")
    name_by_code = {n["Code"]: n.get("Name", n["Code"]) for n in nodes}

    uf = _UF()
    for c in circ:
        uf.find(c["Node 1"]); uf.find(c["Node 2"])
    for t in t2a:
        uf.find(t["Node 1"]); uf.find(t["Node 2"])
    for d in dem:
        uf.find(d["Node"])
    for c in circ:
        if not _is_line(c):
            uf.union(c["Node 1"], c["Node 2"])

    # per-node voltage from the circuits/transformers touching it
    nodeV: dict[str, float] = {}
    for c in circ:
        v = _num(c["Operating Voltage (kV)"])
        if v:
            for n in (c["Node 1"], c["Node 2"]):
                nodeV[n] = max(nodeV.get(n, 0), v)
    for t in t2a:
        for key, n in (("Operating Voltage 1", "Node 1"), ("Operating Voltage 2", "Node 2")):
            v = _num(t[key])
            if v:
                nodeV[t[n]] = max(nodeV.get(t[n], 0), v)

    groups: dict[str, list[str]] = {}
    for n in list(uf.p):
        groups.setdefault(uf.find(n), []).append(n)

    net = pp.create_empty_network(name="NGED Bicker Fen 132kV (LTDS)")
    busid: dict[str, int] = {}
    bus_code: dict[int, str] = {}
    for g, members in groups.items():
        v = max((nodeV.get(n, 0) for n in members), default=0) or 33.0
        # prefer a human-ish code: the shortest member code
        rep = min(members, key=len)
        bid = pp.create_bus(net, vn_kv=v, name=name_by_code.get(rep, rep))
        for n in members:
            busid[n] = bid
        bus_code[bid] = rep

    gb = lambda n: busid[uf.find(n)]

    for c in circ:
        if not _is_line(c):
            continue
        a, b = gb(c["Node 1"]), gb(c["Node 2"])
        if a == b:
            continue
        v = _num(c["Operating Voltage (kV)"]) or net.bus.at[a, "vn_kv"]
        zbase = v * v / 100.0
        r = _num(c["R1"]) / 100.0 * zbase
        x = _num(c["X1"]) / 100.0 * zbase
        length = _num(c["Circuit Length (km)"]) or 1.0
        length = length if length > 0 else 1.0
        imax = (_num(c["Winter"]) or 0.0) / 1000.0
        if imax <= 0:  # LTDS left the rating blank -> fall back to a plausible rating for its voltage
            imax = _RATING_FALLBACK_KA.get(int(v), 0.5)
        pp.create_line_from_parameters(
            net, a, b, length_km=length, r_ohm_per_km=r / length, x_ohm_per_km=x / length,
            c_nf_per_km=0.0, max_i_ka=imax, name=c.get("Circuit Code", ""),
        )

    for t in t2a:
        sn = _num(t["Nominal Rating"])
        if not sn:
            continue
        a, b = gb(t["Node 1"]), gb(t["Node 2"])
        if a == b:
            continue
        v1, v2 = _num(t["Operating Voltage 1"]) or 0, _num(t["Operating Voltage 2"]) or 0
        hv, lv = (a, b) if v1 >= v2 else (b, a)
        hv_kv, lv_kv = max(v1, v2), min(v1, v2)
        if not (hv_kv and lv_kv):
            continue
        net.bus.at[hv, "vn_kv"], net.bus.at[lv, "vn_kv"] = hv_kv, lv_kv
        r1, x1 = _num(t["R1"]) or 0.0, _num(t["X1"]) or 1.0
        vk = min(max(abs(x1) * sn / 100.0, 0.1), 25.0)
        pp.create_transformer_from_parameters(
            net, hv, lv, sn_mva=sn, vn_hv_kv=hv_kv, vn_lv_kv=lv_kv,
            vk_percent=vk, vkr_percent=min(abs(r1) * sn / 100.0, vk), pfe_kw=0.0, i0_percent=0.0,
            name=t.get("Vector Group", ""),
        )

    load_mw: dict[int, float] = {}
    for d in dem:
        p = _num(d["Current Year Max Demand"])
        if not p:
            continue
        b = gb(d["Node"])
        pf = _num(d["Current Year Power Factor"]) or 0.95
        p *= DEMAND_DIVERSITY
        q = p * math.tan(math.acos(min(max(pf, 0.5), 1.0)))
        pp.create_load(net, b, p_mw=p, q_mvar=q, name=d.get("Primary Substation", ""))
        load_mw[b] = load_mw.get(b, 0.0) + p

    # external grid at the best-connected 132 kV busbar (the GSP transmission infeed)
    deg: dict[int, int] = {}
    for _, ln in net.line.iterrows():
        deg[ln.from_bus] = deg.get(ln.from_bus, 0) + 1
        deg[ln.to_bus] = deg.get(ln.to_bus, 0) + 1
    hv = net.bus[net.bus.vn_kv >= 132].index.tolist() or [net.bus.vn_kv.idxmax()]
    slack = max(hv, key=lambda b: deg.get(b, 0))
    pp.create_ext_grid(net, slack, vm_pu=1.02, name="GSP infeed")

    # drop any buses the GSP can't reach (isolated remnants of the switch reduction)
    import pandapower.topology as top
    from pandapower.toolbox import drop_buses
    unsupplied = [int(b) for b in top.unsupplied_buses(net) if b != slack]
    if unsupplied:
        drop_buses(net, unsupplied)

    return {"net": net, "busid": busid, "bus_code": bus_code, "uf": uf, "slack": slack,
            "name_by_code": name_by_code}


@lru_cache(maxsize=1)
def _built():
    return _build()


def build_nged_net():
    """A fresh, solvable copy of the NGED network (deep-copied so callers can mutate freely)."""
    import copy
    return copy.deepcopy(_built()["net"])


def _substation(name: str) -> str:
    """'Horncastle 11kV 1T0' -> 'Horncastle' (the substation, for coord/name joins)."""
    return (name or "").split(" 132")[0].split(" 66")[0].split(" 33")[0].split(" 11")[0].strip() or (name or "")


def _h01(s: str) -> float:
    import hashlib
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def _coords_csv() -> dict[str, tuple[float, float]]:
    """Substation-name -> (lon, lat) from NGED's Primary Substation Location CSV, if downloaded.

    Looks in the pipeline raw dir and the package data dir. Tolerant of column naming.
    """
    repo = Path(__file__).resolve().parents[4]
    for p in (repo / "apps" / "pipeline" / "data" / "raw" / "nged" / "primary_substation_location.csv",
              _DATA / "primary_substation_location.csv", _DATA / "coords.csv"):
        if not p.exists():
            continue
        out: dict[str, tuple[float, float]] = {}
        rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
        if not rows:
            continue
        cols = {k.lower(): k for k in rows[0]}
        namec = next((cols[k] for k in cols if "name" in k or "substation" in k or "site" in k), None)
        latc = next((cols[k] for k in cols if k in ("latitude", "lat") or "latitude" in k), None)
        lonc = next((cols[k] for k in cols if k in ("longitude", "lon", "long") or "longitude" in k), None)
        if not (namec and latc and lonc):
            continue
        for r in rows:
            try:
                out[_substation(r[namec]).lower()] = (float(r[lonc]), float(r[latc]))
            except (TypeError, ValueError):
                continue
        if out:
            return out
    return {}


def _bus_coords(net) -> dict[int, tuple[float, float]]:
    """(lon, lat) per bus: real NGED coords joined by substation name, else a deterministic
    placeholder layout clustered around the GSP so the map still renders before the CSV arrives."""
    real = _coords_csv()
    sub_xy: dict[str, tuple[float, float]] = {}
    for b in net.bus.index:
        sub = _substation(net.bus.at[b, "name"])
        if sub in sub_xy:
            continue
        key = sub.lower()
        if key in real:
            sub_xy[sub] = real[key]
        else:  # placeholder near Bicker Fen, deterministic by name
            sub_xy[sub] = (GSP_CENTER[0] + (_h01(sub + "x") - 0.5) * 0.5,
                           GSP_CENTER[1] + (_h01(sub + "y") - 0.5) * 0.32)
    out = {}
    for b in net.bus.index:
        sub = _substation(net.bus.at[b, "name"])
        lon, lat = sub_xy[sub]
        out[int(b)] = (round(lon + (_h01(str(b) + "jx") - 0.5) * 0.012, 6),
                       round(lat + (_h01(str(b) + "jy") - 0.5) * 0.008, 6))
    return out


def nged_model() -> dict:
    """Geolocated canonical model (buses/lines/transformers/loads) with bus_id = pandapower index.

    Matches build_nged_net() exactly, so the API/map and the optimizer share one network.
    """
    net = _built()["net"]
    xy = _bus_coords(net)
    buses = [{"bus_id": int(i), "name": net.bus.at[i, "name"], "vn_kv": float(net.bus.at[i, "vn_kv"]),
              "lon": xy[int(i)][0], "lat": xy[int(i)][1]} for i in net.bus.index]
    lines = []
    for i in net.line.index:
        f, t = int(net.line.at[i, "from_bus"]), int(net.line.at[i, "to_bus"])
        lines.append({"line_id": int(i), "line_name": net.line.at[i, "name"] or f"L{i}",
                      "rating_a": round(float(net.line.at[i, "max_i_ka"]) * 1000, 0),
                      "voltage_kv": float(net.bus.at[f, "vn_kv"]), "from_bus": f, "to_bus": t,
                      "length_km": round(float(net.line.at[i, "length_km"]), 3),
                      "from_lon": xy[f][0], "from_lat": xy[f][1], "to_lon": xy[t][0], "to_lat": xy[t][1]})
    transformers = []
    for i in net.trafo.index:
        hv, lv = int(net.trafo.at[i, "hv_bus"]), int(net.trafo.at[i, "lv_bus"])
        transformers.append({"trafo_id": int(i), "name": net.trafo.at[i, "name"] or f"T{i}",
                             "sn_mva": float(net.trafo.at[i, "sn_mva"]), "hv_bus": hv, "lv_bus": lv,
                             "hv_lon": xy[hv][0], "hv_lat": xy[hv][1], "lv_lon": xy[lv][0], "lv_lat": xy[lv][1]})
    loads = []
    for n, i in enumerate(net.load.index):
        b = int(net.load.at[i, "bus"])
        loads.append({"load_id": n, "bus_id": b, "p_mw": round(float(net.load.at[i, "p_mw"]), 3),
                      "lon": xy[b][0], "lat": xy[b][1]})
    return {"buses": buses, "lines": lines, "transformers": transformers, "loads": loads}


_FUEL_TECH = {"photovoltaic": "solar", "solar": "solar", "wind": "wind", "onshore wind": "wind",
              "storage": "battery", "battery": "battery", "energy storage": "battery"}
_STATUS_READINESS = {"accepted": 0.9, "connected": 0.95, "budget estimates provided": 0.45,
                     "quotation": 0.55, "offered": 0.7, "scoping": 0.2}


def nged_candidates(max_mw: float) -> list[dict]:
    """A connection queue from LTDS Table 5 (generation), mapped to real buses.

    Real fuel types, export capacities and connection statuses; bus matched by substation name.
    Projects over `max_mw` or without a resolvable bus are flagged needs_review (the intake path).
    """
    net = _built()["net"]
    # town-token -> a representative bus (prefer the lower-voltage/connection buses)
    town_bus: dict[str, int] = {}
    for b in sorted(net.bus.index, key=lambda i: net.bus.at[i, "vn_kv"]):
        town_bus.setdefault(_substation(net.bus.at[b, "name"]).lower(), int(b))
    gen = _load("gen")
    # large generation connects at EHV/primary (33 kV+), so cluster unresolved sites there
    fallback_buses = [int(b) for b in net.bus.index if net.bus.at[b, "vn_kv"] >= 33] or [int(net.bus.index[0])]

    def _bus_for(site: str, i: int) -> int:
        b = town_bus.get(_substation(site or "").lower())
        return b if b is not None else fallback_buses[i % len(fallback_buses)]

    out = []
    for n, g in enumerate(gen):
        rating = _num(g.get("Agreed Export Capacity"))
        site = (g.get("Primary Substation") if g.get("Primary Substation") not in (None, "-", "")
                else g.get("Bulk Supply Point")) or ""
        token = _substation(site).lower()
        bus = town_bus.get(token)
        if bus is None:
            bus = fallback_buses[n % len(fallback_buses)]
        fuel = (g.get("Fuel Type") or "").strip()
        tech = _FUEL_TECH.get(fuel.lower(), "solar")
        status_raw = (g.get("Connection Status") or "").strip().lower()
        readiness = _STATUS_READINESS.get(status_raw, 0.5)
        reasons = []
        if rating is None or rating <= 0:
            reasons.append("missing rating")
        elif rating > max_mw:
            reasons.append("rating is out of range")
        valid = not reasons
        out.append({
            "request_id": f"NG-{3000 + n}", "applicant": f"{fuel or 'DER'} · {site or 'Bicker Fen'}",
            "bus_id": int(bus), "technology": tech, "rating_mw": rating,
            "readiness_score": round(readiness, 2),
            "readiness_rationale": f"LTDS Table 5 connection status: {g.get('Connection Status') or 'unknown'}.",
            "readiness_breakdown": "", "land_rights": "", "planning_status": "",
            "grid_connection_agreement": "", "financing": "", "commissioning_year": None,
            "strategic_fit": 0.75 if tech in ("wind", "battery") else 0.68, "strategic_confidence": None,
            "strategic_rationale": "Clean capacity in a renewables-rich, network-constrained GSP region.",
            "status": "auto_accept" if valid else "needs_review", "review_reasons": ", ".join(reasons),
        })

    # Table 6: the pending connection-interest queue (larger, speculative) — this is what
    # actually stresses a weak GSP. Split each aggregated record into per-project candidates.
    idx = 0
    for row in _load("conn"):
        cap = _num(row.get("Total Generation Capacity (MW)"))
        if not cap or cap <= 0:
            continue
        count = min(max(int(_num(row.get("Total Generation Number")) or 1), 1), 4)
        per = round(cap / count, 1)
        site = next((row.get(k) for k in ("Primary Substation", "Bulk Supply Point", "Grid Supply Point")
                     if row.get(k) not in (None, "-", "")), "")
        status_raw = (row.get("Connection Status") or "").strip().lower()
        readiness = _STATUS_READINESS.get(status_raw, 0.4)
        for _k in range(count):
            bus = _bus_for(site, idx)
            tech = ("solar", "wind", "battery")[idx % 3]
            reasons = [] if (0 < per <= max_mw) else (["rating is out of range"] if per > max_mw else ["missing rating"])
            out.append({
                "request_id": f"NG-32{idx:02d}", "applicant": f"Queued {tech} · {_substation(site) or 'Bicker Fen'}",
                "bus_id": int(bus), "technology": tech, "rating_mw": per, "readiness_score": round(readiness, 2),
                "readiness_rationale": f"LTDS Table 6 interest; connection status: {row.get('Connection Status') or 'unknown'}.",
                "readiness_breakdown": "", "land_rights": "", "planning_status": "",
                "grid_connection_agreement": "", "financing": "", "commissioning_year": None,
                "strategic_fit": 0.72 if tech in ("wind", "battery") else 0.66, "strategic_confidence": None,
                "strategic_rationale": "Speculative queue capacity in a constrained GSP region.",
                "status": "auto_accept" if not reasons else "needs_review", "review_reasons": ", ".join(reasons),
            })
            idx += 1
    return out


if __name__ == "__main__":  # diagnostics
    import pandapower.topology as top
    b = _built()
    net = b["net"]
    print(f"buses={len(net.bus)} lines={len(net.line)} trafos={len(net.trafo)} loads={len(net.load)}")
    print("total demand MW:", round(net.load.p_mw.sum(), 1))
    print("unsupplied:", len(top.unsupplied_buses(net)))
    pp.runpp(net, max_iteration=50, init="flat")
    vm = net.res_bus.vm_pu
    print(f"CONVERGED vm {vm.min():.3f}-{vm.max():.3f}; max line {net.res_line.loading_percent.max():.0f}%; "
          f"max trafo {net.res_trafo.loading_percent.max():.0f}%")
    lowest = vm.nsmallest(5)
    print("lowest buses:", [(int(i), round(v, 3), net.bus.at[i, 'vn_kv'], net.bus.at[i, 'name']) for i, v in lowest.items()])
    wl = net.res_line.loading_percent.nlargest(3)
    print("worst lines:", [(int(i), round(v, 0)) for i, v in wl.items()])
    wt = net.res_trafo.loading_percent.nlargest(3)
    print("worst trafos:", [(int(i), round(v, 0), net.trafo.at[i, 'sn_mva']) for i, v in wt.items()])
