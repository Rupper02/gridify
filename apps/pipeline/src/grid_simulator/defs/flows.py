"""NGED's half-hourly flows for Bicker Fen (its curtailment-analysis data), fetched for the measured year (step 1).

MANUAL asset: `uv run dagster asset materialize -m grid_simulator.definitions --select nged_flows`. It writes the three
files `gridify_optimizer.nged_flows` reads into `warehouse/nged-flows/bicker-fen-2024/`, which git ignores: they are
~23 MB, so they are fetched, not committed (repository size, not licence).

Licence: NGED Open Data Licence (December 2020 version, based on the Open Government Licence v3.0; the portal tags the
packages `wpd-open-data`). It allows copying, adaptation and commercial use on two conditions: the statement
"Supported by NGED Open Data" wherever the data is used, and nothing suggesting NGED endorses Gridify. NGED gives no
warranty. A NOTICE file with this text is written next to the data.
"""

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import dagster as dg

from grid_simulator.config import WAREHOUSE_DIR
from gridify_optimizer.nged_flows import BRANCH_FILE, BUS_MAP_FILE, SUBSTATION_FILE
from gridify_optimizer.nged_points import BICKER_FEN

FLOWS_DIR = WAREHOUSE_DIR / "nged-flows" / "bicker-fen-2024"
CKAN = "https://connecteddata.nationalgrid.co.uk/api/3/action/"
UA = "gridify/0.2 (grid planning research)"
# Connected Data Portal resources: the 2024 historic year ("ID 319"), and NGED's bus numbers -> names
SUBSTATION_RESOURCE_ID, BRANCH_RESOURCE_ID = BICKER_FEN.flows_resources[2024]  # "Bicker Fen Substation Load" / "Branch Load"
BUS_MAP_RESOURCE_ID = "6ba4ccd6-a9f8-405e-a3cf-45c79de9f16e"  # "Bus Mapping", package curtailment_buses
GSP = BICKER_FEN.flows_gsp
NOTICE = ("Supported by NGED Open Data.\n\nNGED Open Data Licence (December 2020 version, based on the Open Government "
          "Licence v3.0): copying, adaptation and commercial use are allowed on condition that this statement appears "
          "wherever the data is used and that nothing suggests NGED endorses the user. NGED gives no warranty for the data.\n")


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=300) as r:
        return r.read()


def _ckan(action: str, **params) -> dict:
    return json.loads(_get(CKAN + action + "?" + urllib.parse.urlencode(params)))["result"]


