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
MAX_CONNECTION_MW = 100.0  # plausibility cap for a single EHV/primary connection on the NGED GSP region

# --- demand growth (fixed, sourced; multiplier on existing load scaling) ---------------------
# Peak-demand growth multipliers vs a ~2024 baseline of ~60 GW GB peak (NESO Winter Outlook
# 2024/25: 59.8 GW ACS). These are FIXED, cited figures — not user-tunable sliders. Growth is
# a function of (pathway, horizon); the optimizer resolves a scenario id to these multipliers
# and network.per_bus_growth spreads them per-bus so the feeder total still lands on the figure.
#
# Anchor: NESO FES 2025 Holistic Transition, UNDERLYING (pre-flexibility) peak — because network
# assets are sized to the unmanaged peak, not the flexibility-managed one. GB peak ~60 GW (2024)
# → 65 GW (2030, x1.08) → 81 GW (2035, x1.35). Note the non-linearity: demand is near-flat to
# 2030 (~+1.3%/yr) then climbs ~+4%/yr to 2035 as EV + heat-pump electrification hits (those two
# drive ~93% of the 2035 peak rise) — which is exactly why 2030 and 2035 are modelled separately.
# Only Holistic Transition is a firmly cited anchor; the spread across the other three pathways is
# DIRECTIONAL (ordered EE > HT > HE > FB) and should be refined from the FES 2025 data workbook.
GROWTH_2030 = 1.08
GROWTH_2035 = 1.35

_FES_2025 = "NESO Future Energy Scenarios 2025 (peak demand), Jul 2025"

FORECASTS = {
    "ht": {
        "label": "Holistic Transition",
        "description": "FES 2025 central pathway, aligned with Clean Power 2030. Peak ~65 GW (2030) / ~81 GW (2035).",
        "growth_2030": 1.08,
        "growth_2035": 1.35,
        "source": _FES_2025,
        "cited": True,  # firmly anchored on published FES 2025 peak figures
    },
    "ee": {
        "label": "Electric Engagement",
        "description": "Highest electrification of heat and transport; top-end demand.",
        "growth_2030": 1.10,
        "growth_2035": 1.42,
        "source": _FES_2025,
        "cited": False,  # directional spread relative to Holistic Transition
    },
    "he": {
        "label": "Hydrogen Evolution",
        "description": "Hydrogen leads heat and transport, so less electricity demand.",
        "growth_2030": 1.07,
        "growth_2035": 1.28,
        "source": _FES_2025,
        "cited": False,
    },
    "fb": {
        "label": "Falling Behind",
        "description": "Slow electrification; the only non-net-zero pathway (FES 2025, ex-'Counterfactual').",
        "growth_2030": 1.04,
        "growth_2035": 1.15,
        "source": _FES_2025,
        "cited": False,
    },
}
DEFAULT_SCENARIO = "ht"

# Policy-anchored planning horizons (GB planning is milestone/snapshot-based, not continuous).
# 2030 = Clean Power 2030 (DESNZ Action Plan, Dec 2024); 2035 = the strategic-need window the
# connections reform's "needed" test (TMO4+, Ofgem Apr 2025) uses for CP2030/CSNP capacities.
HORIZONS = [
    {"year": 2030, "key": "2030", "label": "Clean Power 2030", "note": "95% low-carbon generation (DESNZ Clean Power 2030 Action Plan, Dec 2024)."},
    {"year": 2035, "key": "2035", "label": "2035 strategic window", "note": "Strategic-need horizon for the connections reform (TMO4+, Ofgem Apr 2025)."},
]

# --- per-bus demand-growth shape (network.per_bus_growth) -------------------
# A scenario sets the feeder-total multiplier; growth is then spread per bus so the total is
# preserved while individual buses diverge realistically. These are the shape knobs.
LOAD_TYPE_RESIDENTIAL = "MV/LV Station"  # pandapower load type: LV network behind a secondary substation
GROWTH_BETA_RESIDENTIAL = 1.00   # residential/LV load grows fast (EVs + heat pumps)
GROWTH_BETA_INDUSTRIAL = 0.25    # directly-connected MV industrial load grows slowly
GROWTH_HETEROGENEITY = 0.60      # amplitude of the seeded per-bus growth spread
GROWTH_EDGE_TILT = 0.30          # tilt growth toward the far (rural) feeder edge
GROWTH_HOTSPOT_QUANTILE = 0.80   # buses whose seed exceeds this become adoption hotspots (~top 20%)
GROWTH_HOTSPOT_MULT = 1.80       # extra growth weight applied to a hotspot bus

