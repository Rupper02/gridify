"""Governed ingest of the real NGED Bicker Fen network from open data.

bronze (the pinned snapshot of the LTDS tables, the Embedded Capacity Register and the OSM
coordinates) -> canonical model + project registry + the LTDS edition change-set -> @asset_checks
(power flow converges, referential integrity, single connected network) -> served to the DuckDB
warehouse with an append-only snapshot history.

The bronze tables are passed INTO the shared `gridforge_optimizer.nged` builder, so the Dagster
lineage is the real data path: change a row in `ltds_tables` and every downstream asset sees it.
The engine's `build_base_net()` runs the same builder on the same bundled snapshot, so the warehouse
the map reads and the network the engine solves cannot drift apart.
"""

import hashlib
import json
from datetime import datetime, timezone

import dagster as dg
import duckdb
import networkx as nx
import pandapower as pp
import pandas as pd

from grid_simulator.config import DB_PATH, VOLTAGE_MAX_PU, VOLTAGE_MIN_PU
from gridforge_optimizer.config import MAX_CONNECTION_MW
from gridforge_optimizer.editions import edition_changeset
from gridforge_optimizer.nged import (
    TABLE_NAMES,
    build_nged_net,
    load_bundled_coords,
    load_bundled_tables,
    nged_candidates,
    nged_model,
    tables_hash,
)

_CAND_COLS = [
    "request_id", "applicant", "bus_id", "technology", "rating_mw", "readiness_score",
    "readiness_rationale", "readiness_breakdown", "land_rights", "planning_status",
    "grid_connection_agreement", "financing", "commissioning_year", "strategic_fit",
    "strategic_rationale", "status", "review_reasons",
]
_SNAPSHOT_COLS = {
    "snapshot_id": "VARCHAR", "created_at": "VARCHAR", "ltds_edition": "VARCHAR",
    "buses": "INTEGER", "lines": "INTEGER", "transformers": "INTEGER", "loads": "INTEGER", "candidates": "INTEGER",
}
_WRITER_RETRY = dg.RetryPolicy(max_retries=3, delay=5)  # DuckDB allows one writer per file: retry a lock clash


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- bronze: the pinned snapshot of every raw table ---------------------------------------------
@dg.asset(group_name="ltds", kinds={"json"})
def ltds_tables(context: dg.AssetExecutionContext) -> dict:
    """The bundled NGED LTDS tables (circuit, t2a, demand, node, gen), the Embedded Capacity
    Register, and the OpenStreetMap substation coordinates, as raw rows. `edition` is a content
    hash of the lot: the version id every downstream asset and snapshot is tagged with."""
    tables = load_bundled_tables()
    tables["coords"] = load_bundled_coords()
    edition = tables_hash(tables)
    context.add_output_metadata({
        **{f"{t}_rows": len(tables[t]) for t in TABLE_NAMES},
        "coords_rows": len(tables["coords"]),
        "edition": edition,
        "sources": dg.MetadataValue.md(
            "NGED Connected Data Portal (CKAN): LTDS tabular model, Embedded Capacity Register "
            "(resource 82a4ae83-77a3-4e7b-9060-8072ed96de9d); OpenStreetMap substations (ODbL). "
            "Pinned snapshot in `gridforge_optimizer/data/nged/`; refreshed by the `registers` assets."
        ),
    })
    return tables


# --- silver: canonical model, registry and the edition change-set ------------------------------
@dg.asset(group_name="ltds")
def nged_model_canonical(context: dg.AssetExecutionContext, ltds_tables: dict) -> dict:
    """Reconcile the LTDS tables into one geolocated model (buses/lines/transformers/loads/fleet)."""
    m = nged_model(ltds_tables)
    context.add_output_metadata({k: len(m[k]) for k in ("buses", "lines", "transformers", "loads", "generators")})
    return m


@dg.asset(group_name="ltds")
def nged_connection_queue(context: dg.AssetExecutionContext, ltds_tables: dict) -> list:
    """The registry of projected projects: NGED's Embedded Capacity Register 'accepted to connect'
    sites (+ any LTDS Table 5 project the ECR doesn't list, + the GSP-embedded TEC project), each
    mapped to a bus. OPTIONAL: main stays the live network; projects are pulled onto branches."""
    cands = nged_candidates(MAX_CONNECTION_MW, ltds_tables)
    context.add_output_metadata({
        "candidates": len(cands),
        "valid": sum(1 for c in cands if c["status"] == "auto_accept"),
        "needs_review": sum(1 for c in cands if c["status"] != "auto_accept"),
        "registry_mw": round(sum(c["rating_mw"] or 0 for c in cands), 1),
    })
    return cands


