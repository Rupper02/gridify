"""Build a real National Grid Electricity Distribution (NGED) network from open data.

Region: one NGED Grid Supply Point at a time; what belongs to it (where its data is filed, its published peak and
limits, its named exceptions) is its `nged_points.SupplyPoint` record, Bicker Fen's by default (the 132 kV GSP in
Lincolnshire). Sources, bundled under data/nged/ for Bicker Fen:
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

from .cim import CgmesMeta
from .config import (
    DFES_BASE_YEAR,
    FORECASTS,
    GSP_INFEED_VM_PU,
    LTDS_FORECAST_FIRST_YEAR,
    CONNECTOR_MAX_X_PCT,
    EHV_MIN_KV,
    OLTC_DEADBAND_PU,
    OLTC_SETPOINT_PU,
    OLTC_TAP_STEP_PERCENT,
    PLAN_END_YEAR,
    PLAN_START_YEAR,
    PLAN_YEARS,
)
from .geometry import h01 as _h01
from .geometry import interpolate_positions
from .gridmodel import model_from_net
from .nged_points import BICKER_FEN, SupplyPoint
from .types import ModelAssumption

_DATA = Path(__file__).resolve().parent / "data" / "nged"
BUNDLED_DATA_DIR = _DATA  # where the pipeline's "pin" assets write a promoted edition
TABLE_NAMES = ("circuit", "t2a", "demand", "node", "gen", "ecr", "fault", "dfes")
# raw rows per table, as fetched/bundled; `coords` (optional) = [{name, latitude, longitude, source}]
LtdsTables = dict[str, list[dict]]
EDITION_CURRENT = "current"  # what exists today: every row NGED has not marked Removed
EDITION_PREVIOUS = "previous"  # NGED's previous edition, reconstructed: every row not marked New
# Fallback thermal rating (kA) by operating voltage when LTDS leaves a circuit's rating blank.
_RATING_FALLBACK_KA = {132: 1.0, 66: 0.7, 33: 0.6, 20: 0.5, 11: 0.4}
# NGED Connected Data Portal resources the pipeline's `pin_nged_published` fetches into the bundled snapshot
LTDS_FAULT_RESOURCE_ID = "3bd0243c-71dd-4cdd-9ca9-57e6eb79d61f"  # LTDS Table 4 Fault Level (system impedance, make/break currents and ratings per node)
DFES_POWER_RESOURCE_ID = "7686c0a8-bde8-4a4b-8f26-50a3317882ee"  # DFES 2025 Power Projections: winter peak MW per Electricity Supply Area, scenario, year
DFES_SOURCE = "NGED Distribution Future Energy Scenarios 2025, winter-peak power projections per Electricity Supply Area (Connected Data Portal)"
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




def live_demand_rows(rows, edition: str = EDITION_CURRENT, point: SupplyPoint = BICKER_FEN) -> list[dict]:
    """The LTDS Table 3 rows of an edition: its own Status rule, plus the supply point's rows Removed in error."""
    return [r for r in rows if _in_edition(r.get("Status"), edition) or str(r.get("Node") or "").strip() in point.removed_in_error]


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
    voltage (the ECR names the substation, not the bar, so a site there is shared across its sections;
    whether the sections are coupled is the LTDS's connectivity, see _assume_structure); else the
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
    net.bus["substation"] = [_substation(str(nm)) for nm in net.bus["name"]]  # the site a busbar belongs to (the CIM export groups by it)
    return busid, bus_code


_PF_DEFAULT = 0.95  # LTDS left a demand group's power factor blank: lagging, assumed (registered: pf_default)

# what the builder had to assume, by key: one record per kind of fallback, with the elements it touched.
# Stated, never hidden: the planner lists them and the Sources register cites each.
_ASSUMPTION_TEXT = {
    "rating_fallback": "LTDS left the winter rating blank: a conservative typical rating for the voltage was used (nged._RATING_FALLBACK_KA)",
    "firm_capacity_unpublished": "LTDS Table 3 gives no firm capacity for this substation: nothing is assumed in its place",
    "length_default": "LTDS gave no usable circuit length: 1 km assumed (impedance comes from %Z, so only the per-km split changes)",
    "summer_ratio_median": "LTDS left the summer rating blank: this network's median summer/winter ratio was used",
    "intermediate_cool_ratio_median": "LTDS left the Intermediate Cool rating blank: this network's median ratio to winter was used",
    "intermediate_warm_ratio_median": "LTDS left the Intermediate Warm rating blank: this network's median ratio to winter was used",
    "tap_step_assumed": f"LTDS gives the tap range but not the step: {OLTC_TAP_STEP_PERCENT:g}% per tap assumed, regulated towards {OLTC_SETPOINT_PU:g} pu (config.OLTC_*)",
    "no_oltc": "No tap range published: modelled as a fixed-tap transformer",
    "pf_default": f"LTDS left the power factor blank: {_PF_DEFAULT:g} lagging assumed (nged._pf)",
    "forecast_ltds_only": f"No DFES supply area matches this connection: its LTDS five-year maximum-demand forecast applies (Forecast Year 1 = {LTDS_FORECAST_FIRST_YEAR}), then holds",
    "charging_blank": "LTDS gave no susceptance (B1) for this circuit: modelled without line charging",
    "bus_sections_split": "EHV busbars of one substation are separate LTDS nodes with no coupler or section circuit between them: the model runs them split, so after a fault a circuit on one bar is not picked up by its pair through the substation (NGED publishes the connectivity, not the running arrangement)",
    "small_embedded": "Connected ECR sites under 1 MW (most at 0.4 kV) are aggregated per primary and technology at its 11 kV busbar (the "
                      "model's lowest level), so voltage rise inside the LV network behind it is not modelled; they are added, not netted, "
                      "because the LTDS minimum demand behaves as gross of generation (no negative minimum in 2,294 rows, ~33-36% even "
                      "where generation is twice a primary's peak). Domestic rooftop PV is in no register (the ECR and LTDS Table 5 list "
                      "connections that applied to NGED) and is not modelled",
    "small_embedded_unmodelled": "Connected ECR sites under 1 MW that publish no export capacity or no technology are not modelled",
    "removed_in_error": "LTDS Table 3 marks this demand row Removed, but NGED's other data shows the substation is live: kept "
                        "(the supply point's `removed_in_error` gives the evidence)",
    "unreachable_demand": "Demand on buses the GSP infeed cannot reach in the LTDS connectivity: removed with them, not rescaled "
                          "onto the rest (the coincidence scaling was applied before)",
    "unreachable_generation": "Generation on buses the GSP infeed cannot reach in the LTDS connectivity: removed with them",
    "possible_bsp_aggregate": "Possible aggregate counted as demand, check: rows with no primary place more demand on a "
                              "substation's own bars than half the primaries Table 3 files under its name (nothing is changed)",
    "normally_open": "A circuit run open: the supply point's named normally-open point, inferred from NGED's half-hourly "
                     "flows (the LTDS publishes connectivity, not the running arrangement)",
    "connector": "An LTDS circuit row with zero resistance, negligible reactance and no rating: a connector between two named "
                 "nodes (a closed bus-bus switch; the row is kept, out of service, so no element id moves)",
    "mv_mesh_closed":"33 kV circuits that close a loop: LTDS publishes no normal-open points, so the 33 kV network runs as a closed mesh in parallel with the 132 kV and shares its flows",
}


def _assume(net, key: str, element_kind: str, element_id: int) -> None:
    """Record one element the assumption `key` applies to (net["assumptions"], a ModelAssumption per key)."""
    rec = net["assumptions"].setdefault(
        key, {"key": key, "message": _ASSUMPTION_TEXT[key], "source": "engine-default", "element_kind": element_kind, "element_ids": []})
    rec["element_ids"].append(int(element_id))


# LTDS circuit rating columns besides Winter -> (the net.line ratio column, the assumption key for a blank)
_SEASON_RATIOS = {
    "summer_ratio": ("Summer", "summer_ratio_median"),
    "intermediate_cool_ratio": ("Intermediate Cool", "intermediate_cool_ratio_median"),
    "intermediate_warm_ratio": ("Intermediate Warm", "intermediate_warm_ratio_median"),
}


def _is_connector(c: dict) -> bool:
    """A circuit row that is a connector between two named nodes: zero resistance, reactance at or below
    CONNECTOR_MAX_X_PCT, no rating (NGED's "L0" rows). Rows at exactly zero impedance are not lines at all (`_is_line`)."""
    r, x, w = _num(c["R1"]), _num(c["X1"]), _num(c["Winter"])
    return r == 0 and x is not None and 0 < x <= CONNECTOR_MAX_X_PCT and not (w and w > 0)


def _add_lines(net, circ, gb) -> None:
    """Real circuits (R1/X1 in % on a 100 MVA base + a rating) become lines, with their other seasons' ratings as ratios
    of the winter one (`_SEASON_RATIOS`). A connector row (`_is_connector`) keeps its place in the line table, out of
    service (`connector`), and a closed bus-bus switch joins its two buses: no figure is invented for it and no element id
    moves (README register "A connector published as a circuit")."""
    connector: dict[int, bool] = {}
    ratios: dict[str, dict[int, float | None]] = {col: {} for col in _SEASON_RATIOS}  # column -> line idx -> season / winter
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
        given_length = _num(c["Circuit Length (km)"])
        length = given_length if given_length and given_length > 0 else 1.0
        imax = (_num(c["Winter"]) or 0.0) / 1000.0
        rating_blank = imax <= 0
        if rating_blank:  # LTDS left the rating blank -> fall back to a plausible rating for its voltage
            imax = _RATING_FALLBACK_KA.get(int(v), 0.5)
        # line charging: LTDS B1 is the circuit's positive-sequence susceptance in % on the 100 MVA base, so
        # B (S) = B1 / V_kV² and C = B / (2 pi f) for the whole circuit; pandapower wants nF per km
        b1 = _num(c.get("B1"))
        c_nf = (b1 / (v * v)) / (2 * math.pi * 50.0) * 1e9 / length if b1 and b1 > 0 else 0.0
        li = pp.create_line_from_parameters(
            net, a, b, length_km=length, r_ohm_per_km=r / length, x_ohm_per_km=x / length,
            c_nf_per_km=c_nf, max_i_ka=imax, name=c.get("Circuit Code", ""),
        )
        if _is_connector(c):
            net.line.at[li, "in_service"] = False
            pp.create_switch(net, a, b, et="b", closed=True, name=f"connector {c['Node 1']}-{c['Node 2']}")
            connector[int(li)] = True
            _assume(net, "connector", "line", int(li))
            continue
        if rating_blank:
            _assume(net, "rating_fallback", "line", int(li))
        if c_nf == 0.0:
            _assume(net, "charging_blank", "line", int(li))
        if length != given_length:
            _assume(net, "length_default", "line", int(li))
        w = _num(c["Winter"])
        for col, (field, _) in _SEASON_RATIOS.items():
            s = _num(c.get(field))
            ratios[col][int(li)] = (s / w) if (w and s and w > 0) else None
    # the warmer seasons' ratings run lower (warm ambient, less wind cooling). Where LTDS leaves one blank, use this
    # network's own median ratio for that season rather than assume none.
    for col, (_, key) in _SEASON_RATIOS.items():
        net.line[col] = _ratio_column(net, ratios[col], key)
    net.line["connector"] = [connector.get(int(i), False) for i in net.line.index]


def _ratio_column(net, ratio: dict[int, float | None], key: str) -> list[float]:
    """Per-line rating ratios, with blanks filled by this network's own median ratio (recorded as `key`)."""
    known = sorted(v for v in ratio.values() if v)
    median_ratio = known[len(known) // 2] if known else 1.0
    out = []
    for i in net.line.index:
        if ratio.get(int(i)):
            out.append(ratio[int(i)])
        else:
            _assume(net, key, "line", int(i))
            out.append(median_ratio)
    return out


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
        vk = min(max(math.hypot(r1, x1) * sn / 100.0, 0.1), 25.0)  # the impedance's magnitude, on the unit's rating
        # on-load tap changer on the HV winding (GB practice): LTDS gives the tap range (Min/Max Tap,
        # e.g. -12..+4: negative taps = fewer HV turns = a higher LV voltage), the step is an assumption
        # (OLTC_TAP_STEP_PERCENT). network._solve regulates the taps so each LV busbar sits near
        # OLTC_SETPOINT_PU, as the real AVC relay does: 33/11 kV voltages are held, not left to drift.
        tmin, tmax = _num(t.get("Min Tap")), _num(t.get("Max Tap"))
        has_oltc = tmin is not None and tmax is not None and tmax > tmin
        ti = pp.create_transformer_from_parameters(
            net, hv, lv, sn_mva=sn, vn_hv_kv=hv_kv, vn_lv_kv=lv_kv,
            vk_percent=vk, vkr_percent=min(abs(r1) * sn / 100.0, vk), pfe_kw=0.0, i0_percent=0.0,
            name=t.get("Vector Group", ""),
            tap_side="hv", tap_neutral=0, tap_pos=0,
            tap_min=int(tmin) if has_oltc else 0, tap_max=int(tmax) if has_oltc else 0,
            tap_step_percent=OLTC_TAP_STEP_PERCENT if has_oltc else 0.0, tap_step_degree=0.0,
            tap_changer_type="Ratio" if has_oltc else None,  # pandapower 3: taps are inert without a changer type
        )
        _assume(net, "tap_step_assumed" if has_oltc else "no_oltc", "trafo", int(ti))


def _open_points(net, point: SupplyPoint, gb) -> None:
    """The supply point's named normally-open circuits (`SupplyPoint.normally_open`), out of service: the LTDS publishes
    connectivity, not the running arrangement, so each is an exception with its evidence. A name that is not a circuit of
    this network stops the build."""
    for (a, b), _why in point.normally_open.items():
        x, y = gb(a), gb(b)
        hit = net.line[((net.line.from_bus == x) & (net.line.to_bus == y)) | ((net.line.from_bus == y) & (net.line.to_bus == x))]
        if len(hit) != 1:
            raise ValueError(f"{point.gsp_name}: normally-open circuit {a}-{b} matches {len(hit)} lines, not one")
        net.line.at[hit.index[0], "in_service"] = False
        _assume(net, "normally_open", "line", int(hit.index[0]))


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


def _aliased(d: dict, aliases: dict) -> dict:
    """A Table 3 row with its BSP group renamed per the supply point's `bsp_aliases` (a group Table 3 files a BSP's own
    rows under, though its primaries use another name), keeping any "(GTn)" suffix."""
    g = str(d.get("BSP Group") or "")
    base = _bsp_base(g)
    if base not in aliases:
        return d
    return {**d, "BSP Group": g.replace(base, aliases[base], 1)}


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
    return min(max(_num(d["Current Year Power Factor"]) or _PF_DEFAULT, 0.5), 1.0)


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


def _coincidence(dem, aggregates: set[str], member: dict[str, dict], gsp_peak_mw: float) -> tuple[dict[str, float], float]:
    """How much of each row's own maximum demand is on at the GSP's winter peak.

    Two published figures, no assumed factor: a BSP's own maximum (its rows in Table 3) over its
    primaries' maxima gives their coincidence at the BSP (`bsp_coincidence`, by BSP base name; 1 for
    a row with no BSP group), and NESO's GSP peak (`gsp_peak_mw`, `SupplyPoint.require_peak`) over the BSP-coincident total
    gives the coincidence of everything at the GSP. Returns (per-BSP factor, GSP factor).

    A coincidence cannot exceed 1 (the maxima cannot sum to less than the peak they reach together): above it the build
    stops with the figures (README register "A coincidence factor above 1 stops the build")."""
    bsp = {b: m["bsp_coincidence"] for b, m in member.items()}
    for b, f in bsp.items():
        if f > 1 + COINCIDENCE_TOLERANCE:
            raise ValueError(f"BSP {b}: its published maximum is {f:.3f} times the sum of its primaries' maxima (a coincidence "
                             f"above 1): its figure does not describe the primaries filed under it, or demand is missing")
    total = sum((_num(d["Current Year Max Demand"]) or 0.0) * bsp.get(_bsp_base(str(d.get("BSP Group") or "")), 1.0)
                for d in dem if str(d.get("BSP Group") or "").strip() not in aggregates)
    at_gsp = gsp_peak_mw / total if total > 0 else 1.0
    if at_gsp > 1 + COINCIDENCE_TOLERANCE:
        raise ValueError(f"supply-point peak {gsp_peak_mw:.3f} MW (SupplyPoint.peak_demand_mw) against {total:.2f} MW of its "
                         f"rows' BSP-coincident maxima: a factor of {at_gsp:.3f}, above 1. The peak figure does not describe "
                         f"this group, or demand is missing from its tables")
    return bsp, at_gsp


COINCIDENCE_TOLERANCE = 1e-6  # rounding only


_ESA_SUFFIX = re.compile(r"\s*(33\s*)?11\s*KV\s*S\s*STN\s*$", re.I)  # "SLEAFORD 11kV S STN", "HORNCASTLE 33 11kV S STN"


def _norm_name(s: str) -> str:
    """A name compared on letters and digits only, with the word RD read as ROAD (the DFES abbreviates it)."""
    s = re.sub(r"\bRD\b", "ROAD", (s or "").upper().replace("ST.", "ST"))
    return re.sub(r"[^A-Z0-9]", "", s)


def dfes_search_term(primary: str) -> str:
    """What to search the DFES portal for to find a primary's supply area: its first alphanumeric token ("Carlton-on-Trent"
    -> "Carlton"; the portal's search finds nothing for the hyphenated word)."""
    tokens = re.findall(r"[A-Za-z0-9]+", primary or "")
    return tokens[0] if tokens else ""


def dfes_esa(primary: str, esas) -> str | None:
    """The DFES Electricity Supply Area a Table 3 primary belongs to: the ESA whose name, less its "33 11kV S STN"
    suffix, equals the primary's (less a "(T1)" or trailing-voltage suffix), else the one that starts with it when
    that is unique. None for a connection with no supply area (a customer site, a BSP aggregate)."""
    base = re.sub(r"\s+\d+$", "", re.sub(r"\s*\([^)]*\)", "", primary or "").strip())
    key = _norm_name(base)
    if not key:
        return None
    names = {e: _norm_name(_ESA_SUFFIX.sub("", e)) for e in esas}
    exact = [e for e, n in names.items() if n == key]
    if exact:
        return exact[0]
    starts = [e for e, n in names.items() if n.startswith(key)]
    return starts[0] if len(starts) == 1 else None


def _dfes_index(rows) -> dict[str, dict[str, dict[int, float]]]:
    """DFES power projections as {ESA: {scenario: {year: MW}}}, winter season only (the peak the LTDS maximum is)."""
    out: dict[str, dict[str, dict[int, float]]] = {}
    for r in rows:
        if str(r.get("season", "Winter")).lower() != "winter":
            continue
        mw, year = _num(r.get("MW_total")), _num(r.get("year"))
        if mw is None or year is None or int(year) < DFES_BASE_YEAR:
            continue
        out.setdefault(str(r["ESA"]), {}).setdefault(str(r["scenario"]), {})[int(year)] = float(mw)
    return out


def _growth_curves(d: dict, esa: str | None, dfes: dict) -> dict[str, dict[int, float]]:
    """A Table 3 row's demand curves, as multipliers on its current maximum: one per FORECASTS pathway from its supply
    area's DFES projection (ratio to the DFES base year), else its own LTDS five-year forecast under "ltds"."""
    cur = _num(d.get("Current Year Max Demand"))
    curves: dict[str, dict[int, float]] = {}
    if esa:
        for fid, spec in FORECASTS.items():
            series = dfes.get(esa, {}).get(spec.get("dfes", ""), {})
            base = series.get(DFES_BASE_YEAR)
            if base:
                curves[fid] = {y: round(mw / base, 5) for y, mw in sorted(series.items())}
    if not curves and cur:
        ltds = {LTDS_FORECAST_FIRST_YEAR + k - 1: round(v / cur, 5) for k in range(1, 6) if (v := _num(d.get(f"Forecast Year {k}"))) is not None}
        if ltds:
            curves["ltds"] = ltds
    return curves


def dfes_pathways(tables: LtdsTables | None = None, point: SupplyPoint = BICKER_FEN) -> dict[str, dict[int, float]]:
    """The network-wide multiplier per plan year for every DFES pathway the loads carry: the load-weighted mean of the
    per-load curves (`network.per_load_growth`), so the planner's picker shows what the engine applies."""
    from .network import per_load_growth
    net = _ctx(tables, point=point)["net"]
    p = net.load["p_mw"].astype(float)
    out: dict[str, dict[int, float]] = {}
    for fid in FORECASTS:
        if not any(fid in (c or {}) for c in net.load["growth_curves"]):
            continue
        out[fid] = {y: round(float((p * per_load_growth(net, fid, y).reindex(p.index).fillna(1.0)).sum() / p.sum()), 4) for y in PLAN_YEARS}
    return out


def _screen_bsp_aggregates(net, dem, aggregates: set[str], on_bars: list[tuple[dict, int]]) -> None:
    """A screen, not a rule: for each substation, the demand placed on its own bars from rows with no primary (Primary "-"),
    against the primaries Table 3 files under that substation's name. More than half of it is the signature of a BSP
    aggregate counted as demand (Hawton at Staythorpe): those loads are listed (`possible_bsp_aggregate`), nothing changes."""
    prim: dict[str, float] = {}
    for d in dem:
        if not _is_bsp_row(d) and str(d.get("BSP Group") or "").strip() not in aggregates:
            k = _bsp_base(str(d.get("BSP Group") or "")).lower()
            prim[k] = prim.get(k, 0.0) + (_num(d.get("Current Year Max Demand")) or 0.0)
    by_site: dict[str, list[tuple[dict, int]]] = {}
    for d, i in on_bars:
        by_site.setdefault(_substation(str(net.bus.at[int(net.load.at[i, "bus"]), "name"])).lower(), []).append((d, i))
    for site, rows in by_site.items():
        own = sum(_num(d.get("Current Year Max Demand")) or 0.0 for d, _ in {id(d): (d, i) for d, i in rows}.values())
        if prim.get(site, 0.0) > 0 and own > 0.5 * prim[site]:
            for _, i in rows:
                _assume(net, "possible_bsp_aggregate", "load", i)
            rec = net["assumptions"]["possible_bsp_aggregate"]
            groups = sorted({str(d.get("BSP Group")) for d, _ in rows})
            rec["message"] += f"; {site.title()}: {own:.1f} MW on its bars ({', '.join(groups)}) against its primaries' {prim[site]:.1f} MW"


def _add_loads(net, dem, gb, point: SupplyPoint, dfes_rows=()) -> None:
    """LTDS Table 3 demand at the GSP's winter peak, with each load's summer-minimum scaling and the demand
    group it belongs to. LTDS Table 3 (NGED Connected Data Portal, LTDS
    dataset, filtered to the supply point's group) publishes, per row: the BSP group, the primary substation, the current
    maximum demand (MW), its power factor and the "Firm Capacity of Substation". We read the firm
    capacity as MVA (the usual unit for a transformer group's firm rating; the table does not state
    it) and convert it to MW at the row's own power factor, so comparing it with demand in MW is the
    same as comparing apparent powers. `peak_mw` keeps the row's own maximum demand (no diversity):
    a substation's firm capacity is set against its own peak, not the GSP-coincident share.

    A BSP's own rows are aggregates of its primaries (`_bsp_aggregates`), so they add no load: the
    BSP becomes a parent group of those primaries instead (the `bsp_*` columns).

    `p_mw` is the row's maximum × its `coincidence` (`_coincidence`: at its BSP, then at the GSP), so
    the winter-peak demand of the whole network is NESO's published GSP peak today."""
    aggregates = _bsp_aggregates(dem)
    region_id = _RegionIds()
    member = _bsp_membership(dem, aggregates, _bsp_groups(dem, aggregates, gb, region_id))
    at_bsp, at_gsp = _coincidence(dem, aggregates, member, point.require_peak())
    dfes = _dfes_index(dfes_rows)
    coincidence: dict[int, float] = {}
    on_bars: list[tuple[dict, int]] = []  # a BSP-level row counted as demand, and its load: for the aggregate screen
    min_scale: dict[int, float | None] = {}
    growth_curves: dict[int, dict] = {}
    groups: dict[int, dict] = {}
    for d in dem:
        p = _num(d["Current Year Max Demand"])
        if not p or str(d.get("BSP Group") or "").strip() in aggregates:
            continue
        nodes_d = _demand_nodes(d)
        pf = _pf(d)
        bsp = str(d.get("BSP Group") or "").strip()
        k = at_bsp.get(_bsp_base(bsp), 1.0) * at_gsp
        own = p / len(nodes_d)
        p = own * k
        q = p * math.tan(math.acos(pf))
        # LTDS "Minimum demand Scaling Factor" = minimum demand as a share of maximum demand. Our
        # p_mw is max × coincidence, so the summer-minimum case scales p_mw by f / coincidence.
        # Held at today's level (not grown): forecast growth is winter-evening EV/heat load.
        f = _num(str(d.get("Minimum demand Scaling Factor (%)") or "").rstrip("%"))
        name = _demand_group(d)
        firm_mva = float(_num(d.get("Firm Capacity of Substation")) or 0.0)
        esa = dfes_esa(str(d.get("Primary Substation") or ""), dfes)
        curves = _growth_curves(d, esa, dfes)
        group = {"region_id": region_id(name), "region": name, "bsp": bsp,
                 "primary": str(d.get("Primary Substation") or "").strip(), "firm_mva": firm_mva,
                 "firm_mw": round(firm_mva * pf, 3), "peak_mw": own,
                 **member.get(_bsp_base(bsp), {})}
        for n in nodes_d:
            idx = pp.create_load(net, gb(n), p_mw=p, q_mvar=q, name=d.get("Primary Substation", ""))
            if _num(d["Current Year Power Factor"]) is None:
                _assume(net, "pf_default", "load", int(idx))
            if firm_mva <= 0:
                _assume(net, "firm_capacity_unpublished", "load", int(idx))
            min_scale[int(idx)] = (f / 100.0) / k if f else None
            coincidence[int(idx)] = k
            growth_curves[int(idx)] = curves
            groups[int(idx)] = group
            if _is_bsp_row(d):
                on_bars.append((d, int(idx)))
            if not esa:
                _assume(net, "forecast_ltds_only", "load", int(idx))
            if n in point.removed_in_error and str(d.get("Status") or "").strip().lower() == "removed":
                _assume(net, "removed_in_error", "load", int(idx))
    _screen_bsp_aggregates(net, dem, aggregates, on_bars)
    net.load["min_scale"] = [min_scale.get(int(i)) for i in net.load.index]
    net.load["growth_curves"] = pd.Series([growth_curves.get(int(i), {}) for i in net.load.index], index=net.load.index, dtype=object)
    net.load["coincidence"] = [coincidence.get(int(i)) for i in net.load.index]
    for col in _LOAD_GROUP_COLS + _LOAD_BSP_COLS:
        net.load[col] = pd.Series([groups.get(int(i), {}).get(col) for i in net.load.index],
                                  index=net.load.index, dtype=object)


def _add_existing_fleet(net, tables, point: SupplyPoint) -> list[dict]:
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
        fuel = (g.get("Fuel Type") or "").strip()
        tech = _FUEL_TECH.get(fuel.lower(), "other")
        # the named sites behind a BSP-level total sit on their own buses; the rest of the total stays at the busbar
        sites = [x for x in point.generation_sites if not primary and x["table5"] == (bsp.strip(), fuel)]
        for j, x in enumerate(sites):
            site_buses = [int(_bus_of(net, code)) for code in x["nodes"]]
            site_tech = x.get("tech", tech)
            imp = x.get("import_mw")
            for k, bus in enumerate(site_buses):
                share = x["mw"] / len(site_buses)
                idx = pp.create_sgen(net, bus=bus, p_mw=share, q_mvar=0.0, name=f"EX-{n}.{j + 1}" + (f"-{k}" if k else ""), type=site_tech)
                net.sgen.at[idx, "p_rated_mw"] = share
                net.sgen.at[idx, "import_mw"] = share if imp is None else imp / len(site_buses)
                net.sgen.at[idx, "fleet_id"] = f"EX-{3000 + n}.{j + 1}"
            name = str(net.bus.at[site_buses[0], "name"])
            site_fuel = x.get("fuel", fuel)  # the ECR site's own technology where it overrides Table 5's category
            existing.append({"request_id": f"EX-{3000 + n}.{j + 1}", "bus_id": site_buses[0], "rating_mw": x["mw"],
                             "technology": site_tech, "fuel": site_fuel, "status": "connected",
                             "placement": f"{_substation(name)} (ECR site: {x['site']}; {x['evidence']})",
                             "applicant": f"{site_fuel or 'Existing DER'} · {x['site']} (ECR)"})
        r = float(r) - sum(x["mw"] for x in sites)
        if r <= 1e-9:
            continue
        buses, placement = _site_buses(net, (primary, bsp), kv, deg0)
        share = float(r) / len(buses)
        for k, bus in enumerate(buses):
            idx = pp.create_sgen(net, bus=int(bus), p_mw=share, q_mvar=0.0, name=f"EX-{n}" + (f"-{k}" if k else ""), type=tech)
            net.sgen.at[idx, "p_rated_mw"] = share
            net.sgen.at[idx, "import_mw"] = share
            net.sgen.at[idx, "fleet_id"] = f"EX-{3000 + n}"  # the model's generator id
        bus = buses[0]
        site = primary or bsp
        existing.append({"request_id": f"EX-{3000 + n}", "bus_id": int(bus), "rating_mw": r,
                         "technology": tech, "fuel": fuel, "status": "connected", "placement": placement,
                         "applicant": f"{fuel or 'Existing DER'} · {_substation(site) or point.place}"})
    return existing


# the ECR's conversion technology for a connected sub-MW site -> the model's technology; anything not listed (an engine, a
# turbine) is firm in both cases, as Table 5's non-renewables are; "data not available" is not modelled
_SMALL_TECH = {"photovoltaic": "solar", "storage": "battery", "wind": "wind"}


def _small_tech(row: dict) -> str | None:
    t = (row.get("Energy Conversion Technology 1") or "").lower()
    if not t or "not available" in t:
        return None
    return next((v for k, v in _SMALL_TECH.items() if k in t), "other")


def _bus_of(net, code: str) -> int:
    """The engine bus an LTDS node code was merged into (net["node_bus"], set by _build)."""
    return int(net["node_bus"][code])


def _add_ecr_additions(net, first_id: int, point: SupplyPoint) -> list[dict]:
    """Connected ECR sites this LTDS edition predates (the supply point's `ecr_additions`), at the bus their rule gives."""
    out = []
    for k, x in enumerate(point.ecr_additions):
        bus = _bus_of(net, x["node"])
        fid = f"EX-{first_id + k}"
        idx = pp.create_sgen(net, bus=bus, p_mw=x["mw"], q_mvar=0.0, name=fid, type=x["tech"])
        net.sgen.at[idx, "p_rated_mw"] = x["mw"]
        net.sgen.at[idx, "import_mw"] = x["mw"]
        net.sgen.at[idx, "fleet_id"] = fid
        out.append({"request_id": fid, "bus_id": bus, "rating_mw": x["mw"], "technology": x["tech"], "fuel": x["fuel"],
                    "status": "connected", "placement": f"{_substation(str(net.bus.at[bus, 'name']))} (ECR site: {x['site']}; {x['evidence']})",
                    "applicant": f"{x['fuel']} · {x['site']} (ECR)"})
    return out


def _add_small_embedded(net, tables, first_id: int, point: SupplyPoint) -> list[dict]:
    """The ECR's connected sites under 1 MW, which LTDS Table 5 (1 MW and up) leaves out: aggregated per primary and
    technology, each aggregate shared across that primary's busbars at its connection voltage (0.4 kV sites at 11 kV,
    the model's lowest level). A site with no export capacity or no technology is recorded, not modelled."""
    deg0 = _bus_degree(net)
    groups: dict[tuple[str, str, float], list[float]] = {}
    for i, row in enumerate(tables.get("ecr", [])):
        if (row.get("connection_status") or "") != "Connected":
            continue
        mw = _num(row.get("connected_maximum_export_capacity(mw)"))
        if mw is not None and mw >= ECR_MIN_EXPORT_MW:
            continue  # 1 MW and up: Table 5's fleet
        tech = _small_tech(row)
        if not mw or mw <= 0 or tech is None:
            _assume(net, "small_embedded_unmodelled", "ecr_site", i)
            continue
        kv = max(_num(str(row.get("point_of_connection(poc)_voltage(kv)") or "").lower().replace("kv", "")) or 0.0, 11.0)
        groups.setdefault((row.get("primary") or row.get("bulk_supply_point") or "", tech, kv), []).append(mw)
    out: list[dict] = []
    for k, ((primary, tech, kv), mws) in enumerate(sorted(groups.items())):
        total = sum(mws)
        buses, placement = _site_buses(net, (primary,), kv, deg0)
        fid = f"EX-{first_id + k}"
        for j, bus in enumerate(buses):
            share = total / len(buses)
            idx = pp.create_sgen(net, bus=int(bus), p_mw=share, q_mvar=0.0, name=f"{fid}" + (f"-{j}" if j else ""), type=tech)
            net.sgen.at[idx, "p_rated_mw"] = share
            net.sgen.at[idx, "import_mw"] = share
            net.sgen.at[idx, "fleet_id"] = fid
            _assume(net, "small_embedded", "sgen", int(idx))
        out.append({"request_id": fid, "bus_id": int(buses[0]), "rating_mw": total, "technology": tech,
                    "fuel": f"{len(mws)} sites under 1 MW", "status": "connected", "placement": placement,
                    "applicant": f"{len(mws)} {tech} site{'s' if len(mws) > 1 else ''} under 1 MW · {_substation(primary) or point.place}"})
    return out


def _add_gsp_infeed(net, boundary: dict, infeed_node: str) -> int:
    """The external grid (the GSP transmission infeed) on the busbar of the supply point's published infeed site
    (`SupplyPoint.infeed_node`), the transmission boundary carried on the net, and the buses the GSP can't reach removed:
    whatever demand or generation sat on them is recorded (builder assumptions `unreachable_demand`,
    `unreachable_generation`), never dropped unseen. Returns the slack bus id."""
    if not infeed_node or infeed_node not in net["node_bus"]:
        raise ValueError(f"{boundary.get('gsp_name')}: the infeed node {infeed_node!r} is not a node of this network "
                         f"(SupplyPoint.infeed_node names the published infeed site's busbar)")
    slack = int(net["node_bus"][infeed_node])
    pp.create_ext_grid(net, slack, vm_pu=GSP_INFEED_VM_PU, name="GSP infeed")
    # the transmission boundary, carried on the net so feasibility() can enforce it grid-agnostically
    net["gsp_name"] = boundary["gsp_name"]
    net["gsp_export_limit_mw"] = boundary["export_limit_mw"]
    net["gsp_sgt_mw"] = boundary["firm_export_mw"]  # one SGT's export limit (for "add an SGT")
    net["gsp_import_limit_mw"] = dict(boundary["import_limit_mw"])  # per season, both SGTs: checked per study case

    # remove the buses the GSP can't reach, recording what they carried
    import pandapower.topology as top
    from pandapower.toolbox import drop_buses
    unsupplied = [int(b) for b in top.unsupplied_buses(net) if b != slack]
    if unsupplied:
        for key, tab, kind in (("unreachable_demand", net.load, "load"), ("unreachable_generation", net.sgen, "sgen")):
            gone = tab[tab.bus.isin(unsupplied)]
            if not len(gone):
                continue
            for i in gone.index:
                _assume(net, key, kind, int(i))
            items = "; ".join(f"{gone.at[i, 'name']} {float(gone.at[i, 'p_mw']):.2f} MW at {net.bus.at[int(gone.at[i, 'bus']), 'name']}"
                              for i in gone.index)
            net["assumptions"][key]["message"] += f": {items} (total {float(gone.p_mw.sum()):.2f} MW)"
        drop_buses(net, unsupplied)
    return slack


def _assume_structure(net) -> None:
    """Two things the LTDS connectivity leaves to the reader, recorded (and never filled in): EHV substations whose busbars are separate nodes with no coupler or section
    circuit between them run split, and the 33 kV circuits that close a loop make the 33 kV network a
    closed mesh in parallel with the 132 kV (no normal-open points are published)."""
    import networkx as nx
    kv = net.bus["vn_kv"].astype(float)
    joined = {frozenset((int(a), int(b))) for a, b in zip(net.line["from_bus"], net.line["to_bus"])}
    joined |= {frozenset((int(a), int(b))) for a, b in zip(net.trafo["hv_bus"], net.trafo["lv_bus"])}
    by_site: dict[tuple[str, float], list[int]] = {}
    for b in net.bus.index:
        if kv.loc[b] >= EHV_MIN_KV:
            by_site.setdefault((_substation(net.bus.at[b, "name"]).lower(), float(kv.loc[b])), []).append(int(b))
    for buses in by_site.values():
        site = nx.Graph()
        site.add_nodes_from(buses)
        site.add_edges_from((a, b) for i, a in enumerate(buses) for b in buses[i + 1:] if frozenset((a, b)) in joined)
        if nx.number_connected_components(site) > 1:  # bars (with their tees) that no element joins
            for b in buses:
                _assume(net, "bus_sections_split", "bus", b)
    floor = float(kv.min())  # the lowest level modelled (11 kV): its feeders are radial by construction
    g = nx.Graph()
    lines_by_pair: dict[frozenset, list[int]] = {}
    for i in net.line.index:
        a, b = int(net.line.at[i, "from_bus"]), int(net.line.at[i, "to_bus"])
        if (bool(net.line.at[i, "in_service"]) or bool(net.line.at[i, "connector"])) and floor < kv.loc[a] < EHV_MIN_KV:
            g.add_edge(a, b)
            lines_by_pair.setdefault(frozenset((a, b)), []).append(int(i))
    bridges = {frozenset(e) for e in nx.bridges(g)} if g.number_of_edges() else set()
    for pair, ids in lines_by_pair.items():
        if len(ids) > 1 or pair not in bridges:  # a parallel pair is a loop of its own
            for i in ids:
                _assume(net, "mv_mesh_closed", "line", i)


def _build(tables: LtdsTables | None = None, edition: str = EDITION_CURRENT, point: SupplyPoint = BICKER_FEN):
    """Construct the pandapower net + bookkeeping (node->bus map, names). Returns a dict.

    LTDS flags every row against NGED's previous edition: New / Updated / Unchanged / Removed.
    The base network is what exists TODAY, so "Removed" equipment (decommissioned, or replaced —
    e.g. a transformer swapped for a bigger one appears once as Removed and once as New) is left
    out. Planned works would sit in LTDS Table 7, which has no rows for this GSP. The "previous"
    edition keeps the Removed rows and drops the New ones instead (Updated rows carry their
    current values either way: NGED doesn't publish the old ones).

    Each step below adds one kind of element to the net, in dependency order. Everything that belongs to one supply
    point (its published peak and limits, its named exceptions) comes from `point`."""
    if tables is None and point is not BICKER_FEN:
        raise ValueError(f"no bundled tables for {point.gsp_name}: pass its own")
    tables = tables if tables is not None else load_bundled_tables()
    circ = [r for r in tables.get("circuit", []) if _in_edition(r.get("Circuit Status"), edition)]
    t2a = [r for r in tables.get("t2a", []) if _in_edition(r.get("Status"), edition)]
    dem = [_aliased(d, point.bsp_aliases) for d in live_demand_rows(tables.get("demand", []), edition, point)]
    nodes = tables.get("node", [])  # names only (unreferenced codes simply go unused)
    name_by_code = {n["Code"]: n.get("Name", n["Code"]) for n in nodes}

    uf, groups, node_v = _merge_nodes(circ, t2a, dem)
    net = pp.create_empty_network(name=point.net_name)
    net["assumptions"] = {}  # what the builder had to assume, per element (_assume)
    busid, bus_code = _add_buses(net, groups, node_v, name_by_code)
    gb = lambda n: busid[uf.find(n)]
    net["node_bus"] = {code: int(bus) for code, bus in busid.items()}  # LTDS node code -> engine bus (nged._bus_of)

    _add_lines(net, circ, gb)
    _open_points(net, point, gb)
    _add_transformers(net, t2a, gb)
    _add_loads(net, dem, gb, point, tables.get("dfes", []))
    existing = _add_existing_fleet(net, tables, point)
    existing += _add_small_embedded(net, tables, 4000, point)  # ids after Table 5's (EX-3000...)
    existing += _add_ecr_additions(net, 5000, point)
    slack = _add_gsp_infeed(net, point.boundary, point.infeed_node)
    _assume_structure(net)  # after the unreachable buses are dropped

    return {"net": net, "busid": busid, "bus_code": bus_code, "uf": uf, "slack": slack,
            "name_by_code": name_by_code, "existing": existing, "edition": edition, "tables": tables, "point": point}


@lru_cache(maxsize=1)
def _built_bundled():
    return _build()


_BUILT: dict[str, dict] = {}  # content-hash -> built, for tables passed in explicitly (pipeline)


def tables_hash(tables: LtdsTables) -> str:
    """A stable content fingerprint of a set of raw tables (the edition id the pipeline records)."""
    import hashlib
    blob = json.dumps({k: tables.get(k, []) for k in sorted(tables)}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _ctx(tables: LtdsTables | None = None, edition: str = EDITION_CURRENT, point: SupplyPoint = BICKER_FEN) -> dict:
    """The built network + bookkeeping for `tables` (Bicker Fen's bundled snapshot when None) and supply point, memoised."""
    if tables is None and edition == EDITION_CURRENT and point is BICKER_FEN:
        return _built_bundled()
    key = f"{point.key}:{tables_hash(tables) if tables is not None else 'bundled'}:{edition}"
    if key not in _BUILT:
        if len(_BUILT) >= 6:
            _BUILT.pop(next(iter(_BUILT)))
        _BUILT[key] = _build(tables, edition, point)
    return _BUILT[key]


def build_nged_net(tables: LtdsTables | None = None, edition: str = EDITION_CURRENT, point: SupplyPoint = BICKER_FEN):
    """A fresh, solvable copy of the NGED network (deep-copied so callers can mutate freely)."""
    import copy
    return copy.deepcopy(_ctx(tables, edition, point)["net"])


# the planning assumptions this network is judged under (docs/sources-and-assumptions.md, as records the planner lists
# alongside the builder's own)
PLANNING_ASSUMPTIONS: tuple[ModelAssumption, ...] = (
    ModelAssumption(key="tap_target", message=f"Tap changers step {OLTC_TAP_STEP_PERCENT:g}% and regulate towards {OLTC_SETPOINT_PU:g} pu with a {OLTC_DEADBAND_PU:g} pu deadband: LTDS gives the range, not the step or the target (config.OLTC_*)"),
    ModelAssumption(key="dispatch_factors", message="Per-case dispatch is assumed: PV and wind at nil and batteries charging at winter peak; everything at full export at summer minimum (config.GENERATION_FACTORS)"),
    ModelAssumption(key="demand_coincidence", message="Winter-peak demand is each LTDS maximum scaled by published coincidence (its BSP's maximum, then NESO's GSP peak); the summer minimum uses the LTDS minimum-demand factor, not grown"),
    ModelAssumption(key="forecast_basis", message=f"Demand grows per primary on NGED's DFES 2025 winter-peak projections for the pathway chosen, as a ratio to their {DFES_BASE_YEAR} value (the LTDS edition's current year), so every plan year is NGED's own figure for that substation; connections with no supply area follow their LTDS five-year forecast, then hold"),
    ModelAssumption(key="gsp_sign", message="The GSP export limit's direction is assumed: 'export' read as distribution to transmission (NGED does not document the sign)"),
    ModelAssumption(key="firm_capacity_units", message="LTDS Table 3 firm capacity is read as MVA and converted to MW at the row's power factor (the table states no unit)"),
    ModelAssumption(key="transmission_context", message="The 400 kV network and wider transmission boundaries are context only; the GSP export limit is the only transmission constraint"),
)

def builder_assumptions(tables: LtdsTables | None = None, edition: str = EDITION_CURRENT,
                        point: SupplyPoint = BICKER_FEN) -> list[ModelAssumption]:
    """What the builder had to assume for this edition, one record per kind with the elements it touched."""
    recs = _ctx(tables, edition, point)["net"]["assumptions"]
    return [ModelAssumption(**r, count=len(r["element_ids"]) or None) for r in recs.values()]


def substation_names(tables: LtdsTables | None = None, point: SupplyPoint = BICKER_FEN) -> list[str]:
    """The distinct substation names in the built network (what the OSM geocoder matches against)."""
    net = _ctx(tables, point=point)["net"]
    return sorted({_substation(net.bus.at[b, "name"]) for b in net.bus.index})


def gsp_boundary(tables: LtdsTables | None = None, point: SupplyPoint = BICKER_FEN) -> dict:
    """The GSP boundary for the API/UI: export/import limits, the region's export today, and the
    transmission-registered projects behind it (with which ones this study injects)."""
    from .network import feasibility
    net = build_nged_net(tables, point=point)
    _, _, m = feasibility(net)  # today: existing fleet, today's demand, both study cases
    reg = {c["applicant"].split(" · ")[-1]: c["request_id"] for c in tec_candidates(float("inf"), tables, point)}
    return {**point.boundary, "export_today_mw": m.get("gsp_export_mw", 0.0),
            "transmission_projects": [{**p, "registry_id": reg.get(p["name"])} for p in point.transmission_projects]}


def _substation(name: str) -> str:
    """'Horncastle 11kV 1T0' -> 'Horncastle' (the substation, for coord/name joins)."""
    return (name or "").split(" 132")[0].split(" 66")[0].split(" 33")[0].split(" 11")[0].strip() or (name or "")


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


def _bus_coords(net, coords: dict[str, tuple[float, float]] | None = None,
                center: tuple[float, float] = BICKER_FEN.center) -> dict[int, tuple[float, float]]:
    """(lon, lat) per bus.

    Substations found in `coords.csv` sit at their real position (buses of one substation are
    jittered a few hundred metres apart). Every other bus — mostly line tee-points like
    "Pole 90ZB1E17" — is placed at the average of its connected neighbours, iterated to a fixed
    point, so it sits on the route between real substations. A bus with no placed neighbour falls
    back to a deterministic spot near the GSP (`center`) so the map still renders.
    """
    real = coords if coords is not None else _coords_index(None)
    jit = lambda b: ((_h01(str(b) + "jx") - 0.5) * 0.006, (_h01(str(b) + "jy") - 0.5) * 0.004)
    fixed: dict[int, tuple[float, float]] = {}
    for b in net.bus.index:
        hit = real.get(_substation(net.bus.at[b, "name"]).lower())
        if hit:
            dx, dy = jit(int(b))
            fixed[int(b)] = (hit[0] + dx, hit[1] + dy)
    return interpolate_positions(net, fixed, center)  # the rest between their neighbours (geometry.py)


def nged_model(tables: LtdsTables | None = None, edition: str = EDITION_CURRENT, point: SupplyPoint = BICKER_FEN) -> dict:
    """Geolocated canonical model (buses/lines/transformers/loads) with bus_id = pandapower index.

    Matches build_nged_net() exactly, so the map and the engine share one network.
    """
    ctx = _ctx(tables, edition, point)
    net = ctx["net"]
    xy = _bus_coords(net, _coords_index(tables), point.center)
    return model_from_net(net, xy, ctx["existing"], "wgs84").model_dump()  # shaped like every source's (gridmodel.py)


_FUEL_TECH = {"photovoltaic": "solar", "solar": "solar", "solar pv": "solar",
              "wind": "wind", "onshore wind": "wind", "offshore wind": "wind",
              "storage": "battery", "battery": "battery", "battery storage": "battery",
              "energy storage": "battery"}  # anything else (biomass, 'other generation') -> "other": firm in both cases
_STATUS_READINESS = {"accepted": 0.9, "budget estimates provided": 0.45,
                     "quotation": 0.55, "offered": 0.7, "scoping": 0.2}


def commission_year(readiness: float, tech: str | None, rating: float | None, seed: str) -> int:
    """A deterministic requested-energisation year from the plan's second year to its last — the timeline axis.

    Readiness pulls it earlier (a shovel-ready project energises soonest); wind and large schemes
    take longer to build; a per-project hash breaks ties so the years spread rather than bunch.
    This is a plausible planning heuristic, not a committed date from the developer.
    """
    r = min(max(readiness, 0.0), 1.0)
    year = PLAN_START_YEAR + 1 + round((1.0 - r) * 4)  # the plan's 2nd year (ready) .. its 6th (speculative)
    year += 1 if (tech or "").lower() == "wind" else 0
    year += (1 if rating and rating > 80 else 0) + (1 if rating and rating > 150 else 0)
    year += int(_h01(seed + "yr") * 3)          # deterministic 0/1/2 jitter, to spread the queue
    return max(PLAN_START_YEAR + 1, min(PLAN_END_YEAR, year))


def nged_candidates(max_mw: float, tables: LtdsTables | None = None, point: SupplyPoint = BICKER_FEN) -> list[dict]:
    """A connection queue from LTDS Table 5 (generation), mapped to real buses.

    Real fuel types, export capacities and connection statuses; bus matched by substation name.
    Projects over `max_mw` or without a rating are flagged needs_review (the intake path). A site whose substation
    matches no bus is placed on a 33 kV+ bus in turn (no bundled site needs it).
    """
    ctx = _ctx(tables, point=point)
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
            "request_id": f"NG-{3000 + n}", "applicant": f"{fuel or 'DER'} · {site or point.place}",
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
    ecr = ecr_candidates(max_mw, tables, point)
    # an LTDS Table 5 project the ECR also lists (same export MW + technology) is the same site — keep
    # the ECR record (it has a location and a target date), drop the Table 5 duplicate
    ecr_keys = {(round(c["rating_mw"], 1), c["technology"]) for c in ecr}
    out = [c for c in out if (round(c["rating_mw"] or 0, 1), c["technology"]) not in ecr_keys]
    return out + ecr + tec_candidates(max_mw, tables, point)


def tec_candidates(max_mw: float, tables: LtdsTables | None = None, point: SupplyPoint = BICKER_FEN) -> list[dict]:
    """Transmission-registered projects that would connect AT THE GSP's 132 kV busbar (so their
    export flows up through our supergrid transformers) and aren't built yet — optional registry
    projects like any other. Readiness from the rubric: a TEC position is a signed connection
    agreement; "Awaiting consents" means planning has been submitted."""
    import hashlib
    from .readiness import score_from_checklist

    slack = int(_ctx(tables, point=point)["slack"])
    out = []
    for p in point.transmission_projects:
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
    """The ECR publishes no reference, so derive the project's id from the fields NGED corrects least: where
    it is, what it is, its voltage and when its offer was accepted. Not its name or its capacity, so a
    re-rating or a renamed site keeps its id; a corrected location or acceptance date still gives a new one."""
    import hashlib
    key = "|".join(str(row.get(k)) for k in ("lat", "lon", "energy_source_1", "point_of_connection(poc)_voltage(kv)",
                                             "date_accepted"))
    return "ECR-" + hashlib.sha1(key.encode()).hexdigest()[:5].upper()


def _year(date_str) -> int | None:
    """'15/12/2026' -> 2026."""
    try:
        return int(str(date_str).strip()[-4:])
    except (TypeError, ValueError):
        return None


def ecr_candidates(max_mw: float, tables: LtdsTables | None = None, point: SupplyPoint = BICKER_FEN) -> list[dict]:
    """Registry projects from the ECR's 'Accepted to connect' sites at this GSP.

    Export capacity = the accepted change to maximum export capacity (a solar+storage hybrid may
    register more than it can export). Each site is attached to the nearest bus AT ITS CONNECTION
    VOLTAGE using its published lat/lon; sites without a location fall back to their primary
    substation, else the best-connected bus at that voltage. Readiness uses the deterministic rubric:
    an accepted offer is a signed connection agreement; land, planning and financing aren't
    published in the ECR, so they earn no credit.
    """
    from .readiness import score_from_checklist

    ctx = _ctx(tables, point=point)
    net = ctx["net"]
    xy = _bus_coords(net, _coords_index(tables), point.center)
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

