"""Shared config for the GridForge connection-queue optimizer (physics + LLM + decisions).

The division of labour here is deliberate:
  - readiness  -> deterministic rubric over LLM-*extracted facts* (auditable; see readiness.py)
  - strategic  -> a decisions model (Jev) judging 'is this the right addition', grounded in
                  the measured grid signal (see llm.score_strategic_fit)
  - justify    -> an LLM narrates the finished queue
"""

# --- feasibility constraints ---
VOLTAGE_MIN_PU = 0.9
VOLTAGE_MAX_PU = 1.1
LINE_LOADING_MAX_PCT = 100.0
TRAFO_LOADING_MAX_PCT = 100.0
MAX_CONNECTION_MW = 20.0  # plausibility cap for a DER on this 20 kV feeder

# --- demand growth (multiplier applied to existing load scaling) ---
# Defaults track the Holistic Transition pathway (NESO FES 2025 central case).
GROWTH_2030 = 1.10
GROWTH_2035 = 1.30

# DFES / NESO FES 2025 demand pathways: feeder peak-demand growth multipliers vs a ~2024
# baseline. The optimizer resolves a scenario id to its multipliers, then spreads growth
# per-bus (see network.per_bus_growth) so the feeder total still lands on these figures.
FORECASTS = {
    "ht": {
        "label": "Holistic Transition",
        "description": "FES 2025 central pathway, aligned with Clean Power 2030.",
        "growth_2030": 1.10,
        "growth_2035": 1.30,
    },
    "ee": {
        "label": "Electric Engagement",
        "description": "Highest electrification of heat and transport; top-end demand.",
        "growth_2030": 1.12,
        "growth_2035": 1.36,
    },
    "he": {
        "label": "Hydrogen Evolution",
        "description": "Hydrogen leads heat and transport, so less electricity demand.",
        "growth_2030": 1.07,
        "growth_2035": 1.22,
    },
    "fb": {
        "label": "Falling Behind",
        "description": "Slow electrification; the only non-net-zero pathway.",
        "growth_2030": 1.03,
        "growth_2035": 1.08,
    },
}
DEFAULT_SCENARIO = "ht"

# --- ranking weights (readiness + grid need + strategic fit) ---
W_READINESS = 0.5
W_NEED = 0.35
W_STRATEGIC = 0.15

# --- readiness rubric (deterministic) ---------------------------------------
# Weight of each Gate-2 milestone in the 0..1 readiness score. Sums to 1.0.
# The level -> credit tables live next to the logic in readiness.py.
READINESS_WEIGHTS = {
    "land_rights": 0.30,
    "planning_status": 0.30,
    "grid_connection_agreement": 0.20,
    "financing": 0.10,
    "commissioning_year": 0.10,
}

# Below this Jev confidence, a strategic call is too uncertain to rank on -> flag for review.
STRATEGIC_CONFIDENCE_MIN = 0.55

# --- LLM / decisions (OpenRouter) -------------------------------------------
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SCORING_MODEL = "anthropic/claude-sonnet-5.5"
JUSTIFY_MODEL = "anthropic/claude-sonnet-5.5"

# Jev is a decisions model, not a chat model: it answers via a separate endpoint and
# returns a calibrated choice + confidence (no free text).
DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
JEV_MODEL = "typesafe/jev-1.13"

# --- readiness fact-extraction (LLM extracts; it does NOT score) ------------
READINESS_EXTRACTION_SYSTEM_PROMPT = (
    "You extract the factual readiness milestones of a proposed GB electricity connection project "
    "from its description -- the 'ready' half of 'first ready and needed, first connected'. "
    "Do NOT judge, weigh, or score anything. Report only what the text states, choosing the closest "
    "level, and the lowest level whenever the text is silent on a milestone.\n"
    "land_rights: 'secured' (site owned/leased or option signed), 'in_progress' (negotiating/heads of "
    "terms), 'none'.\n"
    "planning_status: 'granted' (planning consent/permission granted), 'submitted' (application "
    "submitted, awaiting determination), 'pre_application' (scoping / pre-application only), 'none'.\n"
    "grid_connection_agreement: 'signed' (connection offer accepted / agreement in place), 'offered' "
    "(offer received but not yet accepted), 'none'.\n"
    "financing: 'committed' (funding or final investment decision secured), 'in_progress' (raising / "
    "term sheet), 'none'.\n"
    "commissioning_year: the target energisation year as a 4-digit integer if stated, else null.\n"
    "Respond as JSON matching the schema."
)

