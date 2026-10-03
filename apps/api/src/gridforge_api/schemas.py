"""Request bodies."""

from typing import Literal

from pydantic import BaseModel, Field

from gridforge_optimizer.config import DEFAULT_SCENARIO, GROWTH_2030, GROWTH_2035, PLAN_END_YEAR, PLAN_START_YEAR

from .config import MANUAL_READINESS_DEFAULT, MANUAL_STRATEGIC_DEFAULT


class NewCandidate(BaseModel):
    """Request body for adding a project via the UI (scored with neutral placeholders)."""

    applicant: str | None = None
    bus_id: int | None = None
    technology: str | None = None
    rating_mw: float | None = None
    readiness_score: float = MANUAL_READINESS_DEFAULT
    strategic_fit: float = MANUAL_STRATEGIC_DEFAULT
    readiness_rationale: str = ""
    commissioning_year: int | None = None  # requested energisation year; derived if omitted
    import_mw: float | None = None  # charging capacity (batteries); defaults to the rating
    branch_id: str = "main"  # which branch to add the project to


class OptimizeRequest(BaseModel):
    """Request body for a /optimize run: DFES scenario (or custom growth) + optional weight overrides."""

    # a DFES pathway id drives per-bus growth; growth_2030/2035 are the "Custom (manual)" override
    scenario: str | None = DEFAULT_SCENARIO
    growth_2030: float = GROWTH_2030
    growth_2035: float = GROWTH_2035
    w_readiness: float | None = None
    w_need: float | None = None
    w_strategic: float | None = None
    with_justification: bool = True


class BranchOptimizeRequest(BaseModel):
    """Request body for running a branch (its scenario is the branch's own)."""

    with_justification: bool = False
    view_year: int | None = None  # the year the planner is looking at: solved first, published first


class BranchCreate(BaseModel):
    """Open a branch off `from_branch` (default main): a scenario + optional projects to add."""

    name: str
    from_branch: str = "main"
    scenario: str | None = None
    growth_2030: float | None = None
    growth_2035: float | None = None
    w_readiness: float | None = None
    w_need: float | None = None
    w_strategic: float | None = None
    added_projects: list[NewCandidate] = []


class MergeRequest(BaseModel):
    into: str = "main"


class RegistryAdd(BaseModel):
    request_id: str


class ScheduleSet(BaseModel):
    """The operator's chosen energisation year for a project on a branch (None = follow the
    optimizer's recommendation)."""

    request_id: str
    year: int | None = None


class OutageCreate(BaseModel):
    """A planned maintenance window on a branch (studied in its season; reported, never a gate)."""

    element_kind: Literal["line", "trafo", "gen"]
    element_id: str  # line/trafo id, or an existing generator's id (EX-…)
    season: Literal["Winter", "Spring", "Summer", "Autumn"]
    year: int = Field(ge=PLAN_START_YEAR, le=PLAN_END_YEAR)
    weeks: int = Field(default=4, ge=1, le=26)
    kind: Literal["outage", "derate"] = "outage"


class ReinforcementCreate(BaseModel):
    """A simulated reinforcement proposed on a branch (a Copilot lever, "Try on <branch>")."""

    kind: Literal["line", "trafo", "gsp"]
    element_id: int
    action: Literal["add_parallel", "uprate"] = "add_parallel"
    factor: float = Field(default=2.0, gt=1.0, le=4.0)  # an uprate multiplies the rating (impedance unchanged)
    label: str = ""
