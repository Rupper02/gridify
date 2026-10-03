"""Branches ("git for grids"): create, list, pull from the registry, schedule, planned outages,
simulated reinforcements, diff, merge, discard, and the copilot's suggestions."""

import uuid

from fastapi import APIRouter, HTTPException

from gridforge_optimizer.config import MAX_SUGGESTIONS

from .. import narration, proposals, repository
from ..config import now
from ..deps import cache, jobs, narrator, plans, scenarios, warehouse
from ..schemas import (
    BestWindowRequest,
    BranchCreate,
    MergeRequest,
    OutageCreate,
    RegistryAdd,
    ReinforcementCreate,
    ScheduleSet,
)

router = APIRouter()


@router.post("/branches")
def create_branch(body: BranchCreate) -> dict:
    """Create a branch (copy-on-create): snapshot the parent's projects, then apply the change."""
    with scenarios.cursor() as con:
        parent = repository.require_branch(con, body.from_branch)
        bid = "br-" + uuid.uuid4().hex[:8]
        pick = repository.pick
        con.execute(
            "INSERT INTO branches (branch_id, name, parent_id, scenario, growth_2030, growth_2035, "
            "w_readiness, w_need, w_strategic, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)",
            [bid, body.name, parent["branch_id"],
             pick(body.scenario, parent["scenario"]), pick(body.growth_2030, parent["growth_2030"]),
             pick(body.growth_2035, parent["growth_2035"]), pick(body.w_readiness, parent["w_readiness"]),
             pick(body.w_need, parent["w_need"]), pick(body.w_strategic, parent["w_strategic"]), now()],
        )
        repository.copy_projects(con, parent["branch_id"], bid)
        repository.copy_branch_extras(con, parent["branch_id"], bid)
        valid = warehouse.valid_bus_ids()
        for p in body.added_projects:
            repository.insert_candidate(con, bid, p, valid)
        return repository.branch_to_client(con, repository.branch_row(con, bid))


@router.get("/branches")
def list_branches() -> dict:
    """All branches, main first then newest-created."""
    with scenarios.cursor() as con:
        ids = [r[0] for r in con.execute(
            "SELECT branch_id FROM branches ORDER BY (branch_id = 'main') DESC, created_at"
        ).fetchall()]
        branches = [repository.branch_to_client(con, repository.branch_row(con, i)) for i in ids]
    return {"branches": branches}


@router.post("/branches/{branch_id}/registry")
def add_from_registry(branch_id: str, body: RegistryAdd) -> dict:
    """Pull a projected project from the registry onto a branch (copies it into the branch's plan)."""
    row = {r["request_id"]: r for r in warehouse.registry_rows()}.get(body.request_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"registry project '{body.request_id}' not found")
    with scenarios.cursor() as con:
        repository.require_branch(con, branch_id)
        repository.add_registry_row(con, branch_id, row)
    cache.clear()
    return repository.to_client({**row, "branch_id": branch_id})


@router.post("/branches/{branch_id}/schedule")
def set_schedule(branch_id: str, body: ScheduleSet) -> dict:
    """Persist the operator's energisation year for one project on a branch. It's a planning
    decision layered on the optimizer's verdict — it doesn't change accept/defer/rank — so the
    next /optimize just reports it alongside the recommendation (and flags any conflict)."""
    if body.year is not None and not (2026 <= body.year <= 2035):
        raise HTTPException(status_code=422, detail="year must be between 2026 and 2035")
    with scenarios.cursor() as con:
        repository.require_branch(con, branch_id)
        if not repository.project_on_branch(con, branch_id, body.request_id):
            raise HTTPException(
                status_code=404,
                detail=f"project '{body.request_id}' is not on branch '{branch_id}'",
            )
        con.execute(
            "UPDATE added_candidates SET scheduled_year = ? WHERE branch_id = ? AND request_id = ?",
            [body.year, branch_id, body.request_id],
        )
    cache.payload.clear()  # the payload carries scheduled_year; the engine result is unaffected
    return {"branch_id": branch_id, "request_id": body.request_id, "scheduled_year": body.year}


