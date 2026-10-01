"""Seed the warehouse with the real NGED Bicker Fen network (replaces the mv_oberrhein model).

Writes buses/lines/transformers/loads/candidate_projects/snapshots from gridforge_optimizer.nged,
keeping bus ids identical to build_base_net() so the API/map and the optimizer share one network.
Run: `uv run --directory apps/api python ../pipeline/scripts/seed_nged.py` (any env with the
gridforge-optimizer package + duckdb + pandas).

NOTE: the governed path is now the Dagster `served_nged` asset (defs/nged.py) — run
`dagster asset materialize -m grid_simulator.definitions --select ltds_tables*`. This script stays
as a quick, Dagster-free way to (re)seed the same warehouse.
"""
import datetime
import hashlib
import json
from pathlib import Path

import duckdb
import pandas as pd

from gridforge_optimizer.config import MAX_CONNECTION_MW
from gridforge_optimizer.nged import nged_candidates, nged_model

WH = Path(__file__).resolve().parents[1] / "warehouse" / "gridforge.duckdb"
WH.parent.mkdir(parents=True, exist_ok=True)

m = nged_model()
cands = nged_candidates(MAX_CONNECTION_MW)

buses = pd.DataFrame(m["buses"])[["bus_id", "name", "vn_kv", "lon", "lat"]]
lines = pd.DataFrame(m["lines"])[["line_id", "line_name", "rating_a", "voltage_kv", "from_bus", "to_bus"]]
trafos = pd.DataFrame(m["transformers"])[["trafo_id", "name", "sn_mva", "hv_bus", "lv_bus"]]
loads = pd.DataFrame([{"bus_id": l["bus_id"], "p_mw": l["p_mw"]} for l in m["loads"]])
cand_cols = ["request_id", "applicant", "bus_id", "technology", "rating_mw", "readiness_score",
             "readiness_rationale", "readiness_breakdown", "land_rights", "planning_status",
             "grid_connection_agreement", "financing", "commissioning_year", "strategic_fit",
             "strategic_confidence", "strategic_rationale", "status", "review_reasons"]
cdf = pd.DataFrame([{k: c.get(k) for k in cand_cols} for c in cands])

con = duckdb.connect(str(WH))
try:
    for name, df in [("buses", buses), ("lines", lines), ("transformers", trafos),
                     ("loads", loads), ("candidate_projects", cdf)]:
        con.register("df", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM df")
        con.unregister("df")
    sid = "nged-bickerfen-" + hashlib.sha256(
        json.dumps(m, sort_keys=True, default=str).encode()).hexdigest()[:12]
    con.execute("CREATE TABLE IF NOT EXISTS snapshots "
                "(snapshot_id VARCHAR, created_at VARCHAR, buses INT, lines INT, transformers INT)")
    con.execute("DELETE FROM snapshots")
    con.execute("INSERT INTO snapshots VALUES (?, ?, ?, ?, ?)",
                [sid, datetime.datetime.now().isoformat(), len(buses), len(lines), len(trafos)])
finally:
    con.close()

print(f"seeded {WH}")
print(f"  buses={len(buses)} lines={len(lines)} trafos={len(trafos)} loads={len(loads)} "
      f"candidates={len(cdf)} (valid={sum(cdf.status == 'auto_accept')})")
