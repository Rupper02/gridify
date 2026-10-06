"""Where a grid comes from: the `GridSource` seam, and the registry of kinds (`SOURCES`).

Everything the engine needs from a network is behind one small Protocol: a fresh solvable pandapower
net (`build_net`, what every engine function takes as `net_factory`), the geolocated model for the
map (`model`), the optional registry of projects (`candidates`), the GSP boundary card when the
source models one (`boundary`), a content fingerprint (`fingerprint`, the cache baseline) and what
the model had to assume (`assumptions`). NGED's open-data builder is one source (`NgedSource`, zero
behaviour change); a CGMES zip, a pandapower JSON or a MATPOWER case become one through the same
grid-agnostic steps: `normalise_net` (what the engine's columns need), `apply_import_meta` (limits
the operator enters), `inspect_net` (what the file did not carry, stated) and `validate_net`.

An imported grid is simulated as it runs, or not at all: nothing the network's own description needs is assumed.
`normalise_net` keeps what the file says (its voltage-controlled generators, its fixed transformer ratios, its slack
generator) and records every gap instead of filling it: no infeed, a generator without its technology, rating,
voltage setpoint, reactive limits, minimum output or cost, an unrated line, a tap range without a tap-changer type,
buses the infeed cannot reach. `validate_net` turns the gaps into errors, so the import is refused with the exact list
to complete. The study's basis (the cases a grid can be studied in, its export limit, the voltage bands and N-1 scope)
is listed as assumptions.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import tempfile
import zipfile
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple, Protocol, runtime_checkable

import pandapower as pp
import pandapower.topology as top
import pandas as pd

from .config import DEFAULT_SCENARIO, FORECASTS, IMPORT_FORECAST_FACTOR_MAX, IMPORT_PATHWAYS, MAX_CONNECTION_MW, PLAN_END_YEAR, PLAN_START_YEAR, VOLTAGE_BAND_PRESETS
from .dispatch import FLEET_TABLES
from .geometry import SYNTHETIC_CENTER, interpolate_positions, synthetic_positions
from .gridmodel import fleet_of, model_from_net
from .types import GridModel, ImportMeta, ModelAssumption, ValidationReport

IMPORTER_VERSION = "3"  # bump when normalise_net changes what an imported net looks like (it is in the fingerprint)


@runtime_checkable
class GridSource(Protocol):
    """A grid the engine can plan on. Implementations must be substitutable: the engine, the API and
    the pipeline call only what is here."""

    id: str
    name: str
    kind: str

    def build_net(self): ...  # a fresh, solvable pandapower net (callers may mutate it)
    def model(self) -> GridModel: ...
    def candidates(self) -> list[dict]: ...  # the registry of optional projects (may be empty)
    def boundary(self) -> dict | None: ...  # the GSP boundary card, or None when the source models none
    def fingerprint(self) -> str: ...  # the content identity results are cached under
    def forecasts(self) -> dict[str, dict[int, float]] | None: ...  # the grid's own demand pathways; None: the FES pathways
    def assumptions(self) -> list[ModelAssumption]: ...
    def capabilities(self) -> dict: ...  # {boundary, regions, registry, editions, summer_case, crs}


class SourceSpec(NamedTuple):
    label: str
    extensions: tuple[str, ...]  # file extensions this kind imports ("" for the bundled source)
    factory: Callable[..., GridSource]
    offered: bool = True  # offered by the import form (`import_formats`); False: read, but no file of it can pass today


# --- the planning assumptions every imported grid is judged under (listed, never hidden) ---------------------------
_GENERIC = {
    "no_gsp_limit": "No export limit to the external grid in the file: the slack's export is reported, never limited",
    "no_demand_groups": "No demand groups (firm capacities) in the file: no security-of-supply alerts for customers",
    "slack_from_generator": "The file's slack generator is the external-grid infeed, at its voltage setpoint",
    "merit_order_dispatch": "Power stations (voltage-controlled units) share each study case's demand by merit order (equal marginal cost "
                            "from the file's costs, within their minimum and maximum), all staying synchronised: the units an operator keeps "
                            "on for security are not modelled; embedded generation, solar, wind and storage follow the case as on any grid; "
                            "the external grid balances the rest and the losses",
    "inverter_rating": "Units the file rates only by their nominal (apparent) power are rated at it: an inverter's AC rating caps its export",
    "gsp_limit_entered": "Export limit to the external grid entered by the operator at import",
    "gsp_sgt_entered": "One supergrid transformer's rating entered by the operator at import: the size of the 'add a transformer' lever",
    "min_demand_entered": "Minimum-demand factor entered by the operator at import, applied to every load",
    "summer_ratio_entered": "Summer rating ratio entered by the operator at import, applied to every line",
    "intermediate_ratio_entered": "Intermediate-season rating ratio entered by the operator at import, applied to every line",
    "forecast_entered": "Demand forecast entered by the operator at import (peak demand's growth on the year before, every plan year), spread uniformly over every load",
    "n1_scope_entered": "N-1 scope entered by the operator at import; the screen is reported, never a gate",
    "bands_entered": "Voltage limits by level entered by the operator at import",
}
_TECH_FROM_TYPE = {"wp": "wind", "wind": "wind", "pv": "solar", "solar": "solar", "battery": "battery", "storage": "battery",
                   "hydro": "other", "thermal": "other", "gas": "other", "biomass": "other", "nuclear": "other", "chp": "other"}


class _Records:
    """Assumption records being collected for one net: one per key, with the elements it touched."""

    def __init__(self):
        self.by_key: dict[str, dict] = {}

    def add(self, key: str, *, source: str = "engine-default", element_kind: str | None = None, element_ids=(), message: str | None = None) -> None:
        rec = self.by_key.setdefault(key, {"key": key, "message": message or _GENERIC[key], "source": source, "element_kind": element_kind, "element_ids": []})
        rec["element_ids"].extend(int(i) for i in element_ids)

    def list(self) -> list[ModelAssumption]:
        return [ModelAssumption(**r, count=len(r["element_ids"]) or None) for r in self.by_key.values()]


def _isnan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA


def _fill_names(table, prefix: str) -> None:
    if "name" not in table.columns:
        table["name"] = [f"{prefix} {i}" for i in table.index]
        return
    table["name"] = [f"{prefix} {i}" if _isnan(v) or str(v).strip() in ("", "nan", "None") else str(v) for i, v in zip(table.index, table["name"])]


def _tagged(row, key: str) -> str | None:
    """A value our own CGMES export writes into a description (`gridforge.<key>=<value>`), or None."""
    desc = str(row.get("description") or "")
    marker = f"gridforge.{key}="
    return desc.split(marker, 1)[1].split()[0].strip(" ;,") if marker in desc else None


def _tagged_cost(net, table: str, i: int) -> bool:
    """A merit-order cost our own CGMES export wrote into the element's description (`gridforge.cost=<cp1>,<cp2>`), put
    back into `poly_cost` where the engine reads it; False when the description carries none."""
    tag = _tagged(net[table].loc[i], "cost")
    if tag is None:
        return False
    cp1, _, cp2 = tag.partition(",")
    pp.create_poly_cost(net, int(i), table, cp1_eur_per_mw=float(cp1), cp2_eur_per_mw2=float(cp2 or 0.0))
    return True


def _tech_of(row) -> tuple[str, bool]:
    """(technology, known): from our own CGMES tag, else the type the file gives, else 'other'."""
    tagged = _tagged(row, "tech")
    if tagged:
        return tagged, True
    t = str(row.get("type") or "").strip().lower()
    for k, v in _TECH_FROM_TYPE.items():
        if k in t:
            return v, True
    return "other", False


class _Gaps:
    """What an imported grid lacks for a real simulation, by what is missing: refused at import, never filled."""

    def __init__(self):
        self.by_need: dict[str, list[str]] = {}

    def add(self, need: str, element: str) -> None:
        self.by_need.setdefault(need, []).append(element)

    def errors(self, shown: int = 12) -> list[str]:
        out = []
        for need, els in self.by_need.items():
            more = f" and {len(els) - shown} more" if len(els) > shown else ""
            out.append(f"{need}: {', '.join(els[:shown])}{more}")
        return out


def _label(table, i, noun: str) -> str:
    name = table.at[i, "name"] if "name" in table.columns else None
    return f"{noun} {i}" + ("" if _isnan(name) or str(name) in ("", f"{noun} {i}") else f" ({name})")


def _value(table, i, col):
    """A cell as a float, or None when the file leaves it out."""
    if col not in table.columns or _isnan(table.at[i, col]):
        return None
    return float(table.at[i, col])


def _ensure_slack(net, rec: _Records, gaps: _Gaps) -> None:
    """The infeed: the file's external grid, or the generator the file marks as its slack; otherwise a gap."""
    if len(net.ext_grid):
        return
    slack = net.gen[net.gen["slack"].astype(bool)] if len(net.gen) and "slack" in net.gen.columns else net.gen.iloc[:0]
    if not len(slack):
        gaps.add("no infeed: mark the bus that connects to the upstream grid (an external grid) with its voltage setpoint", "the network")
        return
    for i in slack.index:  # the file's price and limits go with it: the merit order prices the external grid by them
        limits = {k: float(net.gen.at[i, k]) for k in ("max_p_mw", "min_p_mw") if _value(net.gen, i, k) is not None}
        eg = pp.create_ext_grid(net, int(net.gen.at[i, "bus"]), vm_pu=float(net.gen.at[i, "vm_pu"]),
                                name=str(net.gen.at[i, "name"] or "slack"), **limits)
        pc = net.get("poly_cost")
        if pc is not None and len(pc):
            own = (pc["et"] == "gen") & (pc["element"].astype(int) == int(i))
            pc.loc[own, "et"], pc.loc[own, "element"] = "ext_grid", int(eg)
    rec.add("slack_from_generator", source="file", element_kind="gen", element_ids=slack.index)
    net.gen.drop(slack.index, inplace=True)


