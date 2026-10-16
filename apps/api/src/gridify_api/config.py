"""Paths, environment and the small helpers every API module shares."""

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
WAREHOUSE = Path(
    os.getenv("GRIDIFY_DB_PATH", str(REPO_ROOT / "apps" / "pipeline" / "warehouse" / "gridify.duckdb"))
)
SCENARIOS = Path(
    os.getenv("GRIDIFY_SCENARIOS_DB", str(Path(__file__).resolve().parents[2] / "data" / "scenarios.duckdb"))
)
# a postgresql:// URL here puts branches, connections and the result cache in Postgres instead of the DuckDB file
# (same schema, same SQL; see store.ScenarioStore)
SCENARIOS_URL: str | None = os.getenv("GRIDIFY_SCENARIOS_URL") or None

MAIN_ID = "main"  # the plan of record: the network as it exists today, changed only by merging a branch into it

log = logging.getLogger("gridify_api")


class _Stderr(logging.StreamHandler):
    """Writes to whatever `sys.stderr` is at the time (pytest swaps it per test; a handler bound to the import-time
    stream writes to a closed one)."""

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, _value):  # StreamHandler.__init__ assigns it; the property stays live
        pass


if not log.handlers:  # uvicorn configures only its own loggers: without a handler every log line here was dropped
    _handler = _Stderr()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s gridify: %(message)s", "%H:%M:%S"))
    log.addHandler(_handler)
    log.setLevel(os.getenv("GRIDIFY_LOG_LEVEL", "INFO"))


def now() -> str:
    """UTC timestamp as an ISO-8601 string (sorts chronologically; JSON-friendly)."""
    return datetime.now(timezone.utc).isoformat()
