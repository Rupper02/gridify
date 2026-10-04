"""The registry of projected projects, adding a manual project to a branch, and changing one there."""

from fastapi import APIRouter, HTTPException

from .. import repository
from ..config import NGED_PROJECT_ID
from ..deps import plans, projects, scenarios
from ..schemas import CandidateChange, NewCandidate

router = APIRouter()


@router.get("/optimize/candidates")
def optimize_candidates() -> list[dict]:
    """The registry pool (projected projects available to add to a branch), shaped for the client."""
    return [repository.to_client(r) for r in projects.registry_rows(NGED_PROJECT_ID)]


@router.get("/registry")
def registry() -> list[dict]:
    """The built-in project's registry of projected connection projects: the pool its branches pull from."""
    return [repository.to_client(r) for r in projects.registry_rows(NGED_PROJECT_ID)]


@router.post("/optimize/candidates")
def add_candidate(body: NewCandidate) -> dict:
    """Add a project to a branch (stored in the API scenarios DB; warehouse untouched)."""
    with scenarios.cursor() as con:
        branch = repository.require_open(con, body.branch_id, allow_main=False)
        row = repository.insert_candidate(con, body.branch_id, body, projects.element_ids(branch["project_id"])["buses"])
    plans.invalidate("plan")  # the candidate set changed
    return repository.to_client(row)


@router.get("/branches/{branch_id}/candidates")
def branch_candidates(branch_id: str) -> list[dict]:
    """The projects on a branch as stored (added by hand, pulled from the registry, or an agent's approved
    proposal): what its next run ranks, shaped for the client."""
    with scenarios.cursor() as con:
        repository.require_branch(con, branch_id)
        return [repository.to_client(r) for r in repository.candidate_rows(con, branch_id)]


@router.patch("/branches/{branch_id}/candidates/{request_id}")
def change_candidate(branch_id: str, request_id: str, body: CandidateChange) -> dict:
    """Change a project on a branch: its point of connection (`bus_id`), export rating, import capacity or
    requested year; re-triaged, and the next run measures it. 404 when the project is not on the branch;
    409 on `main` or a branch that is not open."""
    with scenarios.cursor() as con:
        branch = repository.require_open(con, branch_id, allow_main=False)
        try:
            row = repository.update_candidate(con, branch_id, request_id, body.model_dump(exclude_none=True),
                                              projects.element_ids(branch["project_id"])["buses"])
        except KeyError:
            raise HTTPException(status_code=404, detail=f"project '{request_id}' is not on branch '{branch_id}'") from None
    plans.invalidate("plan")  # the candidate set changed
    return row
