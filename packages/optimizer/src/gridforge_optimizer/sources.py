"""Where a grid comes from: the `GridSource` seam, and the registry of kinds (`SOURCES`).

Everything the engine needs from a network is behind one small Protocol: a fresh solvable pandapower
net (`build_net`, what every engine function takes as `net_factory`), the geolocated model for the
map (`model`), the optional registry of projects (`candidates`), the GSP boundary card when the
source models one (`boundary`), a content fingerprint (`fingerprint`, the cache baseline) and what
the model had to assume (`assumptions`). NGED's open-data builder is one source (`NgedSource`, zero
behaviour change); a CGMES zip, a pandapower JSON or a MATPOWER case become one through the same
grid-agnostic steps: `normalise_net` (what the engine's columns need), `apply_import_meta` (limits
the operator enters), `inspect_net` (what the file did not carry, stated) and `validate_net`.

Honesty over fake precision: nothing is filled silently. A line a file left unrated gets a rating
that reads as near-zero loading AND an `unrated_lines` assumption saying its loading is not checked;
without seasonal ratings and a minimum-demand factor the summer case is simply not studied; without
an export limit the slack's export is reported, never limited; GB statutory bands and the N-1 scope
are listed as assumptions for every imported grid.
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

from .config import MAX_CONNECTION_MW, N1_MIN_KV, VOLTAGE_BANDS
from .geometry import SYNTHETIC_CENTER, interpolate_positions, synthetic_positions
from .gridmodel import UNRATED_I_KA, fleet_of, model_from_net
from .types import GridModel, ImportMeta, ModelAssumption, ValidationReport

IMPORTER_VERSION = "1"  # bump when normalise_net changes what an imported net looks like (it is in the fingerprint)


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
    def assumptions(self) -> list[ModelAssumption]: ...
    def capabilities(self) -> dict: ...  # {boundary, regions, registry, editions, summer_case, crs}


class SourceSpec(NamedTuple):
    label: str
    extensions: tuple[str, ...]  # file extensions this kind imports ("" for the bundled source)
    factory: Callable[..., GridSource]


# --- the planning assumptions every imported grid is judged under (listed, never hidden) ---------------------------
_GENERIC = {
    "gb_voltage_bands": "Statutory GB voltage bands assumed by level (" + "; ".join(
        f"{lo:.2f}-{hi:.2f} pu from {kv:g} kV" for kv, lo, hi in sorted(VOLTAGE_BANDS, key=lambda b: -b[0])) + "); a non-GB grid may use other limits",
    "n1_scope": f"The N-1 screen covers elements at {N1_MIN_KV:g} kV and above at winter peak; it is reported, never a gate",
    "no_seasonal_ratings": "No seasonal line ratings in the file: the summer-minimum case is not studied unless a summer rating ratio is entered",
    "no_min_demand": "No minimum-demand factor in the file: the summer-minimum case is not studied unless one is entered",
    "no_gsp_limit": "No export limit to the external grid in the file: the slack's export is reported, never limited",
    "no_demand_groups": "No demand groups (firm capacities) in the file: no security-of-supply alerts for customers",
    "no_load_types": "No load types in the file: demand growth is spread without a residential/industrial shape",
    "unrated_lines": "Lines the file left unrated: their loading is NOT checked (shown as unrated), nothing was filled in",
    "slack_from_generator": "The file's slack generator became the external-grid infeed at its voltage set-point",
    "slack_from_largest_generator": "The file had no slack: its largest generator became the external-grid infeed at its voltage set-point",
    "slack_assumed": "The file had no slack and no generator: the best-connected highest-voltage bus became the external-grid infeed at 1.02 pu",
    "gen_to_sgen": "Voltage-controlled generators were made PQ injections (the planning convention here, so voltage problems show); their voltage support is not modelled",
    "taps_enabled": "Transformers with a tap range but no tap-changer type were given a ratio tap changer, regulated as the others are",
    "no_oltc": "No tap range in the file: modelled as a fixed-tap transformer",
    "tech_unknown": "Generators whose technology the file does not name are dispatched as firm in every case",
    "rated_from_dispatch": "Generators are rated at the output the file dispatches them at (a unit's maximum is a limit the fleet never reaches at once); the base case is the file's own dispatch",
    "unsupplied_dropped": "Buses the slack cannot reach were dropped",
    "gsp_limit_entered": "Export limit to the external grid entered by the operator at import",
    "min_demand_entered": "Minimum-demand factor entered by the operator at import, applied to every load",
    "summer_ratio_entered": "Summer rating ratio entered by the operator at import, applied to every line",
    "intermediate_ratio_entered": "Intermediate-season rating ratio entered by the operator at import, applied to every line",
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


def _tech_of(row) -> tuple[str, bool]:
    """(technology, known): from our own CGMES tag, else the type the file gives, else 'other'."""
    desc = str(row.get("description") or "")
    if "gridforge.tech=" in desc:
        return desc.split("gridforge.tech=", 1)[1].split()[0].strip(" ;,"), True
    t = str(row.get("type") or "").strip().lower()
    for k, v in _TECH_FROM_TYPE.items():
        if k in t:
            return v, True
    return "other", False


def _best_connected(net, buses) -> int:
    deg: dict[int, int] = {}
    for a, b in list(zip(net.line.from_bus, net.line.to_bus)) + list(zip(net.trafo.hv_bus, net.trafo.lv_bus)):
        deg[int(a)] = deg.get(int(a), 0) + 1
        deg[int(b)] = deg.get(int(b), 0) + 1
    return max((int(b) for b in buses), key=lambda b: deg.get(b, 0))


def _ensure_slack(net, rec: _Records) -> None:
    if len(net.ext_grid):
        return
    if len(net.gen):
        slack = net.gen[net.gen.get("slack", pd.Series(False, index=net.gen.index)).astype(bool)]
        if len(slack):
            key, rows = "slack_from_generator", slack
        else:
            key, rows = "slack_from_largest_generator", net.gen.loc[[net.gen["p_mw"].astype(float).idxmax()]]
        for i in rows.index:
            pp.create_ext_grid(net, int(net.gen.at[i, "bus"]), vm_pu=float(net.gen.at[i, "vm_pu"]) if "vm_pu" in net.gen.columns else 1.02, name=str(net.gen.at[i, "name"] or "slack"))
        rec.add(key, source="file", element_kind="gen", element_ids=rows.index)
        net.gen.drop(rows.index, inplace=True)
        return
    bus = _best_connected(net, net.bus[net.bus.vn_kv >= float(net.bus.vn_kv.max())].index)
    pp.create_ext_grid(net, bus, vm_pu=1.02, name="external grid")
    rec.add("slack_assumed", element_kind="bus", element_ids=[bus])


def _gens_to_sgens(net, rec: _Records) -> None:
    if not len(net.gen):
        return
    ids = list(net.gen.index)
    for i in ids:
        idx = pp.create_sgen(net, int(net.gen.at[i, "bus"]), p_mw=float(net.gen.at[i, "p_mw"]), q_mvar=0.0,
                             name=str(net.gen.at[i, "name"] or f"generator {i}"), type=str(net.gen.at[i, "type"]) if "type" in net.gen.columns and not _isnan(net.gen.at[i, "type"]) else None)
        if "max_p_mw" in net.gen.columns and not _isnan(net.gen.at[i, "max_p_mw"]):
            net.sgen.at[idx, "max_p_mw"] = float(net.gen.at[i, "max_p_mw"])
    rec.add("gen_to_sgen", element_kind="gen", element_ids=ids)
    net.gen.drop(ids, inplace=True)


def _normalise_sgens(net, rec: _Records) -> None:
    from .network import _ensure_sgen_columns
    _ensure_sgen_columns(net)
    if "fleet_id" not in net.sgen.columns:
        net.sgen["fleet_id"] = pd.Series(dtype=object)
    if "type" not in net.sgen.columns:
        net.sgen["type"] = pd.Series(dtype=object)
    unknown, from_dispatch = [], []
    for i in net.sgen.index:
        rated = net.sgen.at[i, "p_rated_mw"]
        if _isnan(rated):
            # the file's dispatch is the generator's rating here: a file's max_p_mw is a unit limit the whole
            # fleet never reaches at once (case9 dispatches 248 MW of a 550 MW maximum into 315 MW of load)
            p = float(net.sgen.at[i, "p_mw"])
            mx = net.sgen.at[i, "max_p_mw"] if "max_p_mw" in net.sgen.columns else None
            net.sgen.at[i, "p_rated_mw"] = p if p > 0 else (float(mx) if not _isnan(mx) and float(mx) > 0 else 0.0)
            from_dispatch.append(int(i))
        if _isnan(net.sgen.at[i, "import_mw"]):
            net.sgen.at[i, "import_mw"] = float(net.sgen.at[i, "p_rated_mw"])
        if _isnan(net.sgen.at[i, "fleet_id"]):
            net.sgen.at[i, "fleet_id"] = f"EX-{int(i)}"
        tech, known = _tech_of(net.sgen.loc[i])
        net.sgen.at[i, "type"] = tech
        if not known:
            unknown.append(int(i))
    if unknown:
        rec.add("tech_unknown", source="file", element_kind="gen", element_ids=unknown)
    if from_dispatch:
        rec.add("rated_from_dispatch", source="file", element_kind="gen", element_ids=from_dispatch)


def _normalise_trafos(net, rec: _Records) -> None:
    if not len(net.trafo):
        return
    for col, default in (("tap_step_percent", 0.0), ("tap_min", 0), ("tap_max", 0), ("tap_neutral", 0), ("tap_pos", 0), ("tap_side", "hv")):
        if col not in net.trafo.columns:
            net.trafo[col] = default
    if "tap_changer_type" not in net.trafo.columns:
        net.trafo["tap_changer_type"] = None
    enabled, fixed = [], []
    for i in net.trafo.index:
        step = net.trafo.at[i, "tap_step_percent"]
        has_range = not _isnan(step) and float(step) > 0 and not _isnan(net.trafo.at[i, "tap_min"]) and not _isnan(net.trafo.at[i, "tap_max"]) \
            and float(net.trafo.at[i, "tap_max"]) > float(net.trafo.at[i, "tap_min"])
        if has_range:
            if _isnan(net.trafo.at[i, "tap_changer_type"]):
                net.trafo.at[i, "tap_changer_type"] = "Ratio"
                enabled.append(int(i))
            if _isnan(net.trafo.at[i, "tap_pos"]):
                net.trafo.at[i, "tap_pos"] = net.trafo.at[i, "tap_neutral"] if not _isnan(net.trafo.at[i, "tap_neutral"]) else 0
            if _isnan(net.trafo.at[i, "tap_side"]):
                net.trafo.at[i, "tap_side"] = "hv"
        else:
            net.trafo.at[i, "tap_changer_type"] = None
            net.trafo.at[i, "tap_step_percent"] = 0.0
            fixed.append(int(i))
    for col in ("tap_min", "tap_max", "tap_neutral", "tap_pos"):
        net.trafo[col] = pd.to_numeric(net.trafo[col], errors="coerce").fillna(0).astype(int)
    if enabled:
        rec.add("taps_enabled", element_kind="trafo", element_ids=enabled)
    if fixed:
        rec.add("no_oltc", source="file", element_kind="trafo", element_ids=fixed)


def _normalise_lines(net, rec: _Records) -> None:
    if not len(net.line):
        return
    imax = pd.to_numeric(net.line["max_i_ka"], errors="coerce")
    unrated = [int(i) for i in net.line.index[imax.isna() | (imax <= 0)]]
    if unrated:
        net.line.loc[unrated, "max_i_ka"] = UNRATED_I_KA
        rec.add("unrated_lines", source="file", element_kind="line", element_ids=unrated)
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
    _ensure_slack(net, rec)
    _gens_to_sgens(net, rec)
    _normalise_sgens(net, rec)
    _normalise_trafos(net, rec)
    _normalise_lines(net, rec)
    unsupplied = [int(b) for b in top.unsupplied_buses(net) if b not in set(net.ext_grid.bus.astype(int))]
    if unsupplied:
        from pandapower.toolbox import drop_buses
        drop_buses(net, unsupplied)
        rec.add("unsupplied_dropped", source="file", element_kind="bus", element_ids=unsupplied)
    if "name" not in net or not net.name:
        net.name = source_id
    for r in rec.by_key.values():  # the builder-style records studies.data_quality reads
        net["assumptions"][r["key"]] = dict(r)
    return rec.list()


def apply_import_meta(net, meta: ImportMeta | None) -> list[ModelAssumption]:
    """Limits the operator knows and the file did not carry, applied uniformly and recorded as
    operator-entered: an export limit, a minimum-demand factor, seasonal rating ratios."""
    rec = _Records()
    if meta is None:
        return []
    if meta.gsp_export_limit_mw is not None:
        net["gsp_name"] = meta.gsp_name or "the external grid"
        net["gsp_export_limit_mw"] = float(meta.gsp_export_limit_mw)
        net["gsp_sgt_mw"] = float(meta.gsp_export_limit_mw)
        rec.add("gsp_limit_entered", source="operator-entered")
    if meta.min_demand_factor is not None and len(net.load):
        net.load["min_scale"] = float(meta.min_demand_factor)
        rec.add("min_demand_entered", source="operator-entered", element_kind="load", element_ids=net.load.index)
    if meta.summer_rating_ratio is not None and len(net.line):
        net.line["summer_ratio"] = float(meta.summer_rating_ratio)
        rec.add("summer_ratio_entered", source="operator-entered", element_kind="line", element_ids=net.line.index)
    if meta.intermediate_rating_ratio is not None and len(net.line):
        net.line["intermediate_ratio"] = float(meta.intermediate_rating_ratio)
        rec.add("intermediate_ratio_entered", source="operator-entered", element_kind="line", element_ids=net.line.index)
    for r in rec.by_key.values():
        net["assumptions"][r["key"]] = dict(r)
    return rec.list()


def inspect_net(net) -> list[ModelAssumption]:
    """What the net does not carry, stated: the cases it cannot be studied in, the limits it has none of."""
    rec = _Records()
    has = lambda table, col: col in table.columns and table[col].notna().any()  # noqa: E731
    if not has(net.line, "summer_ratio"):
        rec.add("no_seasonal_ratings", source="file")
    if not has(net.load, "min_scale"):
        rec.add("no_min_demand", source="file")
    if net.get("gsp_export_limit_mw") is None:
        rec.add("no_gsp_limit", source="file")
    if not has(net.load, "region_id"):
        rec.add("no_demand_groups", source="file")
    if not has(net.load, "type"):
        rec.add("no_load_types", source="file")
    rec.add("gb_voltage_bands")
    rec.add("n1_scope")
    return rec.list()


def validate_net(net) -> ValidationReport:
    """Can the engine plan on this net? Structural errors first, then one power flow in every case."""
    from .network import _study_cases, feasibility
    errors: list[str] = []
    warnings: list[str] = []
    if not len(net.bus):
        errors.append("the file has no buses")
    if not len(net.ext_grid):
        errors.append("no external-grid infeed (slack) could be placed")
    bad_kv = [int(b) for b in net.bus.index if not float(net.bus.at[b, "vn_kv"]) > 0]
    if bad_kv:
        errors.append(f"{len(bad_kv)} buses have no nominal voltage")
    buses = set(int(b) for b in net.bus.index)
    dangling = [int(i) for i in net.line.index if int(net.line.at[i, "from_bus"]) not in buses or int(net.line.at[i, "to_bus"]) not in buses]
    if dangling:
        errors.append(f"{len(dangling)} lines reference buses that do not exist")
    counts = {"buses": int(len(net.bus)), "lines": int(len(net.line)), "transformers": int(len(net.trafo)), "loads": int(len(net.load)),
              "generators": int(len(net.sgen)), "slacks": int(len(net.ext_grid))}
    islands = 0
    if len(net.bus):
        import networkx as nx
        g = top.create_nxgraph(net, respect_switches=False)
        islands = nx.number_connected_components(g)
        if islands > 1:
            warnings.append(f"the network has {islands} separate parts; those without an infeed were dropped")
    converged, feasible, reason, cases = False, None, None, []
    if not errors:
        cases = [c.name for c in _study_cases(net)]
        try:
            ok, why, _ = feasibility(net)
            converged, feasible = True, bool(ok)
            reason = why.message if why is not None else None
            if why is not None and why.type != "gsp":
                warnings.append(f"the base case already breaks a limit: {why.message}; every project would be deferred for it")
        except Exception as e:  # a non-convergent file is a report, not a crash
            errors.append(f"the power flow did not converge: {type(e).__name__}: {e}")
    if converged:  # the plan grows demand to 2035: a small network can collapse there even if today's case solves
        from .config import DEFAULT_SCENARIO, GROWTH_2035
        from .network import grow_demand
        grown = copy.deepcopy(net)
        grow_demand(grown, GROWTH_2035, DEFAULT_SCENARIO, 2035)
        try:
            pp.runpp(grown)
        except Exception:
            warnings.append(f"with demand grown to 2035 (x{GROWTH_2035:g}, the default pathway) the power flow does not converge: "
                            "every plan year it fails in is reported as non-convergent, and projects rank as if the grid were full")
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

    def __init__(self, tables=None, edition: str | None = None):
        from . import nged
        self._nged = nged
        self.tables = tables
        self.edition = edition or nged.EDITION_CURRENT

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

    def assumptions(self) -> list[ModelAssumption]:
        return list(self._assumptions)

    def capabilities(self) -> dict:
        return {"boundary": self._net.get("gsp_export_limit_mw") is not None, "regions": "region_id" in self._net.load.columns and self._net.load["region_id"].notna().any(),
                "registry": False, "editions": False, "summer_case": "min_scale" in self._net.load.columns, "crs": self.model().crs}

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
    "matpower": SourceSpec("MATPOWER case (.mat)", (".mat",), matpower_source),
}


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
           "validate_net", "positions", "from_pandapower_net", "cgmes_source", "pandapower_json_source", "matpower_source",
           "source_kind_for", "source_from_file", "default_source", "SYNTHETIC_CENTER"]