READINESS_CHECKLIST_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "readiness_checklist",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "land_rights": {"type": "string", "enum": ["secured", "in_progress", "none"]},
                "planning_status": {
                    "type": "string",
                    "enum": ["granted", "submitted", "pre_application", "none"],
                },
                "grid_connection_agreement": {"type": "string", "enum": ["signed", "offered", "none"]},
                "financing": {"type": "string", "enum": ["committed", "in_progress", "none"]},
                "commissioning_year": {"type": ["integer", "null"]},
            },
            "required": [
                "land_rights",
                "planning_status",
                "grid_connection_agreement",
                "financing",
                "commissioning_year",
            ],
            "additionalProperties": False,
        },
    },
}

# --- strategic fit (Jev decisions model) ------------------------------------
STRATEGIC_INSTRUCTIONS = (
    "Judge this grid-connection project's strategic fit / system value for a decarbonising GB "
    "distribution grid, in the spirit of the connection-queue reform ('first ready and needed, first "
    "connected'). Weigh the technology and size against the measured local grid signal in the state: "
    "grid_need near 1 means weak voltage / high and growing local demand that local generation or "
    "storage would relieve; grid_need near 0 means the grid is already strong there, so new capacity "
    "adds little. Favour clean, flexible capacity that is actually needed where it connects."
)

STRATEGIC_CRITERIA = {
    "high": (
        "Strongly advances clean-power goals and adds real system value: renewable or storage serving "
        "growing local demand, relieving a constraint, or supporting weak voltage where it connects."
    ),
    "medium": (
        "Moderate system value: useful clean capacity but limited locational benefit, or sited where "
        "the grid is already reasonably strong."
    ),
    "low": (
        "Little strategic value: redundant where the grid is already strong, or fossil / speculative "
        "capacity with weak system benefit."
    ),
}

# Map Jev's choice labels to a 0..1 value; the score is the expected value over the returned
# probability distribution (smoother than snapping to the top label).
STRATEGIC_FIT_VALUE = {"high": 1.0, "medium": 0.5, "low": 0.0}

# Chat fallback used only if the decisions endpoint is unreachable.
STRATEGIC_SYSTEM_PROMPT = (
    "You are a distribution network planner judging whether a proposed generation/storage project is "
    "the RIGHT addition to the grid -- the 'needed' half of the connection reform, beyond raw "
    "power-flow headroom. You receive the project (technology, size, location) and the measured local "
    "grid signal (grid_need in 0..1, where 1 = weak voltage / high local demand). Return strategic_fit "
    "in 0..1 and a one-sentence rationale grounded in the signal. Respond as JSON matching the schema."
)

STRATEGIC_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "strategic_fit",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "strategic_fit": {"type": "number"},
                "strategic_rationale": {"type": "string"},
            },
            "required": ["strategic_fit", "strategic_rationale"],
            "additionalProperties": False,
        },
    },
}

JUSTIFY_SYSTEM_PROMPT = (
    "You are a grid connections planner. Given an optimizer's ordered connection queue -- each project "
    "with its phase (2030 / 2035 / Deferred / Rejected), readiness, grid-need, and the binding network "
    "constraint for any deferral -- write a concise justification: one short paragraph plus brief "
    "per-decision notes, explaining the ordering and why deferred/rejected projects were held back, in "
    "the spirit of 'first ready and needed, first connected'. Name the limiting constraints. Plain "
    "text, no markdown headers."
)
