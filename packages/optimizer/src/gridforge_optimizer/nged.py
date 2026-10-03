"""Build a real National Grid Electricity Distribution (NGED) network from open data.

Region: the Bicker Fen 132 kV GSP (Lincolnshire). Sources, bundled under data/nged/:
  * LTDS tabular model (NGED Connected Data Portal, CKAN API) — circuits, transformers (Table 2a),
    demand (Table 3), nodes, existing generation (Table 5). Rows LTDS marks "Removed" are dropped:
    the base network is what exists TODAY.
  * Embedded Capacity Register (ecr.json) — the real queue of sites accepted to connect.
  * coords.csv — substation positions from OpenStreetMap (© OpenStreetMap contributors, ODbL),
    because NGED's own location datasets are access-restricted.

This module reduces them to a solvable pandapower network (`build_nged_net`), a geolocated canonical
model for the map (`nged_model`), the registry of OPTIONAL projects (`nged_candidates`) and the GSP
boundary (`gsp_boundary`). Every entry point takes an optional `tables` argument (the raw LTDS/ECR
rows, see `LtdsTables`): the Dagster pipeline passes the bronze tables it loaded so the lineage is
real; the engine calls without it and gets the bundled snapshot. `edition` selects which LTDS
edition to build: NGED flags every row New / Updated / Unchanged / Removed against its previous
publication, so "current" drops Removed rows and "previous" drops New rows (see editions.py). Reduction: nodes joined by switches/zero-impedance connectors are
union-find merged into one bus; real circuits (R1/X1 + rating) become lines; %Z on a 100 MVA base is
converted to ohms / pandapower vk%; the 132 kV GSP busbar is the external-grid infeed, with the
supergrid transformers' published export limit enforced in the study.
"""

from __future__ import annotations

import csv
import json
import math
import re
from functools import lru_cache
from pathlib import Path

import pandapower as pp
import pandas as pd

from .config import OLTC_TAP_STEP_PERCENT

_DATA = Path(__file__).resolve().parent / "data" / "nged"
BUNDLED_DATA_DIR = _DATA  # where the pipeline's "pin" assets write a promoted edition
TABLE_NAMES = ("circuit", "t2a", "demand", "node", "gen", "ecr")
# raw rows per table, as fetched/bundled; `coords` (optional) = [{name, latitude, longitude, source}]
LtdsTables = dict[str, list[dict]]
EDITION_CURRENT = "current"  # what exists today: every row NGED has not marked Removed
EDITION_PREVIOUS = "previous"  # NGED's previous edition, reconstructed: every row not marked New
GSP_CENTER = (-0.20, 52.88)  # Bicker Fen, Lincolnshire (lon, lat) — fallback spot for unplaceable buses
# After-diversity factor on LTDS winter-peak demand: peaks don't coincide, so planners assess an
# after-diversity maximum demand. This sets a feasible present-day base; growth scenarios push it up.
DEMAND_DIVERSITY = 0.55
# Fallback thermal rating (kA) by operating voltage when LTDS leaves a circuit's rating blank.
_RATING_FALLBACK_KA = {132: 1.0, 66: 0.7, 33: 0.6, 20: 0.5, 11: 0.4}
# --- the GSP boundary: what sits above/outside this distribution network ----------------------
# Bicker Fen GSP is fed by two 400/132 kV supergrid transformers (SGTs). NGED's "Bicker Fen Td
# Limits" (Connected Data Portal, dataset asset-limits-pre-event-transmission-distribution-limits,
# resource 288e7abd-a45d-4592-b257-064d85d99d8b) gives each SGT an export limit of 263.5 MW in every
# season, and an import limit of 160.1 MW (winter) / 110.8 MW (summer). The sign convention isn't
# documented; we read "export" as distribution → transmission, as the name and this net-exporting
# region suggest. We enforce the INTACT limit (both SGTs) and report the firm (N-1) figure as context:
# beyond it, an SGT outage would force generation curtailment.
GSP_BOUNDARY = {
    "gsp_name": "Bicker Fen GSP",
    "sgt_count": 2,
    "export_limit_mw": 2 * 263.5,       # intact: both SGTs in service
    "firm_export_mw": 263.5,            # N-1: one SGT out
    "import_limit_mw": {"winter": 2 * 160.1, "summer": 2 * 110.8},
    "source": "NGED Connected Data Portal — Bicker Fen Td Limits (resource 288e7abd-a45d-4592-b257-064d85d99d8b)",
}
# Transmission-registered projects at Bicker Fen (NESO TEC + Interconnector registers, Sep 2026).
# `at` = where they connect. Ones not yet built that connect at the GSP's 132 kV ("gsp_132kv") would
# flow up through our SGTs, so — like every project that doesn't exist today — they're OPTIONAL
# registry projects (see tec_candidates), never pre-loaded. The 400 kV ones bypass this network
# entirely but compete for the same transmission capacity out of Lincolnshire: context only.
TRANSMISSION_PROJECTS = [
    {"name": "Viking Link (HVDC interconnector to Denmark)", "mw": 1500, "type": "Interconnector",
     "status": "Built", "year": 2023, "at": "400kv", "source": "NESO Interconnector Register"},
    {"name": "Triton Knoll offshore wind", "mw": 824, "type": "Offshore wind",
     "status": "Built", "year": 2022, "at": "400kv", "source": "NESO TEC Register; tritonknoll.co.uk"},
    {"name": "Bicker Fen 1 Solar", "mw": 57, "type": "Solar + storage",
     "status": "Awaiting consents", "year": 2025, "at": "400kv", "source": "NESO TEC Register"},
    {"name": "Bicker Fen 2 Solar", "mw": 57, "type": "Solar + storage",
     "status": "Awaiting consents", "year": 2026, "at": "400kv", "source": "NESO TEC Register"},
    {"name": "Heckington Fen Solar Park", "mw": 400, "type": "Solar + storage",
     "status": "Scoping", "year": 2028, "at": "400kv", "source": "NESO TEC Register"},
    {"name": "Bicker Fenn Energy Park", "mw": 600, "type": "Solar + storage",
     "status": "Scoping", "year": 2029, "at": "400kv", "source": "NESO TEC Register"},
    {"name": "Temple Oaks Renewable Energy Park", "mw": 240, "type": "Solar + storage",
     "status": "Awaiting consents", "year": 2033, "at": "gsp_132kv", "source": "NESO TEC Register (embedded, site 'Bicker Fen GSP')"},
]