# --- ranking weights (readiness + grid need + strategic fit) ---
W_READINESS = 0.5
W_NEED = 0.35
W_STRATEGIC = 0.15

# --- grid need (scoring.grid_need_from_solved) ------------------------------
GRID_NEED_DEMAND_FULL_MW = 5.0   # local demand (MW) at which the demand term saturates to 1.0
GRID_NEED_DEMAND_WEIGHT = 0.5    # blend of local-demand vs voltage-depression (the two sum to 1.0)
GRID_NEED_VOLTAGE_WEIGHT = 0.5

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

# Commissioning-timeline credit: sooner-energising projects are readier. Years are counted
# from the current year; an unknown year is treated as distant/uncertain (the 'far' credit).
READINESS_COMMISSIONING_NEAR_YEARS = 2
READINESS_COMMISSIONING_MID_YEARS = 5
READINESS_COMMISSIONING_NEAR_CREDIT = 1.0
READINESS_COMMISSIONING_MID_CREDIT = 0.6
READINESS_COMMISSIONING_FAR_CREDIT = 0.3

# Below this Jev confidence, a strategic call is too uncertain to rank on -> flag for review.
STRATEGIC_CONFIDENCE_MIN = 0.55

# --- LLM / decisions (OpenRouter) -------------------------------------------
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SCORING_MODEL = "anthropic/claude-sonnet-5.5"
JUSTIFY_MODEL = "anthropic/claude-sonnet-5.5"
LLM_TEMPERATURE = 0.0            # deterministic extraction / scoring
JUSTIFY_TEMPERATURE = 0.3        # a little warmth for the closing narrative
DECISIONS_TIMEOUT_S = 60         # Jev HTTP decisions-call timeout, seconds

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

# --- consequence-diff narrator ----------------------------------------------
# Re-phrases an already-computed diff between two optimizer runs into one plain-English line.
# It MUST only restate the numbers it is given -- it computes nothing itself.
NARRATE_DIFF_SYSTEM_PROMPT = (
    "You are a grid connections planner comparing two connection-queue scenarios (a baseline and a "
    "proposed option). You are given a pre-computed diff: MW connected by 2030/2035 in each, which "
    "projects accelerated / slipped / were added or dropped, and which network lines newly overload or "
    "clear. Write ONE or TWO sentences stating what the proposed option changes versus the baseline -- "
    "lead with the capacity delta, then the most important project move and the biggest network effect. "
    "Use only the figures provided; invent nothing. Plain text, no markdown."
)

# --- "what would it take" suggestions (suggest.py) --------------------------
MAX_SUGGESTIONS = 5            # deferred projects to propose an unblock for (highest-ranked first)
MAX_REINFORCE_STEPS = 4        # max parallel circuits chained to connect one project (a bottleneck
#                                cascades: reinforcing the worst line exposes the next, so we iterate)
REINFORCEMENT_FACTOR = 2.0     # 'uprate' multiplier on a line/trafo thermal rating (thermal only)
# Reactive-absorption steps tried for a voltage-bound connection, as (power factor, q/p factor).
# q_mvar = -factor * p_mw (the DER absorbing reactive power) counters voltage rise from PQ export.
VOLTAGE_ABSORB_PF_STEPS = [(0.98, 0.20), (0.95, 0.33), (0.90, 0.48)]

# Phrases a pre-computed unblock recommendation. Like the diff narrator, it only restates figures.
SUGGEST_SYSTEM_PROMPT = (
    "You are a grid connections planner. You are given a pre-computed unblock recommendation for a "
    "project the optimizer had to defer: the binding network element, a concrete reinforcement or "
    "operating action, the MW it would free by 2030 and 2035, and which projects then connect. State "
    "it in ONE or TWO plain sentences: the action, the capacity it frees, and the project(s) it "
    "connects. Use only the figures provided; invent nothing; never claim it is the cheapest or only "
    "fix. Plain text, no markdown."
)
