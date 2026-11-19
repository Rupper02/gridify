"""The scenarios store: branches, the connections on them and the durable result cache.

One class owns the connection and the lock; the SQL dialect adapter and the schema migrations live beside it. Nothing
here knows about HTTP, the engine or the cache's policy.
"""

import re
import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

import duckdb

from gridify_optimizer.config import DEFAULT_SCENARIO, GROWTH_2030, GROWTH_2035

from .config import MAIN_ID, now

# `version` counts the changes to a branch's connections; `parent_version` is its parent's version when it was opened
BRANCH_COLS = ["branch_id", "name", "parent_id", "scenario", "growth_2030", "growth_2035", "status", "created_at", "merged_at",
               "version", "parent_version"]
PROFILE_COLS = ["scenario", "growth_2030", "growth_2035"]  # a branch's demand profile
CONNECTION_COLS = ["request_id", "name", "bus_id", "technology", "rating_mw", "import_mw", "control_json", "year", "source", "created_at"]

_DOUBLE_RE = re.compile(r"\bDOUBLE\b(?! PRECISION)")  # DuckDB's DOUBLE is Postgres's DOUBLE PRECISION


def is_postgres_url(target: str | Path) -> bool:
    return str(target).startswith(("postgresql://", "postgres://"))


class Cursor:
    """A cursor that speaks our SQL to either engine. We write DuckDB-style SQL with `?` placeholders; for Postgres the
    placeholders become `%s` and `DOUBLE` becomes `DOUBLE PRECISION`. Everything else used here (ON CONFLICT upserts,
    information_schema) is common SQL."""

    def __init__(self, cur, dialect: str):
        self._c = cur
        self.dialect = dialect

    def _sql(self, sql: str) -> str:
        if self.dialect == "postgres":  # a literal % (LIKE 'CR-%') must be doubled once %s placeholders are in play
            return _DOUBLE_RE.sub("DOUBLE PRECISION", sql.replace("%", "%%").replace("?", "%s"))
        return sql

    def execute(self, sql: str, params=None):
        self._c.execute(self._sql(sql), params if params is not None else [])
        return self

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    @contextmanager
    def transaction(self):
        """Several writes as one: all of them, or none (a failure part-way rolls back)."""
        self._c.execute("BEGIN")
        try:
            yield self
        except BaseException:
            self._c.execute("ROLLBACK")
            raise
        self._c.execute("COMMIT")

    def close(self) -> None:
        self._c.close()


def _connect(target: str):
    if is_postgres_url(target):
        import psycopg  # optional dependency: only needed for a Postgres store

        return psycopg.connect(target, autocommit=True)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(target)


class ScenarioStore:
    """The scenarios database: a DuckDB file (default) or Postgres. Opened lazily, once, with the schema
    created/migrated under the lock; access is serialised through `cursor()`."""

    def __init__(self, target: str | Path):
        self._target = str(target)
        self._lock = threading.RLock()
        self._con = None
        self._on_reset: list[Callable[[], None]] = []

    @property
    def target(self) -> str:
        return self._target

    @property
    def dialect(self) -> str:
        return "postgres" if is_postgres_url(self._target) else "duckdb"

    def on_reset(self, callback: Callable[[], None]) -> None:
        """Register something to run when the store is pointed elsewhere (e.g. drop in-memory caches)."""
        self._on_reset.append(callback)

    def _open(self):
        """Open + migrate once per process, serialised: the planner's boot fires several requests at once, and two
        threads each running CREATE TABLE IF NOT EXISTS on a new DuckDB file raise a catalog conflict."""
        with self._lock:
            if self._con is None:
                con = _connect(self._target)
                cur = Cursor(con.cursor(), self.dialect)
                try:
                    migrate(cur)
                finally:
                    cur.close()
                self._con = con
            return self._con

    def init(self) -> None:
        self._open()

    @contextmanager
    def cursor(self):
        """Serialised access: a cursor on the shared connection, under the lock."""
        con = self._open()
        with self._lock:
            cur = Cursor(con.cursor(), self.dialect)
            try:
                yield cur
            finally:
                cur.close()

    def close(self) -> None:
        with self._lock:
            if self._con is not None:
                self._con.close()
            self._con = None

    def use(self, target: str | Path) -> None:
        """Point at another store (a DuckDB path or a postgresql:// URL), closing the current one."""
        with self._lock:
            self.close()
            self._target = str(target)
        for cb in self._on_reset:
            cb()


# --- schema ------------------------------------------------------------------
def migrate(con: Cursor) -> None:
    """Create/migrate the tables and seed `main` (idempotent)."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS branches (
            branch_id VARCHAR PRIMARY KEY, name VARCHAR, parent_id VARCHAR,
            scenario VARCHAR, growth_2030 DOUBLE, growth_2035 DOUBLE,
            status VARCHAR DEFAULT 'open', created_at VARCHAR, merged_at VARCHAR
        )
        """
    )
    for col in ("version", "parent_version"):
        con.execute(f"ALTER TABLE branches ADD COLUMN IF NOT EXISTS {col} INTEGER DEFAULT 0")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS connections (
            branch_id VARCHAR, request_id VARCHAR, name VARCHAR, bus_id INTEGER, technology VARCHAR,
            rating_mw DOUBLE, import_mw DOUBLE, control_json VARCHAR, year INTEGER, source VARCHAR, created_at VARCHAR
        )
        """
    )
    # durable cache of engine results: the same inputs (model snapshot, demand profile, connections, engine code)
    # always give the same answer, so a run that has happened once never runs again, not even after a restart
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS result_cache (
            cache_key VARCHAR PRIMARY KEY, kind VARCHAR, snapshot_id VARCHAR, engine VARCHAR,
            created_at VARCHAR, compute_ms INTEGER, result_json VARCHAR
        )
        """
    )
    ensure_main_branch(con)


def ensure_main_branch(con: Cursor) -> None:
    """Seed `main` (the network as it exists today, the plan of record) once, with the default demand pathway."""
    if con.execute("SELECT 1 FROM branches WHERE branch_id = ?", [MAIN_ID]).fetchone():
        return
    con.execute(
        "INSERT INTO branches (branch_id, name, parent_id, scenario, growth_2030, growth_2035, status, created_at) "
        "VALUES (?, 'Main', NULL, ?, ?, ?, 'open', ?)",
        [MAIN_ID, DEFAULT_SCENARIO, GROWTH_2030, GROWTH_2035, now()],
    )