@dg.asset(group_name="ltds")
def ltds_edition_changes(context: dg.AssetExecutionContext, ltds_tables: dict) -> dict:
    """What changed between NGED's previous LTDS edition and this one: the flagged rows, the model
    delta (buses / circuits / transformers / demand) and the physics delta (today's power flow on
    each edition). The previous edition is reconstructed from NGED's New/Removed flags."""
    cs = edition_changeset(ltds_tables)
    top = cs["model"]["demand_changes"][:8]
    md = "| substation | previous MW | current MW | delta |\n|---|---|---|---|\n" + "\n".join(
        f"| {d['substation']} | {d['previous_mw']} | {d['current_mw']} | {d['delta_mw']:+} |" for d in top
    )
    context.add_output_metadata({
        **{f"n_{k}": v for k, v in cs["n_changes"].items()},
        **{f"model_delta_{k}": v for k, v in cs["model"]["delta"].items()},
        **{f"physics_delta_{k}": v for k, v in cs["physics"]["delta"].items() if v is not None},
        "top_demand_changes": dg.MetadataValue.md(md),
    })
    return cs


# --- checks: the deterministic safety gate --------------------------------------------------
@dg.asset_check(asset=nged_model_canonical, additional_ins={"ltds_tables": dg.AssetIn("ltds_tables")})
def power_flow_converges(nged_model_canonical: dict, ltds_tables: dict) -> dg.AssetCheckResult:
    net = build_nged_net(ltds_tables)
    pp.runpp(net, max_iteration=50, init="flat")
    v = net.res_bus["vm_pu"]
    ok = bool(net.converged and v.between(VOLTAGE_MIN_PU, VOLTAGE_MAX_PU).all())
    return dg.AssetCheckResult(
        passed=ok,
        severity=dg.AssetCheckSeverity.ERROR,
        metadata={"converged": bool(net.converged), "v_min_pu": round(float(v.min()), 4),
                  "v_max_pu": round(float(v.max()), 4), "buses_in_model": len(nged_model_canonical["buses"]),
                  "max_line_pct": round(float(net.res_line.loading_percent.max()), 1),
                  "max_trafo_pct": round(float(net.res_trafo.loading_percent.max()), 1)},
    )


@dg.asset_check(
    asset=nged_model_canonical,
    additional_ins={"nged_connection_queue": dg.AssetIn("nged_connection_queue")},
)
def referential_integrity(nged_model_canonical: dict, nged_connection_queue: list) -> dg.AssetCheckResult:
    bus_ids = {b["bus_id"] for b in nged_model_canonical["buses"]}
    dangling = []
    for ln in nged_model_canonical["lines"]:
        if ln["from_bus"] not in bus_ids or ln["to_bus"] not in bus_ids:
            dangling.append(("line", ln["line_id"]))
    for t in nged_model_canonical["transformers"]:
        if t["hv_bus"] not in bus_ids or t["lv_bus"] not in bus_ids:
            dangling.append(("trafo", t["trafo_id"]))
    for ld in nged_model_canonical["loads"]:
        if ld["bus_id"] not in bus_ids:
            dangling.append(("load", ld["load_id"]))
    for g in nged_model_canonical["generators"]:
        if g["bus_id"] not in bus_ids:
            dangling.append(("generator", g["request_id"]))
    bad_cand = [c["request_id"] for c in nged_connection_queue
                if c["status"] == "auto_accept" and c["bus_id"] not in bus_ids]
    return dg.AssetCheckResult(
        passed=not dangling and not bad_cand,
        severity=dg.AssetCheckSeverity.ERROR,
        metadata={"dangling_elements": len(dangling), "candidates_off_network": len(bad_cand)},
    )


@dg.asset_check(asset=nged_model_canonical)
def single_connected_network(nged_model_canonical: dict) -> dg.AssetCheckResult:
    g = nx.Graph()
    g.add_nodes_from(b["bus_id"] for b in nged_model_canonical["buses"])
    g.add_edges_from((ln["from_bus"], ln["to_bus"]) for ln in nged_model_canonical["lines"])
    g.add_edges_from((t["hv_bus"], t["lv_bus"]) for t in nged_model_canonical["transformers"])
    components = nx.number_connected_components(g)
    return dg.AssetCheckResult(
        passed=(components == 1),
        severity=dg.AssetCheckSeverity.WARN,
        metadata={"connected_components": components, "buses": g.number_of_nodes()},
    )


