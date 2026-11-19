"""Shared config for the Gridify engine: the physics, the study cases, the plan years and demand growth.
Every constant here is listed in docs/sources-and-assumptions.md."""

# --- feasibility constraints ---
# Statutory voltage bands (GB ESQCR 2002 reg. 27): ±10 % at 132 kV and above, ±6 % above 1 kV and
# below 132 kV. Each entry is (minimum nominal kV, vmin pu, vmax pu); a bus takes the band of the
# highest threshold it reaches. Grid and primary transformers carry on-load tap changers (modelled
# in nged.py) that hold their LV busbar near OLTC_SETPOINT_PU, so the tight band below 132 kV is a
# real planning limit rather than an artefact of fixed taps.
VOLTAGE_BANDS = ((132.0, 0.90, 1.10), (1.0, 0.94, 1.06))
# Tap changers regulate their LV busbar to this voltage. A PLANNING ASSUMPTION: LTDS does not publish
# AVC target voltages, and GB DNOs set them above nominal so feeder ends stay in band at peak. 1.02 pu
# is the lowest value at which today's network (LTDS + NESO's GSP peak) meets the statutory band at
# winter peak (1.00 leaves Horncastle 33 kV at 0.932 pu); it is chosen, not sourced (docs/sources-and-assumptions.md).
OLTC_SETPOINT_PU = 1.02
OLTC_DEADBAND_PU = 0.01  # no tap movement while the LV busbar is within setpoint ± this (AVC relay deadband)
OLTC_MAX_PASSES = 3  # power-flow passes per solve to settle the taps (they persist on the net, so trials usually need one)
OLTC_TAP_STEP_PERCENT = 1.25  # LTDS gives the tap RANGE but not the step; a typical GB value (assumption)
# a converged solution with an in-service busbar below this (after the taps settle) is the low-voltage solution of the
# equations, a voltage collapse, not an operating point: below the nose of the P-V curve for any demand at 0.8 lagging
# or better (V = E / sqrt(2(1 + sin phi)) = 0.56 pu). Not a statutory limit (README register, Work 18)
COLLAPSE_VM_FLOOR_PU = 0.5
# The GSP infeed's voltage on the built-in grid (the slack): LTDS does not publish it; the supergrid side is held at the
# same level the tap changers regulate to. A planning assumption (docs/sources-and-assumptions.md).
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

# --- the plan's years -------------------------------------------------------------------------------
# Every run solves the plan year by year (years.simulate) so the timeline only switches between stored results.
# With the `custom` profile demand is interpolated linearly: 1.0 in PLAN_START_YEAR -> the 2030 multiplier -> the 2035
# multiplier.
PLAN_START_YEAR = 2026
PLAN_END_YEAR = 2035
PLAN_YEARS = tuple(range(PLAN_START_YEAR, PLAN_END_YEAR + 1))  # every year the plan solves
# Busbars at or above this voltage are the EHV backbone (nged.py records how the LTDS leaves their sections and
# couplers unstated).
EHV_MIN_KV = 132.0
# an LTDS circuit row with zero resistance, reactance at or below this (% on 100 MVA) and no rating is a connector, not
# a circuit (NGED's code "L0" rows; README register "A connector published as a circuit")
CONNECTOR_MAX_X_PCT = 0.01
# Loading movements smaller than this are noise, not a change (diff.py; loading points). A planning tolerance, chosen.
DIFF_NOISE = 0.1

# --- demand growth --------------------------------------------------------------------------------
# The built-in grid grows per primary substation on NGED's DFES 2025 power projections (winter peak MW per Electricity
# Supply Area, scenario and year, resource nged.DFES_POWER_RESOURCE_ID), as a ratio to their DFES_BASE_YEAR value: the
# LTDS edition's current year, so today's demand is the LTDS maximum and each later year is NGED's own projection for
# that primary (nged._add_loads, network.per_load_growth). Loads with no supply area (customer connections, the BSP
# aggregates) follow their LTDS five-year forecast ("Forecast Year 1" = LTDS_FORECAST_FIRST_YEAR), then hold. An
# `custom` profile grows uniformly on a pair of anchors (GROWTH_2030 / GROWTH_2035, interpolated). The FORECASTS below name the pathways; `dfes` is the DFES scenario
# each stands for, and the GB-level anchors are FES 2025's, kept as the `custom` defaults.
DFES_BASE_YEAR = 2025
LTDS_FORECAST_FIRST_YEAR = 2026
GROWTH_2030 = 1.08
GROWTH_2035 = 1.35

_FES_2025 = "NESO Future Energy Scenarios 2025 (peak demand), Jul 2025"

FORECASTS = {
    "ht": {
        "label": "Holistic Transition",
        "short": "Standard",
        "dfes": "Holistic Transition",
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
        "dfes": "Electric Engagement",
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
        "dfes": "Hydrogen Evolution",
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
        "dfes": "Counterfactual",
        "description": "Slow electrification; the only non-net-zero pathway (FES 2025, ex-'Counterfactual').",
        "growth_2030": 1.04,
        "growth_2035": 1.15,
        "source": _FES_2025,
        "cited": False,
        "selectable": True,
    },
}
DEFAULT_SCENARIO = "ht"
# --- readiness rubric (deterministic; the registry's published facts, nged.py) -----------------------
# Weight of each Gate-2 milestone in the 0..1 readiness score the registry rows carry. Sums to 1.0.
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

# --- the measured year (step 1) ---------------------------------------------------------------------
# NGED's four circuit-rating seasons by month (ER P27/2, as NGED's SD8A and DFES documents apply it; README register:
# "Circuit rating by month", source wording unverified) and the net.line ratio column each reads (None = the winter
# rating itself). Transformers keep their single LTDS rating all year.
RATING_SEASON_BY_MONTH = {12: "winter", 1: "winter", 2: "winter",
                          3: "intermediate_cool", 4: "intermediate_cool", 11: "intermediate_cool",
                          5: "intermediate_warm", 9: "intermediate_warm", 10: "intermediate_warm",
                          6: "summer", 7: "summer", 8: "summer"}
SEASON_RATIO_COLUMN = {"winter": None, "intermediate_cool": "intermediate_cool_ratio",
                       "intermediate_warm": "intermediate_warm_ratio", "summer": "summer_ratio"}
# a new connection in a year (README register: "Year shape"): a battery's placeholder day, by each half-hour's start in hours
# of the day (charging at its import capacity, exporting at its rating, idle otherwise), and the voltage at and above
# which wind takes the offshore shape
BATTERY_YEAR_RULE = {"charge": (11.0, 14.0), "export": (16.5, 19.5)}  # in the run file's fixed clock (most likely UTC)
WIND_OFFSHORE_MIN_KV = 132.0
IMPUTATION_RUN_HALF_HOURS = 12  # identical half-hourly values in a row (6 h) that flag a node's stretch (register: imputation screen)
