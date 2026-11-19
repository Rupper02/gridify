"""A supply point's snapshot, fetched as Bicker Fen's data is, and kept apart from it (Step 4: a second supply point).

MANUAL asset: `uv run dagster asset materialize -m grid_simulator.definitions --select staythorpe_snapshot`. It writes,
under `warehouse/supply-points/<key>/` (git-ignored):
- `tables/`: the LTDS tables filtered by the supply point's own group spellings (`nged_points.SupplyPoint`, never
  matched loosely), the ECR through the same column whitelist (`registers.ECR_KEEP`: no names, addresses, postcodes or
  meter ids), and the DFES power projections of its primaries (the same name rule as `pin_nged_published`);
- `td_limits.json`: its supergrid transformers' published limits;
- `flows-2024/`, `flows-2025/`: its half-hourly substation and branch loading and its bus names, in the layout
  `gridify_optimizer.nged_flows` reads (2025's header rewritten as `nged_flows_2025` does; no value changed);
- `NOTICE.txt` and `fetched.json`.

Nothing goes into the package's bundled data. Supported by NGED Open Data (licence: see `flows.py`).
"""

import json
import re
from datetime import datetime, timezone

import dagster as dg

from grid_simulator.config import WAREHOUSE_DIR
from grid_simulator.defs.flows import BUS_MAP_RESOURCE_ID, NOTICE, _branch_2025_layout, _ckan, _get, _substation_2025_layout
from grid_simulator.defs.registers import ECR_KEEP, ECR_RESOURCE_ID
from gridify_optimizer.nged import DFES_POWER_RESOURCE_ID, LTDS_FAULT_RESOURCE_ID, dfes_esa, dfes_search_term, live_demand_rows
from gridify_optimizer.nged_flows import BRANCH_FILE, BUS_MAP_FILE, SUBSTATION_FILE
from gridify_optimizer.nged_points import STAYTHORPE, SupplyPoint

# NGED's LTDS tabular model: one resource per table for all four licence areas (package ltds-tabular-model)
LTDS_RESOURCES = {
    "circuit": "7892e22f-e489-49fa-a582-b1384006e4e2",  # Table 1
    "t2a": "8c964d61-a7fb-41e7-99b4-6032d063a8c6",  # Table 2a, two-winding transformers
    "t2b": "56033622-8ed7-4425-916c-82a030df4822",  # Table 2b, three-winding transformers (the builder does not read it)
    "demand": "0ac103b3-5ee0-44e0-be31-51cea65aac7c",  # Table 3
    "node": "a92da9e4-2010-4406-b86a-825cd65761d6",  # Attachment 8
    "fault": LTDS_FAULT_RESOURCE_ID,  # Table 4
}
TABLE5_RESOURCE_ID = "f9495346-1484-427c-bd06-e6c242839f6e"
_DFES_COLS = ("ESA", "year", "scenario", "season", "MW_total")


def _rows(rid: str, filters: dict) -> list[dict]:
    recs = _ckan("datastore_search", resource_id=rid, limit=32000, filters=json.dumps(filters))["records"]
    return [{k: v for k, v in r.items() if k not in ("_id", "rank")} for r in recs]


