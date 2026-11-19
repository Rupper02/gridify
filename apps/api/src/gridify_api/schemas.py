"""Request bodies."""

from pydantic import BaseModel, Field

from gridify_optimizer import Control
from gridify_optimizer.config import MAX_CONNECTION_MW, PLAN_END_YEAR, PLAN_START_YEAR

_YEAR = Field(ge=PLAN_START_YEAR, le=PLAN_END_YEAR)


class ConnectionCreate(BaseModel):
    """A connection placed on a branch: by hand, or pulled from the registry (`from_registry`, its id; the fields
    given here override the registry's)."""

    from_registry: str | None = None
    name: str | None = None
    bus_id: int | None = None
    technology: str | None = None
    rating_mw: float | None = Field(default=None, ge=0, le=MAX_CONNECTION_MW)
    import_mw: float | None = Field(default=None, ge=0, le=MAX_CONNECTION_MW)  # charging or demand capacity; None = the rating
    control: Control | None = None  # how its connection offer runs it; None: unity power factor
    year: int | None = _YEAR


class ConnectionChange(BaseModel):
    """Change a connection on a branch: any field given."""

    name: str | None = None
    bus_id: int | None = None
    technology: str | None = None
    rating_mw: float | None = Field(default=None, ge=0, le=MAX_CONNECTION_MW)
    import_mw: float | None = Field(default=None, ge=0, le=MAX_CONNECTION_MW)
    control: Control | None = None
    year: int | None = _YEAR


class BranchCreate(BaseModel):
    """Open a branch off `from_branch` (copy-on-create: its connections and demand profile come along)."""

    name: str = Field(min_length=1)
    from_branch: str


class ProfileSet(BaseModel):
    """A branch's demand profile: a pathway id (FORECASTS), or `custom` with its two anchors."""

    scenario: str
    growth_2030: float | None = Field(default=None, gt=0)
    growth_2035: float | None = Field(default=None, gt=0)


class YearRunRequest(BaseModel):
    """A branch's year: a plan year and a pathway the catalogue holds a grown year for."""

    year: int
    pathway: str


class RunRequest(BaseModel):
    view_year: int | None = None  # the year the planner is looking at: solved first, published first
