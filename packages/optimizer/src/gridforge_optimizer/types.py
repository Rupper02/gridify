"""Pydantic models exchanged across the optimizer: inputs (Candidate, OptimizeParams) and
outputs (QueueItem, PhaseResult, OptimizeResult, Reason)."""

from __future__ import annotations

from pydantic import BaseModel

from .config import (
    DEFAULT_SCENARIO,
    GROWTH_2030,
    GROWTH_2035,
    W_NEED,
    W_READINESS,
    W_STRATEGIC,
)


class Candidate(BaseModel):
    """A proposed connection project fed into the optimizer (pre-scored by the pipeline)."""

    request_id: str
    bus_id: int | None = None
    technology: str | None = None
    rating_mw: float | None = None
    readiness_score: float = 0.5
    strategic_fit: float = 0.5
    readiness_rationale: str = ""
    status: str = "auto_accept"  # "auto_accept" | "needs_review"
    review_reasons: str = ""
    commissioning_year: int | None = None  # developer's requested energisation year (the timeline axis)
    import_mw: float | None = None  # charging capacity (batteries); None = same as the rating


class Reason(BaseModel):
    """Why a project was deferred or rejected, with the binding element where applicable."""

    type: str  # "voltage" | "line" | "trafo" | "gsp" | "non_convergent" | "rejected"
    element_id: int | None = None
    value: float | None = None
    limit: float | None = None  # the limit breached (pu for voltage, % for thermal, MW for the GSP)
    message: str
    case: str | None = None  # the study case it fails in: "winter_peak" | "summer_min" (None = n/a)


class QueueItem(BaseModel):
    """One project's place in the ordered queue: its rank, phase, scores, and reason."""

    rank: int | None
    request_id: str
    bus_id: int | None
    technology: str | None
    rating_mw: float | None
    readiness_score: float
    strategic_fit: float
    grid_need: float
    rank_score: float | None
    status: str  # "Phase1" | "Phase2" | "Deferred" | "Rejected"
    reason: Reason | None = None
    commissioning_year: int | None = None  # developer's requested energisation year
    recommended_year: int | None = None  # the year the optimizer suggests it energise (None if it can't)
    worst_line_loading_pct: float | None = None
    readiness_rationale: str = ""


class OptimizeParams(BaseModel):
    """Tunable inputs to a run: demand growth per phase, the DFES pathway, and ranking weights."""

    growth_2030: float = GROWTH_2030
    growth_2035: float = GROWTH_2035
    # DFES pathway id driving the per-bus growth shape; "custom" = uniform scalar growth.
    scenario: str = DEFAULT_SCENARIO
    w_readiness: float = W_READINESS
    w_need: float = W_NEED
    w_strategic: float = W_STRATEGIC


class PhaseResult(BaseModel):
    """The solved network state at the end of a phase: who connected and the loading/voltage limits."""

    accepted: list[str]
    worst_line_loading_pct: float
    worst_trafo_loading_pct: float
    min_vm_pu: float
    max_vm_pu: float
    overloaded_line_ids: list[int]
    line_loading: dict[int, float] = {}  # line_id -> loading_percent, for the map heat overlay
    bus_vm: dict[int, float] = {}  # bus_id -> voltage pu, for the map voltage overlay
    voltage_violation_bus_ids: list[int] = []  # buses outside the voltage band
    gsp_export_mw: float = 0.0  # peak power pushed UP through the GSP to transmission (worst case)
    gsp_import_mw: float = 0.0  # peak power drawn DOWN from transmission (worst case)
    gsp_limit_mw: float | None = None  # the GSP's export limit to transmission; None = unlimited
    n1_screened: int = 0  # EHV elements outaged one at a time in the N-1 screen
    n1_violations: list[dict] = []  # {outage_type, outage_id, outage_name, type, element_id, value, message}


class Outage(BaseModel):
    """A planned maintenance window on a branch: an element out of service (or derated) for some weeks
    of one season of one year. Studied in that season's case(s); reported, never a connection gate."""

    outage_id: str
    element_kind: str  # "line" | "trafo" | "gen" (an existing generator, by its model id EX-…)
    element_id: str  # line/trafo index as text, or the generator's request id
    season: str  # "Winter" | "Spring" | "Summer" | "Autumn" (config.SEASON_STUDY)
    year: int
    weeks: int = 4
    kind: str = "outage"  # "outage" | "derate" (maintenance only; the other works take the element fully out)
    # what the window is for (maintenance.WORKS): "maintenance" | "repowering" | "replacement".
    # Maintenance and replacement (like-for-like) return the element as it was; repowering returns it
    # with a new capability from the FOLLOWING year on (years.evaluate_year applies it, the queue run does not)
    work: str = "maintenance"
    repower: str | None = None  # repowering only: "uprate" | "add_parallel"
    factor: float | None = None  # repowering "uprate" only: the rating multiplier (1 < factor <= 4)


