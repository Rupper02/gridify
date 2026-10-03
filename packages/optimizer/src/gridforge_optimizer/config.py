"""Shared config for the GridForge connection-queue optimizer (physics + scoring + narration).

The division of labour is deliberate:
  - feasibility -> deterministic AC power flow (network.py) — never guessed
  - readiness   -> a deterministic rubric over published facts (readiness.py; the NGED registry
                   supplies them directly)
  - strategic   -> a per-technology prior on the registry (nged.py)
  - narration   -> an LLM phrases results the engine has already decided (llm.py; optional)
"""

# --- feasibility constraints ---
# Statutory voltage bands (GB ESQCR 2002 reg. 27): ±10 % at 132 kV and above, ±6 % above 1 kV and
# below 132 kV. Each entry is (minimum nominal kV, vmin pu, vmax pu); a bus takes the band of the
# highest threshold it reaches. Grid and primary transformers carry on-load tap changers (modelled
# in nged.py) that hold their LV busbar near OLTC_SETPOINT_PU, so the tight band below 132 kV is a
# real planning limit rather than an artefact of fixed taps.
VOLTAGE_BANDS = ((132.0, 0.90, 1.10), (1.0, 0.94, 1.06))
VOLTAGE_MIN_PU = 0.9  # the widest (132 kV) band: kept for the pipeline check's headline + docs
VOLTAGE_MAX_PU = 1.1
OLTC_SETPOINT_PU = 1.0  # tap changers regulate their LV busbar to this voltage
OLTC_DEADBAND_PU = 0.01  # no tap movement while the LV busbar is within setpoint ± this (AVC relay deadband)
OLTC_MAX_PASSES = 3  # power-flow passes per solve to settle the taps (they persist on the net, so trials usually need one)
OLTC_TAP_STEP_PERCENT = 1.25  # LTDS gives the tap RANGE but not the step; a typical GB value (assumption)
LINE_LOADING_MAX_PCT = 100.0
TRAFO_LOADING_MAX_PCT = 100.0
MAX_CONNECTION_MW = 300.0  # intake plausibility cap for a single DISTRIBUTION connection (33–132 kV).
#                            NGED's ECR has real 132 kV sites accepted at up to 248 MW at Bicker Fen;
#                            beyond ~300 MW a generator connects to transmission, which this model doesn't cover.

# --- generation dispatch per study case ---------------------------------------------------------
# How much of its rating each technology produces in each planning case. The summer-minimum
# (generation) case runs everything at full export. The winter-peak (demand) case is a demand
# study: PV and wind produce nothing at a winter evening peak, and batteries CHARGE at their import
# capacity (negative = import), which adds demand. Unknown technologies (biomass, 'other') are
# treated as firm. Conservative on both sides; stated in the UI and README.
#
# Import-only projects (demand connections such as a data centre or EV hub, and hydrogen
# electrolysers) export nothing: they draw `import_mw` at winter peak and DEMAND_PROJECT_MIN_FACTOR
# of it at summer minimum (a planning assumption, close to the LTDS minimum-demand factors of ~0.5).
# A solar + battery hybrid is solar at nil and the battery charging at winter peak, full export in summer.
DEMAND_PROJECT_MIN_FACTOR = 0.5
IMPORT_ONLY_TECHS = ("demand", "electrolyser")
GENERATION_FACTORS = {
    "winter_peak": {"solar": 0.0, "wind": 0.0, "battery": -1.0, "hybrid": -1.0,
                    "demand": -1.0, "electrolyser": -1.0},
    "summer_min": {"solar": 1.0, "wind": 1.0, "battery": 1.0, "hybrid": 1.0,
                   "demand": -DEMAND_PROJECT_MIN_FACTOR, "electrolyser": -DEMAND_PROJECT_MIN_FACTOR},
}
GENERATION_FACTOR_DEFAULT = {"winter_peak": 1.0, "summer_min": 1.0}  # gas, gas engines, biomass/EfW: firm

# --- the plan's years and planned maintenance -----------------------------------------------------
# Every run solves the plan year by year (years.evaluate_years) so the timeline only switches between
# stored results. Demand is interpolated linearly: 1.0 in PLAN_START_YEAR -> the 2030 multiplier -> the
# 2035 multiplier.
PLAN_START_YEAR = 2026
PLAN_END_YEAR = 2035
# A planned outage is studied in the case(s) its season stresses, with that season's line ratings
# (net.line column of rating multipliers; LTDS publishes Winter / Intermediate Cool / Intermediate
# Warm / Summer ratings, so spring and autumn take the intermediate-warm rating, the lower of the two).
# Outages are REPORTED per year, like the N-1 screen, not a connection gate.
SEASON_STUDY = {
    "Winter": {"cases": ("winter_peak",), "rating_column": None},
    "Spring": {"cases": ("winter_peak", "summer_min"), "rating_column": "intermediate_ratio"},
    "Summer": {"cases": ("summer_min",), "rating_column": "summer_ratio"},
    "Autumn": {"cases": ("winter_peak", "summer_min"), "rating_column": "intermediate_ratio"},
}
OUTAGE_DERATE_FACTOR = 0.5  # a "derate" window runs the element at this fraction of its rating

# --- N-1 screen ---------------------------------------------------------------------------------
# Single-outage screen of the EHV backbone (every circuit and transformer at or above this kV),
# reported per phase, not enforced as a connection gate. Roughly ENA P2/8 security of supply.
N1_MIN_KV = 132.0
N1_ISLAND_MIN_MW = 1.0  # an outage that islands less demand than this (a generator spur, a tee) is not a supply violation

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
        "short": "Standard",
        "description": "FES 2025 central pathway, aligned with Clean Power 2030. Peak ~65 GW (2030) / ~81 GW (2035).",
        "growth_2030": 1.08,
        "growth_2035": 1.35,
        "source": _FES_2025,
        "cited": True,  # firmly anchored on published FES 2025 peak figures
        "selectable": True,
    },
    "ee": {
        "label": "Electric Engagement",
        "short": "High",
        "description": "Highest electrification of heat and transport; top-end demand.",
        "growth_2030": 1.10,
        "growth_2035": 1.42,
        "source": _FES_2025,
        "cited": False,  # directional spread relative to Holistic Transition
        "selectable": True,
    },
    "he": {
        "label": "Hydrogen Evolution",
        "short": "Hydrogen",
        "description": "Hydrogen leads heat and transport, so less electricity demand.",
        "growth_2030": 1.07,
        "growth_2035": 1.28,
        "source": _FES_2025,
        "cited": False,
        "selectable": False,  # fuel-switch story, not a demand envelope point
    },
    "fb": {
        "label": "Falling Behind",
        "short": "Low",
        "description": "Slow electrification; the only non-net-zero pathway (FES 2025, ex-'Counterfactual').",
        "growth_2030": 1.04,
        "growth_2035": 1.15,
        "source": _FES_2025,
        "cited": False,
        "selectable": True,
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

# --- LLM narration (OpenRouter) ---------------------------------------------
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
JUSTIFY_MODEL = "anthropic/claude-sonnet-5.5"
JUSTIFY_TEMPERATURE = 0.3        # a little warmth for the closing narrative

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