def _normalise_fleet(net, rec: _Records, gaps: _Gaps) -> None:
    """The generators as the file describes them: fixed-power-factor (embedded) units (`sgen`) and voltage-controlled
    units (`gen`, kept so: they hold their setpoint within their reactive limits). Each needs its technology and
    rating; a voltage-controlled one its setpoint and reactive limits; a power station (voltage-controlled, not solar,
    wind or storage) its minimum output and its cost for the merit order. A unit missing any of them is a gap."""
    from .config import IMPORT_ONLY_TECHS
    from .dispatch import _cost, _ensure_fleet_columns, market_units
    _ensure_fleet_columns(net)
    from_nominal = []
    for table, noun, prefix in (("sgen", "generator", "EX-"), ("gen", "voltage-controlled generator", "EX-G")):
        t = net[table]
        for col in ("fleet_id", "type"):
            if col not in t.columns:
                t[col] = pd.Series(dtype=object)
        for i in t.index:
            label = _label(t, i, noun)
            tech, known = _tech_of(t.loc[i])
            t.at[i, "type"] = tech
            if not known:
                gaps.add("generators without their technology (solar, wind, battery, gas, ...)", label)
            if _isnan(t.at[i, "fleet_id"]):
                t.at[i, "fleet_id"] = f"{prefix}{int(i)}"
            rating = _value(t, i, "max_p_mw")
            if rating is None and table == "sgen" and _value(t, i, "sn_mva") is not None:
                rating = _value(t, i, "sn_mva")  # an inverter's AC rating caps its export
                from_nominal.append(int(i))
            if rating is None:
                gaps.add("generators without a rating (max_p_mw)", label)
            elif _isnan(t.at[i, "p_rated_mw"]):
                t.at[i, "p_rated_mw"] = rating
            stated = _tagged(t.loc[i], "import_mw")  # our own export states a charging capacity CIM has no field for
            if stated is not None and _isnan(t.at[i, "import_mw"]):
                t.at[i, "import_mw"] = float(stated)
            if tech == "battery" and _isnan(t.at[i, "import_mw"]):
                gaps.add("batteries without their charging capacity (import_mw)", label)
            elif tech in IMPORT_ONLY_TECHS and _isnan(t.at[i, "import_mw"]):
                gaps.add("demand or electrolyser units without the power they draw (import_mw)", label)
            if table == "gen":
                for col, what in (("vm_pu", "a voltage setpoint (vm_pu)"), ("min_q_mvar", "reactive limits (min_q_mvar, max_q_mvar)"),
                                  ("max_q_mvar", "reactive limits (min_q_mvar, max_q_mvar)")):
                    if _value(t, i, col) is None:
                        gaps.add(f"voltage-controlled generators without {what}", label)
    if from_nominal:
        rec.add("inverter_rating", source="file", element_kind="gen", element_ids=from_nominal)
    stations = market_units(net)  # the units the merit order dispatches: the one definition of a power station
    for i in stations:
        label = _label(net.gen, i, "voltage-controlled generator")
        if _value(net.gen, i, "min_p_mw") is None:
            gaps.add("power stations without their minimum output (min_p_mw)", label)
        if _cost(net, "gen", i) is None and not _tagged_cost(net, "gen", i):
            gaps.add("power stations without a cost for the merit order (poly_cost)", label)
    if len(stations):
        for i in net.ext_grid.index:
            if _cost(net, "ext_grid", i) is None:
                _tagged_cost(net, "ext_grid", i)
            if _cost(net, "ext_grid", i) is None or _value(net.ext_grid, i, "max_p_mw") is None:
                gaps.add("an external grid without the price and limit of its supply (poly_cost, max_p_mw), which the merit order "
                         "needs alongside the power stations", _label(net.ext_grid, i, "external grid"))


