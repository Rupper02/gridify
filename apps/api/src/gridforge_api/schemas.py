"""Request bodies."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

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


Season = Literal["Winter", "Spring", "Summer", "Autumn"]


class WorkSpec(BaseModel):
    """What a planned work does to which element, without its window (shared by OutageCreate and
    BestWindowRequest).

    `work` says what it is for: maintenance (out, or derated with `kind`), a like-for-like
    replacement, or repowering, which brings the element back from the following year with a new
    capability: `repower` "uprate" (rating x `factor`, 1 < factor <= 4) or "add_parallel"."""

    element_kind: Literal["line", "trafo", "gen"]
    element_id: str  # line/trafo id, or an existing generator's id (EX-…)
    weeks: int = Field(default=4, ge=1, le=26)
    kind: Literal["outage", "derate"] = "outage"
    work: Literal["maintenance", "repowering", "replacement"] = "maintenance"
    repower: Literal["uprate", "add_parallel"] | None = None
    factor: float | None = Field(default=None, gt=1.0, le=4.0)

    @model_validator(mode="after")
    def _work_fields(self):
        if self.work != "repowering":
            if self.repower is not None or self.factor is not None:
                raise ValueError("repower and factor apply to repowering only")
            if self.work == "replacement" and self.kind == "derate":
                raise ValueError("a replacement takes the element fully out; derate is for maintenance")
            return self
        if self.kind == "derate":
            raise ValueError("repowering takes the element fully out; derate is for maintenance")
        if self.repower is None:
            raise ValueError("repowering needs repower: 'uprate' or 'add_parallel'")
        if self.repower == "uprate" and self.factor is None:
            raise ValueError("an uprate needs a factor (1 < factor <= 4)")
        if self.repower == "add_parallel" and self.factor is not None:
            raise ValueError("add_parallel takes no factor")
        return self


class OutageCreate(WorkSpec):
    """A planned works window on a branch (studied in its season; reported, never a gate)."""

    season: Season
    year: int = Field(ge=PLAN_START_YEAR, le=PLAN_END_YEAR)


class BestWindowRequest(WorkSpec):
    """Find the best window for a planned work (windows.best_windows): every season of every year in
    `years` = [from, to] (default the whole plan), or only the `seasons` given."""

    years: tuple[int, int] = (PLAN_START_YEAR, PLAN_END_YEAR)
    seasons: list[Season] | None = None

    @model_validator(mode="after")
    def _range(self):
        lo, hi = self.years
        if not (PLAN_START_YEAR <= lo <= hi <= PLAN_END_YEAR):
            raise ValueError(f"years must be [from, to] within {PLAN_START_YEAR}..{PLAN_END_YEAR}")
        if self.seasons is not None and not self.seasons:
            raise ValueError("seasons, when given, must not be empty")
        return self


class ReinforcementCreate(BaseModel):
    """A simulated reinforcement proposed on a branch (a Copilot lever, "Try on <branch>")."""

    kind: Literal["line", "trafo", "gsp"]
    element_id: int
    action: Literal["add_parallel", "uprate"] = "add_parallel"
    factor: float = Field(default=2.0, gt=1.0, le=4.0)  # an uprate multiplies the rating (impedance unchanged)
    label: str = ""
