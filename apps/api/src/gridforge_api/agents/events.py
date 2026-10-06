"""What wakes the agents: a registry of triggers, each naming the workflows it starts and how its
events are deduplicated, and `emit`, the one entry point the routers call. A no-op while the runtime is
starting, recorded but not started while paused; idempotent by deduplication id (a cached re-run never wakes
anyone twice)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple

from . import runs

if TYPE_CHECKING:
    from .runtime import AgentRuntime


class Trigger(NamedTuple):
    workflows: tuple[str, ...]  # names in workflows.WORKFLOWS
    allowed_specialists: tuple[str, ...]  # what the steward may ask for on this event
    dedup: Callable[[dict], str]
    applies: Callable[[dict], bool] = lambda p: True  # which payloads wake anyone at all


TRIGGERS: dict[str, Trigger] = {
    # a run finished on a branch: the reviewer comments like a PR bot, and the steward may send the connections
    # specialist after the projects the run deferred on a grid limit, or the works specialist when the run flags a
    # works window (`works_flagged` in the payload: not simply feasible, or second faults found during it)
    "run.finished": Trigger(("review_branch", "steward_run"), ("connections", "works"), lambda p: f"run:{p['branch_id']}:{p['run_key']}", applies=lambda p: not p.get("is_main")),
    # the plan of record changed: the steward sweeps what a merge can move
    "branch.merged": Trigger(("steward_run",), ("thermal", "voltage", "boundary", "demand_security", "works"), lambda p: f"merge:{p['branch_id']}:{p.get('run_key', '')}"),
    # a new model: everything, data quality first
    "project.imported": Trigger(("steward_run",), ("data_quality", "thermal", "voltage", "demand_security", "boundary"), lambda p: f"snapshot:{p.get('project_id', '')}:{p['snapshot_id']}"),
    # NGED published a new LTDS edition
    "edition.changed": Trigger(("steward_run",), ("data_quality", "thermal"), lambda p: f"edition:{p['ltds_edition']}"),
    # the operator asked a question
    "operator.asked": Trigger(("answer",), (), lambda p: f"ask:{p['message_id']}"),
}


def works_flagged(out: dict) -> tuple[int, int]:
    """A run payload's works windows, and how many of them a planner should look at: not simply feasible,
    or with second faults found during the window."""
    studies = [s for y in (out.get("years") or {}).values() for s in (y.get("outage_studies") or [])]
    flagged = sum(1 for s in studies if s.get("verdict") != "feasible" or ((s.get("n1_during") or {}).get("findings") or 0) > 0)
    return len(studies), flagged


def run_finished(branch_id: str, out: dict, *, is_main: bool) -> dict:
    """The `run.finished` payload of a run, wherever it ran (the router, an agent's approved run): its identity, how many
    works windows it studied and flagged, and whether it was a main's (a main is not reviewed: it merges nowhere)."""
    n_works, flagged = works_flagged(out)
    return {"project_id": out.get("project_id"), "branch_id": branch_id, "run_key": out.get("run_key", ""),
            "n_works": n_works, "works_flagged": flagged, "is_main": is_main}


def emit(rt: AgentRuntime, type_: str, payload: dict) -> dict | None:
    """Record an event and start its workflows. Returns what happened (`deduplicated`, `paused`, the
    workflow ids), or None when the runtime has not launched yet or the trigger does not apply to this
    payload. Unknown types are a KeyError (the router 422s)."""
    trigger = TRIGGERS[type_]
    if not rt.launched or not trigger.applies(payload):
        return None
    dedup = trigger.dedup(payload)
    project_id = payload.get("project_id") or rt.project_id  # the built-in project unless the event names one
    with rt.harness.store.cursor() as con:
        existing = runs.event_by_dedup(con, project_id, dedup)
        if existing:
            return {**existing, "deduplicated": True, "paused": False}
        paused = rt.spend.check(project_id).paused
        event_id = "ev-" + uuid.uuid4().hex[:8]
        runs.insert_event(con, event_id=event_id, project_id=project_id, type_=type_, dedup_id=dedup, payload={**payload, "type": type_})
    if paused:
        return {"event_id": event_id, "workflow_ids": [], "deduplicated": False, "paused": True}
    event = {**payload, "project_id": project_id, "type": type_, "event_id": event_id, "dedup_id": dedup, "allowed_specialists": list(trigger.allowed_specialists)}
    workflow_ids = [rt.start(name, dedup, event) for name in trigger.workflows]
    with rt.harness.store.cursor() as con:
        runs.set_event_workflows(con, event_id, workflow_ids)
    return {"event_id": event_id, "workflow_ids": workflow_ids, "deduplicated": False, "paused": False}
