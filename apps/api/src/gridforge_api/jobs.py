"""Long computations run on a single background worker; the planner polls their progress."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

from .errors import NotFound

from .config import log, now

class JobCancelled(Exception):
    """Raised inside a job's progress callback once the job has been cancelled."""


MAX_JOB_RECORDS = 200  # keep the registry bounded; finished jobs fall off oldest-first
PRUNE_BATCH = 50


class JobRunner:
    """Queue `fn(progress)` on one worker (pandapower is CPU-bound: one run at a time) and track it."""

    def __init__(self, solver_lock: threading.RLock | None = None):
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gridforge-job")
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        # pandapower is CPU-bound and its nets are not shared across threads: every power flow in the
        # process, an operator's job or an agent's study, runs under this one lock (agents.runtime.SolverGate)
        self.solver_lock = solver_lock or threading.RLock()

    def submit(self, fn: Callable[[], None]) -> None:
        """Run a fire-and-forget task on the worker (the warm-up). It does not hold the solver lock for its whole
        length (that would stall every agent study behind it): each result it misses takes the lock on its own
        (`ResultCache.through`), and it yields to jobs by itself (`plans.warm_profiles(idle=)`)."""
        self._pool.submit(fn)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def start(self, kind: str, fn: Callable[[Callable[[str, float], None], Callable[[dict], None]], dict], key: str | None = None) -> dict:
        """Queue `fn(progress, publish)` and return the job record. `publish(partial)` stores a partial
        result the planner can show while the job is still running (GET /jobs/{id}?partial=true).
        `key` names what the job computes: a second start with the key of a queued or running job joins
        it (the same record, its progress from the start) instead of queueing the same work behind it."""
        job_id = "job-" + uuid.uuid4().hex[:10]
        rec = {"job_id": job_id, "kind": kind, "key": key, "status": "queued", "stage": "queued", "fraction": 0.0,
               "created_at": now(), "started_at": None, "finished_at": None, "elapsed_ms": 0, "result": None, "partial": None,
               "partial_version": 0, "error": None, "cancel": False}
        with self._lock:
            if key is not None:
                same = next((r for r in self._jobs.values() if r["key"] == key and r["status"] in ("queued", "running") and not r["cancel"]), None)
                if same is not None:
                    return self._view(same)
            self._jobs[job_id] = rec
            if len(self._jobs) > MAX_JOB_RECORDS:
                for old in sorted(self._jobs, key=lambda k: self._jobs[k]["created_at"])[:PRUNE_BATCH]:
                    if self._jobs[old]["status"] in ("done", "failed", "cancelled"):
                        self._jobs.pop(old, None)

        def progress(stage: str, fraction: float) -> None:
            with self._lock:
                if rec["cancel"]:  # cooperative: the engine reports progress between trials and years
                    raise JobCancelled()
                rec["stage"], rec["fraction"] = stage, round(float(fraction), 3)

        def publish(partial: dict) -> None:
            with self._lock:
                rec["partial"] = partial
                rec["partial_version"] += 1  # a poll that saw this version is not sent the same partial again

        def run() -> None:
            t0 = time.perf_counter()
            with self._lock:
                if rec["cancel"]:  # cancelled while queued: never starts
                    rec.update(status="cancelled", stage="cancelled", finished_at=now())
                    return
                rec["status"], rec["started_at"], rec["stage"] = "running", now(), "starting"
            log.info("job %s (%s%s) started", job_id, kind, f" {key[:12]}" if key else "")
            try:
                with self._solver(rec):
                    out = fn(progress, publish)
                with self._lock:
                    rec.update(status="done", stage="done", fraction=1.0, result=out, partial=None)
            except JobCancelled:
                with self._lock:
                    rec.update(status="cancelled", stage="cancelled", partial=None)
            except Exception as exc:  # the job records its own failure; nothing escapes the worker
                log.exception("job %s failed", job_id)
                with self._lock:
                    rec.update(status="failed", stage="failed", error=f"{type(exc).__name__}: {exc}")
            finally:
                with self._lock:
                    rec["finished_at"] = now()
                    rec["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
                log.info("job %s (%s) %s in %.1f s", job_id, kind, rec["status"], rec["elapsed_ms"] / 1000)

        self._pool.submit(run)
        return self._view(rec)

    @contextmanager
    def _solver(self, rec: dict):
        """Hold the solver for the job. While another holder finishes (an agent's study chunk, a request's cache
        miss) the job says so, rather than reading "starting" as if it were already building the network."""
        if not self.solver_lock.acquire(blocking=False):
            with self._lock:
                rec["stage"] = "waiting for the solver"
            t0 = time.perf_counter()
            self.solver_lock.acquire()
            log.info("job %s waited %.1f s for the solver", rec["job_id"], time.perf_counter() - t0)
            with self._lock:
                rec["stage"] = "starting"
        try:
            yield
        finally:
            self.solver_lock.release()

    def _view(self, rec: dict, with_result: bool = False, with_partial: bool = False, since: int | None = None) -> dict:
        """The job as the planner reads it. The partial result (the queue plus every year solved so far, re-serialised
        on every poll) travels only when asked for and newer than the version the poll last saw (`since`)). A queued
        job says how many jobs hold the worker ahead of it (`stage: "queued behind N"`), so the planner can say why
        it waits rather than "queued" alone."""
        out = {k: v for k, v in rec.items() if k not in ("result", "partial", "cancel", "key")}
        if rec["status"] == "queued":
            ahead = sum(1 for r in self._jobs.values() if r is not rec and r["status"] in ("queued", "running") and not r["cancel"] and r["created_at"] <= rec["created_at"])
            out["stage"] = f"queued behind {ahead}" if ahead else "queued"
        out["has_partial"] = rec["partial"] is not None
        if with_result:
            out["result"] = rec["result"]
        if with_partial and (since is None or since != rec["partial_version"]):
            out["partial"] = rec["partial"]
        return out

    def idle(self) -> bool:
        """No job is waiting for the worker (background warm-up yields to real work)."""
        with self._lock:
            return not any(r["status"] == "queued" for r in self._jobs.values())

    def busy(self) -> bool:
        """An operator's job is queued or running: agent studies wait for it (operator first)."""
        with self._lock:
            return any(r["status"] in ("queued", "running") for r in self._jobs.values())

    def cancel(self, job_id: str) -> dict:
        """Ask a queued or running job to stop (it stops at its next progress report); 404 if unknown.
        Work it already cached (greedy trials, solved years) is kept, so a re-run resumes cheaply."""
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                raise NotFound(f"job '{job_id}' not found")
            if rec["status"] in ("queued", "running"):
                rec["cancel"] = True
            return self._view(rec)

    def get(self, job_id: str, with_result: bool = True, with_partial: bool = False, since: int | None = None) -> dict:
        """A job's status, stage, its partial result while running (if asked, and newer than `since`, the
        `partial_version` the caller last saw) and its result when done; 404 if unknown."""
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                raise NotFound(f"job '{job_id}' not found")
            return self._view(rec, with_result=with_result, with_partial=with_partial, since=since)
