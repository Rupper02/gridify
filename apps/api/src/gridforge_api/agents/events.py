"""What wakes the agents: a registry of triggers, each naming the workflows it starts and how its
events are deduplicated, and `emit`, the one entry point the routers call. A no-op when the agents are
off or paused; idempotent by deduplication id (a cached re-run never wakes anyone twice)."""

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
    # a run finished on a branch: the reviewer comments like a PR bot (cheap, one call); no sweep
    "run.finished": Trigger(("review_branch",), (), lambda p: f"run:{p['branch_id']}:{p['run_key']}", applies=lambda p: p["branch_id"] != "main"),
    # the plan of record changed: the steward sweeps what a merge can move
    "branch.merged": Trigger(("steward_run",), ("thermal", "voltage", "boundary", "demand_security", "works"), lambda p: f"merge:{p['branch_id']}:{p.get('run_key', '')}"),
    # a new model: everything, data quality first
    "project.imported": Trigger(("steward_run",), ("data_quality", "thermal", "voltage", "demand_security", "boundary"), lambda p: f"snapshot:{p['snapshot_id']}"),
    # NGED published a new LTDS edition
    "edition.changed": Trigger(("steward_run",), ("data_quality", "thermal"), lambda p: f"edition:{p['ltds_edition']}"),
    # the operator asked a question
    "operator.asked": Trigger(("answer",), (), lambda p: f"ask:{p['message_id']}"),
}


def emit(rt: AgentRuntime, type_: str, payload: dict) -> dict | None:
    """Record an event and start its workflows. Returns what happened (`deduplicated`, `paused`, the
    workflow ids), or None when the agents are off or the trigger does not apply to this payload. Unknown types are a KeyError (the router 422s)."""
    trigger = TRIGGERS[type_]
    if not rt.enabled or not rt.launched or not trigger.applies(payload):
        return None
    dedup = trigger.dedup(payload)
    project_id = rt.project_id
    with rt.harness.store.cursor() as con:
        existing = runs.event_by_dedup(con, project_id, dedup)
        if existing:
            return {**existing, "deduplicated": True, "paused": False}
        paused = rt.budget.check(project_id).paused
        event_id = "ev-" + uuid.uuid4().hex[:8]
        runs.insert_event(con, event_id=event_id, project_id=project_id, type_=type_, dedup_id=dedup, payload={**payload, "type": type_})
    if paused:
        return {"event_id": event_id, "workflow_ids": [], "deduplicated": False, "paused": True}
    event = {**payload, "type": type_, "event_id": event_id, "dedup_id": dedup, "allowed_specialists": list(trigger.allowed_specialists)}
    workflow_ids = [rt.start(name, dedup, event) for name in trigger.workflows]
    with rt.harness.store.cursor() as con:
        runs.set_event_workflows(con, event_id, workflow_ids)
    return {"event_id": event_id, "workflow_ids": workflow_ids, "deduplicated": False, "paused": False}
