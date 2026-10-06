"""Shared config for the GridForge connection-queue optimizer (physics + scoring + narration).

The division of labour is deliberate:
  - feasibility -> deterministic AC power flow (network.py) — never guessed
  - readiness   -> a deterministic rubric over published facts (readiness.py; the NGED registry
                   supplies them directly)
  - strategic   -> a per-technology prior on the registry (nged.py)
  - narration   -> an LLM phrases results the engine has already decided (llm.py; the API requires its key)
"""

# --- feasibility constraints ---
# Statutory voltage bands (GB ESQCR 2002 reg. 27): ±10 % at 132 kV and above, ±6 % above 1 kV and
# below 132 kV. Each entry is (minimum nominal kV, vmin pu, vmax pu); a bus takes the band of the
# highest threshold it reaches. Grid and primary transformers carry on-load tap changers (modelled
# in nged.py) that hold their LV busbar near OLTC_SETPOINT_PU, so the tight band below 132 kV is a
# real planning limit rather than an artefact of fixed taps.
VOLTAGE_BANDS = ((132.0, 0.90, 1.10), (1.0, 0.94, 1.06))
# An imported grid states its own limits at every voltage level it has (sources.apply_import_meta); these presets
# only fill the import form's boxes. Each band is (min kV, max kV or None, vmin pu, vmax pu); a level takes the
# band with the highest min kV it reaches within that band's max. EN 50160 sets limits at supply terminals up to
# 36 kV only, so its preset leaves the levels above blank for the operator to state.
VOLTAGE_BAND_PRESETS = {
    "gb_esqcr": {"label": "GB ESQCR", "note": "ESQCR 2002 reg. 27: ±10 % at 132 kV and above, ±6 % from 1 kV, +10 / −6 % at low voltage",
                 "bands": ((132.0, None, 0.90, 1.10), (1.0, None, 0.94, 1.06), (0.0, 1.0, 0.94, 1.10))},
    "en_50160": {"label": "EN 50160", "note": "EN 50160: ±10 % at low- and medium-voltage supply terminals (up to 36 kV); it sets no limits above "
                                              "36 kV, so those levels are left for you to state",
                 "bands": ((0.0, 36.0, 0.90, 1.10),)},
}
# Tap changers regulate their LV busbar to this voltage. A PLANNING ASSUMPTION: LTDS does not publish
# AVC target voltages, and GB DNOs set them above nominal so feeder ends stay in band at peak. 1.02 pu
# is the lowest value at which today's network (LTDS + NESO's GSP peak) meets the statutory band at
# winter peak (1.00 leaves Horncastle 33 kV at 0.932 pu); it is chosen, not sourced (README, Sources and assumptions).
OLTC_SETPOINT_PU = 1.02
OLTC_DEADBAND_PU = 0.01  # no tap movement while the LV busbar is within setpoint ± this (AVC relay deadband)
OLTC_MAX_PASSES = 3  # power-flow passes per solve to settle the taps (they persist on the net, so trials usually need one)
OLTC_TAP_STEP_PERCENT = 1.25  # LTDS gives the tap RANGE but not the step; a typical GB value (assumption)
# The GSP infeed's voltage on the built-in grid (the slack): LTDS does not publish it; the supergrid side is held at the
# same level the tap changers regulate to. A planning assumption (README, Sources and assumptions).
GSP_INFEED_VM_PU = 1.02
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
# technologies whose output follows the weather, the season or a schedule, not the merit order (dispatch.py)
VARIABLE_TECHS = frozenset({"solar", "wind", "battery", "hybrid", "electrolyser", "demand"})
# the reactive range a fixed-power-factor unit is given in the CIM export, as a share of its rating (CIM needs one)
CIM_FIXED_PF_Q_SHARE = 0.33
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
PLAN_YEARS = tuple(range(PLAN_START_YEAR, PLAN_END_YEAR + 1))  # every year the plan solves
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
# When a window breaches a limit without stranding demand, maintenance.py constrains generation near
# the binding element (or the biggest exporters, for the GSP) one generator at a time, re-solving each
# time, then bisects the last one. A bounded, first-order planning estimate (not an optimal dispatch):
# at most CURTAIL_MAX_SOLVES extra solves per study case, of which up to CURTAIL_REFINE_STEPS refine.
CURTAIL_MAX_SOLVES = 8
CURTAIL_REFINE_STEPS = 3
# a step that eases the binding breach by less than this fraction of its excess is put back (that
# generator does not feed the breach), so the estimate does not count output that relieves nothing
CURTAIL_MIN_RELIEF = 0.01
# The best-window search (windows.best_windows) studies every (year, season) without the N-1 screen,
# then screens N-1 during the window for this many only (the best of each season, then the next
# best): screening every window took 5.5 to 6.5 min for 10 years x 4 seasons on a busy dev machine,
# the shortlist 2 to 3.5 min. Bounded cost, not tuned for output.
BEST_WINDOW_N1_SHORTLIST = 6