# --- served: write the warehouse the API reads ----------------------------------------------
def _ensure_snapshots_table(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the snapshot history table, or add the columns an older warehouse is missing."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS snapshots ("
        + ", ".join(f"{c} {t}" for c, t in _SNAPSHOT_COLS.items())
        + ")"
    )
    have = {r[1] for r in conn.execute("PRAGMA table_info('snapshots')").fetchall()}
    for col, typ in _SNAPSHOT_COLS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE snapshots ADD COLUMN {col} {typ}")


@dg.asset(group_name="ltds", kinds={"duckdb"}, retry_policy=_WRITER_RETRY)
def served_nged(
    context: dg.AssetExecutionContext,
    ltds_tables: dict,
    nged_model_canonical: dict,
    nged_connection_queue: list,
    ltds_edition_changes: dict,
) -> dg.MaterializeResult:
    """Write the model tables, the registry and the edition change-set to the warehouse, and append
    a row to the snapshot history (only when the content changed: `snapshot_id` is a content hash,
    so `network@<snapshot_id>` names a version)."""
    m = nged_model_canonical
    buses = pd.DataFrame(m["buses"])[["bus_id", "name", "vn_kv", "lon", "lat"]]
    lines = pd.DataFrame(m["lines"])[["line_id", "line_name", "rating_a", "voltage_kv", "from_bus", "to_bus"]]
    trafos = pd.DataFrame(m["transformers"])[["trafo_id", "name", "sn_mva", "hv_bus", "lv_bus"]]
    loads = pd.DataFrame([{"bus_id": ld["bus_id"], "p_mw": ld["p_mw"]} for ld in m["loads"]])
    gens = pd.DataFrame([{"request_id": g["request_id"], "bus_id": g["bus_id"], "rating_mw": g["rating_mw"],
                         "technology": g["technology"], "applicant": g["applicant"]} for g in m["generators"]])
    cdf = pd.DataFrame([{k: c.get(k) for k in _CAND_COLS} for c in nged_connection_queue])
    edition = tables_hash(ltds_tables)
    cs = ltds_edition_changes
    changes = pd.DataFrame([{"ltds_edition": edition, **r} for r in cs["rows"]]) if cs["rows"] else pd.DataFrame(
        columns=["ltds_edition", "table", "change", "key", "description", "value"])
    summary = pd.DataFrame([{
        "ltds_edition": edition, "computed_at": _now(),
        "n_new": cs["n_changes"]["new"], "n_removed": cs["n_changes"]["removed"], "n_updated": cs["n_changes"]["updated"],
        "summary_json": json.dumps({k: cs[k] for k in ("status_counts", "n_changes", "model", "physics", "caveats")}),
    }])

    blob = "".join(df.to_csv(index=False) for df in (buses, lines, trafos, loads, gens))
    snapshot_id = "nged-bickerfen-" + hashlib.sha256(blob.encode()).hexdigest()[:12]
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DB_PATH))
    try:
        for name, df in [("buses", buses), ("lines", lines), ("transformers", trafos), ("loads", loads),
                         ("generators", gens), ("candidate_projects", cdf),
                         ("ltds_changes", changes), ("ltds_change_summary", summary)]:
            conn.register("df_view", df)
            conn.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM df_view")
            conn.unregister("df_view")
        _ensure_snapshots_table(conn)
        latest = conn.execute("SELECT snapshot_id FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
        is_new = latest is None or latest[0] != snapshot_id
        if is_new:
            conn.execute(
                "INSERT INTO snapshots (snapshot_id, created_at, ltds_edition, buses, lines, transformers, loads, candidates) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [snapshot_id, _now(), edition, len(buses), len(lines), len(trafos), len(loads), len(cdf)],
            )
        history = conn.execute("SELECT count(*) FROM snapshots").fetchone()[0]
    finally:
        conn.close()

    return dg.MaterializeResult(metadata={
        "snapshot_id": snapshot_id, "snapshot": "new version" if is_new else "unchanged (no new snapshot row)",
        "snapshot_history": int(history), "ltds_edition": edition, "db_path": str(DB_PATH),
        "buses": len(buses), "lines": len(lines), "transformers": len(trafos), "loads": len(loads),
        "generators": len(gens), "candidates": len(cdf), "edition_changes": len(changes),
    })
