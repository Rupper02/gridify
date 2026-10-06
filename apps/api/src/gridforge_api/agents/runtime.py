"""The agent runtime: owns the DBOS lifecycle, the queues, the built agents and the pause switch.

Constructed once in `deps.py` with every collaborator handed in, the model factory included (the API
requires the OpenRouter key at startup; there is no key-less mode). `launch()` starts DBOS on its
system database (SQLite by default, Postgres when configured) and workflows resume after a restart
from their last completed step; until it has, the agent routes answer 503 "starting".
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from dbos import DBOS, DBOSConfig, SetEnqueueOptions, SetWorkflowID, SetWorkflowTimeout

from ..config import AGENT_ANSWER_RESERVE_S, AGENT_MODELS, AGENT_RUN_BUDGET, log
from . import runs, workflows
from .workflows import CHAT_QUEUE, STEWARD_QUEUE
from .spend import SpendMeter
from .evidence import EvidenceLedger
from .roster import AGENTS, SPECIALIST_STUDIES, build
from .tools import AgentDeps, Harness, SolverGate


# a DBOS workflow that ended -> the status its run gets when the workflow never recorded its own finish
_LIVE = ("PENDING", "ENQUEUED", "DELAYED")  # what an executor of the same version would still pick up
_ENDED = {
    "SUCCESS": ("done", "the workflow finished but did not record its result"),
    "ERROR": ("failed", "the workflow failed before it recorded its result"),
    "MAX_RECOVERY_ATTEMPTS_EXCEEDED": ("failed", "the workflow was abandoned after repeated recovery attempts"),
    "CANCELLED": ("cancelled", "the workflow was cancelled (its time limit passed, possibly while the API was down, or it was stopped) "
                               "before it recorded its result"),
}


def in_workflow() -> bool:
    """Inside DBOS workflow code (not inside a step): where steps may be started."""
    try:
        return DBOS.workflow_id is not None and DBOS.step_id is None
    except Exception:
        return False


def durable(name: str, fn: Callable[[], Any]) -> Any:
    """Run `fn` as a checkpointed DBOS step in a workflow, plainly outside one (tests, the sync path)."""
    return DBOS.run_step({"name": name}, fn) if in_workflow() else fn()


class AgentRuntime:
    def __init__(self, *, store, cache, plans, jobs, warehouse, projects, evidence: EvidenceLedger, spend: SpendMeter,
                 model_factory: Callable[[str], Any], system_db_url: str, app_version: str, project_id: str):
        self.model_factory = model_factory
        self.system_db_url = system_db_url
        self.app_version = app_version
        self.project_id = project_id
        self.spend = spend
        self.evidence = evidence
        self.harness = Harness(plans=plans, store=store, warehouse=warehouse, projects=projects, evidence=evidence,
                               solver_gate=SolverGate(jobs, jobs.solver_lock), in_workflow=in_workflow, durable=durable)
        self.agents: dict[str, Any] = {}
        self.launched = False
        self._lock = threading.Lock()

    # --- lifecycle --------------------------------------------------------------------------------------
    def launch(self) -> None:
        if self.launched:
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
        try:  # runs the last process left open: recovery resumes the live ones, the ended ones are closed here
            self.reconcile()
        except Exception:
            log.exception("could not reconcile agent runs at launch")

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
        """The event sink of a run: the workflow's DBOS stream (outside a workflow, in tests, nobody streams: dropped)."""
        if in_workflow():
            return lambda ev: DBOS.write_stream("events", ev)
        return lambda ev: None

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
                         allowed_studies=allowed if allowed is not None else tuple(), emit=emit, emit_async=emit_async, budget=dict(AGENT_RUN_BUDGET),
                         # the run waits for the solver while its own time allows, keeping a minute to write the answer
                         deadline=time.monotonic() + max(0.0, float(AGENT_RUN_BUDGET["timeout_s"]) - AGENT_ANSWER_RESERVE_S))


    # --- starting work -------------------------------------------------------------------------------------
    def start(self, workflow_name: str, dedup: str, event: dict) -> str:
        """Enqueue one workflow for an event under a deterministic id (the same event never runs twice)."""
        spec = workflows.WORKFLOWS[workflow_name]
        pid = event.get("project_id") or self.project_id
        wid = f"{workflow_name}:{dedup}"
        opts = SetEnqueueOptions(queue_partition_key=pid) if spec.queue == STEWARD_QUEUE else nullcontext()  # one steward activity per project
        with SetWorkflowID(wid), SetWorkflowTimeout(float(AGENT_RUN_BUDGET["timeout_s"]) * spec.timeout_runs), opts:
            DBOS.enqueue_workflow(spec.queue, spec.fn, *spec.args_of(pid, event))
        return wid

    def resume_answer(self, project_id: str, thread_id: str, message_id: str) -> str:
        """Continue the reply `message_id` once every proposal it made is decided (one resume per reply)."""
        return self.start("answer_resume", message_id, {"project_id": project_id, "thread_id": thread_id, "message_id": message_id})

    # --- status and startup events ----------------------------------------------------------------------------
    def status(self, project_id: str | None = None) -> dict:
        """starting (the runtime has not launched yet), idle, running or paused, with what the agents spent and the last events."""
        pid = project_id or self.project_id
        state = self.spend.check(pid)
        if self.launched:
            self.reconcile(pid)
        with self.harness.store.cursor() as con:
            running = runs.running_count(con, pid) if self.launched else 0
            last = runs.recent_events(con, pid) if self.launched else []
        status = "starting" if not self.launched else "paused" if state.paused else "running" if running else "idle"
        return {"status": status, "launched": self.launched, "paused_reason": state.paused_reason if state.paused else "",
                "running": running, "spend": state.as_dict(), "last_events": last, "models": AGENT_MODELS, "project_id": pid}

    def reconcile(self, project_id: str | None = None) -> int:
        """Close the runs DBOS has already ended, and the ones it never will: a workflow cancelled at its timeout (or
        whose deadline passed while the API was down, so recovery cancels it without running it) never reaches its own
        `_finish`; a workflow left pending under another application version (the API restarted on new code) is
        recovered by no executor, so it is cancelled here and its run closed. Either would count as running for ever.
        Returns how many runs it closed."""
        with self.harness.store.cursor() as con:
            open_ = runs.open_runs(con, project_id)
        ended = []
        for run_id, wid in open_:
            st = DBOS.get_workflow_status(wid) if wid else None
            if st is not None and st.status in _ENDED:
                ended.append((run_id, *_ENDED[st.status]))
            elif st is not None and st.status in _LIVE and st.app_version and st.app_version != self.app_version:
                DBOS.cancel_workflow(wid)
                ended.append((run_id, "cancelled", f"interrupted by a restart on new code (version {st.app_version} -> {self.app_version}); not resumed"))
        if ended:
            with self.harness.store.cursor() as con:
                for run_id, status, error in ended:
                    runs.close_run(con, run_id, status=status, error=error)
            log.info("closed %d agent run(s) their workflows had ended: %s", len(ended), ", ".join(r[0] for r in ended))
        return len(ended)

    def cancel(self, workflow_id: str) -> None:
        """Stop a workflow (an answer the operator gave up on): DBOS cancels it at its next step."""
        DBOS.cancel_workflow(workflow_id)

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