class Curtailment(BaseModel):
    """Generation constrained to hold the limits during a window (a first-order planning estimate)."""

    id: str  # the generator's model id (EX-… for the existing fleet) or the project's request id
    name: str  # its technology (the UI resolves the display name by id)
    mw: float  # output constrained in that case
    case: str  # the study case it is needed in


class N1During(BaseModel):
    """An N-1 screen of the 132 kV backbone with the window in place (informational, never a gate)."""

    cases: list[str] = []
    screened: int = 0  # second faults studied, summed over the cases
    findings: int = 0  # second faults that breach a limit or strand demand
    second_fault_at_risk_mw: float = 0.0  # demand stranded by the worst second fault
    worst: str = ""  # that finding's message ("" when nothing is stranded)


# how bad a window's verdict is, worst last: the order maintenance folds cases by and diff compares by
VERDICT_SEVERITY = {"feasible": 0, "curtailment": 1, "not_feasible": 2, "demand_at_risk": 3}


class OutageStudy(BaseModel):
    """What one planned window does to its year's network, in each case its season stresses, studied
    together with the other windows of the same season and year (`with_ids`)."""

    outage_id: str
    year: int
    cases: list[str]
    ok: bool  # True when no limit is breached with the element(s) out, before any curtailment
    violations: list[Reason] = []  # the first limit each case breaches
    worst_line_loading_pct: float = 0.0
    worst_trafo_loading_pct: float = 0.0
    gsp_export_mw: float = 0.0
    message: str
    work: str = "maintenance"
    with_ids: list[str] = []  # the other windows studied at the same time
    verdict: str = "feasible"  # "feasible" | "curtailment" | "demand_at_risk" | "not_feasible"
    demand_at_risk_mw: float = 0.0  # stranded, or at load buses left outside the voltage band
    curtailment: list[Curtailment] = []  # what constraining generation clears the limits ("curtailment" only)
    curtailed_mw: float = 0.0  # the most constrained in any one case
    n1_during: N1During | None = None  # None when the year was solved without the N-1 screen
    after: str = ""  # what the work leaves behind once the window is over


class YearResult(PhaseResult):
    """The plan as it stands in one year: the projects energised by then (their scheduled or
    recommended year), demand interpolated to the year, solved in both cases, plus that year's
    planned outages."""

    year: int
    growth: float  # the demand multiplier this year was solved at
    energised: list[str] = []  # projects in service this year
    trafo_loading: dict[int, float] = {}  # trafo_id -> loading_percent (worst case), for the element card
    outage_studies: list[OutageStudy] = []


class OptimizeResult(BaseModel):
    """The full optimizer output: the parameters used, the ordered queue, per-phase results, per-year
    results (filled by years.evaluate_years), narrative."""

    params: OptimizeParams
    queue: list[QueueItem]
    phases: dict[str, PhaseResult]
    years: dict[str, YearResult] = {}
    justification: str = ""


class Reinforcement(BaseModel):
    """A simulated network reinforcement for a 'what would it take' trial.

    `add_parallel` bumps the element's parallel count (halves series impedance AND doubles its
    rating -> relieves thermal AND voltage). `uprate` raises only the thermal rating by `factor`
    (impedance unchanged -> voltage unmoved).
    """

    kind: str  # "line" | "trafo" | "gsp" (one more supergrid transformer at the GSP)
    element_id: int
    action: str = "add_parallel"  # "add_parallel" | "uprate"
    factor: float = 2.0  # uprate multiplier on the rating (ignored for add_parallel)


class Suggestion(BaseModel):
    """A concrete, quantified unblock recommendation for one binding constraint.

    Every number here is measured by re-running the power flow (suggest.py); the LLM only phrases
    them. `freed_mw_*` is first-order (second-order knock-on is not modelled) -> report it as ≈.
    """

    target_type: str  # "line" | "trafo" | "voltage" | "gsp"
    target_element_id: int
    action: str
    reinforcements: list[Reinforcement] = []  # the full chain of upgrades this suggestion models
    connects_target: bool = True  # did the modelled action actually connect the blocked project(s)?
    freed_mw_2030: float = 0.0
    freed_mw_2035: float = 0.0
    newly_connected_project_ids: list[str] = []
    blocked_project_ids: list[str] = []  # deferred projects this suggestion is for (the motivation)
    extra_solves: int = 0  # power-flow solves this suggestion cost (observability)
    caveat: str = ""
    narration: str = ""  # filled by the API via llm.narrate_suggestion (grounded in the figures)
