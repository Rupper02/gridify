"""The scenarios store: branches, added projects, schedules, planned outages, simulated
reinforcements and the durable result cache.

One class owns the connection and the lock; the SQL dialect adapter and the schema migrations live
beside it. Nothing here knows about HTTP, the engine or the cache's policy.
"""

import re
import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

import duckdb

from gridforge_optimizer.config import DEFAULT_SCENARIO, GROWTH_2030, GROWTH_2035

from .config import now

ADDED_COLS = (
    "request_id, applicant, bus_id, technology, rating_mw, readiness_score, "
    "strategic_fit, readiness_rationale, status, review_reasons, commissioning_year, scheduled_year, import_mw"
)
OUTAGE_COLS = ["outage_id", "element_kind", "element_id", "season", "year", "weeks", "kind", "created_at"]
REINFORCEMENT_COLS = ["reinforcement_id", "kind", "element_id", "action", "factor", "label", "created_at"]
BRANCH_COLS = [
    "branch_id", "name", "parent_id", "scenario", "growth_2030", "growth_2035",
    "w_readiness", "w_need", "w_strategic", "status", "created_at", "merged_at", "created_by",
]

_DOUBLE_RE = re.compile(r"\bDOUBLE\b(?! PRECISION)")  # DuckDB's DOUBLE is Postgres's DOUBLE PRECISION


def is_postgres_url(target: str | Path) -> bool:
    return str(target).startswith(("postgresql://", "postgres://"))


class Cursor:
    """A cursor that speaks our SQL to either engine. We write DuckDB-style SQL with `?` placeholders;
    for Postgres the placeholders become `%s` and `DOUBLE` becomes `DOUBLE PRECISION`. Everything
    else used here (ON CONFLICT upserts, IS NOT DISTINCT FROM, information_schema) is common SQL."""

    def __init__(self, cur, dialect: str):
        self._c = cur
        self.dialect = dialect

    def _sql(self, sql: str) -> str:
        if self.dialect == "postgres":
            return _DOUBLE_RE.sub("DOUBLE PRECISION", sql.replace("?", "%s"))
        return sql

    def execute(self, sql: str, params=None):
        self._c.execute(self._sql(sql), params if params is not None else [])
        return self

    def executemany(self, sql: str, seq):
        if seq:
            self._c.executemany(self._sql(sql), seq)
        return self

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    @property
    def description(self):
        return self._c.description

    def columns(self, table: str) -> list[str]:
        """Column names of a table (the migration helper)."""
        if self.dialect == "postgres":
            self._c.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position", [table])
            return [r[0] for r in self._c.fetchall()]
        self._c.execute(f"PRAGMA table_info('{table}')")
        return [r[1] for r in self._c.fetchall()]

    def close(self) -> None:
        self._c.close()


def _connect(target: str):
    if is_postgres_url(target):
        import psycopg  # optional dependency: only needed for a Postgres store

        return psycopg.connect(target, autocommit=True)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(target)


class ScenarioStore:
    """The scenarios database: a DuckDB file (default) or Postgres. Opened lazily, once, with the
    schema created/migrated under the lock; access is serialised through `cursor()`."""

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
        """Open + migrate once per process. The planner's boot fires several requests at once; with a
        brand-new DB two threads each running CREATE TABLE IF NOT EXISTS made DuckDB raise a catalog
        write-write conflict (a 500 on first run). Doing the DDL exactly once, serialised, removes it."""
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
        """Serialised access: a cursor on the shared connection, under the lock. Cursors are the
        thread-safe way to share one connection; the lock keeps writers from conflicting with each
        other (these operations take milliseconds, so contention is moot)."""
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
    """Create/migrate the scenarios tables and seed the 'main' branch (idempotent)."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS added_candidates (
            request_id VARCHAR, applicant VARCHAR, bus_id INTEGER, technology VARCHAR,
            rating_mw DOUBLE, readiness_score DOUBLE, strategic_fit DOUBLE,
            readiness_rationale VARCHAR, status VARCHAR, review_reasons VARCHAR,
            commissioning_year INTEGER, scheduled_year INTEGER
        )
        """
    )
    # migrate the pre-branch schema: existing global rows become main's (idempotent)
    cols = con.columns("added_candidates")
    if "branch_id" not in cols:
        con.execute("ALTER TABLE added_candidates ADD COLUMN branch_id VARCHAR DEFAULT 'main'")
    if "commissioning_year" not in cols:
        con.execute("ALTER TABLE added_candidates ADD COLUMN commissioning_year INTEGER")
    if "scheduled_year" not in cols:  # operator's chosen energisation year (None = follow recommendation)
        con.execute("ALTER TABLE added_candidates ADD COLUMN scheduled_year INTEGER")
    if "import_mw" not in cols:  # charging capacity (batteries); None = same as the rating
        con.execute("ALTER TABLE added_candidates ADD COLUMN import_mw DOUBLE")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS branches (
            branch_id VARCHAR PRIMARY KEY, name VARCHAR, parent_id VARCHAR,
            scenario VARCHAR, growth_2030 DOUBLE, growth_2035 DOUBLE,
            w_readiness DOUBLE, w_need DOUBLE, w_strategic DOUBLE,
            status VARCHAR DEFAULT 'open', created_at VARCHAR, merged_at VARCHAR, created_by VARCHAR
        )
        """
    )
    # planned maintenance windows and simulated reinforcements ("Try on branch"), per branch; both
    # copy on branch create and merge like the projects do
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS branch_outages (
            branch_id VARCHAR, outage_id VARCHAR, element_kind VARCHAR, element_id VARCHAR,
            season VARCHAR, year INTEGER, weeks INTEGER, kind VARCHAR, created_at VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS branch_reinforcements (
            branch_id VARCHAR, reinforcement_id VARCHAR, kind VARCHAR, element_id INTEGER,
            action VARCHAR, factor DOUBLE, label VARCHAR, created_at VARCHAR
        )
        """
    )
    # durable cache of engine results: the same inputs (model snapshot, parameters, candidate set,
    # engine code) always give the same answer, so a run that has happened once never runs again,
    # not even after a restart
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS result_cache (
            cache_key VARCHAR PRIMARY KEY, kind VARCHAR, snapshot_id VARCHAR, engine VARCHAR,
            created_at VARCHAR, compute_ms INTEGER, result_json VARCHAR
        )
        """
    )
    _ensure_main_branch(con)


def _ensure_main_branch(con: Cursor) -> None:
    """Seed the 'main' branch (the plan of record) once, with the default demand pathway."""
    if con.execute("SELECT 1 FROM branches WHERE branch_id = 'main'").fetchone():
        return
    con.execute(
        "INSERT INTO branches (branch_id, name, parent_id, scenario, growth_2030, growth_2035, "
        "w_readiness, w_need, w_strategic, status, created_at) "
        "VALUES ('main', 'Main', NULL, ?, ?, ?, NULL, NULL, NULL, 'open', ?)",
        [DEFAULT_SCENARIO, GROWTH_2030, GROWTH_2035, now()],
    )
