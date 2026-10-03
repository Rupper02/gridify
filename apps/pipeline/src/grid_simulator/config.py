"""Central configuration for the GridForge pipeline: the warehouse path.

The connection cap, the voltage bands and the LTDS data location live with the shared engine
(`gridforge_optimizer.config` / `gridforge_optimizer.nged`); this module only holds what the
Dagster assets here need.
"""

from pathlib import Path

# config.py sits at src/grid_simulator/config.py, so parents[2] is apps/pipeline.
REPO_ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE_DIR = REPO_ROOT / "warehouse"
DB_PATH = WAREHOUSE_DIR / "gridforge.duckdb"
