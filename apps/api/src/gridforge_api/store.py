"""The scenarios store: branches, added projects, schedules, planned outages, simulated
reinforcements, the durable result cache, the findings ledger and the merge audit.

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

from .config import NGED_MAIN_ID, NGED_PROJECT_ID, now

ADDED_COLS = ["request_id", "applicant", "bus_id", "technology", "rating_mw", "readiness_score", "strategic_fit", "readiness_rationale",
              "status", "review_reasons", "commissioning_year", "scheduled_year", "import_mw", "control_json"]
PROFILE_COLS = ["scenario", "growth_2030", "growth_2035", "w_readiness", "w_need", "w_strategic"]  # a branch's demand profile and weights
OUTAGE_COLS = ["outage_id", "element_kind", "element_id", "season", "year", "weeks", "kind", "created_at",
               "work", "repower", "factor"]
REINFORCEMENT_COLS = ["reinforcement_id", "kind", "element_id", "action", "factor", "label", "created_at"]
BRANCH_COLS = [
    "branch_id", "name", "parent_id", "scenario", "growth_2030", "growth_2035",
    "w_readiness", "w_need", "w_strategic", "status", "created_at", "merged_at", "created_by", "project_id", "fork_json",
]
PROJECT_COLS = ["project_id", "name", "source_kind", "source_ref", "snapshot_id", "created_at", "meta_json", "report_json", "capabilities_json", "main_id"]
FINDING_COLS = [
    "finding_id", "branch_id", "fingerprint", "source", "kind", "severity", "year", "study_case", "element_kind",
    "element_id", "value", "limit_value", "message", "context_json", "status", "note", "evidence_kind",
    "evidence_ref", "evidence_json", "snapshot_id", "engine", "first_seen_at", "last_seen_at", "acked_at", "resolved_at",
]
RUN_COLS = [
    "run_id", "project_id", "kind", "agent", "workflow_id", "branch_id", "thread_id", "event_id", "parent_run_id",
    "status", "started_at", "finished_at", "model", "input_tokens", "output_tokens", "cost_credits", "solves", "summary", "error",
]
STEP_COLS = ["step_id", "run_id", "seq", "tool", "args_json", "cache_key", "result_json", "solves", "started_at", "finished_at",
             "cost_credits", "error"]
THREAD_COLS = ["thread_id", "project_id", "branch_id", "title", "kind", "created_at", "updated_at"]
MESSAGE_COLS = ["message_id", "thread_id", "seq", "role", "content", "status", "workflow_id", "run_id", "tool_trace_json",
                "model_json", "usage_json", "cost_credits", "flags_json", "evidence_json", "created_at"]
APPROVAL_COLS = ["approval_id", "project_id", "thread_id", "message_id", "run_id", "tool_call_id", "tool", "args_json", "status",
                 "decided_at", "decided_by", "note", "result_json", "created_at"]
REVIEW_COLS = ["review_id", "project_id", "branch_id", "run_key", "run_id", "verdict", "verdict_json", "body", "blockers_json",
               "warnings_json", "not_studied_json", "status", "created_at"]
MERGE_COLS = [
    "merge_id", "branch_id", "into_branch", "outcome", "ok", "n_blockers", "n_warnings", "acknowledged",
    "verdict_json", "head_key", "base_key", "snapshot_id", "engine", "created_at",
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
    if "control_json" not in cols:  # how its connection offer runs it (types.Control); None = not stated
        con.execute("ALTER TABLE added_candidates ADD COLUMN control_json VARCHAR")
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
    # projects: the grids planned on. Every branch belongs to one; the built-in NGED project owns `main`
    if "project_id" not in con.columns("branches"):
        con.execute("ALTER TABLE branches ADD COLUMN project_id VARCHAR")
        con.execute("UPDATE branches SET project_id = ? WHERE project_id IS NULL", [NGED_PROJECT_ID])
    # the fork point: the parent's state when the branch was opened (or last rebased), what tells the branch's
    # own changes from the ones its parent received since (rebase.py); NULL on a main and on older branches
    if "fork_json" not in con.columns("branches"):
        con.execute("ALTER TABLE branches ADD COLUMN fork_json VARCHAR")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            project_id VARCHAR PRIMARY KEY, name VARCHAR, source_kind VARCHAR, source_ref VARCHAR, snapshot_id VARCHAR,
            created_at VARCHAR, meta_json VARCHAR, report_json VARCHAR, capabilities_json VARCHAR, main_id VARCHAR
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
    # work types: what a window is for, and what a repowering leaves behind (maintenance.WORKS)
    cols = con.columns("branch_outages")
    if "work" not in cols:
        con.execute("ALTER TABLE branch_outages ADD COLUMN work VARCHAR DEFAULT 'maintenance'")
        con.execute("UPDATE branch_outages SET work = 'maintenance' WHERE work IS NULL")
    if "repower" not in cols:  # repowering only: 'uprate' | 'add_parallel'
        con.execute("ALTER TABLE branch_outages ADD COLUMN repower VARCHAR")
    if "factor" not in cols:  # repowering 'uprate' only: the rating multiplier
        con.execute("ALTER TABLE branch_outages ADD COLUMN factor DOUBLE")
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
    # the findings ledger: what every run found (and what the agents file), one row per
    # branch + fingerprint, upserted by each run; never copied on branch create or merge
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS findings (
            finding_id VARCHAR PRIMARY KEY, branch_id VARCHAR, fingerprint VARCHAR, source VARCHAR,
            kind VARCHAR, severity VARCHAR, year INTEGER, study_case VARCHAR, element_kind VARCHAR, element_id VARCHAR,
            value DOUBLE, limit_value DOUBLE, message VARCHAR, context_json VARCHAR,
            status VARCHAR DEFAULT 'open', note VARCHAR,
            evidence_kind VARCHAR, evidence_ref VARCHAR, evidence_json VARCHAR, snapshot_id VARCHAR, engine VARCHAR,
            first_seen_at VARCHAR, last_seen_at VARCHAR, acked_at VARCHAR, resolved_at VARCHAR
        )
        """
    )
    # the merge audit: every attempt, refused or done, with the gate's verdict
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS merges (
            merge_id VARCHAR PRIMARY KEY, branch_id VARCHAR, into_branch VARCHAR, outcome VARCHAR,
            ok BOOLEAN, n_blockers INTEGER, n_warnings INTEGER, acknowledged BOOLEAN, verdict_json VARCHAR,
            head_key VARCHAR, base_key VARCHAR, snapshot_id VARCHAR, engine VARCHAR, created_at VARCHAR
        )
        """
    )
    # the agent harness (agents/): events in, runs and their recorded tool steps (the evidence every
    # figure is bound to), operator threads, approvals of proposed actions, daily budgets, branch reviews
    for ddl in (
        "CREATE TABLE IF NOT EXISTS project_events (event_id VARCHAR PRIMARY KEY, project_id VARCHAR, type VARCHAR, dedup_id VARCHAR, "
        "payload_json VARCHAR, created_at VARCHAR, workflow_ids VARCHAR)",
        "CREATE TABLE IF NOT EXISTS project_state (project_id VARCHAR, key VARCHAR, value VARCHAR, updated_at VARCHAR, PRIMARY KEY (project_id, key))",
        "CREATE TABLE IF NOT EXISTS agent_runs (run_id VARCHAR PRIMARY KEY, project_id VARCHAR, kind VARCHAR, agent VARCHAR, workflow_id VARCHAR, "
        "branch_id VARCHAR, thread_id VARCHAR, event_id VARCHAR, parent_run_id VARCHAR, status VARCHAR, started_at VARCHAR, finished_at VARCHAR, "
        "model VARCHAR, input_tokens INTEGER, output_tokens INTEGER, cost_credits DOUBLE, solves INTEGER, summary VARCHAR, error VARCHAR)",
        "CREATE TABLE IF NOT EXISTS agent_steps (step_id VARCHAR PRIMARY KEY, run_id VARCHAR, seq INTEGER, tool VARCHAR, args_json VARCHAR, "
        "cache_key VARCHAR, result_json VARCHAR, solves INTEGER, started_at VARCHAR, finished_at VARCHAR, cost_credits DOUBLE, error VARCHAR)",
        "CREATE TABLE IF NOT EXISTS threads (thread_id VARCHAR PRIMARY KEY, project_id VARCHAR, branch_id VARCHAR, title VARCHAR, kind VARCHAR, "
        "created_at VARCHAR, updated_at VARCHAR)",
        "CREATE TABLE IF NOT EXISTS messages (message_id VARCHAR PRIMARY KEY, thread_id VARCHAR, seq INTEGER, role VARCHAR, content VARCHAR, "
        "status VARCHAR, workflow_id VARCHAR, run_id VARCHAR, tool_trace_json VARCHAR, model_json VARCHAR, usage_json VARCHAR, "
        "cost_credits DOUBLE, flags_json VARCHAR, evidence_json VARCHAR, created_at VARCHAR)",
        "CREATE TABLE IF NOT EXISTS approvals (approval_id VARCHAR PRIMARY KEY, project_id VARCHAR, thread_id VARCHAR, message_id VARCHAR, "
        "run_id VARCHAR, tool_call_id VARCHAR, tool VARCHAR, args_json VARCHAR, status VARCHAR, decided_at VARCHAR, decided_by VARCHAR, "
        "note VARCHAR, result_json VARCHAR, created_at VARCHAR)",
        "CREATE TABLE IF NOT EXISTS agent_budgets (project_id VARCHAR, day VARCHAR, credits DOUBLE, tokens INTEGER, solves INTEGER, "
        "paused BOOLEAN, paused_reason VARCHAR, updated_at VARCHAR, PRIMARY KEY (project_id, day))",
        "CREATE TABLE IF NOT EXISTS reviews (review_id VARCHAR PRIMARY KEY, project_id VARCHAR, branch_id VARCHAR, run_key VARCHAR, run_id VARCHAR, "
        "verdict VARCHAR, verdict_json VARCHAR, body VARCHAR, blockers_json VARCHAR, warnings_json VARCHAR, not_studied_json VARCHAR, "
        "status VARCHAR, created_at VARCHAR)",
    ):
        con.execute(ddl)
    _ensure_builtin_project(con)
    ensure_main_branch(con, NGED_MAIN_ID, NGED_PROJECT_ID)


def ensure_main_branch(con: Cursor, branch_id: str, project_id: str) -> None:
    """Seed a project's main branch (its plan of record) once, with the default demand pathway."""
    if con.execute("SELECT 1 FROM branches WHERE branch_id = ?", [branch_id]).fetchone():
        return
    con.execute(
        "INSERT INTO branches (branch_id, name, parent_id, scenario, growth_2030, growth_2035, "
        "w_readiness, w_need, w_strategic, status, created_at, project_id) "
        "VALUES (?, 'Main', NULL, ?, ?, ?, NULL, NULL, NULL, 'open', ?, ?)",
        [branch_id, DEFAULT_SCENARIO, GROWTH_2030, GROWTH_2035, now(), project_id],
    )


def _ensure_builtin_project(con: Cursor) -> None:
    """The built-in project (NGED, read from the pipeline's warehouse) is a row like any other, once."""
    if con.execute("SELECT 1 FROM projects WHERE project_id = ?", [NGED_PROJECT_ID]).fetchone():
        return
    con.execute(
        f"INSERT INTO projects ({', '.join(PROJECT_COLS)}) VALUES ({', '.join('?' * len(PROJECT_COLS))})",
        [NGED_PROJECT_ID, "NGED Bicker Fen 132 kV GSP", "nged", None, "warehouse", now(), None, None, None, NGED_MAIN_ID],
    )