# --- N-1 screen ---------------------------------------------------------------------------------
# Single-outage screen of the EHV backbone (every circuit and transformer at or above this kV),
# reported per phase, not enforced as a connection gate. Roughly ENA P2/8 security of supply.
N1_MIN_KV = 132.0
N1_ISLAND_MIN_MW = 1.0  # an outage that islands less demand than this (a generator spur, a tee) is not a supply violation
# The cases the backbone is screened in, every plan year and after every phase (network.n1_screen_cases):
# each contributes its thermal, voltage and convergence findings (export binds at summer minimum, demand at
# winter peak). Islanded demand is reported on the FIRST case only, the demand case the P2/8-style check
# reads: an island is topology, the same in every case, and its MW is the peak's.
N1_CASES = ("winter_peak", "summer_min")

# --- studies (studies.py): deterministic analyses the agents and the API run on a plan ----------------
# Hosting capacity: per bus, the MW of new export (or import) before the first limit breaks, found by
# bisection on today's network between 0 and the intake cap to this resolution. Scope is bounded:
# connection-level buses (>= HOSTING_MIN_KV) and at most HOSTING_MAX_BUSES of them per study.
HOSTING_STEP_MW = 5.0
HOSTING_MIN_KV = 33.0
HOSTING_MAX_BUSES = 24
# Connection options: how a project could connect when its own busbar cannot take it. Besides its own
# bus (sized by bisection) and the parallel-circuit chain, this many higher-voltage busbars, nearest
# first by network steps from the project's bus, are probed with the project's full MW.
CONNECTION_OPTION_BUSES = 4
# Contingency ranking: the N-1 screen's mechanics extended to every circuit and transformer at or above
# this kV, in both study cases, each contingency scored by what it does. The index is a RANKING
# HEURISTIC (a weighted sum of islanded demand in MW, thermal excess in MVA and the worst voltage
# shortfall in pu x 100), never a gate; the components are reported alongside it.
CONTINGENCY_MIN_KV = 33.0
CONTINGENCY_SEVERITY_WEIGHTS = {"islanded_mw": 1.0, "thermal_excess_mva": 1.0, "voltage_shortfall_pu": 100.0}
# Tap margin: a regulated transformer within this many steps of a tap stop has (almost) no voltage
# control left; at the stop it is reported as a breach of margin, one step away as a warning.
TAP_MARGIN_MIN_STEPS = 1

