"""The registry of projected projects, and adding a manual project to a branch."""

from fastapi import APIRouter

from .. import repository
from ..config import NGED_PROJECT_ID
from ..deps import plans, projects, scenarios
from ..schemas import NewCandidate

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
