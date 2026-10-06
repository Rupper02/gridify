"""Result caching: an in-process layer over the durable `result_cache` table.

Every key includes the project's baseline (its model snapshot or file fingerprint), the parameters, the
candidate set and the engine's code fingerprint, so branches and projects never serve each other's
results and a code change retires stale physics.
"""

import hashlib
import json
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import TypeVar

from gridforge_optimizer import Candidate, OptimizeParams

from .config import now
from .store import ScenarioStore

T = TypeVar("T")

MAX_TRIAL_CACHE_ENTRIES = 50_000  # bounded: a cold start costs one full run, nothing else
MAX_YEAR_CACHE_ENTRIES = 2_000  # solved plan years (years.year_signature): an edit re-solves only what it touches
MAX_RESULT_ENTRIES = 256  # engine results kept in process (the durable table keeps them all): the oldest go first
MAX_PAYLOAD_ENTRIES = 32  # enriched run payloads (the largest objects here)


def remember(d: dict, key, value, cap: int):
    """Keep `value` under `key` in a dict bounded to `cap` entries, dropping the oldest stored first."""
    d.pop(key, None)
    d[key] = value
    while len(d) > cap:
        d.pop(next(iter(d)))
    return value


def cand_key(cands: list[Candidate]) -> str:
    """A stable hash of a candidate set, so the compute cache never serves one branch's result for
    another branch with different projects (the highest-risk bug of branch-scoping)."""
    sig = sorted(
        (c.request_id, c.bus_id, c.rating_mw, round(c.readiness_score, 4),
         round(c.strategic_fit, 4), c.status, c.import_mw, c.technology, c.commissioning_year)
        + ((c.control.model_dump_json(),) if c.control else ())  # how it runs changes its physics; unstated keys as before
        for c in cands
    )
    return hashlib.md5(json.dumps(sig, default=str).encode()).hexdigest()


def params_key(params: OptimizeParams) -> tuple:
    key = (params.scenario, round(params.growth_2030, 3), round(params.growth_2035, 3),
           params.w_readiness, params.w_need, params.w_strategic)
    # an entered forecast's in-between years (the FES path is set by its two anchors alone)
    return key + (tuple((y, round(m, 4)) for y, m in sorted(params.curve.items())),) if params.curve else key


