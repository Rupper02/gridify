import hashlib
from datetime import datetime, timezone

import dagster as dg
import duckdb
import pandas as pd

from grid_simulator.config import DB_PATH


@dg.asset
def served_model(
    context: dg.AssetExecutionContext,
    canonical_buses: pd.DataFrame,
    canonical_lines: pd.DataFrame,
    canonical_transformers: pd.DataFrame,
) -> dg.MaterializeResult:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    tables = {
        "buses": canonical_buses,
        "lines": canonical_lines,
        "transformers": canonical_transformers,
    }

    # a content fingerprint of the whole model = the "versioned source of truth" id
    blob = "".join(df.to_csv(index=False) for df in tables.values())
    snapshot_id = hashlib.sha256(blob.encode()).hexdigest()[:12]

    conn = duckdb.connect(str(DB_PATH))
    try:
        # write the three data tables
        for name, df in tables.items():
            conn.register("df_view", df)
            conn.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM df_view")

        # create the append-only snapshot log once, then record this run
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id VARCHAR,
                created_at VARCHAR,
                buses INT,
                lines INT,
                transformers INT
            )
            """
        )
        conn.execute(
            "INSERT INTO snapshots VALUES (?, ?, ?, ?, ?)",
            [
                snapshot_id,
                datetime.now(timezone.utc).isoformat(),
                len(canonical_buses),
                len(canonical_lines),
                len(canonical_transformers),
            ],
        )
    finally:
        conn.close()

    return dg.MaterializeResult(
        metadata={
            "snapshot_id": snapshot_id,
            "db_path": str(DB_PATH),
            "buses": len(canonical_buses),
            "lines": len(canonical_lines),
            "transformers": len(canonical_transformers),
        }
    )