def _normalise_trafos(net, gaps: _Gaps) -> None:
    """Transformers as the file states them: a fixed ratio (a tap position with no range) is kept, a transformer with
    no tap data is at its nominal ratio, one with a tap range and a tap-changer type is an on-load tap changer the
    engine regulates. A range without a type is a gap: on-load (regulated) or fixed, the file has to say."""
    if not len(net.trafo):
        return
    for col in ("tap_min", "tap_max", "tap_neutral", "tap_pos", "tap_step_percent", "tap_side", "tap_changer_type"):
        if col not in net.trafo.columns:
            net.trafo[col] = None
    for i in net.trafo.index:
        has_range = _value(net.trafo, i, "tap_min") is not None and _value(net.trafo, i, "tap_max") is not None \
            and float(net.trafo.at[i, "tap_max"]) > float(net.trafo.at[i, "tap_min"]) and (_value(net.trafo, i, "tap_step_percent") or 0) > 0
        if has_range and _isnan(net.trafo.at[i, "tap_changer_type"]):
            gaps.add("transformers with a tap range but no tap-changer type: set tap_changer_type for an on-load tap changer "
                     "(regulated), or remove the range to keep it fixed at its position", _label(net.trafo, i, "transformer"))
        if has_range and _value(net.trafo, i, "tap_pos") is None:
            gaps.add("transformers with a tap range but no tap position", _label(net.trafo, i, "transformer"))
        if (_value(net.trafo, i, "tap_pos") is not None and _value(net.trafo, i, "tap_neutral") is None
                and (_value(net.trafo, i, "tap_step_percent") or 0) > 0):  # its ratio is the position against neutral
            gaps.add("transformers with a tap position but no neutral position (tap_neutral)", _label(net.trafo, i, "transformer"))
    for col in ("tap_min", "tap_max", "tap_neutral", "tap_pos"):
        net.trafo[col] = pd.to_numeric(net.trafo[col], errors="coerce").fillna(0).astype(int)
    net.trafo["tap_step_percent"] = pd.to_numeric(net.trafo["tap_step_percent"], errors="coerce").fillna(0.0)


