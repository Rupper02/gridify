"""Long computations run on a single background worker; the planner polls their progress."""

import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException

from .config import log, now

MAX_JOB_RECORDS = 200  # keep the registry bounded; finished jobs fall off oldest-first
PRUNE_BATCH = 50


class JobRunner:
    """Queue `fn(progress)` on one worker (pandapower is CPU-bound: one run at a time) and track it."""

    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gridforge-job")
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def submit(self, fn: Callable[[], None]) -> None:
        """Run a fire-and-forget task on the worker (warm-up)."""
        self._pool.submit(fn)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def start(self, kind: str, fn: Callable[[Callable[[str, float], None]], dict]) -> dict:
        """Queue `fn(progress)` and return the job record."""
        job_id = "job-" + uuid.uuid4().hex[:10]
        rec = {"job_id": job_id, "kind": kind, "status": "queued", "stage": "queued", "fraction": 0.0,
               "created_at": now(), "started_at": None, "finished_at": None, "elapsed_ms": 0, "result": None, "error": None}
        with self._lock:
            self._jobs[job_id] = rec
            if len(self._jobs) > MAX_JOB_RECORDS:
                for old in sorted(self._jobs, key=lambda k: self._jobs[k]["created_at"])[:PRUNE_BATCH]:
                    if self._jobs[old]["status"] in ("done", "failed"):
                        self._jobs.pop(old, None)

        def progress(stage: str, fraction: float) -> None:
            with self._lock:
                rec["stage"], rec["fraction"] = stage, round(float(fraction), 3)

        def run() -> None:
            t0 = time.perf_counter()
            with self._lock:
                rec["status"], rec["started_at"], rec["stage"] = "running", now(), "starting"
            try:
                out = fn(progress)
                with self._lock:
                    rec.update(status="done", stage="done", fraction=1.0, result=out)
            except Exception as exc:  # the job records its own failure; nothing escapes the worker
                log.exception("job %s failed", job_id)
                with self._lock:
                    rec.update(status="failed", stage="failed", error=f"{type(exc).__name__}: {exc}")
            finally:
                with self._lock:
                    rec["finished_at"] = now()
                    rec["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)

        self._pool.submit(run)
        return self._view(rec)

    @staticmethod
    def _view(rec: dict, with_result: bool = False) -> dict:
        out = {k: v for k, v in rec.items() if k != "result"}
        if with_result:
            out["result"] = rec["result"]
        return out

    def get(self, job_id: str, with_result: bool = True) -> dict:
        """A job's status, stage and (when done) its result; 404 if unknown."""
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")
            return self._view(rec, with_result=with_result)