def fetch_supply_point(point: SupplyPoint, context=None) -> dict:
    """Everything one supply point is built and commissioned from, into its own warehouse folder. Returns the metadata."""
    log = context.log.info if context else print
    root = WAREHOUSE_DIR / "supply-points" / point.key
    (root / "tables").mkdir(parents=True, exist_ok=True)
    meta: dict = {"supply_point": point.key, "tables": {}}
    tables: dict[str, list[dict]] = {}
    for name, rid in LTDS_RESOURCES.items():
        tables[name] = _rows(rid, {"GSP Group": point.ltds_group})
        meta["tables"][name] = {"resource": rid, "filter": {"GSP Group": point.ltds_group}, "rows": len(tables[name])}
    tables["gen"] = _rows(TABLE5_RESOURCE_ID, {"GSP Group": point.table5_group})
    meta["tables"]["gen"] = {"resource": TABLE5_RESOURCE_ID, "filter": {"GSP Group": point.table5_group}, "rows": len(tables["gen"])}
    ecr = _rows(ECR_RESOURCE_ID, {"grid_supply_point": point.ecr_gsp})
    tables["ecr"] = [{k: r.get(k) for k in ECR_KEEP} for r in ecr]
    meta["tables"]["ecr"] = {"resource": ECR_RESOURCE_ID, "filter": {"grid_supply_point": point.ecr_gsp}, "rows": len(ecr),
                             "columns_kept": list(ECR_KEEP)}
    # DFES power projections for its primaries: the same rule as pin_nged_published (a search per primary, then the name match)
    primaries = sorted({re.sub(r"\s*\([^)]*\)", "", str(d.get("Primary Substation") or "")).strip()
                        for d in live_demand_rows(tables["demand"], point=point)} - {"", "-"})
    dfes: dict[tuple, dict] = {}
    matched: dict[str, str] = {}
    for name in primaries:
        recs = _ckan("datastore_search", resource_id=DFES_POWER_RESOURCE_ID, limit=2000, q=dfes_search_term(name))["records"]
        esa = dfes_esa(name, {r["ESA"] for r in recs})
        if esa is None:
            continue
        matched[name] = esa
        for r in recs:
            if r["ESA"] == esa:
                dfes[(r["ESA"], r["year"], r["scenario"], r["season"])] = {c: r.get(c) for c in _DFES_COLS}
    tables["dfes"] = sorted(dfes.values(), key=lambda r: (r["ESA"], r["scenario"], r["year"]))
    meta["tables"]["dfes"] = {"resource": DFES_POWER_RESOURCE_ID, "rows": len(tables["dfes"]), "matched": matched,
                              "unmatched": [p for p in primaries if p not in matched]}
    for name, rows in tables.items():
        (root / "tables" / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
    td = _rows(point.td_limits_resource, {})
    (root / "td_limits.json").write_text(json.dumps(td, indent=1), encoding="utf-8")
    meta["td_limits"] = {"resource": point.td_limits_resource, "rows": len(td)}
    # the half-hourly loading, both years, and its bus names
    bus_map = _ckan("datastore_search", resource_id=BUS_MAP_RESOURCE_ID, limit=5000, filters=json.dumps({"grid_supply_point": point.flows_gsp}))["records"]
    for year, (sub_id, br_id) in sorted(point.flows_resources.items()):
        folder = root / f"flows-{year}"
        folder.mkdir(exist_ok=True)
        for rid, name, layout in ((sub_id, SUBSTATION_FILE, _substation_2025_layout if year >= 2025 else None),
                                  (br_id, BRANCH_FILE, _branch_2025_layout if year >= 2025 else None)):
            res = _ckan("resource_show", id=rid)
            body = _get(res["url"])
            (folder / name).write_bytes(layout(body) if layout else body)
            meta[f"flows-{year}/{name}"] = {"resource": rid, "name": res.get("name"), "url": res["url"], "last_modified": res.get("last_modified"),
                                            "bytes_published": len(body), "layout": "rewritten to 2024's header; values unchanged" if layout else "as published"}
        (folder / BUS_MAP_FILE).write_text(json.dumps(bus_map), encoding="utf-8")
        (folder / "NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    meta[BUS_MAP_FILE] = {"resource": BUS_MAP_RESOURCE_ID, "filter": {"grid_supply_point": point.flows_gsp}, "rows": len(bus_map)}
    (root / "NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    meta["fetched_at"] = datetime.now(timezone.utc).isoformat()
    (root / "fetched.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    log(f"fetched {point.key}: " + json.dumps({k: v.get("rows") for k, v in meta["tables"].items()}))
    return meta


@dg.asset(group_name="registers", kinds={"ckan"})
def staythorpe_snapshot(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    """MANUAL: Staythorpe's LTDS tables, ECR, DFES rows, supply-point limits and 2024/2025 half-hourly loading into the
    git-ignored `warehouse/supply-points/staythorpe/` (Step 4, the second supply point)."""
    meta = fetch_supply_point(STAYTHORPE, context)
    return dg.MaterializeResult(metadata={"folder": str(WAREHOUSE_DIR / "supply-points" / STAYTHORPE.key),
                                          "tables": dg.MetadataValue.json({k: v["rows"] for k, v in meta["tables"].items()})})