def _normalise_lines(net, gaps: _Gaps) -> None:
    if not len(net.line):
        return
    imax = pd.to_numeric(net.line["max_i_ka"], errors="coerce")
    for i in net.line.index[imax.isna() | (imax <= 0)]:
        gaps.add("lines without a thermal rating (max_i_ka)", _label(net.line, i, "line"))
    if "parallel" not in net.line.columns:
        net.line["parallel"] = 1


def normalise_net(net, source_id: str = "import") -> list[ModelAssumption]:
    """Make any pandapower net one the engine can plan on, recording every step that assumes
    something. The net is changed in place."""
    rec = _Records()
    if "assumptions" not in net or not isinstance(net["assumptions"], dict):
        net["assumptions"] = {}
    _fill_names(net.bus, "bus")
    _fill_names(net.line, "line")
    _fill_names(net.trafo, "transformer")
    _fill_names(net.load, "load")
    if "substation" not in net.bus.columns:
        zone = net.bus["zone"] if "zone" in net.bus.columns else pd.Series(None, index=net.bus.index, dtype=object)
        net.bus["substation"] = [str(z) if not _isnan(z) and str(z).strip() not in ("", "nan", "None") else str(n) for z, n in zip(zone, net.bus["name"])]
    if "scaling" not in net.load.columns:
        net.load["scaling"] = 1.0
    gaps = _Gaps()
    _ensure_slack(net, rec, gaps)
    _normalise_fleet(net, rec, gaps)
    _normalise_trafos(net, gaps)
    _normalise_lines(net, gaps)
    if len(net.ext_grid):  # buses the infeed cannot reach: the file's topology is wrong, or they are out of service
        live = set(net.bus.index[net.bus["in_service"].astype(bool)])
        for b in sorted(int(b) for b in top.unsupplied_buses(net) if int(b) in live):
            gaps.add("in-service buses the infeed cannot reach (connect them, or set them out of service)", _label(net.bus, b, "bus"))
    rec.add("merit_order_dispatch")
    net["gaps"] = gaps.errors()
    if "name" not in net or not net.name:
        net.name = source_id
    for r in rec.by_key.values():  # the builder-style records studies.data_quality reads
        net["assumptions"][r["key"]] = dict(r)
    return rec.list()


def levels_of(net) -> list[float]:
    """The grid's voltage levels (the in-service buses' nominal kV), highest first."""
    live = net.bus[net.bus["in_service"].astype(bool)]
    return sorted({round(float(v), 3) for v in live["vn_kv"] if float(v) > 0}, reverse=True)


def _study_basis(net, meta: ImportMeta, rec: _Records) -> list[str]:
    """The study basis a grid file does not carry and the operator must state: the demand forecast (Standard at
    least), the lowest level the N-1 screen covers, the voltage limits at every level. Applied to the net and
    recorded as entered; what is missing is a gap (the import is refused with the list)."""
    from .network import n1_elements
    gaps: list[str] = []
    levels = levels_of(net)
    years = f"{PLAN_START_YEAR + 1} to {PLAN_END_YEAR}"
    if not meta.forecasts or "ht" not in meta.forecasts:
        gaps.append(f"no demand forecast: enter the Standard pathway's peak-demand growth on the year before (1.02 = +2 %) for every year "
                    f"from {years} (Low and High are optional)")
    else:
        net["forecasts"] = meta.cumulative()  # what each year is studied at: the year-on-year factors multiplied up
        named = "; ".join(f"{FORECASTS[p]['short']} x{c[2030]:.2f} by 2030, x{c[PLAN_END_YEAR]:.2f} by {PLAN_END_YEAR}" for p, c in net["forecasts"].items())
        cited = f" (source: {meta.forecast_source.strip()})" if meta.forecast_source and meta.forecast_source.strip() else " (no source given)"
        rec.add("forecast_entered", source="operator-entered", element_kind="load", element_ids=net.load.index,
                message=f"Demand forecast entered at import as year-on-year growth{cited}: {named}; each year's demand is spread uniformly over every load")
    if meta.n1_min_kv is None:
        gaps.append(f"no N-1 scope: choose the lowest voltage level the single-outage screen covers (this grid's levels: {', '.join(f'{v:g}' for v in levels)} kV)")
    elif round(float(meta.n1_min_kv), 3) not in levels:
        gaps.append(f"the N-1 scope {meta.n1_min_kv:g} kV is not one of this grid's voltage levels ({', '.join(f'{v:g}' for v in levels)} kV)")
    else:
        net["n1_min_kv"] = float(meta.n1_min_kv)
        n = len(n1_elements(net))
        rec.add("n1_scope_entered", source="operator-entered",
                message=f"The N-1 screen covers lines and transformers at {meta.n1_min_kv:g} kV and above ({n} elements), entered at import; "
                        "it is reported, never a gate")
    stated = {round(b.kv, 3): b for b in meta.voltage_bands or []}
    missing = [v for v in levels if v not in stated]
    if missing:
        gaps.append(f"no voltage limits at {', '.join(f'{v:g}' for v in missing)} kV: state the minimum and maximum (pu) for every level of the grid")
    else:
        net["voltage_bands"] = tuple((v, stated[v].vmin_pu, stated[v].vmax_pu) for v in sorted(levels))
        rec.add("bands_entered", source="operator-entered", element_kind="bus", element_ids=net.bus.index,
                message="Voltage limits entered at import: " + "; ".join(f"{stated[v].vmin_pu:g}-{stated[v].vmax_pu:g} pu at {v:g} kV" for v in levels))
    return gaps


