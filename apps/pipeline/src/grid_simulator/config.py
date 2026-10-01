"""Central configuration for the GridForge pipeline — paths and validation thresholds.

The connection cap and the LTDS data location live with the shared builder
(`gridforge_optimizer.config` / `gridforge_optimizer.nged`); this module only holds what the
Dagster assets here need: the warehouse path and the power-flow voltage band.
"""

from pathlib import Path

# config.py sits at src/grid_simulator/config.py, so parents[2] is apps/pipeline.
REPO_ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE_DIR = REPO_ROOT / "warehouse"
DB_PATH = WAREHOUSE_DIR / "gridforge.duckdb"

# Acceptable per-unit voltage band for the power-flow asset check.
VOLTAGE_MIN_PU = 0.9
VOLTAGE_MAX_PU = 1.1
