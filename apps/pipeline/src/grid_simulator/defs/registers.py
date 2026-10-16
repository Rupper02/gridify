"""Live register ingestion: the sources the bundled snapshot is pinned from.

Two external registers change on their own clock, so they are fetched on a schedule, stored as
append-only EDITIONS in the warehouse (one row per fetch whose content differs from the last) and
diffed edition-to-edition. Nothing here touches the model the engine runs on: that stays pinned
to the bundled snapshot until someone runs the `pin_*` assets, which promote the latest edition
into `gridify_optimizer/data/nged/` (a reviewable, committable change).

  ecr_register_fetch  ->  ecr_editions  ->  ecr_changes        (monthly: NGED republishes the ECR)
  osm_substations_fetch  ->  coords_editions                   (quarterly: positions rarely move)
  pin_ecr_edition / pin_osm_coords                             (manual: adopt an edition)

Provenance kept per edition: fetched_at, the source's own last_modified (CKAN), resource id, row
count and a content hash (the edition id). The register's customer-name, address, postcode and
MPAN/MSID columns are dropped at the fetch boundary. `customer_site` is kept as NGED publishes it:
for small sites it is often a property name or an address, sometimes with a postcode.
"""

import csv
import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import dagster as dg
import duckdb

from grid_simulator.config import DB_PATH
from gridify_optimizer.editions import diff_ecr_editions, ecr_site_key
from gridify_optimizer.nged import (
    BUNDLED_DATA_DIR,
    DFES_POWER_RESOURCE_ID,
    LTDS_FAULT_RESOURCE_ID,
    LTDS_GSP_GROUP,
    dfes_esa,
    load_bundled_coords,
    load_bundled_tables,
    substation_names,
)

