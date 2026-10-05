"""Branches ("git for grids"): create, list, pull from the registry, schedule, planned outages,
simulated reinforcements, diff, the merge gate, merge, discard, and the copilot's suggestions."""

import uuid

from fastapi import APIRouter, HTTPException

from gridforge_optimizer import MergeVerdict
from gridforge_optimizer.config import MAX_SUGGESTIONS

from .. import ledger, narration, proposals, repository
from ..agents import events
from ..config import now
from ..deps import agents, jobs, narrator, plans, projects, scenarios
from ..schemas import (
    BestWindowRequest,
    BranchCreate,
    MergeRequest,
    OutageCreate,
    RegistryAdd,
    ReinforcementCreate,
    ScenarioUpdate,
    ScheduleSet,
)

router = APIRouter()


@router.post("/branches")
def create_branch(body: BranchCreate) -> dict:
    """Create a branch (copy-on-create): snapshot the parent's projects, then apply the change."""
    with scenarios.cursor() as con:
        parent = repository.require_branch(con, body.from_branch)
        bid = repository.open_branch(con, parent, body.name, created_by="operator",
                                     overrides=body.model_dump(include={"scenario", "growth_2030", "growth_2035", "w_readiness", "w_need", "w_strategic"}))
        valid = projects.element_ids(parent["project_id"])["buses"]
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
    plans.invalidate("plan")
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
    plans.invalidate("payload")  # the payload carries scheduled_year; the engine result is unaffected
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
    """The head branch and the base it is compared with / merges into (`into`, else its parent, else main)."""
    head = repository.require_branch(con, branch_id)
    base = repository.require_branch(con, into) if into else repository.base_of(con, head)
    if base["branch_id"] == branch_id:
        raise HTTPException(status_code=400, detail="cannot merge a branch into itself")
    return head, base


def _changes_on_merge(con, base_id: str, head_id: str) -> dict:
    """The planned works and reinforcements a merge adds to or removes from the base."""
    return proposals.on_merge(repository.outage_rows(con, base_id), repository.outage_rows(con, head_id),
                              repository.reinforcement_rows(con, base_id), repository.reinforcement_rows(con, head_id))


def _gate(branch_id: str, base_id: str, changes: dict) -> tuple[MergeVerdict, dict]:
    return plans.merge_check(branch_id, base_id,
                             removed_works=[w["outage_id"] for w in changes["works_removed"]],
                             removed_reinforcements=[r["reinforcement_id"] for r in changes["reinforcements_removed"]])


@router.get("/branches/{branch_id}/diff")
def diff_branch(branch_id: str, with_narration: bool = False) -> dict:
    """Consequence diff of a branch (head) vs its parent (base, default main): the queue, the
    2030/2035 phases, every plan year, the branch's planned works on the parent's plan vs its own,
    and the planned works and reinforcements a merge would add to or remove from the parent."""
    with scenarios.cursor() as con:
        head, base = _pair(con, branch_id, None)
        merge = _changes_on_merge(con, base["branch_id"], branch_id)
    d = plans.diff(branch_id, base["branch_id"])
    out = d.model_dump()
    out["on_merge"] = merge
    out["base_branch"] = base["branch_id"]
    out["head_branch"] = branch_id
    out["narration"] = ""
    if with_narration:
        out["narration"] = narration.safely(narrator.narrate_diff, narration.summarize_diff(d, projects.names(_project_of(branch_id))))
    return out


@router.get("/branches/{branch_id}/merge-check")
def merge_check(branch_id: str, into: str | None = None) -> dict:
    """May this branch merge? The gate's verdict (gate.merge_verdict) against `into` (default its
    parent): fresh or stale, the blockers, the warnings that need acknowledging, and what the
    parent already carries. Read-only; it solves the parent's plan if it is not cached yet."""
    with scenarios.cursor() as con:
        head, base = _pair(con, branch_id, into)
        changes = _changes_on_merge(con, base["branch_id"], branch_id)
    verdict, evidence = _gate(branch_id, base["branch_id"], changes)
    return {
        "branch_id": branch_id, "into": base["branch_id"], "branch_status": head["status"],
        "fresh": evidence["fresh"], "stale_reasons": evidence["stale_reasons"],
        "requires_acknowledgement": verdict.ok and bool(verdict.warnings),
        "verdict": verdict.model_dump(), "evidence": evidence, "checked_at": now(),
    }


