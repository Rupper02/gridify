from __future__ import annotations

from pydantic import BaseModel

from .config import (
    GROWTH_2030,
    GROWTH_2035,
    W_NEED,
    W_READINESS,
    W_STRATEGIC,
)


class Candidate(BaseModel):
    request_id: str
    bus_id: int | None = None
    technology: str | None = None
    rating_mw: float | None = None
    readiness_score: float = 0.5
    strategic_fit: float = 0.5
    readiness_rationale: str = ""
    status: str = "auto_accept"  # "auto_accept" | "needs_review"
    review_reasons: str = ""


class Reason(BaseModel):
    type: str  # "voltage" | "line" | "trafo" | "non_convergent" | "rejected"
    element_id: int | None = None
    value: float | None = None
    message: str


class QueueItem(BaseModel):
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
    worst_line_loading_pct: float | None = None


class OptimizeParams(BaseModel):
    growth_2030: float = GROWTH_2030
    growth_2035: float = GROWTH_2035
    w_readiness: float = W_READINESS
    w_need: float = W_NEED
    w_strategic: float = W_STRATEGIC


class PhaseResult(BaseModel):
    accepted: list[str]
    worst_line_loading_pct: float
    worst_trafo_loading_pct: float
    min_vm_pu: float
    max_vm_pu: float
    overloaded_line_ids: list[int]


class OptimizeResult(BaseModel):
    params: OptimizeParams
    queue: list[QueueItem]
    phases: dict[str, PhaseResult]
    justification: str = ""