# who is asking, honestly: NGED's portal refuses Python's default agent (403) but serves a named one
UA = "gridify/0.2 (grid planning research)"
CKAN = "https://connecteddata.nationalgrid.co.uk/api/3/action/"
ECR_RESOURCE_ID = "82a4ae83-77a3-4e7b-9060-8072ed96de9d"
ECR_GSP = "Bicker Fen 132Kv S Stn"
# the columns the model needs; not the customer-name, address, postcode or MPAN/MSID columns
# (`customer_site` is kept as published and can name a property)
ECR_KEEP = [
    "reference", "customer_site", "grid_supply_point", "bulk_supply_point", "primary",
    "point_of_connection(poc)_voltage(kv)", "energy_source_1", "Energy Conversion Technology 1",
    "energy_source_2", "storage_capacity_1(mwh)", "flexible_connection (Yes/No)", "connection_status",
    "connected_maximum_export_capacity(mw)", "accepted_to_connect_registered_capacity(mw)",
    "accepted_change_to_maximum_export_capacity(mw)", "accepted_change_to_maximum_import_capacity(mw)",
    "date_accepted", "target_energisation_date", "date_connected", "in_a_connection_queue(y/n)",
    "transmission_reinforcement_reference", "last_updated", "lat", "lon",
]
OSM_BBOX = (52.6, -0.9, 53.45, 0.45)  # south, west, north, east: the Bicker Fen GSP region
OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter")
_WRITER_RETRY = dg.RetryPolicy(max_retries=3, delay=5)
_FETCH_RETRY = dg.RetryPolicy(max_retries=2, delay=120)  # public mirrors have bad minutes; a scheduled fetch should ride them out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(rows: list, key_fn=None) -> str:
    """Order-independent content fingerprint: the same rows in any order give the same edition id."""
    ordered = sorted(rows, key=key_fn) if key_fn else rows
    return hashlib.sha256(json.dumps(ordered, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _norm_coords(rows: list[dict]) -> list[dict]:
    """Coords rows with numeric lat/lon, whether they came from the CSV (strings) or Overpass (floats)."""
    out = []
    for r in rows:
        try:
            out.append({"name": str(r["name"]), "latitude": round(float(r["latitude"]), 6),
                        "longitude": round(float(r["longitude"]), 6), "source": str(r.get("source") or "")})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _ckan(action: str, **params) -> dict:
    url = CKAN + action + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
        return json.load(r)["result"]


# ---- edition store -------------------------------------------------------------------------------
def _editions_schema(conn: duckdb.DuckDBPyConnection, name: str) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {name}_editions (edition_id VARCHAR PRIMARY KEY, fetched_at VARCHAR, "
        "source VARCHAR, source_last_modified VARCHAR, row_count INTEGER, note VARCHAR)"
    )
    conn.execute(f"CREATE TABLE IF NOT EXISTS {name}_edition_rows (edition_id VARCHAR, row_key VARCHAR, row_json VARCHAR)")


def _store_edition(conn, name: str, rows: list[dict], *, fetched_at: str, source: str, source_last_modified: str | None,
                   note: str, key_fn) -> tuple[str, bool]:
    """Insert `rows` as a new edition unless an edition with the same content already exists.
    Returns (edition_id, inserted)."""
    _editions_schema(conn, name)
    edition_id = _content_hash(rows, key_fn)
    if conn.execute(f"SELECT 1 FROM {name}_editions WHERE edition_id = ?", [edition_id]).fetchone():
        return edition_id, False
    conn.execute(
        f"INSERT INTO {name}_editions VALUES (?, ?, ?, ?, ?, ?)",
        [edition_id, fetched_at, source, source_last_modified, len(rows), note],
    )
    if rows:
        conn.executemany(
            f"INSERT INTO {name}_edition_rows VALUES (?, ?, ?)",
            [[edition_id, key_fn(r), json.dumps(r, default=str)] for r in rows],
        )
    return edition_id, True


def _seed_bundled_edition(conn, name: str, rows: list[dict], key_fn, path) -> None:
    """The first edition in the store is the bundled snapshot, so the first live fetch has a baseline."""
    _editions_schema(conn, name)
    if conn.execute(f"SELECT count(*) FROM {name}_editions").fetchone()[0] == 0:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat() if path.exists() else _now()
        _store_edition(conn, name, rows, fetched_at=mtime, source=f"bundled snapshot {path.name}", source_last_modified=None,
                       note="pinned snapshot shipped with the repo", key_fn=key_fn)


def _latest_editions(conn, name: str, n: int = 2) -> list[dict]:
    rows = conn.execute(
        f"SELECT edition_id, fetched_at, source, source_last_modified, row_count FROM {name}_editions ORDER BY fetched_at DESC LIMIT ?",
        [n],
    ).fetchall()
    return [dict(zip(("edition_id", "fetched_at", "source", "source_last_modified", "row_count"), r)) for r in rows]


def _edition_rows(conn, name: str, edition_id: str) -> list[dict]:
    return [json.loads(r[0]) for r in conn.execute(f"SELECT row_json FROM {name}_edition_rows WHERE edition_id = ?", [edition_id]).fetchall()]


# ---- the Embedded Capacity Register --------------------------------------------------------------
@dg.asset(group_name="registers", kinds={"ckan"}, retry_policy=_FETCH_RETRY)
def ecr_register_fetch(context: dg.AssetExecutionContext) -> dict:
    """Fetch NGED's Embedded Capacity Register rows for the Bicker Fen GSP from the Connected Data
    Portal (CKAN). Keeps only the columns the model needs (`ECR_KEEP`; the metadata lists the
    columns dropped) and records the source's own last-modified stamp alongside the fetch time."""
    meta = _ckan("resource_show", id=ECR_RESOURCE_ID)
    recs = _ckan("datastore_search", resource_id=ECR_RESOURCE_ID, limit=5000,
                 filters=json.dumps({"grid_supply_point": ECR_GSP}))["records"]
    rows = [{k: rec.get(k) for k in ECR_KEEP} for rec in recs]
    rows.sort(key=lambda x: (x["connection_status"] or "", ecr_site_key(x)))
    by_status: dict[str, int] = {}
    for x in rows:
        by_status[str(x["connection_status"])] = by_status.get(str(x["connection_status"]), 0) + 1
    out = {"rows": rows, "fetched_at": _now(), "resource_id": ECR_RESOURCE_ID,
           "source_last_modified": meta.get("last_modified"), "content_hash": _content_hash(rows, ecr_site_key)}
    context.add_output_metadata({"rows": len(rows), "by_status": dg.MetadataValue.json(by_status),
                                 "source_last_modified": str(meta.get("last_modified")), "content_hash": out["content_hash"],
                                 "columns_dropped": dg.MetadataValue.json(sorted({k for rec in recs for k in rec} - {"_id", *ECR_KEEP}))})
    return out


@dg.asset(group_name="registers", kinds={"duckdb"}, retry_policy=_WRITER_RETRY)
def ecr_editions(context: dg.AssetExecutionContext, ecr_register_fetch: dict) -> str:
    """Append the fetch to the edition store if its content is new. Returns the edition id (a content
    hash). The bundled snapshot is seeded as the first edition, so there is always a baseline."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DB_PATH))
    try:
        _seed_bundled_edition(conn, "ecr", load_bundled_tables()["ecr"], ecr_site_key, BUNDLED_DATA_DIR / "ecr.json")
        edition_id, inserted = _store_edition(
            conn, "ecr", ecr_register_fetch["rows"], fetched_at=ecr_register_fetch["fetched_at"],
            source=f"CKAN datastore_search resource {ecr_register_fetch['resource_id']}",
            source_last_modified=ecr_register_fetch["source_last_modified"], note="scheduled fetch", key_fn=ecr_site_key,
        )
        history = conn.execute("SELECT count(*) FROM ecr_editions").fetchone()[0]
    finally:
        conn.close()
    context.add_output_metadata({"edition_id": edition_id, "inserted": inserted, "editions_in_store": int(history)})
    return edition_id


@dg.asset(group_name="registers", kinds={"duckdb"}, retry_policy=_WRITER_RETRY)
def ecr_changes(context: dg.AssetExecutionContext, ecr_editions: str) -> dict:
    """Diff the latest ECR edition against the one before it: sites added, withdrawn, connected, or
    changed in capacity / target date. Written to `ecr_changes` (history kept per edition pair)."""
    conn = duckdb.connect(str(DB_PATH))
    try:
        latest = _latest_editions(conn, "ecr", 2)
        cur = latest[0]
        prev = latest[1] if len(latest) > 1 else None
        changes = diff_ecr_editions(_edition_rows(conn, "ecr", prev["edition_id"]), _edition_rows(conn, "ecr", cur["edition_id"])) if prev else []
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ecr_changes (edition_id VARCHAR, prev_edition_id VARCHAR, computed_at VARCHAR, "
            "change VARCHAR, site VARCHAR, site_key VARCHAR, energy_source VARCHAR, status VARCHAR, export_mw DOUBLE, "
            "target_energisation_date VARCHAR, detail VARCHAR)"
        )
        conn.execute("DELETE FROM ecr_changes WHERE edition_id = ? AND prev_edition_id IS NOT DISTINCT FROM ?",
                     [cur["edition_id"], prev["edition_id"] if prev else None])
        now = _now()
        if changes:
            conn.executemany(
                "INSERT INTO ecr_changes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [[cur["edition_id"], prev["edition_id"] if prev else None, now, c["change"], c["site"], c["site_key"],
                  c["energy_source"], c["status"], c["export_mw"], c["target_energisation_date"], c["detail"]] for c in changes],
            )
    finally:
        conn.close()
    counts: dict[str, int] = {}
    for c in changes:
        counts[c["change"]] = counts.get(c["change"], 0) + 1
    preview = "\n".join(f"- **{c['change']}** {c['site']}: {c['detail']}" for c in changes[:12]) or "_no changes_"
    context.add_output_metadata({
        "edition_id": cur["edition_id"], "previous_edition_id": prev["edition_id"] if prev else "none",
        "changes": len(changes), "by_change": dg.MetadataValue.json(counts), "preview": dg.MetadataValue.md(preview),
    })
    return {"edition_id": cur["edition_id"], "previous_edition_id": prev["edition_id"] if prev else None, "changes": changes}


@dg.asset(group_name="registers", kinds={"json"})
def pin_ecr_edition(context: dg.AssetExecutionContext, ecr_editions: str) -> dg.MaterializeResult:
    """MANUAL: promote the latest ECR edition into the bundled snapshot the engine runs on
    (`data/nged/ecr.json`). Review the resulting git diff, re-materialise `ltds_tables*`, commit."""
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        rows = _edition_rows(conn, "ecr", ecr_editions)
    finally:
        conn.close()
    dst = BUNDLED_DATA_DIR / "ecr.json"
    dst.write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
    context.log.info("pinned ECR edition %s -> %s (%d rows)", ecr_editions, dst, len(rows))
    return dg.MaterializeResult(metadata={"edition_id": ecr_editions, "rows": len(rows), "path": str(dst)})


# ---- the published tables beside the LTDS model: fault levels and the DFES projections ----------------------
_DFES_COLS = ("ESA", "year", "scenario", "season", "MW_total")


@dg.asset(group_name="registers", kinds={"ckan"}, retry_policy=_FETCH_RETRY)
def pin_nged_published(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    """MANUAL: fetch the published tables the engine reads beside the LTDS model and write them into the bundled
    snapshot: LTDS Table 4 fault levels for the GSP group (`data/nged/fault.json`: system impedance, NGED's make and
    break currents and the switchgear ratings per node) and the DFES power projections for every primary in Table 3
    (`data/nged/dfes.json`: winter peak MW per supply area, scenario and year). Review the git diff, re-materialise
    `ltds_tables*`, commit."""
    fault = _ckan("datastore_search", resource_id=LTDS_FAULT_RESOURCE_ID, limit=5000, filters=json.dumps({"GSP Group": LTDS_GSP_GROUP}))["records"]
    fault = [{k: v for k, v in r.items() if k not in ("_id", "rank")} for r in fault]
    primaries = sorted({re.sub(r"\s*\([^)]*\)", "", str(d.get("Primary Substation") or "")).strip() for d in load_bundled_tables()["demand"]
                        if d.get("Status") != "Removed"} - {"", "-"})
    rows: dict[tuple, dict] = {}
    matched: dict[str, str] = {}
    for name in primaries:
        recs = _ckan("datastore_search", resource_id=DFES_POWER_RESOURCE_ID, limit=2000, q=name.split()[0])["records"]
        esa = dfes_esa(name, {r["ESA"] for r in recs})
        if esa is None:
            continue
        matched[name] = esa
        for r in recs:
            if r["ESA"] == esa:
                rows[(r["ESA"], r["year"], r["scenario"], r["season"])] = {c: r.get(c) for c in _DFES_COLS}
    dfes = sorted(rows.values(), key=lambda r: (r["ESA"], r["scenario"], r["year"]))
    (BUNDLED_DATA_DIR / "fault.json").write_text(json.dumps(fault, ensure_ascii=False, indent=0), encoding="utf-8")
    (BUNDLED_DATA_DIR / "dfes.json").write_text(json.dumps(dfes, ensure_ascii=False, indent=0), encoding="utf-8")
    context.log.info("pinned %d fault-level rows and %d DFES rows (%d of %d primaries matched a supply area)", len(fault), len(dfes), len(matched), len(primaries))
    return dg.MaterializeResult(metadata={"fault_rows": len(fault), "dfes_rows": len(dfes), "esas": dg.MetadataValue.json(matched),
                                          "unmatched": [p for p in primaries if p not in matched], "fetched_at": _now()})


# ---- OpenStreetMap substation positions ------------------------------------------------------------
def _osm_key(name: str) -> str:
    n = re.sub(r"\b(substation|grid|primary|bsp|s\.? ?stn|33kv|132kv|11kv|local|main)\b", "", (name or "").lower())
    return " ".join(re.sub(r"[^a-z ]", " ", n).split())


@dg.asset(group_name="registers", kinds={"api"}, retry_policy=_FETCH_RETRY)
def osm_substations_fetch(context: dg.AssetExecutionContext) -> dict:
    """Geocode the network's substations from OpenStreetMap (Overpass): named power substations in
    the GSP's bounding box, matched to the network's substation names after stripping words like
    'Substation'. Data © OpenStreetMap contributors, ODbL."""
    query = (f"[out:json][timeout:90];\nnwr[\"power\"=\"substation\"][\"name\"]"
             f"({OSM_BBOX[0]},{OSM_BBOX[1]},{OSM_BBOX[2]},{OSM_BBOX[3]});\nout center tags;")
    elements = None
    errors = []
    for ep in OVERPASS:
        try:
            req = urllib.request.Request(ep, data=urllib.parse.urlencode({"data": query}).encode(),
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=150) as r:
                elements = json.load(r)["elements"]
            break
        except Exception as e:  # mirrors are flaky: try the next one
            errors.append(f"{ep}: {e}")
    if elements is None:
        raise RuntimeError("no Overpass endpoint answered: " + "; ".join(errors))
    osm: dict[str, dict] = {}
    for e in elements:
        c = e.get("center") or {"lat": e.get("lat"), "lon": e.get("lon")}
        k = _osm_key(e["tags"]["name"])
        if k and c.get("lat") is not None:
            osm.setdefault(k, {"name": e["tags"]["name"], "lat": c["lat"], "lon": c["lon"]})
    subs = substation_names()
    rows = _norm_coords([{"name": s, "latitude": osm[_osm_key(s)]["lat"], "longitude": osm[_osm_key(s)]["lon"],
                          "source": f"OpenStreetMap: {osm[_osm_key(s)]['name']}"} for s in subs if _osm_key(s) in osm])
    unmatched = [s for s in subs if _osm_key(s) not in osm]
    key = lambda r: str(r.get("name"))
    out = {"rows": rows, "fetched_at": _now(), "osm_named_substations": len(elements), "content_hash": _content_hash(rows, key)}
    context.add_output_metadata({"osm_named_substations": len(elements), "network_substations": len(subs),
                                 "matched": len(rows), "unmatched": dg.MetadataValue.json(unmatched),
                                 "content_hash": out["content_hash"], "licence": "ODbL, © OpenStreetMap contributors"})
    return out


@dg.asset(group_name="registers", kinds={"duckdb"}, retry_policy=_WRITER_RETRY)
def coords_editions(context: dg.AssetExecutionContext, osm_substations_fetch: dict) -> str:
    """Append the geocoding result to the coords edition store if its content is new."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DB_PATH))
    try:
        _seed_bundled_edition(conn, "coords", _norm_coords(load_bundled_coords()), lambda r: str(r.get("name")), BUNDLED_DATA_DIR / "coords.csv")
        edition_id, inserted = _store_edition(
            conn, "coords", osm_substations_fetch["rows"], fetched_at=osm_substations_fetch["fetched_at"],
            source="OpenStreetMap Overpass", source_last_modified=None, note="scheduled fetch", key_fn=lambda r: str(r.get("name")),
        )
        history = conn.execute("SELECT count(*) FROM coords_editions").fetchone()[0]
    finally:
        conn.close()
    context.add_output_metadata({"edition_id": edition_id, "inserted": inserted, "editions_in_store": int(history)})
    return edition_id


@dg.asset(group_name="registers", kinds={"csv"})
def pin_osm_coords(context: dg.AssetExecutionContext, coords_editions: str) -> dg.MaterializeResult:
    """MANUAL: promote the latest coords edition into the bundled `data/nged/coords.csv`."""
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        rows = _edition_rows(conn, "coords", coords_editions)
    finally:
        conn.close()
    dst = BUNDLED_DATA_DIR / "coords.csv"
    with dst.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name", "latitude", "longitude", "source"])
        w.writeheader()
        w.writerows(rows)
    context.log.info("pinned coords edition %s -> %s (%d rows)", coords_editions, dst, len(rows))
    return dg.MaterializeResult(metadata={"edition_id": coords_editions, "rows": len(rows), "path": str(dst)})


# ---- jobs + schedules (schedules start STOPPED; turn them on in the Dagster UI) ----------------------
registers_refresh = dg.define_asset_job(
    "ecr_refresh",
    selection=dg.AssetSelection.assets("ecr_register_fetch", "ecr_editions", "ecr_changes"),
    description="Fetch the NGED Embedded Capacity Register, store it as an edition, diff it against the previous one.",
)
ecr_monthly_refresh = dg.ScheduleDefinition(
    name="ecr_monthly_refresh", job=registers_refresh, cron_schedule="0 6 2 * *", execution_timezone="Europe/London",
    description="NGED republishes the ECR monthly: fetch on the 2nd at 06:00.",
)
osm_refresh = dg.define_asset_job(
    "osm_refresh",
    selection=dg.AssetSelection.assets("osm_substations_fetch", "coords_editions"),
    description="Re-geocode the network's substations from OpenStreetMap and store the result as an edition.",
)
osm_quarterly_refresh = dg.ScheduleDefinition(
    name="osm_quarterly_refresh", job=osm_refresh, cron_schedule="0 6 1 1,4,7,10 *", execution_timezone="Europe/London",
    description="Substation positions rarely change: quarterly is plenty.",
)
