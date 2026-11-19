"""Branches over HTTP: create and list them, the connections on them, the demand profile, runs, the diff against the
parent, merge and discard. Each handler parses the request and calls one service method."""

from fastapi import APIRouter

from ..deps import branches, plans
from ..schemas import BranchCreate, ConnectionChange, ConnectionCreate, ProfileSet, RunRequest

router = APIRouter()


@router.get("/branches")
def list_branches() -> dict:
    """Every branch, main first."""
    return {"branches": branches.list()}


@router.post("/branches")
def create_branch(body: BranchCreate) -> dict:
    """Open a branch off another (copy-on-create: its connections and demand profile come along)."""
    return branches.open(body.name, body.from_branch)


@router.get("/branches/{branch_id}")
def get_branch(branch_id: str) -> dict:
    return branches.get(branch_id)


# --- connections ---------------------------------------------------------------------------------------------
@router.get("/branches/{branch_id}/connections")
def list_connections(branch_id: str) -> list[dict]:
    return branches.connections(branch_id)


@router.post("/branches/{branch_id}/connections")
def add_connection(branch_id: str, body: ConnectionCreate) -> dict:
    """Place a connection on a branch: by hand, or a registry project (`from_registry`) with any field overridden."""
    return branches.add_connection(branch_id, body.model_dump(exclude_none=True, exclude={"from_registry"}), body.from_registry)


@router.patch("/branches/{branch_id}/connections/{request_id}")
def change_connection(branch_id: str, request_id: str, body: ConnectionChange) -> dict:
    """Change a connection on a branch: where it connects, its size, how it runs, or the year it energises."""
    return branches.change_connection(branch_id, request_id, body.model_dump(exclude_none=True))


@router.delete("/branches/{branch_id}/connections/{request_id}")
def remove_connection(branch_id: str, request_id: str) -> dict:
    branches.remove_connection(branch_id, request_id)
    return {"removed": request_id}


@router.post("/branches/{branch_id}/profile")
def set_profile(branch_id: str, body: ProfileSet) -> dict:
    """A branch's demand profile: a pathway, or `custom` with both anchors. Editable on main too."""
    return branches.set_profile(branch_id, body.scenario, body.growth_2030, body.growth_2035)


# --- runs -----------------------------------------------------------------------------------------------------
@router.post("/branches/{branch_id}/run")
def run_branch(branch_id: str, body: RunRequest | None = None) -> dict:
    """Start a run of the branch in the background: every plan year, `view_year` first. Poll GET /jobs/{job_id}
    (`partial=true` shows the years as they land); a cached run finishes at once, and a run of the same inputs already
    queued or running is joined."""
    return plans.start_run(branch_id, body.view_year if body else None)


@router.post("/branches/{branch_id}/simulate")
def simulate_branch(branch_id: str) -> dict:
    """Run the branch and wait for it (scripts and tests; the planner uses the job)."""
    return plans.simulate(branch_id)


@router.get("/branches/{branch_id}/result")
def branch_result(branch_id: str) -> dict:
    """The branch's result for what it holds now, never solving: 409 `not_solved` until it has run."""
    return plans.latest(branch_id)


@router.get("/branches/{branch_id}/diff")
def diff_branch(branch_id: str) -> dict:
    """The branch against its parent, year by year, on the branch's demand profile (so the difference is its
    connections). The branch must have run; 409 `not_solved` otherwise."""
    return plans.compare_with_parent(branch_id)


# --- merge and discard ------------------------------------------------------------------------------------------
@router.post("/branches/{branch_id}/merge")
def merge_branch(branch_id: str) -> dict:
    """Merge a branch into its parent: the parent adopts its connections and demand profile, and the branch closes.
    409 when the parent has changed since the branch was opened."""
    return branches.merge(branch_id)


@router.post("/branches/{branch_id}/discard")
def discard_branch(branch_id: str) -> dict:
    return branches.discard(branch_id)
