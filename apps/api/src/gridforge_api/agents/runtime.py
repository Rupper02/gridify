"""The agent runtime: owns the DBOS lifecycle, the queues, the built agents and the pause switch.

Constructed once in `deps.py` with every collaborator handed in. `enabled` is false without a model
factory (no `OPENROUTER_API_KEY`): nothing launches, every agent route answers "off", and the rest of
the API is untouched. With one, `launch()` starts DBOS on its system database (SQLite by default,
Postgres when configured) and workflows resume after a restart from their last completed step.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from dbos import DBOS, DBOSConfig, SetEnqueueOptions, SetWorkflowID, SetWorkflowTimeout

from ..config import AGENT_MODELS, AGENT_RUN_BUDGET, log
from . import runs, workflows
from .budget import BudgetMeter
from .evidence import EvidenceLedger
from .roster import AGENTS, SPECIALIST_STUDIES, build
from .tools import AgentDeps, Harness, SolverGate

STEWARD_QUEUE = "steward"  # partitioned by project: one steward activity per project at a time
CHAT_QUEUE = "chat"  # reviews and answers: a few at once


def in_workflow() -> bool:
    """Inside DBOS workflow code (not inside a step): where steps may be started."""
    try:
        return DBOS.workflow_id is not None and DBOS.step_id is None
    except Exception:
        return False


def durable(name: str, fn: Callable[[], Any]) -> Any:
    """Run `fn` as a checkpointed DBOS step in a workflow, plainly outside one (tests, the sync path)."""
    return DBOS.run_step(None, fn) if in_workflow() else fn()


class AgentRuntime:
    def __init__(self, *, store, cache, plans, jobs, warehouse, projects, evidence: EvidenceLedger, budget: BudgetMeter,
                 model_factory: Callable[[str], Any] | None, system_db_url: str, app_version: str, project_id: str):
        self.model_factory = model_factory
        self.system_db_url = system_db_url
        self.app_version = app_version
        self.project_id = project_id
        self.budget = budget
        self.evidence = evidence
        self.harness = Harness(plans=plans, store=store, warehouse=warehouse, projects=projects, evidence=evidence,
                               solver_gate=SolverGate(jobs, jobs.solver_lock), project_id=project_id, in_workflow=in_workflow, durable=durable)
        self.agents: dict[str, Any] = {}
        self.launched = False
        self._lock = threading.Lock()
        self._sinks: dict[str, list] = {}  # run_id -> captured events, outside a workflow (tests)

    @property
    def enabled(self) -> bool:
        return self.model_factory is not None

    # --- lifecycle --------------------------------------------------------------------------------------
    def launch(self) -> None:
        if not self.enabled or self.launched:
            return
        with self._lock:
            if self.launched:
                return
            if self.system_db_url.startswith("sqlite:///"):
                Path(self.system_db_url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
            DBOS(config=DBOSConfig(name="gridforge", system_database_url=self.system_db_url, application_version=self.app_version,
                                   log_level=os.getenv("DBOS_LOG_LEVEL", "WARNING")))
            if not self.agents:  # once per process: the durability capability registers each agent's steps by name
                self.agents = build(self.model_factory)
            workflows.RUNTIME = self
            DBOS.launch()
            DBOS.register_queue(STEWARD_QUEUE, partition_concurrency=1)
            DBOS.register_queue(CHAT_QUEUE, worker_concurrency=2)
            self.launched = True
            log.info("agents launched on %s (version %s)", self.system_db_url, self.app_version)

    def destroy(self) -> None:
        if not self.launched:
            return
        with self._lock:
            try:
                DBOS.destroy(destroy_registry=False)
            finally:
                self.launched = False
                workflows.RUNTIME = None

    # --- what a run needs -----------------------------------------------------------------------------------
    def model_name(self, agent: str) -> str | None:
        spec = AGENTS.get(agent)
        return AGENT_MODELS.get(spec.role) if spec else None

    def studies_for(self, agent: str) -> tuple[str, ...]:
        return AGENTS[agent].studies if agent in AGENTS else ()

    def remits(self) -> str:
        return "; ".join(f"{k}: {', '.join(v)}" for k, v in SPECIALIST_STUDIES.items())

    def emit_for(self, run_id: str) -> Callable[[dict], None]:
        """The event sink of a run: the workflow's DBOS stream, or a list when there is no workflow."""
        if in_workflow():
            return lambda ev: DBOS.write_stream("events", ev)
        sink = self._sinks.setdefault(run_id, [])
        return sink.append

    def deps_for(self, run_id: str, *, project_id: str | None = None, branch_id: str | None = None, thread_id: str | None = None,
                 allowed: tuple[str, ...] | None = None) -> AgentDeps:
        pid = project_id or self.project_id
        emit = self.emit_for(run_id)

        async def emit_async(ev: dict) -> None:
            if in_workflow() or DBOS.step_id is not None:
                await DBOS.write_stream_async("events", ev)
            else:
                emit(ev)

        return AgentDeps(h=self.harness, run_id=run_id, project_id=pid, main_id=self.harness.projects.main_id(pid), branch_id=branch_id, thread_id=thread_id,
                         allowed_studies=allowed if allowed is not None else tuple(), emit=emit, emit_async=emit_async, budget=dict(AGENT_RUN_BUDGET))

    def captured(self, run_id: str) -> list:
        return list(self._sinks.get(run_id, []))

    # --- starting work -------------------------------------------------------------------------------------
    def start(self, workflow_name: str, dedup: str, event: dict) -> str:
        """Enqueue one workflow for an event under a deterministic id (the same event never runs twice)."""
        fn, args_of = workflows.WORKFLOWS[workflow_name]
        pid = event.get("project_id") or self.project_id
        wid = f"{workflow_name}:{dedup}"
        queue = STEWARD_QUEUE if workflow_name == "steward_run" else CHAT_QUEUE
        opts = SetEnqueueOptions(queue_partition_key=pid) if queue == STEWARD_QUEUE else nullcontext()  # one steward activity per project
        with SetWorkflowID(wid), SetWorkflowTimeout(float(AGENT_RUN_BUDGET["timeout_s"]) * 3), opts:
            DBOS.enqueue_workflow(queue, fn, *args_of(pid, event))
        return wid

    def resume_answer(self, project_id: str, thread_id: str, message_id: str, approval_id: str, approved: bool, note: str) -> str:
        wid = f"answer_resume:{approval_id}"
        with SetWorkflowID(wid), SetWorkflowTimeout(float(AGENT_RUN_BUDGET["timeout_s"])):
            DBOS.enqueue_workflow(CHAT_QUEUE, workflows.answer_resume, project_id, thread_id, message_id, approval_id, approved, note)
        return wid

    # --- status and startup events ----------------------------------------------------------------------------
    def status(self, project_id: str | None = None) -> dict:
        pid = project_id or self.project_id
        if not self.enabled:
            return {"status": "off", "enabled": False, "launched": False, "reason": "OPENROUTER_API_KEY is not set", "models": AGENT_MODELS,
                    "running": 0, "budget": None, "last_events": [], "project_id": pid}
        state = self.budget.check(pid)
        with self.harness.store.cursor() as con:
            running = runs.running_count(con, pid) if self.launched else 0
            last = runs.recent_events(con, pid) if self.launched else []
        status = "paused" if state.paused else "running" if running else "idle" if self.launched else "off"
        return {"status": status, "enabled": True, "launched": self.launched, "paused_reason": state.paused_reason if state.paused else "",
                "running": running, "budget": state.as_dict(), "last_events": last, "models": AGENT_MODELS, "project_id": pid}

    def emit_startup_events(self) -> list[dict]:
        """What changed while the API was down: a new model snapshot or LTDS edition wakes the steward."""
        if not self.launched:
            return []
        from .events import emit
        out = []
        snapshot = self.harness.warehouse.baseline_id()
        with self.harness.store.cursor() as con:
            last = runs.state_get(con, self.project_id, "snapshot_id")
        if last != snapshot:
            kind = "project.imported" if last is None else "edition.changed"
            payload = {"snapshot_id": snapshot, "ltds_edition": snapshot, "previous": last}
            r = emit(self, kind, payload)
            if r:
                out.append({"type": kind, **r})
            with self.harness.store.cursor() as con:
                runs.state_set(con, self.project_id, "snapshot_id", snapshot)
        return out