def apply_import_meta(net, meta: ImportMeta | None) -> list[ModelAssumption]:
    """What the operator states and the file did not carry, applied and recorded as operator-entered: the
    known limits (an export limit, a minimum-demand factor, seasonal rating ratios, each optional and applied
    uniformly) and the study basis (required: a missing part is a gap, `_study_basis`)."""
    rec = _Records()
    meta = meta or ImportMeta()
    net["gaps"] = list(net.get("gaps") or []) + _study_basis(net, meta, rec)
    if meta.gsp_export_limit_mw is not None:
        net["gsp_name"] = meta.gsp_name or "the external grid"
        net["gsp_export_limit_mw"] = float(meta.gsp_export_limit_mw)
        rec.add("gsp_limit_entered", source="operator-entered")
    if meta.gsp_sgt_mw is not None:  # without it the GSP lever is not offered: its size is never invented
        net["gsp_sgt_mw"] = float(meta.gsp_sgt_mw)
        rec.add("gsp_sgt_entered", source="operator-entered")
    if meta.min_demand_factor is not None and len(net.load):
        net.load["min_scale"] = float(meta.min_demand_factor)
        rec.add("min_demand_entered", source="operator-entered", element_kind="load", element_ids=net.load.index)
    if meta.summer_rating_ratio is not None and len(net.line):
        net.line["summer_ratio"] = float(meta.summer_rating_ratio)
        rec.add("summer_ratio_entered", source="operator-entered", element_kind="line", element_ids=net.line.index)
    if meta.intermediate_rating_ratio is not None and len(net.line):
        net.line["intermediate_ratio"] = float(meta.intermediate_rating_ratio)
        rec.add("intermediate_ratio_entered", source="operator-entered", element_kind="line", element_ids=net.line.index)
    # both study cases run on every grid: the summer minimum (where reverse flow, voltage rise and export peak) needs the
    # file's or the operator's minimum demand and summer ratings, never a stand-in
    has = lambda table, col: col in table.columns and table[col].notna().any()  # noqa: E731
    if len(net.load) and not has(net.load, "min_scale"):
        net["gaps"].append("no minimum demand for the summer-minimum case: enter the minimum demand as a share of the maximum")
    if len(net.line) and not has(net.line, "summer_ratio"):
        net["gaps"].append("no summer line ratings for the summer-minimum case: enter the summer / winter line rating ratio")
    for r in rec.by_key.values():
        net["assumptions"][r["key"]] = dict(r)
    return rec.list()


def inspect_net(net) -> list[ModelAssumption]:
    """What the net does not carry, stated: the cases it cannot be studied in, the limits it has none of."""
    rec = _Records()
    has = lambda table, col: col in table.columns and table[col].notna().any()  # noqa: E731
    if net.get("gsp_export_limit_mw") is None:
        rec.add("no_gsp_limit", source="file")
    if not has(net.load, "region_id"):
        rec.add("no_demand_groups", source="file")
    return rec.list()


def _generation_shortfall(net) -> tuple[float, float] | None:
    """(demand, supply) when the demand is more than every in-service generator's rating plus the external grid's limit;
    None when it is not, or when the external grid states no limit."""
    if not len(net.ext_grid) or "max_p_mw" not in net.ext_grid.columns or net.ext_grid["max_p_mw"].isna().any():
        return None
    demand = float((net.load["p_mw"] * net.load["scaling"])[net.load["in_service"].astype(bool)].sum())
    supply = float(net.ext_grid["max_p_mw"].sum())
    for t in (net[name] for name in FLEET_TABLES):
        if len(t):
            supply += float(t.loc[t["in_service"].astype(bool), "p_rated_mw"].fillna(0).sum())
    return (demand, supply) if demand > supply else None


def _non_convergence(net, message: str) -> str:
    """Why the base case has no solution, told apart: the file's own operating point does not solve either (the grid as
    described has no steady state), or it does and the case as studied (merit-order dispatch, the case's demand) is
    more than the grid can carry."""
    given = copy.deepcopy(net)
    from .network import _no_solution

    try:
        pp.runpp(given, enforce_q_lims=bool(len(given.gen)))
        solves = bool(given.converged)
    except Exception as e:
        if not _no_solution(e):
            raise
        solves = False
    if solves:
        return (f"the file solves at its own operating point, but the base case as studied does not ({message}): with its power "
                "stations dispatched by merit order at that case's demand the grid has no steady state")
    return f"the power flow does not converge, at the file's own operating point either ({message}): the grid as described has no steady state"


