"""The registry of projected projects, and adding a manual project to a branch."""

from fastapi import APIRouter

from .. import repository
from ..deps import plans, scenarios, warehouse
from ..schemas import NewCandidate

router = APIRouter()


@router.get("/optimize/candidates")
def optimize_candidates() -> list[dict]:
    """The registry pool (projected projects available to add to a branch), shaped for the client."""
    return [repository.to_client(r) for r in warehouse.registry_rows()]


@router.get("/registry")
def registry() -> list[dict]:
    """The registry of projected connection projects: the pool branches pull from."""
    return [repository.to_client(r) for r in warehouse.registry_rows()]


@router.post("/optimize/candidates")
def add_candidate(body: NewCandidate) -> dict:
    """Add a project to a branch (stored in the API scenarios DB; warehouse untouched)."""
    with scenarios.cursor() as con:
        repository.require_open(con, body.branch_id, allow_main=False)
        row = repository.insert_candidate(con, body.branch_id, body, warehouse.valid_bus_ids())
    plans.invalidate("plan")  # the candidate set changed
    return repository.to_client(row)