# LTDS Table 5 connection statuses treated as the EXISTING fleet (baked into the base network).
# Everything not yet connected is an OPTIONAL project in the registry (see nged_candidates).
_EXISTING_STATUSES = ("Connected", "Energised")


def _load(name: str) -> list[dict]:
    p = _DATA / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def load_bundled_tables() -> LtdsTables:
    """The bundled snapshot of every raw table (the pinned edition the engine runs on)."""
    return {name: _load(name) for name in TABLE_NAMES}


def _in_edition(status, edition: str) -> bool:
    """Is a row with this LTDS Status part of the requested edition?"""
    st = str(status or "").strip().lower()
    if edition == EDITION_PREVIOUS:
        return st != "new"
    return st != "removed"


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


def _bus_degree(net) -> dict[int, int]:
    deg: dict[int, int] = {}
    for _, ln in net.line.iterrows():
        deg[int(ln.from_bus)] = deg.get(int(ln.from_bus), 0) + 1
        deg[int(ln.to_bus)] = deg.get(int(ln.to_bus), 0) + 1
    return deg


def _site_buses(net, names: tuple[str, ...], kv: float, deg: dict[int, int]) -> tuple[list[int], str]:
    """The buses to connect a named site at: every busbar of the named substation at the connection
    voltage (a double busbar runs coupled, so a site there is shared across its sections); else the
    named substation at its nearest voltage level; else the best-connected bus at that voltage.
    Substation names are matched after stripping the voltage suffix, then by shorter and shorter
    word prefixes ('Warth Lane Skegness' -> 'Warth Lane'). Returns (buses, how it was placed)."""
    by_token: dict[str, list[int]] = {}
    for b in net.bus.index:
        by_token.setdefault(_substation(net.bus.at[b, "name"]).lower(), []).append(int(b))
    levels = sorted({float(v) for v in net.bus.vn_kv})
    for name in names:
        tok = _substation(name or "").lower()
        words = tok.split()
        for k in range(len(words), 0, -1):
            cands = by_token.get(" ".join(words[:k]))
            if not cands:
                continue
            at_kv = sorted((b for b in cands if abs(float(net.bus.at[b, "vn_kv"]) - kv) < 0.5), key=lambda b: -deg.get(b, 0))
            if at_kv:
                how = f"{name} at {kv:g} kV" + (f", shared across its {len(at_kv)} busbars" if len(at_kv) > 1 else "")
                return at_kv, how
            best = min(cands, key=lambda b: (abs(float(net.bus.at[b, "vn_kv"]) - kv), -deg.get(b, 0)))
            return [best], f"{name} ({net.bus.at[best, 'vn_kv']:g} kV busbar; no {kv:g} kV busbar in the model)"
    level = min(levels, key=lambda v: abs(v - kv))
    pool = [int(b) for b in net.bus.index if float(net.bus.at[b, "vn_kv"]) == level]
    return [max(pool, key=lambda b: deg.get(b, 0))], f"best-connected {level:g} kV busbar (site not matched)"


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


def _demand_nodes(d: dict) -> list[str]:
    """A demand row can name several busbars ("GRNO8_MAIN1, GRNO8_MAIN2"): its load is split."""
    return [n.strip() for n in str(d["Node"]).split(",") if n.strip()]


def _merge_nodes(circ, t2a, dem):
    """Union-find the nodes joined by switches / zero-impedance connectors into buses.
    Returns (uf, groups root -> member nodes, node -> highest operating voltage touching it)."""
    uf = _UF()
    for c in circ:
        uf.find(c["Node 1"]); uf.find(c["Node 2"])
    for t in t2a:
        uf.find(t["Node 1"]); uf.find(t["Node 2"])
    for d in dem:
        for n in _demand_nodes(d):
            uf.find(n)
    for c in circ:
        if not _is_line(c):
            uf.union(c["Node 1"], c["Node 2"])

    # per-node voltage from the circuits/transformers touching it
    node_v: dict[str, float] = {}
    for c in circ:
        v = _num(c["Operating Voltage (kV)"])
        if v:
            for n in (c["Node 1"], c["Node 2"]):
                node_v[n] = max(node_v.get(n, 0), v)
    for t in t2a:
        for key, n in (("Operating Voltage 1", "Node 1"), ("Operating Voltage 2", "Node 2")):
            v = _num(t[key])
            if v:
                node_v[t[n]] = max(node_v.get(t[n], 0), v)

    groups: dict[str, list[str]] = {}
    for n in list(uf.p):
        groups.setdefault(uf.find(n), []).append(n)
    return uf, groups, node_v


def _add_buses(net, groups, node_v, name_by_code) -> tuple[dict[str, int], dict[int, str]]:
    """One bus per merged group of nodes. Returns (node -> bus id, bus id -> representative code)."""
    busid: dict[str, int] = {}
    bus_code: dict[int, str] = {}
    for members in groups.values():
        v = max((node_v.get(n, 0) for n in members), default=0) or 33.0
        # prefer a human-ish code: the shortest member code
        rep = min(members, key=len)
        bid = pp.create_bus(net, vn_kv=v, name=name_by_code.get(rep, rep))
        for n in members:
            busid[n] = bid
        bus_code[bid] = rep
    return busid, bus_code


