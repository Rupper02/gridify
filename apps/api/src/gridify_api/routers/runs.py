"""The measured and grown years, read-only: which runs exist, a run's summary for the year view, and one element's
month-by-hour grid; and a branch's year, started as a job on the single worker (about 16 minutes) and compared with its
"before". Nothing else here solves."""

import threading

from fastapi import APIRouter

from gridify_optimizer import engine_fingerprint

from ..deps import jobs, run_files, year_runs
from ..errors import Invalid, NotFound
from ..schemas import YearRunRequest

router = APIRouter()
_cache: dict[tuple, dict] = {}  # (run, file time, engine) -> summary: a summary takes a few seconds to compute
_lock = threading.Lock()


def _require(run_id: str) -> None:
    if not run_files.known(run_id):
        raise NotFound(f"unknown run '{run_id}'")
    if not run_files.info(run_id).available:
        raise NotFound(f"run '{run_id}' has no file yet: {run_files.info(run_id).make}")


@router.get("/runs")
def list_runs() -> list[dict]:
    """Every catalogued year run, whether its file exists, how to make it, and its limits in plain words."""
    return [r.model_dump() for r in run_files.catalogue()]


@router.get("/runs/{run_id}")
def run_summary(run_id: str) -> dict:
    """A run's summary: every line and transformer (peak, hours at or above 80/90 % and above 100 %, its agreement with
    the source's model), the busbars out of band and the substations above firm capacity."""
    return _summary(run_id).model_dump()


def _summary(run_id: str):
    _require(run_id)
    key = (run_id, run_files.path(run_id).stat().st_mtime, engine_fingerprint())
    with _lock:
        if key not in _cache:
            _cache[key] = run_files.summarise(run_id)
        return _cache[key]


@router.post("/branches/{branch_id}/year-run")
def start_year_run(branch_id: str, body: YearRunRequest) -> dict:
    """Run a branch's year (its connections in service by `year`, on the catalogued grown year of `year` and `pathway`) as
    a job: poll GET /jobs/{job_id}; its result names the run (`run_id`) and its "before". A run of the same inputs
    already on file finishes at once; one already queued or running is joined."""
    key, job = year_runs.prepare(branch_id, body.year, body.pathway)
    return jobs.start("year", job, key=key)


@router.get("/runs/{run_id}/compare")
def compare_run(run_id: str) -> dict:
    """A branch's year against its "before": what changed, the MVAh above rating on the worst element, the GSP exchange."""
    after = _summary(run_id)
    if not after.info.before:
        raise Invalid(f"'{run_id}' is not a branch's year: it has nothing to compare with")
    return run_files.compare(run_id, _summary(after.info.before), after).model_dump()


@router.get("/runs/{run_id}/grid/{kind}/{element_id}")
def run_grid(run_id: str, kind: str, element_id: int) -> dict:
    """When one line, transformer or busbar is over in a run: hours per month and hour of day."""
    _require(run_id)
    if kind not in ("line", "trafo", "bus"):
        raise Invalid("kind must be line, trafo or bus")
    return run_files.month_hour_grid(run_id, kind, element_id).model_dump()
