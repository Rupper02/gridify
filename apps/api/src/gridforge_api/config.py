"""Paths, environment and the small helpers every API module shares."""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[4]
WAREHOUSE = Path(
    os.getenv("GRIDFORGE_DB_PATH", str(REPO_ROOT / "apps" / "pipeline" / "warehouse" / "gridforge.duckdb"))
)
SCENARIOS = Path(
    os.getenv("GRIDFORGE_SCENARIOS_DB", str(Path(__file__).resolve().parents[2] / "data" / "scenarios.duckdb"))
)
# a postgresql:// URL here puts branches, added projects, schedules and the result cache in Postgres
# instead of the DuckDB file (same schema, same SQL; see store.ScenarioStore)
SCENARIOS_URL: str | None = os.getenv("GRIDFORGE_SCENARIOS_URL") or None

# reuse the pipeline's OPENROUTER_API_KEY for the LLM narration (dev)
load_dotenv(REPO_ROOT / "apps" / "pipeline" / ".env")

log = logging.getLogger("gridforge_api")

# placeholder scores for a manually added project: it bypasses the registry's published-facts scoring
MANUAL_READINESS_DEFAULT = 0.5
MANUAL_STRATEGIC_DEFAULT = 0.5
ADDED_CANDIDATE_ID_BASE = 2056  # user-added projects are numbered CR-2056, CR-2057, …

# --- the agent harness (agents/) ---------------------------------------------------------------------------
NGED_PROJECT_ID = "nged-bickerfen"  # the one project today; every agent record is keyed by project
# OpenRouter model ids per role (AGENTS.md rule 2: they plan studies and phrase; the engine computes)
AGENT_MODELS = {
    "steward": "anthropic/claude-sonnet-5.5",
    "reviewer": "anthropic/claude-sonnet-5.5",
    "answerer": "anthropic/claude-sonnet-5.5",
    "specialist": "anthropic/claude-haiku-4.5",
}
# per project and day: OpenRouter credits, tokens and power-flow solves before the agents pause themselves
AGENT_BUDGET_DAILY = {"credits": 5.0, "tokens": 2_000_000, "solves": 3_000}
# per agent run: tool calls, solves and wall time before it is cut short
AGENT_RUN_BUDGET = {"max_tool_calls": 12, "max_solves": 600, "timeout_s": 600}
SOLVER_GATE_MAX_WAIT_S = 180.0  # how long an agent study waits for an operator's job before it gives up
AGENT_STEP_RETENTION_DAYS = 90  # recorded tool steps older than this are dropped unless an open finding cites them


def now() -> str:
    """UTC timestamp as an ISO-8601 string (sorts chronologically; JSON-friendly)."""
    return datetime.now(timezone.utc).isoformat()
