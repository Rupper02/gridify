"""The pipeline warehouse, read-only: the geolocated grid, the registry and the snapshot history.

Reads are consistent and stay available while the pipeline writes. The pipeline writes in one transaction, but on
this platform its writer locks the file against every other process, so a reader cannot see even the previous
version while it writes (about a second per run). Each logical read (the whole model, one query) therefore runs on
ONE read-only connection, so it is one committed version, never a mix of two; it retries briefly while the writer
holds the file; and if the file is still locked it answers with the last consistent read of the same thing (kept
with the `snapshot_id` it was read at), one write behind at most. With nothing read yet it raises `WarehouseBusy`.
Every read records, for the request in progress (`request_state`), the snapshot it was read at and whether it was the
fallback, so the response can say so (`X-Warehouse-Snapshot`, `X-Warehouse-Stale`). A route that reads several
things reads them together with `read(key, fn)`, one committed version for all of them.
"""

import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import duckdb

from ..config import log

# how long a read waits for the pipeline's writer (it holds the file about a second per run) before it falls back, and
# how long after seeing the lock later reads try once and fall back at once instead of each waiting again
_LOCK_RETRY_S = (0.25, 0.5, 0.75)
LOCK_MEMORY_S = 3.0


class WarehouseBusy(Exception):
    """The pipeline is writing the warehouse and nothing was read before: retry in a moment."""


def _locked(e: Exception) -> bool:
    """Is this the writer's lock (another process holds the file), not a real error?"""
    m = str(e).lower()
    return "being used by another process" in m or "could not set lock" in m or "conflicting lock" in m


# what the request in progress read: {"snapshot": id, "stale": bool} (set per request by the API's middleware)
_REQUEST: ContextVar[dict | None] = ContextVar("warehouse_request", default=None)


def request_state() -> dict:
    """Start recording, for the request in progress, which snapshot its warehouse reads were and whether any was stale;
    returns the record the middleware reads once the response is ready."""
    state: dict = {}
    _REQUEST.set(state)
    return state


def _note(snapshot: str, stale: bool) -> None:
    state = _REQUEST.get()
    if state is not None:
        state["snapshot"] = snapshot
        state["stale"] = state.get("stale", False) or stale