def validate_net(net) -> ValidationReport:
    """Can the engine plan on this net? Structural errors first, then one power flow in every case."""
    from .network import _study_cases, feasibility
    errors: list[str] = []
    warnings: list[str] = []
    if not len(net.bus):
        errors.append("the file has no buses")
    if not len(net.ext_grid) and not net.get("gaps"):  # an import says so in its gaps (`_ensure_slack`)
        errors.append("no infeed: the network has no external grid")
    bad_kv = [int(b) for b in net.bus.index if not float(net.bus.at[b, "vn_kv"]) > 0]
    if bad_kv:
        errors.append(f"{len(bad_kv)} buses have no nominal voltage")
    buses = set(int(b) for b in net.bus.index)
    dangling = [int(i) for i in net.line.index if int(net.line.at[i, "from_bus"]) not in buses or int(net.line.at[i, "to_bus"]) not in buses]
    if dangling:
        errors.append(f"{len(dangling)} lines reference buses that do not exist")
    counts = {"buses": int(len(net.bus)), "lines": int(len(net.line)), "transformers": int(len(net.trafo)), "loads": int(len(net.load)),
              "generators": int(len(net.sgen) + len(net.gen)), "slacks": int(len(net.ext_grid))}
    islands = 0
    if len(net.bus):
        import networkx as nx
        g = top.create_nxgraph(net, respect_switches=False)
        islands = nx.number_connected_components(g)
        if islands > 1:
            warnings.append(f"the network has {islands} separate parts, each with its own infeed or out of service")
    errors.extend(net.get("gaps") or [])  # what the file lacks for a real simulation: refused, never filled
    converged, feasible, reason, cases = False, None, None, []
    if not errors:  # only a complete grid is simulated
        cases = [c.name for c in _study_cases(net)]
        try:
            ok, why, _ = feasibility(net)
        except Exception as e:  # a power flow that errors is a report, not a crash
            ok, why = False, None
            errors.append(f"the power flow failed: {type(e).__name__}: {e}")
        converged = not errors and (why is None or why.type != "non_convergent")
        feasible = bool(ok) if converged else None
        reason = why.message if why is not None else None
        if why is not None and why.type == "non_convergent":
            warnings.append(_non_convergence(net, why.message))
        elif why is not None and why.type != "gsp":
            warnings.append(f"the base case already breaks a limit: {why.message}; every project would be deferred for it")
    if converged:  # the plan grows demand to its last year: a network can collapse there even if today's case solves
        from .network import apply_growth
        m_end = net["forecasts"]["ht"][PLAN_END_YEAR]
        grown = copy.deepcopy(net)
        apply_growth(grown, m_end)  # the Standard forecast, spread as every run spreads it (network.grow_for)
        _, why_grown, _ = feasibility(grown)
        if why_grown is not None and why_grown.type == "non_convergent":
            short = _generation_shortfall(grown)
            cause = (f"its demand of {short[0]:,.0f} MW is more than every power station and the external grid can supply "
                     f"({short[1]:,.0f} MW)" if short else "the grid as described cannot carry that demand")
            warnings.append(f"with demand grown to {PLAN_END_YEAR} (x{m_end:.2f}, the Standard forecast) the power flow does not converge: "
                            f"{cause}; every plan year it fails in is reported as having no solution")
    recorded = [ModelAssumption(**{k: v for k, v in r.items()}, count=len(r.get("element_ids", [])) or None)
                for r in (net["assumptions"].values() if isinstance(net.get("assumptions"), dict) else [])]
    return ValidationReport(ok=not errors, errors=errors, warnings=warnings, counts=counts, islands=islands, converged=converged,
                            feasible=feasible, reason=reason, cases=cases, assumptions=recorded)


def positions(net) -> tuple[dict[int, tuple[float, float]], str]:
    """Where the net's buses sit: the positions the file carries (pandapower `bus.geo` GeoJSON points),
    the rest interpolated between them; a file with none gets a synthetic layout."""
    fixed: dict[int, tuple[float, float]] = {}
    if "geo" in net.bus.columns:
        for b in net.bus.index:
            g = net.bus.at[b, "geo"]
            if _isnan(g):
                continue
            try:
                d = json.loads(g) if isinstance(g, str) else g
                lon, lat = (float(d["coordinates"][0]), float(d["coordinates"][1])) if isinstance(d, dict) else (float(d[0]), float(d[1]))
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            if math.isfinite(lon) and math.isfinite(lat) and (lon, lat) != (0.0, 0.0):
                fixed[int(b)] = (lon, lat)
    if fixed:
        cx = sum(p[0] for p in fixed.values()) / len(fixed)
        cy = sum(p[1] for p in fixed.values()) / len(fixed)
        return interpolate_positions(net, fixed, (cx, cy)), "wgs84"
    return synthetic_positions(net), "synthetic"


