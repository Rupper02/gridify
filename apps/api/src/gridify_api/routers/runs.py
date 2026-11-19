"""The measured and grown years over HTTP: which runs exist, a run's summary for the year view, one element's
month-by-hour grid, and a branch's year started as a job and compared with its "before"."""

from typing import Literal

from fastapi import APIRouter

from ..deps import run_views, year_runs
from ..schemas import YearRunRequest

router = APIRouter()


@router.get("/runs")
def list_runs() -> list[dict]:
    """Every catalogued year run, whether its file exists, how to make it, and its limits in plain words."""
    return run_views.catalogue()


@router.get("/runs/{run_id}")
def run_summary(run_id: str) -> dict:
    """A run's summary: every line and transformer (peak, hours at or above 80/90 % and above 100 %, its agreement with
    the source's model), the busbars out of band and the substations above firm capacity."""
    return run_views.summary(run_id).model_dump()


@router.post("/branches/{branch_id}/year-run")
def start_year_run(branch_id: str, body: YearRunRequest) -> dict:
    """Run a branch's year (its connections in service by `year`, on the catalogued grown year of `year` and `pathway`) as
    a job: poll GET /jobs/{job_id}; its result names the run (`run_id`) and its "before". A run of the same inputs
    already on file finishes at once; one already queued or running is joined."""
    return year_runs.start(branch_id, body.year, body.pathway)


@router.get("/runs/{run_id}/compare")
def compare_run(run_id: str) -> dict:
    """A branch's year against its "before": what changed, the MVAh above rating on the worst element, the GSP exchange."""
    return run_views.compare(run_id).model_dump()


@router.get("/runs/{run_id}/grid/{kind}/{element_id}")
def run_grid(run_id: str, kind: Literal["line", "trafo", "bus"], element_id: int) -> dict:
    """When one line, transformer or busbar is over in a run: hours per month and hour of day."""
    return run_views.month_hour_grid(run_id, kind, element_id).model_dump()
