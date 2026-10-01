"""Governed ingest of the real NGED network from LTDS open data.

bronze (bundled LTDS tables) -> canonical model + connection queue -> @asset_checks (power flow
converges, referential integrity, single connected network) -> served to the DuckDB warehouse.
This replaces the mv_oberrhein asset chain: the shared `gridforge_optimizer.nged` builder is the
single source of truth, so the pipeline warehouse and the optimizer's `build_base_net()` stay in
lockstep.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import dagster as dg
import duckdb
import networkx as nx
import pandapower as pp
import pandas as pd

from grid_simulator.config import DB_PATH, VOLTAGE_MAX_PU, VOLTAGE_MIN_PU
from gridforge_optimizer import nged as _nged
from gridforge_optimizer.config import MAX_CONNECTION_MW
from gridforge_optimizer.nged import build_nged_net, nged_candidates, nged_model

_LTDS_DIR = Path(_nged.__file__).resolve().parent / "data" / "nged"
_LTDS_TABLES = ("circuit", "t2a", "demand", "node", "gen", "conn")
_CAND_COLS = [
    "request_id", "applicant", "bus_id", "technology", "rating_mw", "readiness_score",
    "readiness_rationale", "readiness_breakdown", "land_rights", "planning_status",
    "grid_connection_agreement", "financing", "commissioning_year", "strategic_fit",
    "strategic_confidence", "strategic_rationale", "status", "review_reasons",
]


# --- bronze: raw LTDS tables pulled from NGED's Connected Data (CKAN) API ---------------------
@dg.asset
def ltds_tables(context: dg.AssetExecutionContext) -> dict:
    """The bundled NGED LTDS tables for the Bicker Fen 132 kV GSP region (Lincolnshire)."""
    tables = {t: json.loads((_LTDS_DIR / f"{t}.json").read_text(encoding="utf-8")) for t in _LTDS_TABLES}
    context.add_output_metadata({f"{t}_rows": len(v) for t, v in tables.items()})
    return tables


# --- silver: canonical model + connection queue (via the shared deterministic builder) --------
@dg.asset
def nged_model_canonical(context: dg.AssetExecutionContext, ltds_tables: dict) -> dict:
    """Reconcile the LTDS tables into one geolocated model (buses/lines/transformers/loads)."""
    m = nged_model()
    context.add_output_metadata({k: len(m[k]) for k in ("buses", "lines", "transformers", "loads")})
    return m


@dg.asset
def nged_connection_queue(context: dg.AssetExecutionContext, ltds_tables: dict) -> list:
    """The connection queue from LTDS Table 5 (generation) + Table 6 (interest), mapped to buses."""
    cands = nged_candidates(MAX_CONNECTION_MW)
    context.add_output_metadata({
        "candidates": len(cands),
        "valid": sum(1 for c in cands if c["status"] == "auto_accept"),
        "needs_review": sum(1 for c in cands if c["status"] != "auto_accept"),
    })
    return cands


# --- checks: the deterministic safety gate --------------------------------------------------
@dg.asset_check(asset="nged_model_canonical")
def power_flow_converges(nged_model_canonical: dict) -> dg.AssetCheckResult:
    net = build_nged_net()
    pp.runpp(net, max_iteration=50, init="flat")
    v = net.res_bus["vm_pu"]
    ok = bool(net.converged and v.between(VOLTAGE_MIN_PU, VOLTAGE_MAX_PU).all())
    return dg.AssetCheckResult(
        passed=ok,
        severity=dg.AssetCheckSeverity.ERROR,
        metadata={"converged": bool(net.converged), "v_min_pu": round(float(v.min()), 4),
                  "v_max_pu": round(float(v.max()), 4),
                  "max_line_pct": round(float(net.res_line.loading_percent.max()), 1),
                  "max_trafo_pct": round(float(net.res_trafo.loading_percent.max()), 1)},
    )


@dg.asset_check(
    asset="nged_model_canonical",
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
    bad_cand = [c["request_id"] for c in nged_connection_queue
                if c["status"] == "auto_accept" and c["bus_id"] not in bus_ids]
    return dg.AssetCheckResult(
        passed=not dangling and not bad_cand,
        severity=dg.AssetCheckSeverity.ERROR,
        metadata={"dangling_elements": len(dangling), "candidates_off_network": len(bad_cand)},
    )


@dg.asset_check(asset="nged_model_canonical")
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
@dg.asset
def served_nged(context: dg.AssetExecutionContext, nged_model_canonical: dict,
                nged_connection_queue: list) -> dg.MaterializeResult:
    """Write buses/lines/transformers/loads/candidate_projects/snapshots to the warehouse DuckDB."""
    m = nged_model_canonical
    buses = pd.DataFrame(m["buses"])[["bus_id", "name", "vn_kv", "lon", "lat"]]
    lines = pd.DataFrame(m["lines"])[["line_id", "line_name", "rating_a", "voltage_kv", "from_bus", "to_bus"]]
    trafos = pd.DataFrame(m["transformers"])[["trafo_id", "name", "sn_mva", "hv_bus", "lv_bus"]]
    loads = pd.DataFrame([{"bus_id": ld["bus_id"], "p_mw": ld["p_mw"]} for ld in m["loads"]])
    cdf = pd.DataFrame([{k: c.get(k) for k in _CAND_COLS} for c in nged_connection_queue])

    blob = "".join(df.to_csv(index=False) for df in (buses, lines, trafos, loads))
    snapshot_id = "nged-bickerfen-" + hashlib.sha256(blob.encode()).hexdigest()[:12]
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DB_PATH))
    try:
        for name, df in [("buses", buses), ("lines", lines), ("transformers", trafos),
                         ("loads", loads), ("candidate_projects", cdf)]:
            conn.register("df_view", df)
            conn.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM df_view")
            conn.unregister("df_view")
        conn.execute("CREATE TABLE IF NOT EXISTS snapshots "
                     "(snapshot_id VARCHAR, created_at VARCHAR, buses INT, lines INT, transformers INT)")
        conn.execute("DELETE FROM snapshots")
        conn.execute("INSERT INTO snapshots VALUES (?, ?, ?, ?, ?)",
                     [snapshot_id, datetime.now(timezone.utc).isoformat(),
                      len(buses), len(lines), len(trafos)])
    finally:
        conn.close()

    return dg.MaterializeResult(metadata={
        "snapshot_id": snapshot_id, "db_path": str(DB_PATH), "buses": len(buses),
        "lines": len(lines), "transformers": len(trafos), "loads": len(loads), "candidates": len(cdf),
    })
