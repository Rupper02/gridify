"""Result caching: an in-process layer over the durable `result_cache` table.

Every key includes the model snapshot, the parameters, the candidate set and the engine's code
fingerprint, so branches never serve each other's results and a code change retires stale physics.
"""

import hashlib
import json
import time
from collections.abc import Callable
from typing import TypeVar

from gridforge_optimizer import Candidate, OptimizeParams

from .config import now
from .store import ScenarioStore
from .warehouse import Warehouse

T = TypeVar("T")

MAX_TRIAL_CACHE_ENTRIES = 50_000  # bounded: a cold start costs one full run, nothing else
MAX_YEAR_CACHE_ENTRIES = 2_000  # solved plan years (years.year_signature): an edit re-solves only what it touches


def cand_key(cands: list[Candidate]) -> str:
    """A stable hash of a candidate set, so the compute cache never serves one branch's result for
    another branch with different projects (the highest-risk bug of branch-scoping)."""
    sig = sorted(
        (c.request_id, c.bus_id, c.rating_mw, round(c.readiness_score, 4),
         round(c.strategic_fit, 4), c.status, c.import_mw, c.technology, c.commissioning_year)
        for c in cands
    )
    return hashlib.md5(json.dumps(sig, default=str).encode()).hexdigest()


def params_key(params: OptimizeParams) -> tuple:
    return (params.scenario, round(params.growth_2030, 3), round(params.growth_2035, 3),
            params.w_readiness, params.w_need, params.w_strategic)


class ResultCache:
    """In-process dicts (engine results, enriched payloads, trial caches) plus the durable table."""

    def __init__(self, store: ScenarioStore, warehouse: Warehouse, engine: str):
        self._store = store
        self._warehouse = warehouse
        self.engine = engine
        self.compute: dict = {}  # key -> OptimizeResult / suggestions
        self.payload: dict = {}  # key -> the enriched /optimize payload
        # per (parameters, snapshot, engine): the engine's exact trial cache, so a branch that gains
        # one project re-solves only the trials whose state changed (see greedy.optimize)
        self._trials: dict[tuple, dict] = {}
        self._years: dict[tuple, dict] = {}
        store.on_reset(self.clear)

    def clear(self) -> None:
        """Drop the in-process layers (the candidate set or the store changed)."""
        self.compute.clear()
        self.payload.clear()

    def key(self, kind: str, params: OptimizeParams, ckey: str, extra: str = "") -> str:
        sig = json.dumps([kind, params_key(params), ckey, self._warehouse.baseline_id(), self.engine, extra], default=str)
        return hashlib.sha256(sig.encode()).hexdigest()[:32]

    def trial_cache(self, params: OptimizeParams) -> dict:
        cache = self._trials.setdefault((params_key(params), self._warehouse.baseline_id(), self.engine), {})
        if len(cache) > MAX_TRIAL_CACHE_ENTRIES:
            cache.clear()
        return cache

    def year_cache(self) -> dict:
        """Solved plan years by `years.year_signature` (which already covers the parameters), per
        snapshot and engine: what a re-run after a small edit reuses."""
        cache = self._years.setdefault((self._warehouse.baseline_id(), self.engine), {})
        if len(cache) > MAX_YEAR_CACHE_ENTRIES:
            cache.clear()
        return cache

    def has(self, key: str) -> bool:
        """Whether a result for this key exists, in process or durably: the merge gate's freshness test."""
        if key in self.compute:
            return True
        with self._store.cursor() as con:
            return con.execute("SELECT 1 FROM result_cache WHERE cache_key = ?", [key]).fetchone() is not None

    def through(self, key: str, kind: str, *, parse: Callable[[str], T], compute: Callable[[], T],
                dump: Callable[[T], str], on_hit: Callable[[T], None] | None = None) -> T:
        """The one read-through path every engine result takes: the in-process dict, then the durable
        table (`parse`d from JSON), then `compute` (stored with `dump` and its compute time). `on_hit`
        sees a value that did not come from `compute` (a cached plan still reaches a per-year callback)."""
        if key in self.compute:
            value, hit = self.compute[key], True
        else:
            cached = self.get(key)
            if cached is not None:
                value, hit = parse(cached), True
            else:
                t0 = time.perf_counter()
                value, hit = compute(), False
                self.put(key, kind, int((time.perf_counter() - t0) * 1000), dump(value))
            self.compute[key] = value
        if hit and on_hit is not None:
            on_hit(value)
        return value

    def get(self, key: str) -> str | None:
        with self._store.cursor() as con:
            row = con.execute("SELECT result_json FROM result_cache WHERE cache_key = ?", [key]).fetchone()
        return row[0] if row else None

    def put(self, key: str, kind: str, compute_ms: int, result_json: str) -> None:
        with self._store.cursor() as con:
            con.execute(
                "INSERT INTO result_cache VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (cache_key) DO UPDATE SET result_json = EXCLUDED.result_json, created_at = EXCLUDED.created_at, "
                "compute_ms = EXCLUDED.compute_ms",
                [key, kind, self._warehouse.baseline_id(), self.engine, now(), compute_ms, result_json],
            )

    def stats(self) -> dict:
        """What the durable cache holds: runs and suggestion sets per kind, with the engine
        fingerprint they were computed under (a code change retires them)."""
        with self._store.cursor() as con:
            rows = con.execute(
                "SELECT kind, engine, count(*) AS n, sum(compute_ms) AS compute_ms FROM result_cache GROUP BY kind, engine ORDER BY kind, engine"
            ).fetchall()
        return {"engine": self.engine, "entries": [dict(zip(("kind", "engine", "n", "compute_ms_saved"), r)) for r in rows]}