@dg.asset(group_name="registers", kinds={"ckan"})
def nged_flows(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    """MANUAL: NGED's 2024 half-hourly substation and branch loading for Bicker Fen, and its bus names, into the
    git-ignored warehouse folder the measured year reads (`gridify_optimizer.timeseries`)."""
    FLOWS_DIR.mkdir(parents=True, exist_ok=True)
    meta = {}
    for rid, name in ((SUBSTATION_RESOURCE_ID, SUBSTATION_FILE), (BRANCH_RESOURCE_ID, BRANCH_FILE)):
        res = _ckan("resource_show", id=rid)
        body = _get(res["url"])
        (FLOWS_DIR / name).write_bytes(body)
        meta[name] = {"resource": rid, "url": res["url"], "last_modified": res.get("last_modified"), "bytes": len(body)}
    recs = _ckan("datastore_search", resource_id=BUS_MAP_RESOURCE_ID, limit=5000,
                 filters=json.dumps({"grid_supply_point": GSP}))["records"]
    (FLOWS_DIR / BUS_MAP_FILE).write_text(json.dumps(recs), encoding="utf-8")
    meta[BUS_MAP_FILE] = {"resource": BUS_MAP_RESOURCE_ID, "rows": len(recs)}
    (FLOWS_DIR / "NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    (FLOWS_DIR / "fetched.json").write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), **meta}, indent=1), encoding="utf-8")
    context.log.info("fetched %s", {k: v.get("bytes", v.get("rows")) for k, v in meta.items()})
    return dg.MaterializeResult(metadata={"folder": str(FLOWS_DIR), "files": dg.MetadataValue.json(meta)})


# A second measured year (Work 12; README register "A second measured year: 2025"): NGED's 2025 historic year, "2025
# Connected Export (ID 1124)", published in a different layout from 2024's. Written in 2024's layout; no value changes.
FLOWS_2025_DIR = WAREHOUSE_DIR / "nged-flows" / "bicker-fen-2025"
SUBSTATION_2025_ID, BRANCH_2025_ID = BICKER_FEN.flows_resources[2025]  # "Bicker Fen - 2025 Connected Export (ID 1124)"


def _substation_2025_layout(body: bytes) -> bytes:
    """2025's three header rows (units, bus number, bus name) -> 2024's one ("Power Units_Bus Number", "MW_<bus>", ...)."""
    lines = body.decode("utf-8-sig").splitlines()
    units, buses = lines[0].split(","), lines[1].split(",")
    if units[0] != "Power Units" or buses[0] != "Bus Number" or not lines[2].startswith("Bus Name"):
        raise ValueError("unexpected header in NGED's 2025 substation file")
    head = "Power Units_Bus Number," + ",".join(f"{u}_{b}" for u, b in zip(units[1:], buses[1:]))
    return ("\n".join([head, *lines[3:]]) + "\n").encode("utf-8")


def _branch_2025_layout(body: bytes) -> bytes:
    """2025's second row (the branches' names, first cell empty) dropped: 2024's file has one header row."""
    lines = body.decode("utf-8-sig").splitlines()
    if not lines[1].startswith(","):
        raise ValueError("unexpected header in NGED's 2025 branch file")
    return ("\n".join([lines[0], *lines[2:]]) + "\n").encode("utf-8")


@dg.asset(group_name="registers", kinds={"ckan"})
def nged_flows_2025(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    """MANUAL: NGED's 2025 half-hourly substation and branch loading for Bicker Fen, and its bus names, into
    `warehouse/nged-flows/bicker-fen-2025/` in the layout `gridify_optimizer.nged_flows` reads."""
    FLOWS_2025_DIR.mkdir(parents=True, exist_ok=True)
    meta = {}
    for rid, name, layout in ((SUBSTATION_2025_ID, SUBSTATION_FILE, _substation_2025_layout),
                              (BRANCH_2025_ID, BRANCH_FILE, _branch_2025_layout)):
        res = _ckan("resource_show", id=rid)
        body = _get(res["url"])
        (FLOWS_2025_DIR / name).write_bytes(layout(body))
        meta[name] = {"resource": rid, "name": res.get("name"), "url": res["url"], "last_modified": res.get("last_modified"),
                      "bytes_published": len(body), "layout": "rewritten to 2024's header; values unchanged"}
    recs = _ckan("datastore_search", resource_id=BUS_MAP_RESOURCE_ID, limit=5000,
                 filters=json.dumps({"grid_supply_point": GSP}))["records"]
    (FLOWS_2025_DIR / BUS_MAP_FILE).write_text(json.dumps(recs), encoding="utf-8")
    meta[BUS_MAP_FILE] = {"resource": BUS_MAP_RESOURCE_ID, "rows": len(recs)}
    (FLOWS_2025_DIR / "NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    (FLOWS_2025_DIR / "fetched.json").write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), **meta}, indent=1), encoding="utf-8")
    context.log.info("fetched %s", {k: v.get("bytes_published", v.get("rows")) for k, v in meta.items()})
    return dg.MaterializeResult(metadata={"folder": str(FLOWS_2025_DIR), "files": dg.MetadataValue.json(meta)})


# NGED's DFES 2025 in full, for the demand-shape study (Work 8; docs/reports/grown-year-2026-11-13/scoping-demand-shape.md).
# The portal's preview of these resources is partial (the profiles' preview has no heat-pump row), so the files are fetched
# whole. Same licence and notice as the flows: the portal labels the package "WPD Open Data Licence", the licence's name
# before WPD became NGED; the owner supplied its text (NGED Open Data Licence, December 2020).
DFES_DIR = WAREHOUSE_DIR / "nged-flows" / "dfes-2025"
DFES_RESOURCES = {
    "dfes_profiles.csv": "bc4bfcb3-6ec3-400e-a4c3-3f73e3627802",  # half-hourly per-unit profiles, five representative days
    "dfes_profile_splits.csv": "2a85581e-ceac-4b0f-ba9d-9d69b4e8db9f",  # unabated / flexed share by technology, scenario, year
    "dfes_annual_scaling.csv": "7448e109-7a77-467e-b5a9-4e9a313afb94",  # a factor per profile, technology, year, scenario, area
    "dfes_power_projections.csv": "7686c0a8-bde8-4a4b-8f26-50a3317882ee",  # peak MW per ESA, scenario, year, season
    "dfes_volumes_esa.zip": "95c1a397-11f9-42dd-a1a7-401802de4f62",  # volumes per Electricity Supply Area
}


@dg.asset(group_name="registers", kinds={"ckan"})
def nged_dfes_detail(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    """MANUAL: NGED's DFES 2025 profiles, profile splits, annual scaling, power projections and supply-area volumes, whole,
    into the git-ignored warehouse folder (about 110 MB): the inputs of the demand-shape study."""
    DFES_DIR.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name, rid in DFES_RESOURCES.items():
        res = _ckan("resource_show", id=rid)
        body = _get(res["url"])
        (DFES_DIR / name).write_bytes(body)
        meta[name] = {"resource": rid, "name": res.get("name"), "url": res["url"], "last_modified": res.get("last_modified"), "bytes": len(body)}
    (DFES_DIR / "NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    (DFES_DIR / "fetched.json").write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), **meta}, indent=1), encoding="utf-8")
    context.log.info("fetched %s", {k: v["bytes"] for k, v in meta.items()})
    return dg.MaterializeResult(metadata={"folder": str(DFES_DIR), "files": dg.MetadataValue.json(meta)})
