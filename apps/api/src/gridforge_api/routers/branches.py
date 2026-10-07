"""Branches ("git for grids"): create, list, pull from the registry, schedule, planned outages,
simulated reinforcements, diff, the merge gate, merge, discard and rebase."""

import uuid

from fastapi import APIRouter, HTTPException

from gridforge_optimizer import MergeVerdict

from .. import ledger, proposals, rebase, repository
from ..agents import events
from ..config import now
from ..store import PROFILE_COLS
from ..deps import agents, plans, projects, scenarios
from ..schemas import (
    BranchCreate,
    MergeRequest,
    OutageCreate,
    RebaseRequest,
    RegistryAdd,
    ReinforcementCreate,
    ScenarioUpdate,
    ScheduleSet,
)

router = APIRouter()


@router.post("/branches")
def create_branch(body: BranchCreate) -> dict:
    """Create a branch (copy-on-create): snapshot the parent's projects, then apply the change."""
    valid = projects.element_ids(_project_of(body.from_branch))["buses"]  # a model read: never under the store lock
    with scenarios.cursor() as con:
        parent = repository.require_branch(con, body.from_branch)
        bid = repository.open_branch(con, parent, body.name, created_by="operator",
                                     overrides=body.model_dump(include=set(PROFILE_COLS)))
        for p in body.added_projects:
            repository.insert_candidate(con, bid, p, valid)
        return repository.branch_to_client(con, repository.branch_row(con, bid))


@router.get("/branches")
def list_branches(project_id: str | None = None) -> dict:
    """All branches (or one project's), each project's main first then newest-created."""
    with scenarios.cursor() as con:
        ids = repository.branch_ids(con, project_id)
        branches = [repository.branch_to_client(con, repository.branch_row(con, i)) for i in ids]
    return {"branches": branches}


def _project_of(branch_id: str) -> str:
    with scenarios.cursor() as con:
        return repository.require_branch(con, branch_id)["project_id"]


@router.post("/branches/{branch_id}/registry")
def add_from_registry(branch_id: str, body: RegistryAdd) -> dict:
    """Pull a projected project from the registry onto a branch (copies it into the branch's plan)."""
    row = {r["request_id"]: r for r in projects.registry_rows(_project_of(branch_id))}.get(body.request_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"registry project '{body.request_id}' not found")
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id, allow_main=False)
        repository.add_registry_row(con, branch_id, row)
    plans.edited()
    return repository.to_client({**row, "branch_id": branch_id})


@router.post("/branches/{branch_id}/schedule")
def set_schedule(branch_id: str, body: ScheduleSet) -> dict:
    """Persist the operator's energisation year for one project on a branch. It's a planning
    decision layered on the optimizer's verdict (it doesn't change accept/defer/rank), so the next
    run just reports it alongside the recommendation and flags any conflict."""
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id, allow_main=False)
        if not repository.project_on_branch(con, branch_id, body.request_id):
            raise HTTPException(status_code=404, detail=f"project '{body.request_id}' is not on branch '{branch_id}'")
        repository.set_schedule(con, branch_id, body.request_id, body.year)
    plans.edited()
    return {"branch_id": branch_id, "request_id": body.request_id, "scheduled_year": body.year}


@router.post("/branches/{branch_id}/scenario")
def update_scenario(branch_id: str, body: ScenarioUpdate) -> dict:
    """Update a branch's demand profile (scenario + growth), main's included: the profile picker
    changes it so later runs use the selected profile instead of reverting to the stored one."""
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id)
        repository.update_scenario(con, branch_id, body.scenario, body.growth_2030, body.growth_2035)
        return repository.branch_to_client(con, repository.branch_row(con, branch_id))


# --- review: diff, the merge gate, merge, discard ------------------------------------------------------
def _pair(con, branch_id: str, into: str | None) -> tuple[dict, dict]:
    """The head branch and the base it is compared with / merges into (`into`, else its parent). A project's main
    is the plan of record: branches merge into it and it merges nowhere (400); `into` must be a branch of the same
    project."""
    head = repository.require_branch(con, branch_id)
    if repository.is_main(head):
        raise HTTPException(status_code=400, detail=f"'{branch_id}' is its project's main, the plan of record: branches merge into it, it merges nowhere")
    base = repository.require_branch(con, into) if into else repository.base_of(con, head)
    if base is None or base["branch_id"] == branch_id:
        raise HTTPException(status_code=400, detail="cannot merge a branch into itself")
    if base.get("project_id") != head.get("project_id"):
        raise HTTPException(status_code=400, detail=f"'{base['branch_id']}' belongs to another project: a branch merges only within its own")
    return head, base


def _changes_on_merge(con, base_id: str, head_id: str) -> dict:
    """The planned works and reinforcements a merge adds to or removes from the base."""
    return proposals.on_merge(repository.outage_rows(con, base_id), repository.outage_rows(con, head_id),
                              repository.reinforcement_rows(con, base_id), repository.reinforcement_rows(con, head_id))


def _gate(branch_id: str, base_id: str, *, blocking: bool = True) -> tuple[MergeVerdict, dict]:
    return plans.merge_check(branch_id, base_id, blocking=blocking)


