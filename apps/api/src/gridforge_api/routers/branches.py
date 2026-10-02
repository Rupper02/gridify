"""Branches ("git for grids"): create, list, pull from the registry, schedule, diff, merge, discard,
and the copilot's suggestions."""

import uuid

from fastapi import APIRouter, HTTPException

from gridforge_optimizer import diff_results
from gridforge_optimizer.config import MAX_SUGGESTIONS

from .. import narration, repository
from ..cache import cand_key
from ..config import now
from ..deps import cache, narrator, plans, scenarios, warehouse
from ..schemas import BranchCreate, MergeRequest, RegistryAdd, ScheduleSet

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


@router.get("/branches/{branch_id}/diff")
def diff_branch(branch_id: str, with_narration: bool = False) -> dict:
    """Consequence diff of a branch (head) vs its parent (base, default main)."""
    with scenarios.cursor() as con:
        head_row = repository.require_branch(con, branch_id)
        base_row = repository.branch_row(con, head_row["parent_id"] or "main") or repository.branch_row(con, "main")
    head_cands = plans.candidates(branch_id)
    base_cands = plans.candidates(base_row["branch_id"])
    head = plans.compute(repository.branch_request(head_row), head_cands, cand_key(head_cands))
    base = plans.compute(repository.branch_request(base_row), base_cands, cand_key(base_cands))
    d = diff_results(base, head)
    out = d.model_dump()
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
def branch_suggestions(branch_id: str, limit: int = MAX_SUGGESTIONS, with_narration: bool = False) -> dict:
    """The copilot: concrete, quantified unblocks for the projects this branch defers on the grid."""
    with scenarios.cursor() as con:
        row = repository.require_branch(con, branch_id)
    cands = plans.candidates(branch_id)
    ckey = cand_key(cands)
    req = repository.branch_request(row)
    base = plans.compute(req, cands, ckey)
    out = []
    for s in plans.suggestions(req, cands, ckey, limit):
        d = s.model_dump()
        d["narration"] = ""
        if with_narration:
            d["narration"] = narration.safely(narrator.narrate_suggestion, narration.summarize_suggestion(s, base))
        out.append(d)
    return {"branch_id": branch_id, "suggestions": out}