# --- sources ----------------------------------------------------------------------------------------------------
class NgedSource:
    """NGED's Bicker Fen GSP from the bundled LTDS/ECR/OSM snapshot (or the tables the pipeline passes):
    the builder in `nged.py`, unchanged, behind the seam."""

    kind = "nged"
    id = "nged-bickerfen"
    name = "NGED Bicker Fen 132 kV GSP"

    def __init__(self, tables=None):
        from . import nged
        self._nged = nged
        self.tables = tables
        self.edition = nged.EDITION_CURRENT

    def build_net(self):
        return self._nged.build_nged_net(self.tables, self.edition)

    def model(self) -> GridModel:
        return GridModel.model_validate(self._nged.nged_model(self.tables, self.edition))

    def candidates(self) -> list[dict]:
        return self._nged.nged_candidates(MAX_CONNECTION_MW, self.tables)

    def boundary(self) -> dict | None:
        return self._nged.gsp_boundary(self.tables)

    def fingerprint(self) -> str:
        return self._nged.tables_hash(self.tables if self.tables is not None else self._nged.load_bundled_tables()) + f":{self.edition}"

    def assumptions(self) -> list[ModelAssumption]:
        recorded = self._nged.builder_assumptions(self.tables, self.edition)
        return recorded + list(self._nged.PLANNING_ASSUMPTIONS)

    def capabilities(self) -> dict:
        return {"boundary": True, "regions": True, "registry": True, "editions": True, "summer_case": True, "crs": "wgs84"}

    def forecasts(self) -> None:
        return None  # NGED plans on the FES pathways (config.FORECASTS)

    @property
    def cgmes_meta(self):
        return self._nged.NGED_CGMES_META


class NetBackedSource:
    """A grid imported from a file: the net after `normalise_net` and `apply_import_meta`, kept
    pristine and deep-copied on every `build_net`; the model shaped by `gridmodel.model_from_net`."""

    def __init__(self, *, id: str, name: str, kind: str, net, meta: ImportMeta | None, fingerprint: str, assumptions: list[ModelAssumption]):
        self.id, self.name, self.kind = id, name, kind
        self.meta = meta
        self._net = net
        self._fingerprint = fingerprint
        self._assumptions = assumptions
        self._model: GridModel | None = None
        self._report: ValidationReport | None = None

    def build_net(self):
        return copy.deepcopy(self._net)

    def model(self) -> GridModel:
        if self._model is None:
            xy, crs = positions(self._net)
            self._model = model_from_net(self._net, xy, fleet_of(self._net), crs)
        return self._model

    def candidates(self) -> list[dict]:
        return []

    def boundary(self) -> dict | None:
        limit = self._net.get("gsp_export_limit_mw")
        if limit is None:
            return None
        return {"gsp_name": self._net.get("gsp_name") or "the external grid", "export_limit_mw": float(limit), "firm_export_mw": float(limit),
                "export_today_mw": _export_today(self.build_net()), "transmission_projects": [],
                "source": "operator-entered at import"}

    def fingerprint(self) -> str:
        return self._fingerprint

    def forecasts(self) -> dict[str, dict[int, float]] | None:
        return self._net.get("forecasts")  # entered at import (apply_import_meta)

    def assumptions(self) -> list[ModelAssumption]:
        return list(self._assumptions)

    def capabilities(self) -> dict:
        from .network import _study_cases

        return {"boundary": self._net.get("gsp_export_limit_mw") is not None, "regions": "region_id" in self._net.load.columns and self._net.load["region_id"].notna().any(),
                "registry": False, "editions": False, "summer_case": any(c.name == "summer_min" for c in _study_cases(self._net)), "crs": self.model().crs}

    def validate(self) -> ValidationReport:
        """The import report (computed once on a fresh copy, so the pristine net keeps no results)."""
        if self._report is None:
            self._report = validate_net(self.build_net())
        return self._report


def _export_today(net) -> float:
    from .network import feasibility
    _, _, m = feasibility(net)
    return float(m.get("gsp_export_mw", 0.0))


def _fingerprint(data: bytes, kind: str, meta: ImportMeta | None) -> str:
    h = hashlib.sha256()
    h.update(data)
    h.update(f"|{kind}|{IMPORTER_VERSION}|{meta.model_dump_json() if meta else ''}".encode())
    return h.hexdigest()[:16]


def from_pandapower_net(net, *, id: str, name: str, kind: str, data: bytes, meta: ImportMeta | None = None) -> NetBackedSource:
    """Any pandapower net as a source: normalised, the operator's limits applied, what is missing stated."""
    assumptions = normalise_net(net, id) + apply_import_meta(net, meta) + inspect_net(net)
    return NetBackedSource(id=id, name=name, kind=kind, net=net, meta=meta, fingerprint=_fingerprint(data, kind, meta), assumptions=assumptions)


def study_levels(net) -> list[dict]:
    """Each voltage level of a grid, highest first, with what an N-1 screen from that level up would cover."""
    from .network import n1_elements
    out = []
    for v in levels_of(net):
        els = n1_elements(net, v - 1e-6)
        out.append({"kv": v, "buses": int((net.bus["vn_kv"].astype(float).round(3) == v).sum()),
                    "n1_lines": sum(1 for k, _ in els if k == "line"), "n1_trafos": sum(1 for k, _ in els if k == "trafo")})
    return out