def _add_lines(net, circ, gb) -> None:
    """Real circuits (R1/X1 in % on a 100 MVA base + a rating) become lines, with a summer rating."""
    summer_ratio: dict[int, float | None] = {}  # line idx -> LTDS summer / winter rating
    inter_ratio: dict[int, float | None] = {}  # line idx -> LTDS intermediate-warm / winter rating
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
        li = pp.create_line_from_parameters(
            net, a, b, length_km=length, r_ohm_per_km=r / length, x_ohm_per_km=x / length,
            c_nf_per_km=0.0, max_i_ka=imax, name=c.get("Circuit Code", ""),
        )
        w, s = _num(c["Winter"]), _num(c.get("Summer"))
        summer_ratio[int(li)] = (s / w) if (w and s and w > 0) else None
        iw = _num(c.get("Intermediate Warm"))
        inter_ratio[int(li)] = (iw / w) if (w and iw and w > 0) else None
    # summer ratings run lower (warm ambient, no wind cooling). Where LTDS leaves a circuit's
    # summer rating blank, use this network's own median summer/winter ratio rather than assume none.
    net.line["summer_ratio"] = _ratio_column(net, summer_ratio)
    # spring/autumn (LTDS "Intermediate Warm"): used only to study planned outages in those seasons
    net.line["intermediate_ratio"] = _ratio_column(net, inter_ratio)