@router.post("/branches/{branch_id}/scenario")
def update_scenario(branch_id: str, body: dict) -> dict:
    """Update a branch's demand profile (scenario + growth). Used when the profile picker changes
    on main, so subsequent runs use the selected profile instead of reverting to the stored one."""
    scenario = body.get("scenario")
    growth_2030 = body.get("growth_2030")
    growth_2035 = body.get("growth_2035")
    
    if not scenario or growth_2030 is None or growth_2035 is None:
        raise HTTPException(status_code=422, detail="scenario, growth_2030, and growth_2035 are required")
    
    with scenarios.cursor() as con:
        repository.require_branch(con, branch_id)
        con.execute(
            "UPDATE branches SET scenario=?, growth_2030=?, growth_2035=? WHERE branch_id=?",
            [scenario, growth_2030, growth_2035, branch_id],
        )
        return repository.branch_to_client(con, repository.branch_row(con, branch_id))


@router.get("/branches/{branch_id}/diff")
def diff_branch(branch_id: str, with_narration: bool = False) -> dict:
    """Consequence diff of a branch (head) vs its parent (base, default main): the queue, the
    2030/2035 phases, every plan year, the branch's planned works on the parent's plan vs its own,
    and the planned works and reinforcements a merge would add to or remove from the parent."""
    with scenarios.cursor() as con:
        head_row = repository.require_branch(con, branch_id)
        base_row = repository.branch_row(con, head_row["parent_id"] or "main") or repository.branch_row(con, "main")
        base_id = base_row["branch_id"]
        merge = proposals.on_merge(repository.outage_rows(con, base_id), repository.outage_rows(con, branch_id),
                                   repository.reinforcement_rows(con, base_id), repository.reinforcement_rows(con, branch_id))
    d = plans.diff(branch_id, base_id)
    out = d.model_dump()
    out["on_merge"] = merge
    out["base_branch"] = base_row["branch_id"]
    out["head_branch"] = branch_id
    out["narration"] = ""
    if with_narration:
        out["narration"] = narration.safely(narrator.narrate_diff, narration.summarize_diff(d))
    return out


@router.post("/branches/{branch_id}/merge")
def merge_branch(branch_id: str, body: MergeRequest | None = None) -> dict:
    """Squash-merge a branch into `into` (default main): it adopts the branch's scenario + projects."""
    into = (body.into if body else "main") or "main"
    if branch_id == into:
        raise HTTPException(status_code=400, detail="cannot merge a branch into itself")
    with scenarios.cursor() as con:
        b = repository.require_branch(con, branch_id)
        repository.require_branch(con, into)
        if b["status"] != "open":
            raise HTTPException(status_code=409, detail=f"branch is '{b['status']}', not open")
        con.execute(
            "UPDATE branches SET scenario=?, growth_2030=?, growth_2035=?, "
            "w_readiness=?, w_need=?, w_strategic=? WHERE branch_id=?",
            [b["scenario"], b["growth_2030"], b["growth_2035"],
             b["w_readiness"], b["w_need"], b["w_strategic"], into],
        )
        con.execute("DELETE FROM added_candidates WHERE branch_id = ?", [into])
        repository.copy_projects(con, branch_id, into)
        repository.clear_branch_extras(con, into)
        repository.copy_branch_extras(con, branch_id, into)
        con.execute("UPDATE branches SET status='merged', merged_at=? WHERE branch_id=?", [now(), branch_id])
        out = repository.branch_to_client(con, repository.branch_row(con, into))
    cache.clear()
    return out


@router.post("/branches/{branch_id}/discard")
def discard_branch(branch_id: str) -> dict:
    """Soft-discard a branch (kept for audit; main cannot be discarded)."""
    if branch_id == "main":
        raise HTTPException(status_code=400, detail="cannot discard main")
    with scenarios.cursor() as con:
        repository.require_branch(con, branch_id)
        con.execute("UPDATE branches SET status='discarded' WHERE branch_id=?", [branch_id])
        return repository.branch_to_client(con, repository.branch_row(con, branch_id))


@router.get("/branches/{branch_id}/suggestions")
def branch_suggestions(branch_id: str, limit: int = MAX_SUGGESTIONS, with_narration: bool = False,
                       request_id: str | None = None) -> dict:
    """The copilot: concrete, quantified unblocks for the projects this branch defers on the grid
    (or for one of them, `request_id`), trialled on the branch's reinforced network."""
    sugs = plans.suggestions(branch_id, limit, request_id)
    base = plans.branch_result(branch_id) if with_narration else None
    out = []
    for s in sugs:
        d = s.model_dump()
        d["narration"] = ""
        if with_narration:
            d["narration"] = narration.safely(narrator.narrate_suggestion, narration.summarize_suggestion(s, base))
        out.append(d)
    return {"branch_id": branch_id, "request_id": request_id, "suggestions": out}


