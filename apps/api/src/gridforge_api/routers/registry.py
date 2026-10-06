"""The registry of projected projects, adding a manual project to a branch, and changing one there."""

from fastapi import APIRouter, HTTPException

from .. import repository
from ..config import NGED_PROJECT_ID
from ..deps import plans, projects, scenarios
from ..schemas import CandidateChange, CandidateCreate

router = APIRouter()


@router.get("/registry")
def registry() -> list[dict]:
    """The built-in project's registry of projected connection projects: the pool its branches pull from."""
    return [repository.to_client(r) for r in projects.registry_rows(NGED_PROJECT_ID)]


def _branch_project(branch_id: str) -> str:
    with scenarios.cursor() as con:
        return repository.require_branch(con, branch_id)["project_id"]


@router.post("/optimize/candidates")
def add_candidate(body: CandidateCreate) -> dict:
    """Add a project to a branch (stored in the API scenarios DB; warehouse untouched)."""
    valid = projects.element_ids(_branch_project(body.branch_id))["buses"]  # a model read: never under the store lock
    with scenarios.cursor() as con:
        repository.require_open(con, body.branch_id, allow_main=False)
        row = repository.insert_candidate(con, body.branch_id, body, valid)
    plans.edited()
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
    valid = projects.element_ids(_branch_project(branch_id))["buses"]  # a model read: never under the store lock
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id, allow_main=False)
        try:
            row = repository.update_candidate(con, branch_id, request_id, body.model_dump(exclude_none=True), valid)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"project '{request_id}' is not on branch '{branch_id}'") from None
    plans.edited()
    return row
