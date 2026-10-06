"""Running the engine: synchronous, as background jobs with progress, and the cache report."""

from fastapi import APIRouter

from .. import repository
from ..agents import events
from ..config import NGED_MAIN_ID
from ..deps import agents, cache, jobs, plans, scenarios
from ..schemas import BranchOptimizeRequest, OptimizeRequest

router = APIRouter()


@router.post("/optimize")
def run_optimize(body: OptimizeRequest) -> dict:
    """Run the built-in project's main plan and return the enriched queue + per-phase results (= POST /projects/nged-bickerfen/optimize)."""
    return ran(NGED_MAIN_ID, plans.optimize_payload(body, NGED_MAIN_ID), is_main=True)


def ran(branch_id: str, out: dict, *, is_main: bool) -> dict:
    """A run finished: the agents hear about it (`events.run_finished`; deduplicated by the result's identity)."""
    events.emit(agents, "run.finished", events.run_finished(branch_id, out, is_main=is_main))
    return out


@router.post("/branches/{branch_id}/optimize")
def optimize_branch(branch_id: str, body: BranchOptimizeRequest | None = None) -> dict:
    """Run the optimizer on a branch's scenario + candidate set."""
    with scenarios.cursor() as con:
        row = repository.require_branch(con, branch_id)
    req = repository.branch_request(row)
    req.with_justification = bool(body and body.with_justification)
    return ran(branch_id, plans.optimize_payload(req, branch_id, view_year=body.view_year if body else None), is_main=repository.is_main(row))


@router.post("/branches/{branch_id}/optimize/jobs")
def start_optimize_job(branch_id: str, body: BranchOptimizeRequest | None = None) -> dict:
    """Start a run of this branch in the background: the queue, then every year of the plan with
    `view_year` first. Poll GET /jobs/{job_id}?partial=true to show results as they land; a cached
    run finishes at once. The response is the job record (status, stage, fraction)."""
    return start_branch_run(branch_id, with_justification=bool(body and body.with_justification), view_year=body.view_year if body else None)


def start_branch_run(branch_id: str, *, with_justification: bool, view_year: int | None = None) -> dict:
    """Queue a run of the branch on its own demand profile as a job keyed by its result: a request for a
    run that is already queued or running (the startup warm-up's run of main, a double click) joins that
    job and shows its progress instead of waiting behind it for a cached copy."""
    with scenarios.cursor() as con:
        row = repository.require_branch(con, branch_id)
    req = OptimizeRequest(with_justification=with_justification, **repository.branch_params(row))
    main = repository.is_main(row)
    return jobs.start("optimize", lambda progress, publish: ran(branch_id, plans.optimize_payload(
        req, branch_id, progress=progress, publish=publish, view_year=view_year), is_main=main), key=plans.payload_key(req, branch_id))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    """Stop a queued or running job (a newer edit supersedes it). What it already solved stays cached."""
    return jobs.cancel(job_id)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, with_result: bool = True, partial: bool = False) -> dict:
    """A background job's status, stage, its partial result while running (`partial=true`: the
    queue plus the years solved so far) and its result when done."""
    return jobs.get(job_id, with_result=with_result, with_partial=partial)


@router.get("/cache")
def cache_stats() -> dict:
    """What the durable result cache holds (see ResultCache.stats)."""
    return cache.stats()
