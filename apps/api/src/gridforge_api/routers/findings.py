"""The findings ledger over HTTP: what a branch's last run found, and the operator's call on each."""

from fastapi import APIRouter, HTTPException

from .. import ledger, repository
from ..config import now
from ..deps import scenarios
from ..schemas import FindingStatusSet

router = APIRouter()


@router.get("/branches/{branch_id}/findings")
def branch_findings(branch_id: str, status: str | None = None, year: int | None = None) -> dict:
    """A branch's findings (the engine's after every run, and the agents'), breaches first, with
    the counts per status. `status` filters open | acknowledged | resolved; `year` one plan year."""
    if status is not None and status not in ledger.STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {', '.join(ledger.STATUSES)}")
    with scenarios.cursor() as con:
        repository.require_branch(con, branch_id)
        return {"branch_id": branch_id, "counts": ledger.counts(con, branch_id),
                "findings": ledger.list_findings(con, branch_id, status=status, year=year)}


@router.post("/findings/{finding_id}/ack")
def set_finding_status(finding_id: str, body: FindingStatusSet) -> dict:
    """Acknowledge a finding (default), resolve it by hand, or reopen it. The next run still
    refreshes its figures; an acknowledged finding stays acknowledged while it persists."""
    with scenarios.cursor() as con:
        row = ledger.set_status(con, finding_id, body.status, body.note, now())
    if row is None:
        raise HTTPException(status_code=404, detail=f"finding '{finding_id}' not found")
    return row
