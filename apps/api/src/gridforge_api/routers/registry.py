"""The registry of projected projects, and adding a manual project to a branch."""

from fastapi import APIRouter, HTTPException

from gridforge_optimizer.config import GENERATION_FACTORS

from .. import repository
from ..deps import cache, scenarios, warehouse
from ..schemas import ChatFileProject, NewCandidate

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
        row = repository.insert_candidate(con, body.branch_id, body, warehouse.valid_bus_ids())
    cache.clear()  # candidate set changed
    return repository.to_client(row)


@router.post("/chat/file-project")
def chat_file_project(body: ChatFileProject) -> dict:
    """File a connection project from chat after confirming MW, bus (must exist on this GSP), and
    technology (must be one the engine models). Returns the filed project or an error explaining
    what is missing. Does not set year, does not rank, does not adopt. The chat does not run its
    own power flow."""
    valid_bus_ids = warehouse.valid_bus_ids()
    modeled_techs = set(GENERATION_FACTORS.get("winter_peak", {}).keys()) | set(
        GENERATION_FACTORS.get("summer_min", {}).keys()
    )
    # Validation: must have all three pieces confirmed
    reasons = []
    if body.rating_mw is None or body.rating_mw <= 0:
        reasons.append("rating_mw must be > 0")
    if body.bus_id not in valid_bus_ids:
        reasons.append(f"bus {body.bus_id} not found on this GSP")
    if body.technology not in modeled_techs:
        reasons.append(
            f"technology '{body.technology}' not modeled (engine models: {', '.join(sorted(modeled_techs))})"
        )
    if reasons:
        raise HTTPException(status_code=422, detail="; ".join(reasons))
    # File the project onto the target branch WITHOUT a commissioned year (allow_no_year=True)
    candidate = NewCandidate(
        applicant=body.applicant or "Chat-filed project",
        bus_id=body.bus_id,
        technology=body.technology,
        rating_mw=body.rating_mw,
        branch_id=body.branch_id,
    )
    with scenarios.cursor() as con:
        row = repository.insert_candidate(con, body.branch_id, candidate, valid_bus_ids, allow_no_year=True)
    cache.clear()
    return repository.to_client(row)