@router.get("/branches/{branch_id}/diff")
def diff_branch(branch_id: str, with_narration: bool = False, solve: bool = False) -> dict:
    """Consequence diff of a branch (head) vs its parent (base, default main): the queue, the
    2030/2035 phases, every plan year, the branch's planned works on the parent's plan vs its own,
    and the planned works and reinforcements a merge would add to or remove from the parent. A read:
    the branch's own plan must have run for what it holds now (else 409 `not_solved`, run it first), and
    the parent's side and the branch's windows on the parent's plan are computed only while the engine is
    free (else 409 `not_solved` with `retry: true`). `?solve=1` waits and solves whatever is missing."""
    with scenarios.cursor() as con:
        head, base = _pair(con, branch_id, None)
        merge = _changes_on_merge(con, base["branch_id"], branch_id)
    d = plans.diff(branch_id, base["branch_id"], blocking=solve)
    out = d.model_dump()
    out["on_merge"] = merge
    out["base_branch"] = base["branch_id"]
    out["head_branch"] = branch_id
    out["narration"] = plans.diff_narration(branch_id, base["branch_id"], d) if with_narration else ""
    return out


@router.get("/branches/{branch_id}/limits")
def branch_limits(branch_id: str) -> dict:
    """What limits the branch's plan, as the engine reduces it (`analysis.limits`): the binding set (each element with its
    envelope per year and its case, the first year it comes near its limit, the headroom left, the projects deferred on
    it, the outages that breach it), the deferrals with their chains, the N-1 rows folded into clusters by cause, and the
    works verdicts. A read: 409 `not_solved` until the branch has run for what it holds now."""
    with scenarios.cursor() as con:
        repository.require_branch(con, branch_id)
    return plans.limits(branch_id).model_dump()


@router.get("/branches/{branch_id}/merge-check")
def merge_check(branch_id: str, into: str | None = None, solve: bool = False) -> dict:
    """May this branch merge? The gate's verdict (gate.merge_verdict) against `into` (default its
    parent): fresh or stale, the blockers, the warnings that need acknowledging, and what the
    parent already carries. A stale branch is judged without a solve; the parent's plan is computed only
    while the engine is free (else 409 `not_solved` with `retry: true`); `?solve=1` waits for it."""
    with scenarios.cursor() as con:
        head, base = _pair(con, branch_id, into)
    verdict, evidence = _gate(branch_id, base["branch_id"], blocking=solve)
    return {
        "branch_id": branch_id, "into": base["branch_id"], "branch_status": head["status"],
        "fresh": evidence["fresh"], "stale_reasons": evidence["stale_reasons"],
        "requires_acknowledgement": verdict.ok and bool(verdict.warnings),
        "verdict": verdict.model_dump(), "evidence": evidence, "checked_at": now(),
    }


@router.post("/branches/{branch_id}/merge")
def merge_branch(branch_id: str, body: MergeRequest | None = None) -> dict:
    """Squash-merge a branch into `into` (default its parent, the project's main for a branch off it): it adopts the branch's scenario, projects,
    planned works and reinforcements. Gated: a stale branch, or one that introduces or worsens a
    problem in any plan year, is refused (409, `code: "blocked"`, the verdict in the body); warnings
    are refused until `acknowledge` is true (`code: "warnings_unacknowledged"`). Every attempt,
    refused or done, is recorded with the verdict it was judged on."""
    body = body or MergeRequest()
    with scenarios.cursor() as con:
        head, base = _pair(con, branch_id, body.into)
        repository.require_open(con, branch_id, allow_main=False)
        repository.require_open(con, base["branch_id"])
    verdict, evidence = _gate(branch_id, base["branch_id"])
    if verdict.blockers:
        code, message = "blocked", verdict.blockers[0].message
    elif verdict.warnings and not body.acknowledge:
        n = len(verdict.warnings)
        code, message = "warnings_unacknowledged", f"{n} warning{'s' if n != 1 else ''} to acknowledge before merging: {verdict.warnings[0].message}"
    else:
        code = message = None
    # the gate can take minutes: a branch edited meanwhile (its profile, its projects) is not what was judged
    if not code and evidence["fresh"] and plans.freshness(branch_id).years_key != evidence.get("head_years_key"):
        code, message = "blocked", "The branch changed while the gate judged it: check it again before merging."
    with scenarios.cursor() as con:
        head = repository.require_branch(con, branch_id)  # merged as it stands now, never as it was read before the gate
        ledger.record_merge(con, merge_id="mg-" + uuid.uuid4().hex[:8], branch_id=branch_id, into=base["branch_id"],
                            outcome="refused" if code else "merged", verdict=verdict.model_dump(),
                            acknowledged=body.acknowledge, evidence=evidence, at=now())
        if code:
            raise HTTPException(status_code=409, detail={"code": code, "message": message, "fresh": evidence["fresh"],
                                                         "verdict": verdict.model_dump()})
        repository.merge_into(con, head, base["branch_id"])
        out = repository.branch_to_client(con, repository.branch_row(con, base["branch_id"]))
    plans.edited()
    events.emit(agents, "branch.merged", {"project_id": base["project_id"], "branch_id": branch_id, "into": base["branch_id"], "run_key": evidence.get("head_years_key", "")})
    return out


