"""Paths, environment and the small helpers every API module shares."""

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from gridforge_optimizer import engine_fingerprint

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

# the pipeline's .env carries OPENROUTER_API_KEY; the API loads it from there
load_dotenv(REPO_ROOT / "apps" / "pipeline" / ".env")

log = logging.getLogger("gridforge_api")


class _Stderr(logging.StreamHandler):
    """Writes to whatever `sys.stderr` is at the time (pytest swaps it per test; a handler bound to the import-time
    stream wrote to a closed one and logged a "Logging error" for every line)."""

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, _value):  # StreamHandler.__init__ assigns it; the property stays live
        pass


if not log.handlers:  # uvicorn configures only its own loggers: without a handler every log line here was dropped
    _handler = _Stderr()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s gridforge: %(message)s", "%H:%M:%S"))
    log.addHandler(_handler)
    log.setLevel(os.getenv("GRIDFORGE_LOG_LEVEL", "INFO"))
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")  # the agents' library prints a Logfire advert per agent it builds otherwise


def require_openrouter_key() -> str:
    """The OpenRouter key every model call needs. GridForge does not run without it: the agents and the
    the agents are not optional, so a missing key stops the API at startup with the reason, never a
    degraded mode."""
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. GridForge needs it (put it in apps/pipeline/.env, which the API loads): "
            "the agents are not optional, and nothing runs without a model."
        )
    return key

# placeholder scores for a manually added project: it bypasses the registry's published-facts scoring
MANUAL_READINESS_DEFAULT = 0.5
MANUAL_STRATEGIC_DEFAULT = 0.5
ADDED_CANDIDATE_ID_BASE = 2056  # user-added projects are numbered CR-2056, CR-2057, …

# --- projects --------------------------------------------------------------------------------------------
NGED_PROJECT_ID = "nged-bickerfen"  # the built-in project; imports get their own ids (projects.py)
PROJECTS_DIR = Path(os.getenv("GRIDFORGE_PROJECTS_DIR") or (SCENARIOS.parent / "projects"))  # the files imported projects were built from
MAX_IMPORT_BYTES = 50 * 1024 * 1024

# --- the agent harness (agents/) ---------------------------------------------------------------------------
# OpenRouter model ids per role (AGENTS.md rule 2: they plan studies and phrase; the engine computes)
AGENT_MODELS = {
    "answerer": "anthropic/claude-sonnet-5.5",  # plans typed queries, cites, proposes
    "digest": "anthropic/claude-sonnet-5.5",  # one call per run: the engineer's note from the engine's digest
}
# per agent run: tool calls, solves and wall time before it is cut short
NGED_MAIN_ID = "main"  # the built-in project's main (an import's is `<project id>-main`)
AGENT_RUN_BUDGET = {"max_tool_calls": 12, "max_solves": 600, "timeout_s": 600, "max_tokens": 400_000,
                    "max_output_tokens": 8_000}  # per model response: a note or a markdown answer is well under it; a model that
                                                 # loops (one once streamed 17 000 tokens of "(.)") ends there, not at its context
# max_tokens: the run's model requests and responses together (a healthy answer is 20-40k; a model that once restated
# 750 gate rows over three attempts read 1.45M tokens for $4)
# an agent run waits for an operator's job to free the solver for as long as its own time allows, less this reserve to write the answer
AGENT_ANSWER_RESERVE_S = 60.0
OPENROUTER_APP = {"app_url": "https://github.com/Rupper02/gridforge", "app_title": "GridForge"}  # OpenRouter attribution headers
# the durable runtime's own database (DBOS): SQLite beside the scenarios file by default, Postgres when the
# scenarios store is Postgres (or GRIDFORGE_DBOS_URL). Recovery after a restart is pinned to an application
# version: the engine fingerprint by default, so a code change that retires cached physics also retires
# in-flight runs; set GRIDFORGE_DBOS_APP_VERSION to keep runs across `--reload` restarts in dev
DBOS_URL: str = os.getenv("GRIDFORGE_DBOS_URL") or (
    SCENARIOS_URL if SCENARIOS_URL and SCENARIOS_URL.startswith(("postgresql://", "postgres://"))
    else "sqlite:///" + str(SCENARIOS.parent / "dbos.sqlite").replace("\\", "/"))
AGENTS_APP_VERSION: str = os.getenv("GRIDFORGE_DBOS_APP_VERSION") or engine_fingerprint()


def now() -> str:
    """UTC timestamp as an ISO-8601 string (sorts chronologically; JSON-friendly)."""
    return datetime.now(timezone.utc).isoformat()
