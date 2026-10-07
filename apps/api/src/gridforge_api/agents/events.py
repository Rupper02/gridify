"""Project events and what they wake.

`TRIGGERS` is the registry: an event type maps to the workflows it starts, with a dedup identity so a
repeated event never wakes anyone twice (the planner's poll, a replay, two routes seeing one run). Every
event is recorded in `project_events` whether or not it starts a workflow; a paused project records and
starts nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple

from .. import repository
from . import runs

if TYPE_CHECKING:
    from .runtime import AgentRuntime


class Trigger(NamedTuple):
    workflows: tuple[str, ...]  # names in workflows.WORKFLOWS
    dedup: Callable[[dict], str]
    applies: Callable[[dict], bool] = lambda p: True  # which payloads wake anyone at all


TRIGGERS: dict[str, Trigger] = {
    # a run finished (main's or a branch's): the engine's digest of it gets its engineer's note. A run whose physics
    # is its parent's (a branch just opened, nothing changed: `run_key == parent_run_key`) wakes nobody
    "run.finished": Trigger(("digest_run",), lambda p: f"run:{p['branch_id']}:{p['run_key']}",
                            applies=lambda p: p.get("run_key") != p.get("parent_run_key")),
    # recorded for the audit trail; the next run of main carries the note (a merge, an import or a new edition change
    # nothing that is cached, so there is nothing to digest until that run)
    "branch.merged": Trigger((), lambda p: f"merge:{p['branch_id']}:{p.get('run_key', '')}"),
    "project.imported": Trigger((), lambda p: f"snapshot:{p.get('project_id', '')}:{p['snapshot_id']}"),
    "edition.changed": Trigger((), lambda p: f"edition:{p['ltds_edition']}"),
    # the operator asked a question
    "operator.asked": Trigger(("answer",), lambda p: f"ask:{p['message_id']}"),
}


def run_finished(branch_id: str, out: dict, *, is_main: bool, parent_run_key: str | None = None) -> dict:
    """The `run.finished` payload of a run, wherever it ran (the router, an agent's approved run): its identity, its
    parent's (`parent_run_key`: equal when the run changed no physics) and whether it was a main's."""
    return {"project_id": out.get("project_id"), "branch_id": branch_id, "run_key": out.get("run_key", ""), "parent_run_key": parent_run_key,
            "is_main": is_main}


def parent_run_key(plans, store, branch_id: str) -> str | None:
    """The plan-years key of the branch's parent as it stands (no solve: `PlanService.freshness`); None for a main."""
    with store.cursor() as con:
        base = repository.base_of(con, repository.require_branch(con, branch_id))
    return plans.freshness(base["branch_id"]).years_key if base else None


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
    event = {**payload, "project_id": project_id, "type": type_, "event_id": event_id, "dedup_id": dedup}
    workflow_ids = [rt.start(name, dedup, event) for name in trigger.workflows]
    with rt.harness.store.cursor() as con:
        runs.set_event_workflows(con, event_id, workflow_ids)
    return {"event_id": event_id, "workflow_ids": workflow_ids, "deduplicated": False, "paused": False}
