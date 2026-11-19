"""Jobs over HTTP: a plan run's or a branch year's progress, partial result and result, and stopping one."""

from fastapi import APIRouter

from ..deps import jobs

router = APIRouter()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, with_result: bool = True, partial: bool = False, since: int | None = None) -> dict:
    """A job's status, stage, its partial result while running (`partial=true`, sent only when its
    `partial_version` differs from `since`) and its result when done."""
    return jobs.get(job_id, with_result=with_result, with_partial=partial, since=since)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    """Stop a queued or running job (a newer edit supersedes it). What it already solved stays cached."""
    return jobs.cancel(job_id)
