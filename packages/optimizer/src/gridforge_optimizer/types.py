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


class Reason(BaseModel):
    """Why a project was deferred or rejected, with the binding element where applicable."""

    type: str  # "voltage" | "line" | "trafo" | "gsp" | "non_convergent" | "rejected"
    element_id: int | None = None
    value: float | None = None
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


class OptimizeResult(BaseModel):
    """The full optimizer output: the parameters used, the ordered queue, per-phase results, narrative."""

    params: OptimizeParams
    queue: list[QueueItem]
    phases: dict[str, PhaseResult]
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