@router.post("/branches/{branch_id}/merge")
def merge_branch(branch_id: str, body: MergeRequest | None = None) -> dict:
    """Squash-merge a branch into `into` (default main): it adopts the branch's scenario, projects,
    planned works and reinforcements. Gated: a stale branch, or one that introduces or worsens a
    problem in any plan year, is refused (409, `code: "blocked"`, the verdict in the body); warnings
    are refused until `acknowledge` is true (`code: "warnings_unacknowledged"`). Every attempt,
    refused or done, is recorded with the verdict it was judged on."""
    body = body or MergeRequest()
    with scenarios.cursor() as con:
        head, base = _pair(con, branch_id, body.into)
        repository.require_open(con, branch_id, allow_main=False)
        repository.require_open(con, base["branch_id"])
        changes = _changes_on_merge(con, base["branch_id"], branch_id)
    verdict, evidence = _gate(branch_id, base["branch_id"], changes)
    if verdict.blockers:
        code, message = "blocked", verdict.blockers[0].message
    elif verdict.warnings and not body.acknowledge:
        n = len(verdict.warnings)
        code, message = "warnings_unacknowledged", f"{n} warning{'s' if n != 1 else ''} to acknowledge before merging: {verdict.warnings[0].message}"
    else:
        code = message = None
    with scenarios.cursor() as con:
        ledger.record_merge(con, merge_id="mg-" + uuid.uuid4().hex[:8], branch_id=branch_id, into=base["branch_id"],
                            outcome="refused" if code else "merged", verdict=verdict.model_dump(),
                            acknowledged=body.acknowledge, evidence=evidence, at=now())
        if code:
            raise HTTPException(status_code=409, detail={"code": code, "message": message, "fresh": evidence["fresh"],
                                                         "verdict": verdict.model_dump()})
        repository.merge_into(con, head, base["branch_id"])
        out = repository.branch_to_client(con, repository.branch_row(con, base["branch_id"]))
    plans.invalidate("plan")
    events.emit(agents, "branch.merged", {"project_id": base["project_id"], "branch_id": branch_id, "into": base["branch_id"], "run_key": evidence.get("head_years_key", "")})
    return out


@router.post("/branches/{branch_id}/discard")
def discard_branch(branch_id: str) -> dict:
    """Soft-discard an open branch (kept for audit; main cannot be discarded, a merged one neither)."""
    if branch_id == "main":
        raise HTTPException(status_code=400, detail="cannot discard main")
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id)
        repository.set_branch_status(con, branch_id, "discarded")
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
            d["narration"] = narration.safely(narrator.narrate_suggestion, narration.summarize_suggestion(s, base, projects.names(_project_of(branch_id))))
        out.append(d)
    return {"branch_id": branch_id, "request_id": request_id, "suggestions": out}


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
    _require_element(branch_id, body.element_kind, body.element_id)
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id, allow_main=False)
        return repository.insert_outage(con, branch_id, body)


def _require_element(branch_id: str, kind: str, element_id: str) -> None:
    ids = projects.element_ids(_project_of(branch_id))
    known = {"line": ids["lines"], "trafo": ids["trafos"], "gen": ids["generators"]}[kind]
    if element_id not in known:
        raise HTTPException(status_code=422, detail=f"{kind} '{element_id}' is not in the network model")


@router.post("/branches/{branch_id}/works/best-window")
def start_best_window(branch_id: str, body: BestWindowRequest) -> dict:
    """Find the best window for a planned work: the element studied out in every season of every
    year in `years`, against the branch's plan as it stands that year (its queue, schedule,
    reinforcements and other windows), ranked by verdict, then curtailment, demand at risk, N-1
    findings during the window and loading. Read-only, so it runs on main too. Runs as a background
    job (progress per year); the job's result is {branch_id, element_kind, element_id, work, options}."""
    _require_element(branch_id, body.element_kind, body.element_id)
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
        repository.require_open(con, branch_id, allow_main=False)
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
    ids = projects.element_ids(_project_of(branch_id))
    known = {"line": ids["lines"], "trafo": ids["trafos"]}.get(body.kind)
    if known is not None and str(body.element_id) not in known:
        raise HTTPException(status_code=422, detail=f"{body.kind} '{body.element_id}' is not in the network model")
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id, allow_main=False)
        return repository.insert_reinforcement(con, branch_id, body)


@router.delete("/branches/{branch_id}/reinforcements/{reinforcement_id}")
def remove_reinforcement(branch_id: str, reinforcement_id: str) -> dict:
    with scenarios.cursor() as con:
        repository.require_open(con, branch_id, allow_main=False)
        if not repository.delete_branch_row(con, "branch_reinforcements", "reinforcement_id", branch_id, reinforcement_id):
            raise HTTPException(status_code=404, detail=f"reinforcement '{reinforcement_id}' not on branch '{branch_id}'")
    return {"branch_id": branch_id, "reinforcement_id": reinforcement_id, "removed": True}