def rows(con, sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def has_table(con, name: str) -> bool:
    return bool(con.execute("SELECT 1 FROM information_schema.tables WHERE table_name = ?", [name]).fetchone())


def _snapshot_id(con) -> str:
    if not has_table(con, "snapshots"):
        return "baseline"
    r = con.execute("SELECT snapshot_id FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
    return r[0] if r else "baseline"


class Warehouse:
    """Read-only access to the pipeline's DuckDB warehouse. Nothing here ever writes."""

    def __init__(self, path: Path):
        self.path = path
        self._last: dict[str, tuple[str, Any]] = {}  # read -> (snapshot id it was read at, value): the last consistent read
        self._guard = threading.Lock()
        self._locked_until = 0.0  # monotonic time until which the writer is assumed to still hold the file
        self._baseline: tuple[int | None, str] | None = None  # (the file's mtime, its snapshot id): read once per version

    def exists(self) -> bool:
        return self.path.exists()

    @contextmanager
    def _connection(self):
        """One read-only connection, opened as soon as the pipeline's writer lets go (`_LOCK_RETRY_S`); right after a
        lock was seen (`LOCK_MEMORY_S`), one attempt only, so a burst of reads during a write does not each wait."""
        waits = () if time.monotonic() < self._locked_until else _LOCK_RETRY_S
        for wait in (*waits, None):
            try:
                con = duckdb.connect(str(self.path), read_only=True)
                break
            except duckdb.IOException as e:
                if not _locked(e):
                    raise
                if wait is None:
                    self._locked_until = time.monotonic() + LOCK_MEMORY_S
                    raise
                time.sleep(wait)
        try:
            yield con
        finally:
            con.close()

    def read(self, key: str, fn: Callable[[Any], Any]) -> Any:
        """`fn(con)` on one connection (one committed version); while the writer still holds the file, the last
        consistent read of `key`, or `WarehouseBusy` when there is none. Right after a lock was seen, a read that has
        a last consistent answer gives it without touching the file (opening a locked file is itself slow)."""
        if time.monotonic() < self._locked_until:
            with self._guard:
                hit = self._last.get(key)
            if hit is not None:
                _note(hit[0], True)
                return hit[1]
        try:
            with self._connection() as con:
                value = fn(con)
                sid = _snapshot_id(con)
        except duckdb.IOException as e:
            if not _locked(e):
                raise
            with self._guard:
                hit = self._last.get(key)
            if hit is None:
                raise WarehouseBusy("the pipeline is writing the warehouse; retry in a moment") from e
            log.warning("warehouse locked by the pipeline: serving %s as read at snapshot %s", key, hit[0])
            _note(hit[0], True)
            return hit[1]
        with self._guard:
            self._last[key] = (sid, value)
        _note(sid, False)
        return value

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        """Run a read-only SQL query and return rows as dicts."""
        return self.read(f"query:{sql}:{params}", lambda con: rows(con, sql, params))

    def baseline_id(self) -> str:
        """The latest model snapshot's content-hash id (used to key the result caches). Nearly every request asks for
        it (every cache key carries it), and each read opens the file: it is read once per version of the file."""
        try:
            mtime = self.path.stat().st_mtime_ns
        except OSError:
            mtime = None
        with self._guard:
            hit = self._baseline
        if hit is not None and hit[0] == mtime:
            return hit[1]
        sid = self.read("baseline_id", _snapshot_id)
        with self._guard:
            self._baseline = (mtime, sid)
        return sid

    def baseline_model(self) -> dict:
        """The geolocated grid (buses, lines, transformers, loads, generators) for the map, read as one
        committed version. A line's `length_km` is NULL where the LTDS gives none; `in_service` FALSE is an open point."""
        return self.read("baseline_model", self._model)

    @staticmethod
    def _model(con) -> dict:
        buses = rows(con, "SELECT bus_id, name, vn_kv, lon, lat FROM buses WHERE lon IS NOT NULL")
        lines = rows(con, """
            SELECT l.line_id, l.line_name, l.rating_a, l.voltage_kv, l.from_bus, l.to_bus, l.length_km, l.in_service,
                   f.lon AS from_lon, f.lat AS from_lat, t.lon AS to_lon, t.lat AS to_lat
            FROM lines l
            JOIN buses f ON l.from_bus = f.bus_id
            JOIN buses t ON l.to_bus   = t.bus_id
            WHERE f.lon IS NOT NULL AND t.lon IS NOT NULL
            """)
        transformers = rows(con, """
            SELECT tr.trafo_id, tr.name, tr.sn_mva, tr.hv_bus, tr.lv_bus,
                   h.vn_kv AS hv_kv, lv.vn_kv AS lv_kv, h.name AS hv_name,
                   h.lon AS hv_lon, h.lat AS hv_lat, lv.lon AS lv_lon, lv.lat AS lv_lat
            FROM transformers tr
            JOIN buses h  ON tr.hv_bus = h.bus_id
            JOIN buses lv ON tr.lv_bus = lv.bus_id
            WHERE h.lon IS NOT NULL AND lv.lon IS NOT NULL
            """)
        loads = rows(con, """
            SELECT ld.bus_id, ld.p_mw, ld.region_id, b.lon, b.lat
            FROM loads ld
            JOIN buses b ON ld.bus_id = b.bus_id
            WHERE b.lon IS NOT NULL
            """)
        for i, ld in enumerate(loads):
            ld["load_id"] = i
        generators = rows(con, """
            SELECT g.request_id, g.bus_id, g.rating_mw, g.technology, g.applicant, b.lon, b.lat
            FROM generators g JOIN buses b ON g.bus_id = b.bus_id
            WHERE b.lon IS NOT NULL
            """)
        return {"buses": buses, "lines": lines, "transformers": transformers, "loads": loads, "generators": generators}

    def registry_rows(self) -> list[dict]:
        """The registry: the not-yet-built projects, available to pull onto a branch (main never includes them)."""
        return self.query("SELECT * FROM candidate_projects")