class ResultCache:
    """In-process dicts (engine results, enriched payloads, trial caches) plus the durable table."""

    def __init__(self, store: ScenarioStore, engine: str, solver_lock: AbstractContextManager | None = None):
        self._store = store
        self.engine = engine
        # every engine computation in the process takes this lock (re-entrant: a job and an agent's gated study
        # already hold it), so a request or an agent tool that misses the cache waits for the solver instead of
        # solving alongside it, at half speed each, often the very result the job is computing
        self._solver = solver_lock or nullcontext()
        self.compute: dict = {}  # key -> OptimizeResult / suggestions (content-addressed, bounded)
        self.payload: dict = {}  # key -> the enriched /optimize payload (bounded; cleared on every edit, see PlanService.edited)
        # per (parameters, snapshot, engine): the engine's exact trial cache, so a branch that gains
        # one project re-solves only the trials whose state changed (see greedy.optimize)
        self._trials: dict[tuple, dict] = {}
        self._years: dict[tuple, dict] = {}
        store.on_reset(self.clear)

    def clear(self) -> None:
        """Drop the in-process layers (the candidate set or the store changed)."""
        self.compute.clear()
        self.payload.clear()

    def key(self, kind: str, params: OptimizeParams, ckey: str, baseline: str, extra: str = "") -> str:
        """The key a result lives under: its kind, the parameters, the candidate set, the project's baseline
        (the model snapshot or an imported file's fingerprint), the engine fingerprint and what else it depends on."""
        sig = json.dumps([kind, params_key(params), ckey, baseline, self.engine, extra], default=str)
        return hashlib.sha256(sig.encode()).hexdigest()[:32]

    def trial_cache(self, params: OptimizeParams, baseline: str) -> dict:
        cache = self._trials.setdefault((params_key(params), baseline, self.engine), {})
        if len(cache) > MAX_TRIAL_CACHE_ENTRIES:
            cache.clear()
        return cache

    def year_cache(self, baseline: str) -> dict:
        """Solved plan years by `years.year_signature` (which already covers the parameters), per
        baseline and engine: what a re-run after a small edit reuses."""
        cache = self._years.setdefault((baseline, self.engine), {})
        if len(cache) > MAX_YEAR_CACHE_ENTRIES:
            cache.clear()
        return cache

    def has(self, key: str) -> bool:
        """Whether a result for this key exists, in process or durably: the merge gate's freshness test."""
        if key in self.compute:
            return True
        with self._store.cursor() as con:
            return con.execute("SELECT 1 FROM result_cache WHERE cache_key = ?", [key]).fetchone() is not None

    def through(self, key: str, kind: str, *, baseline: str, parse: Callable[[str], T], compute: Callable[[], T],
                dump: Callable[[T], str], on_hit: Callable[[T], None] | None = None, locked: bool = True) -> T:
        """The one read-through path every engine result takes: the in-process dict, then the durable
        table (`parse`d from JSON), then `compute` (stored with `dump` and its compute time). `on_hit`
        sees a value that did not come from `compute` (a cached plan still reaches a per-year callback).
        A miss computes under the solver lock, and looks again once it has it: whoever held the solver may
        just have stored this very key. `locked=False` is for a compute that takes the solver itself, through a
        gate that must wait for an operator's job before it holds the lock (an agent study, chunk by chunk):
        holding the lock while that gate waits would deadlock the job. Two such computes of one key may both run.
        Never call it while holding a store cursor (the store has its own lock)."""
        value, hit = self._lookup(key, parse)
        if not hit:
            with self._solver if locked else nullcontext():
                value, hit = self._lookup(key, parse)
                if not hit:
                    t0 = time.perf_counter()
                    value = compute()
                    self.put(key, kind, baseline, int((time.perf_counter() - t0) * 1000), dump(value))
                    remember(self.compute, key, value, MAX_RESULT_ENTRIES)
        if hit and on_hit is not None:
            on_hit(value)
        return value

    def _lookup(self, key: str, parse: Callable[[str], T]) -> tuple[T | None, bool]:
        """The in-process dict, then the durable table (kept in process once read)."""
        if key in self.compute:
            return self.compute[key], True
        cached = self.get(key)
        if cached is None:
            return None, False
        return remember(self.compute, key, parse(cached), MAX_RESULT_ENTRIES), True

    def get(self, key: str) -> str | None:
        with self._store.cursor() as con:
            row = con.execute("SELECT result_json FROM result_cache WHERE cache_key = ?", [key]).fetchone()
        return row[0] if row else None

    def get_with_kind(self, key: str) -> tuple[str, str, str] | None:
        """A durable result with the kind it was stored as ("study:hosting_capacity", "years", ...) and the engine
        fingerprint that computed it."""
        with self._store.cursor() as con:
            row = con.execute("SELECT kind, result_json, engine FROM result_cache WHERE cache_key = ?", [key]).fetchone()
        return (row[0], row[1], row[2]) if row else None

    def put(self, key: str, kind: str, baseline: str, compute_ms: int, result_json: str) -> None:
        with self._store.cursor() as con:
            con.execute(
                "INSERT INTO result_cache VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (cache_key) DO UPDATE SET result_json = EXCLUDED.result_json, created_at = EXCLUDED.created_at, "
                "compute_ms = EXCLUDED.compute_ms",
                [key, kind, baseline, self.engine, now(), compute_ms, result_json],
            )

    def stats(self) -> dict:
        """What the durable cache holds: runs and suggestion sets per kind, with the engine
        fingerprint they were computed under (a code change retires them)."""
        with self._store.cursor() as con:
            rows = con.execute(
                "SELECT kind, engine, count(*) AS n, sum(compute_ms) AS compute_ms FROM result_cache GROUP BY kind, engine ORDER BY kind, engine"
            ).fetchall()
        return {"engine": self.engine, "entries": [dict(zip(("kind", "engine", "n", "compute_ms_saved"), r)) for r in rows]}