def _ratio_column(net, ratio: dict[int, float | None]) -> list[float]:
    """Per-line rating ratios, with blanks filled by this network's own median ratio."""
    known = sorted(v for v in ratio.values() if v)
    median_ratio = known[len(known) // 2] if known else 1.0
    return [ratio.get(int(i)) or median_ratio for i in net.line.index]


def _add_transformers(net, t2a, gb) -> None:
    """Table 2a transformers: %Z on a 100 MVA base to pandapower vk%, with the HV-winding OLTC."""
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
        # on-load tap changer on the HV winding (GB practice): LTDS gives the tap range (Min/Max Tap,
        # e.g. -12..+4: negative taps = fewer HV turns = a higher LV voltage), the step is an assumption
        # (OLTC_TAP_STEP_PERCENT). network._solve regulates the taps so each LV busbar sits near
        # OLTC_SETPOINT_PU, as the real AVC relay does: 33/11 kV voltages are held, not left to drift.
        tmin, tmax = _num(t.get("Min Tap")), _num(t.get("Max Tap"))
        has_oltc = tmin is not None and tmax is not None and tmax > tmin
        pp.create_transformer_from_parameters(
            net, hv, lv, sn_mva=sn, vn_hv_kv=hv_kv, vn_lv_kv=lv_kv,
            vk_percent=vk, vkr_percent=min(abs(r1) * sn / 100.0, vk), pfe_kw=0.0, i0_percent=0.0,
            name=t.get("Vector Group", ""),
            tap_side="hv", tap_neutral=0, tap_pos=0,
            tap_min=int(tmin) if has_oltc else 0, tap_max=int(tmax) if has_oltc else 0,
            tap_step_percent=OLTC_TAP_STEP_PERCENT if has_oltc else 0.0, tap_step_degree=0.0,
            tap_changer_type="Ratio" if has_oltc else None,  # pandapower 3: taps are inert without a changer type
        )


def _demand_group(d: dict) -> str:
    """The demand group a Table 3 row describes: its primary substation, or its BSP group for a row
    at the BSP itself (Primary Substation "-")."""
    p = str(d.get("Primary Substation") or "").strip()
    return p if p and p != "-" else str(d.get("BSP Group") or d.get("Node") or "").strip()


def _is_bsp_row(d: dict) -> bool:
    return str(d.get("Primary Substation") or "").strip() in ("", "-")


def _bsp_base(bsp_group: str) -> str:
    """A BSP group's name without its transformer suffix: "Sleaford (GT1)" -> "Sleaford"."""
    return re.sub(r"\s*\(GT\d+\)\s*$", "", bsp_group or "").strip()


def _bsp_aggregates(dem) -> set[str]:
    """The BSP groups whose own Table 3 rows are aggregates of the primaries below them.

    Table 3 lists a BSP's 132/33 kV transformer group as rows of its own (BSP Group "Sleaford
    (GT1)", "Sleaford (GT2)", Primary Substation "-", on the BSP's 33 kV busbars), and every primary
    that BSP feeds as rows under BSP Group "Sleaford". The BSP rows are the group demand those
    transformers carry, split equally between them (30.78 + 30.78 MW against 66.2 MW of primary
    maxima in the bundled edition): the same customers seen one level up, not extra demand. A BSP
    row is an aggregate when primaries are listed under its base name; a BSP-level row with no
    primaries under it (a customer's own 132/33 kV connection) is real demand."""
    with_primaries = {_bsp_base(str(d.get("BSP Group") or "")) for d in dem if not _is_bsp_row(d)}
    return {str(d.get("BSP Group") or "").strip() for d in dem
            if _is_bsp_row(d) and _bsp_base(str(d.get("BSP Group") or "")) in with_primaries}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "region"


class _RegionIds:
    """Unique, stable region ids (slugs) by group name."""

    def __init__(self):
        self.ids: dict[str, str] = {}

    def __call__(self, name: str) -> str:
        if name not in self.ids:
            rid, k = _slug(name), 2
            while rid in self.ids.values():
                rid, k = f"{_slug(name)}-{k}", k + 1
            self.ids[name] = rid
        return self.ids[name]


def _pf(d: dict) -> float:
    return min(max(_num(d["Current Year Power Factor"]) or 0.95, 0.5), 1.0)


def _bsp_groups(dem, aggregates: set[str], gb, region_id) -> dict[str, dict]:
    """The parent group of each BSP whose own rows are aggregates, by base name: its firm capacity
    (MVA, read as for a primary; the smallest its rows state), its published maximum demand (the
    sum of its transformer rows) and its 33 kV busbars (where it sits on the map)."""
    out: dict[str, dict] = {}
    for d in dem:
        if str(d.get("BSP Group") or "").strip() not in aggregates:
            continue
        base = _bsp_base(str(d["BSP Group"]))
        g = out.setdefault(base, {"bsp_region_id": region_id(f"{base} BSP"), "bsp_region": f"{base} BSP",
                                  "bsp_firm_mva": None, "bsp_firm_mw": None, "published_mw": 0.0, "sites": []})
        firm_mva = float(_num(d.get("Firm Capacity of Substation")) or 0.0)
        if g["bsp_firm_mva"] is None or firm_mva < g["bsp_firm_mva"]:
            g["bsp_firm_mva"], g["bsp_firm_mw"] = firm_mva, round(firm_mva * _pf(d), 3)
        g["published_mw"] += _num(d["Current Year Max Demand"]) or 0.0
        g["sites"] += [gb(n) for n in _demand_nodes(d) if gb(n) not in g["sites"]]
    return out


_LOAD_GROUP_COLS = ("region_id", "region", "bsp", "primary", "firm_mva", "firm_mw", "peak_mw")
_LOAD_BSP_COLS = ("bsp_region_id", "bsp_region", "bsp_firm_mva", "bsp_firm_mw", "bsp_sites", "bsp_coincidence")


def _bsp_membership(dem, aggregates: set[str], parents: dict[str, dict]) -> dict[str, dict]:
    """Per BSP base name, the `bsp_*` columns its primaries' loads carry. `bsp_coincidence` =
    the BSP's published maximum / the sum of its primaries' own maxima, so the members' peaks sum
    to the BSP's own published figure today (the BSP's peak is not the sum of theirs)."""
    total = {b: 0.0 for b in parents}
    for d in dem:
        b = _bsp_base(str(d.get("BSP Group") or ""))
        if b in total and str(d.get("BSP Group") or "").strip() not in aggregates:
            total[b] += _num(d["Current Year Max Demand"]) or 0.0
    return {b: {"bsp_region_id": g["bsp_region_id"], "bsp_region": g["bsp_region"],
                "bsp_firm_mva": g["bsp_firm_mva"], "bsp_firm_mw": g["bsp_firm_mw"],
                "bsp_sites": tuple(int(x) for x in g["sites"]),
                "bsp_coincidence": g["published_mw"] / total[b] if total[b] > 0 else 1.0}
            for b, g in parents.items()}


def _add_loads(net, dem, gb) -> None:
    """LTDS Table 3 demand (after diversity), with each load's summer-minimum scaling and the demand
    groups it belongs to (demand.py's regions). LTDS Table 3 (NGED Connected Data Portal, LTDS
    dataset for Bicker Fen) publishes, per row: the BSP group, the primary substation, the current
    maximum demand (MW), its power factor and the "Firm Capacity of Substation". We read the firm
    capacity as MVA (the usual unit for a transformer group's firm rating; the table does not state
    it) and convert it to MW at the row's own power factor, so comparing it with demand in MW is the
    same as comparing apparent powers. `peak_mw` keeps the row's own maximum demand (no diversity):
    a substation's firm capacity is set against its own peak, not the GSP-coincident share.

    A BSP's own rows are aggregates of its primaries (`_bsp_aggregates`), so they add no load: the
    BSP becomes a parent group of those primaries instead (the `bsp_*` columns)."""
    aggregates = _bsp_aggregates(dem)
    region_id = _RegionIds()
    member = _bsp_membership(dem, aggregates, _bsp_groups(dem, aggregates, gb, region_id))
    min_scale: dict[int, float | None] = {}
    groups: dict[int, dict] = {}
    for d in dem:
        p = _num(d["Current Year Max Demand"])
        if not p or str(d.get("BSP Group") or "").strip() in aggregates:
            continue
        nodes_d = _demand_nodes(d)
        pf = _pf(d)
        p *= DEMAND_DIVERSITY / len(nodes_d)
        q = p * math.tan(math.acos(pf))
        # LTDS "Minimum demand Scaling Factor" = minimum demand as a share of maximum demand. Our
        # p_mw is max × DEMAND_DIVERSITY, so the summer-minimum case scales p_mw by f / diversity.
        # Held at today's level (not grown): forecast growth is winter-evening EV/heat load.
        f = _num(str(d.get("Minimum demand Scaling Factor (%)") or "").rstrip("%"))
        name = _demand_group(d)
        firm_mva = float(_num(d.get("Firm Capacity of Substation")) or 0.0)
        bsp = str(d.get("BSP Group") or "").strip()
        group = {"region_id": region_id(name), "region": name, "bsp": bsp,
                 "primary": str(d.get("Primary Substation") or "").strip(), "firm_mva": firm_mva,
                 "firm_mw": round(firm_mva * pf, 3), "peak_mw": p / DEMAND_DIVERSITY,
                 **member.get(_bsp_base(bsp), {})}
        for n in nodes_d:
            idx = pp.create_load(net, gb(n), p_mw=p, q_mvar=q, name=d.get("Primary Substation", ""))
            min_scale[int(idx)] = (f / 100.0) / DEMAND_DIVERSITY if f else None
            groups[int(idx)] = group
    net.load["min_scale"] = [min_scale.get(int(i)) for i in net.load.index]
    for col in _LOAD_GROUP_COLS + _LOAD_BSP_COLS:
        net.load[col] = pd.Series([groups.get(int(i), {}).get(col) for i in net.load.index],
                                  index=net.load.index, dtype=object)


def _add_existing_fleet(net, tables) -> list[dict]:
    """Existing/connected generation (LTDS Table 5, status Connected) IS the base network's fleet,
    sited at the substation NGED names for it (primary if given, else the bulk supply point) at
    its connection voltage, so local constraints are where they really are."""
    conn_gen = sorted(
        [g for g in tables.get("gen", [])
         if (_num(g.get("Agreed Export Capacity")) or 0) > 0
         and (g.get("Connection Status") or "").strip() in _EXISTING_STATUSES],
        key=lambda g: -(_num(g.get("Agreed Export Capacity")) or 0),
    )
    existing: list[dict] = []
    deg0 = _bus_degree(net)
    for n, g in enumerate(conn_gen):
        r = _num(g["Agreed Export Capacity"])
        primary = g.get("Primary Substation") if g.get("Primary Substation") not in (None, "-", "") else ""
        bsp = g.get("Bulk Supply Point") or ""
        kv = _num(g.get("Connection Voltage")) or 33.0
        buses, placement = _site_buses(net, (primary, bsp), kv, deg0)
        fuel = (g.get("Fuel Type") or "").strip()
        tech = _FUEL_TECH.get(fuel.lower(), "other")
        share = float(r) / len(buses)
        for k, bus in enumerate(buses):
            idx = pp.create_sgen(net, bus=int(bus), p_mw=share, q_mvar=0.0, name=f"EX-{n}" + (f"-{k}" if k else ""), type=tech)
            net.sgen.at[idx, "p_rated_mw"] = share
            net.sgen.at[idx, "import_mw"] = share
            net.sgen.at[idx, "fleet_id"] = f"EX-{3000 + n}"  # the model's generator id (planned outages)
        bus = buses[0]
        site = primary or bsp
        existing.append({"request_id": f"EX-{3000 + n}", "bus_id": int(bus), "rating_mw": r,
                         "technology": tech, "fuel": fuel, "status": "connected", "placement": placement,
                         "applicant": f"{fuel or 'Existing DER'} · {_substation(site) or 'Bicker Fen'}"})
    return existing


def _add_gsp_infeed(net) -> int:
    """The external grid at the best-connected 132 kV busbar (the GSP transmission infeed), the
    transmission boundary carried on the net, and the buses the GSP can't reach dropped.
    Returns the slack bus id."""
    deg = _bus_degree(net)
    hv = net.bus[net.bus.vn_kv >= 132].index.tolist() or [net.bus.vn_kv.idxmax()]
    slack = max(hv, key=lambda b: deg.get(b, 0))
    pp.create_ext_grid(net, slack, vm_pu=1.02, name="GSP infeed")
    # the transmission boundary, carried on the net so feasibility() can enforce it grid-agnostically
    net["gsp_name"] = GSP_BOUNDARY["gsp_name"]
    net["gsp_export_limit_mw"] = GSP_BOUNDARY["export_limit_mw"]
    net["gsp_sgt_mw"] = GSP_BOUNDARY["firm_export_mw"]  # one SGT's export limit (for "add an SGT")

    # drop any buses the GSP can't reach (isolated remnants of the switch reduction)
    import pandapower.topology as top
    from pandapower.toolbox import drop_buses
    unsupplied = [int(b) for b in top.unsupplied_buses(net) if b != slack]
    if unsupplied:
        drop_buses(net, unsupplied)
    return slack


def _build(tables: LtdsTables | None = None, edition: str = EDITION_CURRENT):
    """Construct the pandapower net + bookkeeping (node->bus map, names). Returns a dict.

    LTDS flags every row against NGED's previous edition: New / Updated / Unchanged / Removed.
    The base network is what exists TODAY, so "Removed" equipment (decommissioned, or replaced —
    e.g. a transformer swapped for a bigger one appears once as Removed and once as New) is left
    out. Planned works would sit in LTDS Table 7, which has no rows for this GSP. The "previous"
    edition keeps the Removed rows and drops the New ones instead (Updated rows carry their
    current values either way: NGED doesn't publish the old ones).

    Each step below adds one kind of element to the net, in dependency order."""
    tables = tables if tables is not None else load_bundled_tables()
    circ = [r for r in tables.get("circuit", []) if _in_edition(r.get("Circuit Status"), edition)]
    t2a = [r for r in tables.get("t2a", []) if _in_edition(r.get("Status"), edition)]
    dem = [r for r in tables.get("demand", []) if _in_edition(r.get("Status"), edition)]
    nodes = tables.get("node", [])  # names only (unreferenced codes simply go unused)
    name_by_code = {n["Code"]: n.get("Name", n["Code"]) for n in nodes}

    uf, groups, node_v = _merge_nodes(circ, t2a, dem)
    net = pp.create_empty_network(name="NGED Bicker Fen 132kV (LTDS)")
    busid, bus_code = _add_buses(net, groups, node_v, name_by_code)
    gb = lambda n: busid[uf.find(n)]

    _add_lines(net, circ, gb)
    _add_transformers(net, t2a, gb)
    _add_loads(net, dem, gb)
    existing = _add_existing_fleet(net, tables)
    slack = _add_gsp_infeed(net)

    return {"net": net, "busid": busid, "bus_code": bus_code, "uf": uf, "slack": slack,
            "name_by_code": name_by_code, "existing": existing, "edition": edition, "tables": tables}


@lru_cache(maxsize=1)
def _built_bundled():
    return _build()


_BUILT: dict[str, dict] = {}  # content-hash -> built, for tables passed in explicitly (pipeline)


def tables_hash(tables: LtdsTables) -> str:
    """A stable content fingerprint of a set of raw tables (the edition id the pipeline records)."""
    import hashlib
    blob = json.dumps({k: tables.get(k, []) for k in sorted(tables)}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _ctx(tables: LtdsTables | None = None, edition: str = EDITION_CURRENT) -> dict:
    """The built network + bookkeeping for `tables` (bundled snapshot when None), memoised."""
    if tables is None and edition == EDITION_CURRENT:
        return _built_bundled()
    key = f"{tables_hash(tables) if tables is not None else 'bundled'}:{edition}"
    if key not in _BUILT:
        if len(_BUILT) >= 6:
            _BUILT.pop(next(iter(_BUILT)))
        _BUILT[key] = _build(tables, edition)
    return _BUILT[key]


def build_nged_net(tables: LtdsTables | None = None, edition: str = EDITION_CURRENT):
    """A fresh, solvable copy of the NGED network (deep-copied so callers can mutate freely)."""
    import copy
    return copy.deepcopy(_ctx(tables, edition)["net"])


def substation_names(tables: LtdsTables | None = None) -> list[str]:
    """The distinct substation names in the built network (what the OSM geocoder matches against)."""
    net = _ctx(tables)["net"]
    return sorted({_substation(net.bus.at[b, "name"]) for b in net.bus.index})


def gsp_boundary(tables: LtdsTables | None = None) -> dict:
    """The GSP boundary for the API/UI: export/import limits, the region's export today, and the
    transmission-registered projects behind it (with which ones this study injects)."""
    from .network import feasibility
    net = build_nged_net(tables)
    _, _, m = feasibility(net)  # today: existing fleet, today's demand, both study cases
    reg = {c["applicant"].split(" · ")[-1]: c["request_id"] for c in tec_candidates(float("inf"), tables)}
    return {**GSP_BOUNDARY, "export_today_mw": m.get("gsp_export_mw", 0.0),
            "transmission_projects": [{**p, "registry_id": reg.get(p["name"])} for p in TRANSMISSION_PROJECTS]}


def _substation(name: str) -> str:
    """'Horncastle 11kV 1T0' -> 'Horncastle' (the substation, for coord/name joins)."""
    return (name or "").split(" 132")[0].split(" 66")[0].split(" 33")[0].split(" 11")[0].strip() or (name or "")


def _h01(s: str) -> float:
    import hashlib
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def load_bundled_coords() -> list[dict]:
    """The bundled OpenStreetMap join table `coords.csv` as rows {name, latitude, longitude, source}
    (maintained by the pipeline's `osm_substations_fetch` / `pin_osm_coords` assets)."""
    p = _DATA / "coords.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _coords_index(tables: LtdsTables | None) -> dict[str, tuple[float, float]]:
    """Substation-name -> (lon, lat), from `tables['coords']` when given, else the bundled csv."""
    rows = tables.get("coords") if tables is not None and tables.get("coords") is not None else load_bundled_coords()
    out: dict[str, tuple[float, float]] = {}
    for r in rows:
        try:
            out[_substation(r["name"]).lower()] = (float(r["longitude"]), float(r["latitude"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _bus_coords(net, coords: dict[str, tuple[float, float]] | None = None) -> dict[int, tuple[float, float]]:
    """(lon, lat) per bus.

    Substations found in `coords.csv` sit at their real position (buses of one substation are
    jittered a few hundred metres apart). Every other bus — mostly line tee-points like
    "Pole 90ZB1E17" — is placed at the average of its connected neighbours, iterated to a fixed
    point, so it sits on the route between real substations. A bus with no placed neighbour falls
    back to a deterministic spot near the GSP so the map still renders.
    """
    real = coords if coords is not None else _coords_index(None)
    jit = lambda b: ((_h01(str(b) + "jx") - 0.5) * 0.006, (_h01(str(b) + "jy") - 0.5) * 0.004)
    pos: dict[int, tuple[float, float]] = {}
    for b in net.bus.index:
        hit = real.get(_substation(net.bus.at[b, "name"]).lower())
        if hit:
            dx, dy = jit(int(b))
            pos[int(b)] = (hit[0] + dx, hit[1] + dy)
    fixed = set(pos)
    adj: dict[int, set[int]] = {int(b): set() for b in net.bus.index}
    for a, c in list(zip(net.line.from_bus, net.line.to_bus)) + list(zip(net.trafo.hv_bus, net.trafo.lv_bus)):
        adj[int(a)].add(int(c)); adj[int(c)].add(int(a))
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
        lon, lat = pos.get(b) or (GSP_CENTER[0] + (_h01(str(b) + "x") - 0.5) * 0.5,
                                  GSP_CENTER[1] + (_h01(str(b) + "y") - 0.5) * 0.32)
        if b not in fixed:  # keep interpolated buses from stacking exactly on each other
            dx, dy = jit(b)
            lon, lat = lon + dx * 0.5, lat + dy * 0.5
        out[b] = (round(lon, 6), round(lat, 6))
    return out


def nged_model(tables: LtdsTables | None = None, edition: str = EDITION_CURRENT) -> dict:
    """Geolocated canonical model (buses/lines/transformers/loads) with bus_id = pandapower index.

    Matches build_nged_net() exactly, so the API/map and the optimizer share one network.
    """
    ctx = _ctx(tables, edition)
    net = ctx["net"]
    xy = _bus_coords(net, _coords_index(tables))
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
                             "hv_kv": float(net.bus.at[hv, "vn_kv"]), "lv_kv": float(net.bus.at[lv, "vn_kv"]),
                             "hv_name": net.bus.at[hv, "name"],
                             "hv_lon": xy[hv][0], "hv_lat": xy[hv][1], "lv_lon": xy[lv][0], "lv_lat": xy[lv][1]})
    loads = []
    for n, i in enumerate(net.load.index):
        b = int(net.load.at[i, "bus"])
        loads.append({"load_id": n, "bus_id": b, "p_mw": round(float(net.load.at[i, "p_mw"]), 3),
                      "region_id": net.load.at[i, "region_id"], "lon": xy[b][0], "lat": xy[b][1]})
    # the existing/connected fleet (baked into the base network), for the map
    generators = []
    for g in ctx["existing"]:
        b = int(g["bus_id"])
        generators.append({"request_id": g["request_id"], "bus_id": b, "rating_mw": g["rating_mw"],
                           "technology": g["technology"], "applicant": g["applicant"],
                           "lon": xy[b][0], "lat": xy[b][1]})
    from .demand import regions_of  # the demand groups (LTDS Table 3 rows), as the engine judges them
    return {"buses": buses, "lines": lines, "transformers": transformers, "loads": loads,
            "generators": generators, "regions": regions_of(net)}


_FUEL_TECH = {"photovoltaic": "solar", "solar": "solar", "solar pv": "solar",
              "wind": "wind", "onshore wind": "wind", "offshore wind": "wind",
              "storage": "battery", "battery": "battery", "battery storage": "battery",
              "energy storage": "battery"}  # anything else (biomass, 'other generation') -> "other": firm in both cases
_STATUS_READINESS = {"accepted": 0.9, "connected": 0.95, "budget estimates provided": 0.45,
                     "quotation": 0.55, "offered": 0.7, "scoping": 0.2}


def commission_year(readiness: float, tech: str | None, rating: float | None, seed: str) -> int:
    """A deterministic requested-energisation year in [2027, 2035] — the timeline axis.

    Readiness pulls it earlier (a shovel-ready project energises soonest); wind and large schemes
    take longer to build; a per-project hash breaks ties so the years spread rather than bunch.
    This is a plausible planning heuristic, not a committed date from the developer.
    """
    r = min(max(readiness, 0.0), 1.0)
    year = 2027 + round((1.0 - r) * 4)          # 2027 (ready) .. 2031 (speculative)
    year += 1 if (tech or "").lower() == "wind" else 0
    year += (1 if rating and rating > 80 else 0) + (1 if rating and rating > 150 else 0)
    year += int(_h01(seed + "yr") * 3)          # deterministic 0/1/2 jitter, to spread the queue
    return max(2027, min(2035, year))


def nged_candidates(max_mw: float, tables: LtdsTables | None = None) -> list[dict]:
    """A connection queue from LTDS Table 5 (generation), mapped to real buses.

    Real fuel types, export capacities and connection statuses; bus matched by substation name.
    Projects over `max_mw` or without a resolvable bus are flagged needs_review (the intake path).
    """
    ctx = _ctx(tables)
    net = ctx["net"]
    # town-token -> a representative bus (prefer the lower-voltage/connection buses)
    town_bus: dict[str, int] = {}
    for b in sorted(net.bus.index, key=lambda i: net.bus.at[i, "vn_kv"]):
        town_bus.setdefault(_substation(net.bus.at[b, "name"]).lower(), int(b))
    gen = ctx["tables"].get("gen", [])
    # large generation connects at EHV/primary (33 kV+), so cluster unresolved sites there
    fallback_buses = [int(b) for b in net.bus.index if net.bus.at[b, "vn_kv"] >= 33] or [int(net.bus.index[0])]

    out = []
    for n, g in enumerate(gen):
        # Connected generation is the EXISTING fleet (baked into the base net) — not a queue project
        if (g.get("Connection Status") or "").strip() in _EXISTING_STATUSES:
            continue
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
            "grid_connection_agreement": "", "financing": "",
            "commissioning_year": commission_year(readiness, tech, rating, f"NG-{3000 + n}"),
            "strategic_fit": 0.75 if tech in ("wind", "battery") else 0.68,
            "strategic_rationale": "Clean capacity in a renewables-rich, network-constrained GSP region.",
            "status": "auto_accept" if valid else "needs_review", "review_reasons": ", ".join(reasons),
        })

    # The real connection queue: every site NGED's Embedded Capacity Register lists as ACCEPTED TO
    # CONNECT at this GSP. (LTDS Table 6 only gives aggregate interest per substation, so it isn't used.)
    ecr = ecr_candidates(max_mw, tables)
    # an LTDS Table 5 project the ECR also lists (same export MW + technology) is the same site — keep
    # the ECR record (it has a location and a target date), drop the Table 5 duplicate
    ecr_keys = {(round(c["rating_mw"], 1), c["technology"]) for c in ecr}
    out = [c for c in out if (round(c["rating_mw"] or 0, 1), c["technology"]) not in ecr_keys]
    return out + ecr + tec_candidates(max_mw, tables)


def tec_candidates(max_mw: float, tables: LtdsTables | None = None) -> list[dict]:
    """Transmission-registered projects that would connect AT THE GSP's 132 kV busbar (so their
    export flows up through our supergrid transformers) and aren't built yet — optional registry
    projects like any other. Readiness from the rubric: a TEC position is a signed connection
    agreement; "Awaiting consents" means planning has been submitted."""
    import hashlib
    from .readiness import score_from_checklist

    slack = int(_ctx(tables)["slack"])
    out = []
    for p in TRANSMISSION_PROJECTS:
        if p["at"] != "gsp_132kv" or p["status"] == "Built":
            continue
        planning = "submitted" if "consent" in p["status"].lower() else "none"
        ready = score_from_checklist({"grid_connection_agreement": "signed", "planning_status": planning,
                                      "commissioning_year": p["year"]})
        storage = "storage" in p["type"].lower()
        reasons = ["rating is out of range"] if p["mw"] > max_mw else []
        out.append({
            "request_id": "TEC-" + hashlib.sha1(p["name"].encode()).hexdigest()[:5].upper(),
            "applicant": f"{p['type']} · {p['name']}",
            "bus_id": slack, "technology": "solar" if "solar" in p["type"].lower() else "battery",
            "rating_mw": float(p["mw"]), "readiness_score": ready["readiness_score"],
            "readiness_rationale": (f"{p['source']}: transmission connection agreement for {p['mw']} MW, "
                                    f"MW-effective {p['year']}, status '{p['status']}'. Connects at the GSP's "
                                    f"132 kV busbar, so its export flows up through the supergrid transformers. "
                                    f"Land and financing aren't published, so they earn no credit."),
            "readiness_breakdown": json.dumps(ready["readiness_breakdown"]),
            "land_rights": "", "planning_status": planning, "grid_connection_agreement": "signed", "financing": "",
            "commissioning_year": p["year"],
            "strategic_fit": 0.72 if storage else 0.66,
            "strategic_rationale": ("Storage can absorb surplus at export peaks in an export-constrained GSP."
                                    if storage else "Clean capacity in a renewables-rich, export-constrained GSP region."),
            "status": "auto_accept" if not reasons else "needs_review", "review_reasons": ", ".join(reasons),
        })
    return out


# --- the NGED Embedded Capacity Register (ECR): the real queue of accepted connections -----------
ECR_MIN_EXPORT_MW = 1.0  # sub-MW sites connect at LV (0.4 kV), below this model's 11 kV floor


def _ecr_tech(row: dict) -> tuple[str | None, str]:
    """(model technology, display label) from the ECR energy sources; None = not modelled."""
    s1 = (row.get("energy_source_1") or "").lower()
    s2 = (row.get("energy_source_2") or "").lower()
    if "stor" in s1:
        return "battery", "Battery storage"
    if "solar" in s1:
        return "solar", "Solar + storage" if "stor" in s2 else "Solar PV"
    if "wind" in s1:
        return "wind", "Wind"
    return None, (row.get("energy_source_1") or "other")


def _ecr_id(row: dict) -> str:
    """The ECR publishes no reference, so derive a stable id from the site's own fields."""
    import hashlib
    key = "|".join(str(row.get(k)) for k in ("customer_site", "lat", "lon", "energy_source_1",
                                             "accepted_change_to_maximum_export_capacity(mw)", "date_accepted"))
    return "ECR-" + hashlib.sha1(key.encode()).hexdigest()[:5].upper()


def _year(date_str) -> int | None:
    """'15/12/2026' -> 2026."""
    try:
        return int(str(date_str).strip()[-4:])
    except (TypeError, ValueError):
        return None


def ecr_candidates(max_mw: float, tables: LtdsTables | None = None) -> list[dict]:
    """Registry projects from the ECR's 'Accepted to connect' sites at this GSP.

    Export capacity = the accepted change to maximum export capacity (a solar+storage hybrid may
    register more than it can export). Each site is attached to the nearest bus AT ITS CONNECTION
    VOLTAGE using its published lat/lon; sites without a location fall back to their primary
    substation, else the best-connected bus at that voltage. Readiness uses the deterministic rubric:
    an accepted offer is a signed connection agreement; land, planning and financing aren't
    published in the ECR, so they earn no credit.
    """
    from .readiness import score_from_checklist

    ctx = _ctx(tables)
    net = ctx["net"]
    xy = _bus_coords(net, _coords_index(tables))
    deg: dict[int, int] = {}
    for _, ln in net.line.iterrows():
        deg[int(ln.from_bus)] = deg.get(int(ln.from_bus), 0) + 1
        deg[int(ln.to_bus)] = deg.get(int(ln.to_bus), 0) + 1
    levels = sorted({float(v) for v in net.bus.vn_kv})

    def buses_at(kv: float) -> list[int]:
        level = min(levels, key=lambda v: abs(v - kv))
        return [int(b) for b in net.bus.index if float(net.bus.at[b, "vn_kv"]) == level]

    def nearest(cands: list[int], lon: float, lat: float) -> int:
        k = math.cos(math.radians(lat))
        return min(cands, key=lambda b: ((xy[b][0] - lon) * k) ** 2 + (xy[b][1] - lat) ** 2)

    out = []
    for row in ctx["tables"].get("ecr", []):
        if (row.get("connection_status") or "") != "Accepted to connect":
            continue
        mw = _num(row.get("accepted_change_to_maximum_export_capacity(mw)"))
        tech, label = _ecr_tech(row)
        if mw is None or mw < ECR_MIN_EXPORT_MW or tech is None:
            continue
        kv = _num(str(row.get("point_of_connection(poc)_voltage(kv)") or "").lower().replace("kv", "")) or 33.0
        pool = buses_at(kv)
        lat, lon = _num(row.get("lat")), _num(row.get("lon"))
        primary = row.get("primary") or ""
        if lat is not None and lon is not None:
            bus, where = nearest(pool, lon, lat), "nearest bus to its published location"
        else:
            named = [b for b in pool if _substation(net.bus.at[b, "name"]).lower()
                     == _substation(primary).lower()] if "not available" not in primary else []
            bus = named[0] if named else max(pool, key=lambda b: deg.get(b, 0))
            where = "its primary substation" if named else "the best-connected busbar at its voltage (location not published)"
        rid = _ecr_id(row)
        import_mw = _num(row.get("accepted_change_to_maximum_import_capacity(mw)"))
        year = _year(row.get("target_energisation_date"))
        ready = score_from_checklist({"grid_connection_agreement": "signed", "commissioning_year": year})
        site = (row.get("customer_site") or "").strip()
        site = site if site and "not available" not in site and "redacted" not in site else "Unnamed site"
        reasons = ["rating is out of range"] if mw > max_mw else []
        accepted = row.get("date_accepted") or "date not published"
        out.append({
            "request_id": rid, "applicant": f"{label} · {site[:40]}",
            "bus_id": int(bus), "technology": tech, "rating_mw": round(mw, 2),
            "import_mw": round(import_mw, 3) if import_mw is not None else None,
            "readiness_score": ready["readiness_score"],
            "readiness_rationale": (f"NGED Embedded Capacity Register: connection offer accepted ({accepted}), "
                                    f"target energisation {row.get('target_energisation_date') or 'not published'}. "
                                    f"Land, planning and financing aren't published in the ECR, so they earn no credit. "
                                    f"{int(kv) if kv >= 1 else kv} kV connection, placed at {where}."),
            "readiness_breakdown": json.dumps(ready["readiness_breakdown"]),
            "land_rights": "", "planning_status": "", "grid_connection_agreement": "signed", "financing": "",
            "commissioning_year": year,
            "strategic_fit": {"battery": 0.78, "wind": 0.72}.get(tech, 0.72 if "storage" in label.lower() else 0.66),
            "strategic_rationale": ("Storage can absorb surplus at export peaks in an export-constrained GSP."
                                    if tech == "battery" or "storage" in label.lower()
                                    else "Clean capacity in a renewables-rich, export-constrained GSP region."),
            "status": "auto_accept" if not reasons else "needs_review", "review_reasons": ", ".join(reasons),
        })
    return out

