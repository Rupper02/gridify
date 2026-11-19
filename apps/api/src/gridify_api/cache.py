"""Result caching: an in-process layer over the durable `result_cache` table.

Every key includes the grid's baseline (its model snapshot), the demand profile, the connections and the engine's code
fingerprint, so branches never serve each other's results and a code change retires stale physics.
"""

import hashlib
import json
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import TypeVar

from gridify_optimizer import Connection, PlanParams

from .config import log, now
from .errors import NotSolved
from .store import ScenarioStore

T = TypeVar("T")

MAX_YEAR_CACHE_ENTRIES = 2_000  # solved plan years (years.year_signature): an edit re-solves only what it touches
_MISSING = object()
MAX_RESULT_ENTRIES = 128  # results kept in process (the durable table keeps them all): the oldest go first


def remember(d: dict, key, value, cap: int):
    """Keep `value` under `key` in a dict bounded to `cap` entries, dropping the oldest stored first."""
    d.pop(key, None)
    d[key] = value
    while len(d) > cap:
        d.pop(next(iter(d)))
    return value


def connections_key(connections: list[Connection]) -> str:
    """A stable hash of a branch's connections: every field the physics reads, and the year."""
    sig = sorted([*c.signature(), c.year] for c in connections)
    return hashlib.md5(json.dumps(sig, default=str).encode()).hexdigest()


def params_key(params: PlanParams) -> tuple:
    return (params.scenario, round(params.growth_2030, 4), round(params.growth_2035, 4))  # as years.year_signature


class ResultCache:
    """An in-process dict of results and of solved plan years, plus the durable table."""

    def __init__(self, store: ScenarioStore, engine: str, solver_lock: threading.RLock):
        self._store = store
        self.engine = engine
        # every engine computation in the process takes this lock (re-entrant: a job already holds it), so a request
        # that misses the cache waits for the solver instead of solving alongside it
        self._solver = solver_lock
        self.compute: dict = {}
        self._years: dict[tuple, dict] = {}
        store.on_reset(self.compute.clear)

    def key(self, kind: str, params: PlanParams, ckey: str, baseline: str) -> str:
        """The key a result lives under: its kind, the demand profile, the connections, the grid's baseline and the
        engine fingerprint."""
        sig = json.dumps([kind, params_key(params), ckey, baseline, self.engine], default=str)
        return hashlib.sha256(sig.encode()).hexdigest()[:32]

    def year_cache(self, baseline: str) -> dict:
        """Solved plan years by `years.year_signature` (which already covers the profile and the connections), per
        baseline and engine: what a re-run after a small edit reuses."""
        cache = self._years.setdefault((baseline, self.engine), {})
        if len(cache) > MAX_YEAR_CACHE_ENTRIES:
            cache.clear()
        return cache

    def has(self, key: str) -> bool:
        if key in self.compute:
            return True
        with self._store.cursor() as con:
            return con.execute("SELECT 1 FROM result_cache WHERE cache_key = ?", [key]).fetchone() is not None

    def through(self, key: str, kind: str, *, baseline: str, parse: Callable[[str], T], compute: Callable[[], T],
                dump: Callable[[T], str], on_hit: Callable[[T], None] | None = None, solve: bool = True, wait: bool = True) -> T:
        """The one read-through path every engine result takes: the in-process dict, then the durable table (`parse`d
        from JSON), then `compute` (stored with `dump`). `on_hit` sees a value that did not come from `compute`. A miss
        computes under the solver lock and looks again once it has it (whoever held the solver may just have stored
        this very key). `solve=False` never computes (`NotSolved`: run the branch); `wait=False` never queues behind a
        run (`NotSolved` with `retry`). Never call it while holding a store cursor (the store has its own lock)."""
        value, hit = self._lookup(key, parse)
        if not hit:
            if not solve:
                raise NotSolved(f"{kind} is not computed yet for these inputs", retry=False)
            with self._hold(wait):
                value, hit = self._lookup(key, parse)
                if not hit:
                    t0 = time.perf_counter()
                    value = compute()
                    ms = int((time.perf_counter() - t0) * 1000)
                    self.put(key, kind, baseline, ms, dump(value))
                    remember(self.compute, key, value, MAX_RESULT_ENTRIES)
                    log.info("computed %s in %.1f s (%s)", kind, ms / 1000, key[:12])
        if hit and on_hit is not None:
            on_hit(value)
        return value

    @contextmanager
    def _hold(self, wait: bool):
        if not self._solver.acquire(blocking=wait):
            raise NotSolved("the engine is busy with a run: ask again when it finishes", retry=True)
        try:
            yield
        finally:
            self._solver.release()

    def _lookup(self, key: str, parse: Callable[[str], T]) -> tuple[T | None, bool]:
        value = self.compute.get(key, _MISSING)  # one read: another thread may evict the key between two
        if value is not _MISSING:
            return value, True
        with self._store.cursor() as con:
            row = con.execute("SELECT result_json FROM result_cache WHERE cache_key = ?", [key]).fetchone()
        if row is None:
            return None, False
        return remember(self.compute, key, parse(row[0]), MAX_RESULT_ENTRIES), True

    def put(self, key: str, kind: str, baseline: str, compute_ms: int, result_json: str) -> None:
        with self._store.cursor() as con:
            con.execute(
                "INSERT INTO result_cache VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (cache_key) DO UPDATE SET result_json = EXCLUDED.result_json, created_at = EXCLUDED.created_at, "
                "compute_ms = EXCLUDED.compute_ms",
                [key, kind, baseline, self.engine, now(), compute_ms, result_json],
            )
