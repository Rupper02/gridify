"""Central configuration for GridForge.

Every tunable the pipeline uses lives here - paths, validation thresholds, and the
LLM extraction settings - so a reviewer can see them at a glance and swapping an
environment (DuckDB -> Postgres, or a different model) is a one-line change.
"""

from pathlib import Path

# --- paths (all derived from the repo root) ---------------------------------
# config.py sits at src/grid_simulator/config.py, so the repo root is parents[2].
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "raw"
REQUESTS_DIR = DATA_DIR / "connection_requests"
WAREHOUSE_DIR = REPO_ROOT / "warehouse"
DB_PATH = WAREHOUSE_DIR / "gridforge.duckdb"

# --- validation thresholds --------------------------------------------------
VOLTAGE_MIN_PU = 0.9        # acceptable per-unit voltage band for the power-flow check
VOLTAGE_MAX_PU = 1.1
MAX_CONNECTION_MW = 20.0    # plausibility cap for a DER on this 20 kV feeder

# --- LLM extraction (OpenRouter) --------------------------------------------
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
EXTRACTION_MODEL = "anthropic/claude-sonnet-5.5"

EXTRACTION_SYSTEM_PROMPT = (
    "You extract electricity grid connection requests into JSON matching the schema. "
    "bus_id = the point-of-connection bus number if stated, else null. "
    "technology = one of solar/battery/wind/load if stated, else null. "
    "rating_mw = capacity in MW (convert kW to MW; 4,500 kW = 4.5), else null. "
    "voltage_kv = voltage in kV if stated, else null. "
    "applicant = the applicant or company name if stated, else null. "
    "confidence = your 0.0-1.0 confidence in this extraction."
)

EXTRACTION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "connection_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "bus_id": {"type": ["integer", "null"]},
                "technology": {"type": ["string", "null"]},
                "rating_mw": {"type": ["number", "null"]},
                "voltage_kv": {"type": ["number", "null"]},
                "applicant": {"type": ["string", "null"]},
                "confidence": {"type": "number"},
            },
            "required": ["bus_id", "technology", "rating_mw", "voltage_kv", "applicant", "confidence"],
            "additionalProperties": False,
        },
    },
}