# --- merge guardrails (gate.py) -----------------------------------------------------------------
# Merging a branch into the plan of record is gated by a pure policy over results the engine has
# already produced: a branch is refused when its result is stale, or when it INTRODUCES or WORSENS a
# problem relative to its parent in the same plan year. Problems the parent already carries are
# context, never blockers (main itself is not perfect). Connections are never gated by this.
# Levels are data: every kind a check can emit is listed here and this is the only place a level
# is decided, so a policy change is a one-line, registered change (README, Sources and assumptions).
MERGE_GATE_LEVELS = {
    "stale": "blocker", "no_result": "blocker", "unstudied_years": "blocker", "non_convergent": "blocker",
    "behind_base": "blocker", "fork_unknown": "warning",
    "new_overload": "blocker", "overload_worse": "blocker",
    "new_voltage_violation": "blocker", "voltage_worse": "warning",
    "gsp_over_limit": "blocker", "gsp_worse": "blocker", "gsp_near_limit": "warning",
    "n1_new_islanded": "blocker", "n1_new_limit": "blocker", "n1_worse": "warning",
    "alert_new_breach": "blocker", "alert_new_warn": "warning", "alert_worse": "warning",
    "work_worse_severe": "blocker", "work_worse": "warning", "work_infeasible": "warning", "work_new": "warning",
    "against_recommendation": "warning", "profile_differs": "warning", "proposals_removed": "warning",
    "preexisting": "info", "deferred_on_grid": "info",
}
# An element already past its limit on the parent counts as WORSENED on the branch only beyond these
# margins (loading points, MW of GSP export, pu of voltage): planning tolerances, chosen, not sourced.
GATE_WORSEN_PTS = 1.0
GATE_GSP_WORSEN_MW = 1.0
GATE_VM_WORSEN_PU = 0.005
# GSP export above this share of its export limit is a warning (the planner's gauge turns amber here too)
GSP_NEAR_LIMIT_FRACTION = 0.9
# GSP margin by year: export within this share of the limit is a warning: the gate's point above, read as a margin
GSP_MARGIN_WARN_FRACTION = round(1.0 - GSP_NEAR_LIMIT_FRACTION, 10)
# Movements smaller than these are noise, not a change: the gate's GSP-near-limit and alert-worse checks (MW, alert
# units), and the diff's works windows and loadings (loading points, MW). Planning tolerances, chosen, not sourced.
GATE_NOISE = 0.05
DIFF_NOISE = 0.1

# --- demand-side security (demand.py) -----------------------------------------------------------
# A SIMPLIFIED P2/8-STYLE check, not a P2/8 assessment: restoration times, switching, transfer
# capacity and second-circuit outages are not modelled. Source: ENA Engineering Recommendation P2/8
# "Security of Supply" (2019), Table 1 (demand classes by Group Demand, first-circuit-outage
# requirement). Each entry is (class, upper bound of Group Demand in MW, loss_mw, loss_fraction):
# on a first circuit outage, P2/8 lets max(loss_mw, loss_fraction x group demand) wait beyond the
# fast-restoration window (C: 15 min restores the smaller of group - 12 MW and 2/3 of the group, so
# max(12 MW, 1/3 of the group) may wait; D: up to 20 MW may be lost by automatic disconnection;
# E and F: none). None = the whole group may wait for restoration within 3 hours (B) or repair time (A).
P2_8_CLASSES = (
    ("A", 1.0, None, None),
    ("B", 12.0, None, None),
    ("C", 60.0, 12.0, 1 / 3),
    ("D", 300.0, 20.0, 0.0),
    ("E", 1500.0, 0.0, 0.0),
    ("F", float("inf"), 0.0, 0.0),
)
# Warn when a group's firm headroom falls below this share of its firm capacity. A planning
# assumption (an early-warning margin), not a figure from P2/8.
HEADROOM_WARN_FRACTION = 0.10

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
# An imported grid's own forecast stands in for these pathways (by id, so the planner's picker works on it):
# Low, Standard (required at import) and High.
IMPORT_PATHWAYS = ("fb", "ht", "ee")
IMPORT_FORECAST_FACTOR_MAX = 2.0  # an entered forecast's year-on-year factor: above 0 and at most this (a sanity bound)

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
# Power factors tried, absorbing, for a voltage-bound connection (suggest.py): its reactive power then follows its
# output in every case (types.Control, network.inject_project), countering the voltage rise its export causes.
VOLTAGE_ABSORB_PF_STEPS = [0.98, 0.95, 0.90]

# Phrases a pre-computed unblock recommendation. Like the diff narrator, it only restates figures.