def inspect_file(filename: str, data: bytes) -> dict:
    """What the import form needs to ask about a file before importing it: its voltage levels (`study_levels`) and
    the voltage-limit presets. Read only: nothing is simulated or kept."""
    net = source_from_file(filename, data, id="inspect", name=filename).build_net()
    presets = [{"id": k, "label": p["label"], "note": p["note"],
                "bands": [{"min_kv": lo_kv, "max_kv": hi_kv, "vmin_pu": lo, "vmax_pu": hi} for lo_kv, hi_kv, lo, hi in p["bands"]]}
               for k, p in VOLTAGE_BAND_PRESETS.items()]
    # the pathways a forecast stands in for, named as the demand picker names them; the default one is required
    pathways = [{"id": p, "label": FORECASTS[p]["short"], "required": p == DEFAULT_SCENARIO} for p in IMPORT_PATHWAYS]
    return {"levels": study_levels(net), "presets": presets, "pathways": pathways, "factor_max": IMPORT_FORECAST_FACTOR_MAX}


def _cgmes_version(xml_heads: list[bytes]) -> str:
    blob = b"".join(h[:4000] for h in xml_heads)
    return "3.0" if b"CIM100" in blob or b"cim17" in blob.lower() else "2.4.15"


def cgmes_source(data: bytes, *, id: str, name: str, meta: ImportMeta | None = None) -> NetBackedSource:
    """A CGMES exchange (a zip of profile XMLs, 2.4.15 or 3.0) through pandapower's CGMES importer."""
    from pandapower.converter.cim.cim2pp.from_cim import from_cim
    with tempfile.TemporaryDirectory() as d:
        paths: list[str] = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if info.is_dir() or not info.filename.lower().endswith(".xml"):
                    continue
                target = Path(d) / Path(info.filename).name
                target.write_bytes(z.read(info))
                paths.append(str(target))
        if not paths:
            raise ValueError("the zip holds no CGMES profile files (.xml)")
        version = _cgmes_version([Path(p).read_bytes() for p in paths])
        net = from_cim(file_list=paths, cgmes_version=version, run_powerflow=False, ignore_errors=True)
    return from_pandapower_net(net, id=id, name=name, kind="cgmes", data=data, meta=meta)


def pandapower_json_source(data: bytes, *, id: str, name: str, meta: ImportMeta | None = None) -> NetBackedSource:
    net = pp.from_json_string(data.decode("utf-8"))
    return from_pandapower_net(net, id=id, name=name, kind="pandapower_json", data=data, meta=meta)


def matpower_source(data: bytes, *, id: str, name: str, meta: ImportMeta | None = None) -> NetBackedSource:
    """A MATPOWER case saved as .mat (pandapower's converter; needs scipy)."""
    from pandapower.converter.matpower import from_mpc
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "case.mat"
        p.write_bytes(data)
        net = from_mpc(str(p))
    return from_pandapower_net(net, id=id, name=name, kind="matpower", data=data, meta=meta)


SOURCES: dict[str, SourceSpec] = {
    "nged": SourceSpec("NGED LTDS open data (bundled)", (), NgedSource),
    "cgmes": SourceSpec("CIM/CGMES exchange (zip of EQ/TP/SSH/GL profiles)", (".zip",), cgmes_source),
    "pandapower_json": SourceSpec("pandapower network (JSON)", (".json",), pandapower_json_source),
    # a MATPOWER case carries no generator technology, so its import is always refused until it can say one (findings #23)
    "matpower": SourceSpec("MATPOWER case (.mat)", (".mat",), matpower_source, offered=False),
}


def import_formats() -> list[dict]:
    """Every source kind as the planner names it, and the extensions the import form offers (`SourceSpec.offered`)."""
    return [{"kind": k, "label": s.label, "extensions": list(s.extensions), "offered": s.offered and bool(s.extensions)}
            for k, s in SOURCES.items()]


def source_kind_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    for kind, spec in SOURCES.items():
        if ext in spec.extensions:
            return kind
    raise ValueError(f"unsupported file type '{ext or filename}'; one of {', '.join(e for s in SOURCES.values() for e in s.extensions)}")


def source_from_file(filename: str, data: bytes, *, id: str, name: str, meta: ImportMeta | None = None) -> NetBackedSource:
    """Import a grid from a file by its extension (the `SOURCES` registry)."""
    return SOURCES[source_kind_for(filename)].factory(data, id=id, name=name, meta=meta)


@lru_cache(maxsize=1)
def default_source() -> NgedSource:
    """The grid the engine runs on when no project is named: NGED's bundled snapshot."""
    return NgedSource()


__all__ = ["GridSource", "SourceSpec", "SOURCES", "NgedSource", "NetBackedSource", "normalise_net", "apply_import_meta", "inspect_net",
           "inspect_file", "study_levels", "levels_of",
           "validate_net", "positions", "from_pandapower_net", "cgmes_source", "pandapower_json_source", "matpower_source",
           "source_kind_for", "source_from_file", "default_source", "import_formats", "SYNTHETIC_CENTER"]
