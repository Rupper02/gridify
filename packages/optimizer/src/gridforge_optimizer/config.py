"""Shared config for the GridForge connection-queue optimizer (physics + LLM)."""

# --- feasibility constraints ---
VOLTAGE_MIN_PU = 0.9
VOLTAGE_MAX_PU = 1.1
LINE_LOADING_MAX_PCT = 100.0
TRAFO_LOADING_MAX_PCT = 100.0
MAX_CONNECTION_MW = 20.0  # plausibility cap for a DER on this 20 kV feeder

# --- demand growth (multiplier applied to existing load scaling) ---
GROWTH_2030 = 1.10
GROWTH_2035 = 1.25

# --- ranking weights (readiness + grid need + strategic fit) ---
W_READINESS = 0.5
W_NEED = 0.35
W_STRATEGIC = 0.15

# --- LLM (OpenRouter) ---
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SCORING_MODEL = "anthropic/claude-sonnet-5.5"
JUSTIFY_MODEL = "anthropic/claude-sonnet-5.5"

SCORING_SYSTEM_PROMPT = (
    "You assess a proposed electricity grid connection project's readiness and strategic fit from its "
    "description, as in the GB connection-queue reform ('first ready and needed, first connected'). "
    "readiness_score (0..1): how deliverable it is — land rights secured, planning/consent granted, "
    "financing in place, near-term commissioning => high; pre-application, no land rights, speculative => low. "
    "strategic_fit (0..1): alignment with clean-power priorities (renewables/storage that add system value). "
    "Give a one-sentence rationale for each. Respond as JSON matching the schema."
)

SCORING_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "readiness_scoring",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "readiness_score": {"type": "number"},
                "readiness_rationale": {"type": "string"},
                "strategic_fit": {"type": "number"},
                "strategic_rationale": {"type": "string"},
            },
            "required": ["readiness_score", "readiness_rationale", "strategic_fit", "strategic_rationale"],
            "additionalProperties": False,
        },
    },
}

JUSTIFY_SYSTEM_PROMPT = (
    "You are a grid connections planner. Given an optimizer's ordered connection queue — each project with "
    "its phase (2030 / 2035 / Deferred / Rejected), readiness, grid-need, and the binding network constraint "
    "for any deferral — write a concise justification: one short paragraph plus brief per-decision notes, "
    "explaining the ordering and why deferred/rejected projects were held back, in the spirit of 'first ready "
    "and needed, first connected'. Name the limiting constraints. Plain text, no markdown headers."
)