@router.post("/branches/{branch_id}/discard")
def discard_branch(branch_id: str) -> dict:
    """Soft-discard an open branch (kept for audit; a project's main cannot be discarded, a merged branch neither)."""
    with scenarios.cursor() as con:
        row = repository.require_open(con, branch_id)
        if repository.is_main(row):
            raise HTTPException(status_code=409, detail="cannot discard a project's main, the plan of record")
        repository.set_branch_status(con, branch_id, "discarded")
        return repository.branch_to_client(con, repository.branch_row(con, branch_id))


def _rebase_plan(con, branch_id: str) -> tuple[dict, rebase.Plan]:
    head = repository.require_open(con, branch_id, allow_main=False)
    p = repository.rebase_plan(con, head)
    if p is None:
        raise HTTPException(status_code=409, detail=f"the branch '{branch_id}' was opened from is gone: there is nothing to rebase onto")
    return head, p


@router.get("/branches/{branch_id}/rebase")
def rebase_preview(branch_id: str) -> dict:
    """What rebasing this branch onto its parent as it is now would do: the parent's changes since the branch was
    opened, the branch's own, which of the parent's the branch lacks (`behind`), and the conflicts to pick, with where
    the fork point comes from (`fork`: recorded, rebuilt from the merge history, or none). Writes nothing."""
    with scenarios.cursor() as con:
        head, p = _rebase_plan(con, branch_id)
    return {"branch_id": branch_id, **rebase.preview(p, onto=head["parent_id"])}


@router.post("/branches/{branch_id}/rebase")
def rebase_branch(branch_id: str, body: RebaseRequest) -> dict:
    """Rebase the branch onto its parent as it is now: the parent's state plus the branch's own changes, every conflict
    answered by the operator's `picks` (409 when one is missing or the parent moved since the preview). Returns the
    branch and how many of the parent's changes it took in (`taken`). The branch's result is out of date until it runs
    again; the gate then judges it as usual."""
    valid = projects.element_ids(_project_of(branch_id))["buses"]  # a model read: never under the store lock
    with scenarios.cursor() as con:
        head, p = _rebase_plan(con, branch_id)
        try:
            taken = repository.apply_rebase(con, head, p, body.picks, valid)
        except rebase.PicksError as e:
            raise HTTPException(status_code=409, detail={"code": "picks", "message": "The picks do not answer this rebase's conflicts "
                                                         "(the parent may have moved since the preview): review it again.", **e.args[0]}) from e
        out = repository.branch_to_client(con, repository.branch_row(con, branch_id))
    plans.edited()
    return {"branch": out, "taken": taken}


# --- planned maintenance and simulated reinforcements --------------------------
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
    ids = projects.element_ids(_project_of(branch_id))  # a model read: never under the store lock
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id, allow_main=False)
        row = repository.insert_outage(con, branch_id, body, ids)  # 422 when its element is not in the model (UnknownElement)
    plans.edited()
    return row


@router.delete("/branches/{branch_id}/outages/{outage_id}")
def remove_outage(branch_id: str, outage_id: str) -> dict:
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id, allow_main=False)
        if not repository.delete_branch_row(con, "branch_outages", "outage_id", branch_id, outage_id):
            raise HTTPException(status_code=404, detail=f"outage '{outage_id}' not on branch '{branch_id}'")
    plans.edited()
    return {"branch_id": branch_id, "outage_id": outage_id, "removed": True}


@router.get("/branches/{branch_id}/reinforcements")
def list_reinforcements(branch_id: str) -> dict:
    """The simulated reinforcements proposed on a branch (each run applies them)."""
    with scenarios.cursor() as con:
        repository.require_branch(con, branch_id)
        return {"branch_id": branch_id, "reinforcements": repository.reinforcement_rows(con, branch_id)}


@router.post("/branches/{branch_id}/reinforcements")
def add_reinforcement(branch_id: str, body: ReinforcementCreate) -> dict:
    """Propose a reinforcement on a branch (a lever from the suggestions, or the operator's own). The next run measures it against the queue."""
    ids = projects.element_ids(_project_of(branch_id))  # a model read: never under the store lock
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id, allow_main=False)
        row = repository.insert_reinforcement(con, branch_id, body, ids)  # 422 when its element is not in the model (UnknownElement)
    plans.edited()
    return row


@router.delete("/branches/{branch_id}/reinforcements/{reinforcement_id}")
def remove_reinforcement(branch_id: str, reinforcement_id: str) -> dict:
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id, allow_main=False)
        if not repository.delete_branch_row(con, "branch_reinforcements", "reinforcement_id", branch_id, reinforcement_id):
            raise HTTPException(status_code=404, detail=f"reinforcement '{reinforcement_id}' not on branch '{branch_id}'")
    plans.edited()
    return {"branch_id": branch_id, "reinforcement_id": reinforcement_id, "removed": True}
