"""Running the engine: synchronous, as background jobs with progress, and the cache report."""

from fastapi import APIRouter

from .. import repository
from ..deps import cache, jobs, plans, scenarios
from ..schemas import BranchOptimizeRequest, OptimizeRequest

router = APIRouter()


@router.post("/optimize")
def run_optimize(body: OptimizeRequest) -> dict:
    """Run the optimizer on the main plan and return the enriched queue + per-phase results."""
    return plans.optimize_payload(body, "main")


@router.post("/branches/{branch_id}/optimize")
def optimize_branch(branch_id: str, body: BranchOptimizeRequest | None = None) -> dict:
    """Run the optimizer on a branch's scenario + candidate set."""
    with scenarios.cursor() as con:
        row = repository.require_branch(con, branch_id)
    req = repository.branch_request(row)
    req.with_justification = bool(body and body.with_justification)
    if body and body.study_year is not None:
        req.study_year = body.study_year
    return plans.optimize_payload(req, branch_id)


@router.post("/branches/{branch_id}/optimize/jobs")
def start_optimize_job(branch_id: str, body: BranchOptimizeRequest | None = None) -> dict:
    """Start a run of this branch in the background. Poll GET /jobs/{job_id}; a cached run finishes
    at once. The response is the job record (status, stage, fraction)."""
    with scenarios.cursor() as con:
        row = repository.require_branch(con, branch_id)
    req = OptimizeRequest(with_justification=bool(body and body.with_justification), **repository.branch_params(row))
    if body and body.study_year is not None:
        req.study_year = body.study_year
    return jobs.start("optimize", lambda progress: plans.optimize_payload(req, branch_id, progress=progress))


@router.get("/jobs/{job_id}")
def get_job(job_id: str, with_result: bool = True) -> dict:
    """A background job's status, stage and (when done) its result."""
    return jobs.get(job_id, with_result=with_result)


@router.get("/cache")
def cache_stats() -> dict:
    """What the durable result cache holds (see ResultCache.stats)."""
    return cache.stats()