# --- planned maintenance and simulated reinforcements --------------------------
def _require_editable(con, branch_id: str) -> None:
    """Outages and reinforcements are proposals: main (the plan of record) is changed only by merging."""
    b = repository.require_branch(con, branch_id)
    if branch_id == "main":
        raise HTTPException(status_code=409, detail="main is read-only: open a branch to propose this")
    if b["status"] != "open":
        raise HTTPException(status_code=409, detail=f"branch is '{b['status']}', not open")


@router.get("/branches/{branch_id}/outages")
def list_outages(branch_id: str) -> dict:
    """The planned maintenance windows on a branch (studied in each run, in their season)."""
    with scenarios.cursor() as con:
        repository.require_branch(con, branch_id)
        return {"branch_id": branch_id, "outages": repository.outage_rows(con, branch_id)}


@router.post("/branches/{branch_id}/outages")
def add_outage(branch_id: str, body: OutageCreate) -> dict:
    """Schedule a works window (maintenance, like-for-like replacement or repowering) on a line,
    transformer or existing generator. The next run studies it, and a repowering changes the years
    after it; until then the planner shows the result as out of date."""
    _require_element(body.element_kind, body.element_id)
    with scenarios.cursor() as con:
        _require_editable(con, branch_id)
        return repository.insert_outage(con, branch_id, body)


def _require_element(kind: str, element_id: str) -> None:
    known = {"line": warehouse.line_ids, "trafo": warehouse.trafo_ids, "gen": warehouse.generator_ids}[kind]()
    if element_id not in known:
        raise HTTPException(status_code=422, detail=f"{kind} '{element_id}' is not in the network model")


@router.post("/branches/{branch_id}/works/best-window")
def start_best_window(branch_id: str, body: BestWindowRequest) -> dict:
    """Find the best window for a planned work: the element studied out in every season of every
    year in `years`, against the branch's plan as it stands that year (its queue, schedule,
    reinforcements and other windows), ranked by verdict, then curtailment, demand at risk, N-1
    findings during the window and loading. Read-only, so it runs on main too. Runs as a background
    job (progress per year); the job's result is {branch_id, element_kind, element_id, work, options}."""
    _require_element(body.element_kind, body.element_id)
    with scenarios.cursor() as con:
        repository.require_branch(con, branch_id)

    def run(progress, _publish) -> dict:
        options = plans.best_windows(branch_id, body, progress=progress)
        return {"branch_id": branch_id, "element_kind": body.element_kind, "element_id": body.element_id,
                "work": body.work, "options": options}
    return jobs.start("best_window", run)


@router.delete("/branches/{branch_id}/outages/{outage_id}")
def remove_outage(branch_id: str, outage_id: str) -> dict:
    with scenarios.cursor() as con:
        _require_editable(con, branch_id)
        if not repository.delete_branch_row(con, "branch_outages", "outage_id", branch_id, outage_id):
            raise HTTPException(status_code=404, detail=f"outage '{outage_id}' not on branch '{branch_id}'")
    return {"branch_id": branch_id, "outage_id": outage_id, "removed": True}


@router.get("/branches/{branch_id}/reinforcements")
def list_reinforcements(branch_id: str) -> dict:
    """The simulated reinforcements proposed on a branch (each run applies them)."""
    with scenarios.cursor() as con:
        repository.require_branch(con, branch_id)
        return {"branch_id": branch_id, "reinforcements": repository.reinforcement_rows(con, branch_id)}


@router.post("/branches/{branch_id}/reinforcements")
def add_reinforcement(branch_id: str, body: ReinforcementCreate) -> dict:
    """Propose a reinforcement on a branch (a Copilot lever). The next run measures it against the queue."""
    known = {"line": warehouse.line_ids, "trafo": warehouse.trafo_ids}.get(body.kind)
    if known is not None and str(body.element_id) not in known():
        raise HTTPException(status_code=422, detail=f"{body.kind} '{body.element_id}' is not in the network model")
    with scenarios.cursor() as con:
        _require_editable(con, branch_id)
        return repository.insert_reinforcement(con, branch_id, body)


@router.delete("/branches/{branch_id}/reinforcements/{reinforcement_id}")
def remove_reinforcement(branch_id: str, reinforcement_id: str) -> dict:
    with scenarios.cursor() as con:
        _require_editable(con, branch_id)
        if not repository.delete_branch_row(con, "branch_reinforcements", "reinforcement_id", branch_id, reinforcement_id):
            raise HTTPException(status_code=404, detail=f"reinforcement '{reinforcement_id}' not on branch '{branch_id}'")
    return {"branch_id": branch_id, "reinforcement_id": reinforcement_id, "removed": True}
