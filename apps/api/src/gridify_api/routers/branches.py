"""Branches: create, list, the connections on them, the demand profile, runs, the diff against the parent, merge
and discard."""

from fastapi import APIRouter

from gridify_optimizer.config import FORECASTS

from .. import repository
from ..config import now
from ..deps import cache, grid, jobs, plans, scenarios
from ..errors import Conflict, Invalid, NotFound
from ..schemas import BranchCreate, ConnectionChange, ConnectionCreate, ProfileSet, RunRequest

router = APIRouter()


@router.get("/branches")
def list_branches() -> dict:
    """Every branch, main first."""
    with scenarios.cursor() as con:
        return {"branches": repository.list_branches(con)}


@router.post("/branches")
def create_branch(body: BranchCreate) -> dict:
    """Open a branch off another (copy-on-create: its connections and demand profile come along)."""
    with scenarios.cursor() as con:
        parent = repository.require_branch(con, body.from_branch)
        return repository.branch_to_client(con, repository.open_branch(con, parent, body.name))


@router.get("/branches/{branch_id}")
def get_branch(branch_id: str) -> dict:
    with scenarios.cursor() as con:
        return repository.branch_to_client(con, repository.require_branch(con, branch_id))


# --- connections ---------------------------------------------------------------------------------------------
@router.get("/branches/{branch_id}/connections")
def list_connections(branch_id: str) -> list[dict]:
    with scenarios.cursor() as con:
        repository.require_branch(con, branch_id)
        return [repository.to_client(r) for r in repository.connection_rows(con, branch_id)]


@router.post("/branches/{branch_id}/connections")
def add_connection(branch_id: str, body: ConnectionCreate) -> dict:
    """Place a connection on a branch: by hand, or a registry project (`from_registry`) with any field overridden."""
    fields = body.model_dump(exclude_none=True, exclude={"from_registry"})
    request_id, source = None, "manual"
    if body.from_registry:
        reg = next((r for r in grid.registry() if r["request_id"] == body.from_registry), None)
        if reg is None:
            raise NotFound(f"'{body.from_registry}' is not in the registry")
        keep = ("name", "bus_id", "technology", "rating_mw", "import_mw", "year")
        fields = {**{k: reg[k] for k in keep if reg.get(k) is not None}, **fields}
        request_id, source = reg["request_id"], "registry"
    bus_ids = grid.bus_ids()  # a model read: never under the store lock
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id, allow_main=False)
        return repository.insert_connection(con, branch_id, fields, bus_ids, source=source, request_id=request_id)


@router.patch("/branches/{branch_id}/connections/{request_id}")
def change_connection(branch_id: str, request_id: str, body: ConnectionChange) -> dict:
    """Change a connection on a branch: where it connects, its size, how it runs, or the year it energises."""
    bus_ids = grid.bus_ids()
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id, allow_main=False)
        return repository.update_connection(con, branch_id, request_id, body.model_dump(exclude_none=True), bus_ids)


@router.delete("/branches/{branch_id}/connections/{request_id}")
def remove_connection(branch_id: str, request_id: str) -> dict:
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id, allow_main=False)
        repository.delete_connection(con, branch_id, request_id)
    return {"removed": request_id}


# --- demand profile -------------------------------------------------------------------------------------------
@router.post("/branches/{branch_id}/profile")
def set_profile(branch_id: str, body: ProfileSet) -> dict:
    """A branch's demand profile: a pathway, or `custom` with both anchors. Editable on main too (it is how today's
    network is studied, not a change to it)."""
    if body.scenario != "custom" and body.scenario not in FORECASTS:
        raise Invalid(f"unknown demand pathway '{body.scenario}'")
    if body.scenario == "custom" and (body.growth_2030 is None or body.growth_2035 is None):
        raise Invalid("a custom profile needs both anchors (growth_2030, growth_2035)")
    with scenarios.cursor() as con:
        row = repository.require_open(con, branch_id)
        profile = {"scenario": body.scenario, "growth_2030": body.growth_2030 if body.growth_2030 is not None else row["growth_2030"],
                   "growth_2035": body.growth_2035 if body.growth_2035 is not None else row["growth_2035"]}
        repository.set_profile(con, branch_id, profile)
        return repository.branch_to_client(con, repository.require_branch(con, branch_id))


# --- runs -----------------------------------------------------------------------------------------------------
@router.post("/branches/{branch_id}/run")
def run_branch(branch_id: str, body: RunRequest | None = None) -> dict:
    """Start a run of the branch in the background: every plan year, `view_year` first. Poll GET /jobs/{job_id}
    (`partial=true` shows the years as they land); a cached run finishes at once. A run of the same inputs already
    queued or running is joined, not queued again."""
    view_year = body.view_year if body else None
    b = plans.inputs(branch_id)
    if not cache.has(plans.run_key(b)):  # a cached plan finishes at once: it need not stop anything
        _stop_year_runs()
    return jobs.start("run", lambda progress, publish: plans.run(b, progress=progress, publish=publish, view_year=view_year),
                      key=plans.run_key(b))


@router.post("/branches/{branch_id}/simulate")
def simulate_branch(branch_id: str) -> dict:
    """Run the branch and wait for it (scripts and tests; the planner uses the job)."""
    _stop_year_runs()
    return plans.run(plans.inputs(branch_id))


YEAR_STOPPED = ("stopped so a branch's plan years could solve first. Nothing of it was kept: run the year again once the "
                "branch holds what you want to study")


def _stop_year_runs() -> None:
    """A plan run never waits behind a branch's year (up to twenty minutes on the one worker): the year job stops at its
    next progress report, a few seconds, and leaves no file (`year_runs`: whole or not at all)."""
    jobs.stop_kind("year", YEAR_STOPPED)


@router.get("/branches/{branch_id}/result")
def branch_result(branch_id: str) -> dict:
    """The branch's result for what it holds now, never solving: 409 `not_solved` until it has run."""
    return plans.latest(branch_id)


@router.get("/branches/{branch_id}/diff")
def diff_branch(branch_id: str) -> dict:
    """The branch against its parent, year by year, on the branch's demand profile (so the difference is its
    connections). The branch must have run; 409 `not_solved` otherwise."""
    with scenarios.cursor() as con:
        head = repository.require_branch(con, branch_id)
    if repository.is_main(head):
        raise Conflict("main has no parent to compare with")
    return {"base": head["parent_id"], **plans.diff(branch_id, head["parent_id"]).model_dump()}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    """Stop a queued or running job (a newer edit supersedes it). What it already solved stays cached."""
    return jobs.cancel(job_id)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, with_result: bool = True, partial: bool = False, since: int | None = None) -> dict:
    """A job's status, stage, its partial result while running (`partial=true`, sent only when its
    `partial_version` differs from `since`) and its result when done."""
    return jobs.get(job_id, with_result=with_result, with_partial=partial, since=since)


# --- merge and discard ------------------------------------------------------------------------------------------
@router.post("/branches/{branch_id}/merge")
def merge_branch(branch_id: str) -> dict:
    """Merge a branch into its parent: the parent adopts its connections and demand profile, and the branch closes."""
    with scenarios.cursor() as con:
        head = repository.require_open(con, branch_id, allow_main=False)
        parent = repository.require_open(con, head["parent_id"])
        repository.merge_into(con, head, parent)
        return {"merged": branch_id, "into": parent["branch_id"], "at": now()}


@router.post("/branches/{branch_id}/discard")
def discard_branch(branch_id: str) -> dict:
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id, allow_main=False)
        repository.set_status(con, branch_id, "discarded")
    return {"discarded": branch_id}
