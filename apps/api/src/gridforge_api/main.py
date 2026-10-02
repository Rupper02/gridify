"""GridForge API.

Serves the validated canonical grid model (read-only, from the pipeline's DuckDB
warehouse) and runs the connection-queue optimizer. Projects added via the UI are
stored in a separate scenarios DB, so the pipeline baseline is never mutated.
"""

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse

from gridforge_optimizer import (
    Candidate,
    OptimizeParams,
    OptimizeResult,
    diff_results,
    optimize,
    suggest_unblock,
)
from gridforge_optimizer import llm as opt_llm
from gridforge_optimizer import engine_fingerprint
from gridforge_optimizer.nged import _commission_year, gsp_boundary
from gridforge_optimizer.config import (
    DEFAULT_SCENARIO,
    FORECASTS,
    GROWTH_2030,
    GROWTH_2035,
    HORIZONS,
    MAX_CONNECTION_MW,
    MAX_SUGGESTIONS,
)


def _now() -> str:
    """UTC timestamp as an ISO-8601 string (sorts chronologically; JSON-friendly)."""
    return datetime.now(timezone.utc).isoformat()

_REPO_ROOT = Path(__file__).resolve().parents[4]
WAREHOUSE = Path(
    os.getenv("GRIDFORGE_DB_PATH", str(_REPO_ROOT / "apps" / "pipeline" / "warehouse" / "gridforge.duckdb"))
)
SCENARIOS = Path(
    os.getenv("GRIDFORGE_SCENARIOS_DB", str(Path(__file__).resolve().parents[2] / "data" / "scenarios.duckdb"))
)

# reuse the pipeline's OPENROUTER_API_KEY for the LLM justification (dev)
load_dotenv(_REPO_ROOT / "apps" / "pipeline" / ".env")

log = logging.getLogger("gridforge_api")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Startup: open + migrate the scenarios DB once (so the planner's first, concurrent requests
    never race on DDL), then warm pandapower's numba JIT so the first /optimize isn't slow."""
    _init_scenarios_db()

    def _warm() -> None:
        try:
            from gridforge_optimizer.network import build_base_net, feasibility
            feasibility(build_base_net())
            if WAREHOUSE.exists():
                _optimize_payload(OptimizeRequest(with_justification=False), "main")
        except Exception:  # warming is best-effort; a broken network surfaces on the first real call
            log.exception("warm-up failed")

    _JOBS.submit(_warm)
    yield
    _JOBS.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="GridForge API", lifespan=_lifespan)


@app.middleware("http")
async def _json_errors(request: Request, call_next):
    """Turn an unhandled exception into a JSON 500. Registered BEFORE the CORS middleware so it sits
    inside it: the browser then sees CORS headers plus the reason, not an opaque CORS error."""
    try:
        return await call_next(request)
    except Exception as exc:  # the one place a blind except is right: it's the last line of defence
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


# dev: permissive CORS so the planner works from any local host. Lock down in prod.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# intake cap is shared with the optimizer (imported above) so the UI and engine agree.
# placeholder scores for a manually added project — it bypasses the registry's published-facts scoring.
MANUAL_READINESS_DEFAULT = 0.5
MANUAL_STRATEGIC_DEFAULT = 0.5
ADDED_CANDIDATE_ID_BASE = 2056  # user-added projects are numbered CR-2056, CR-2057, …
_optimize_cache: dict = {}
_compute_cache: dict = {}


# --- read-only baseline (pipeline warehouse) --------------------------------
def _warehouse_query(sql: str) -> list[dict]:
    """Run a read-only SQL query against the pipeline warehouse and return rows as dicts."""
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        cur = con.execute(sql)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        con.close()


def baseline_model() -> dict:
    """The geolocated grid (buses, lines, transformers, loads) for the map, from the warehouse."""
    buses = _warehouse_query("SELECT bus_id, name, vn_kv, lon, lat FROM buses WHERE lon IS NOT NULL")
    lines = _warehouse_query(
        """
        SELECT l.line_id, l.line_name, l.rating_a, l.voltage_kv,
               f.lon AS from_lon, f.lat AS from_lat, t.lon AS to_lon, t.lat AS to_lat
        FROM lines l
        JOIN buses f ON l.from_bus = f.bus_id
        JOIN buses t ON l.to_bus   = t.bus_id
        WHERE f.lon IS NOT NULL AND t.lon IS NOT NULL
        """
    )
    transformers = _warehouse_query(
        """
        SELECT tr.trafo_id, tr.name, tr.sn_mva, tr.hv_bus, tr.lv_bus,
               h.vn_kv AS hv_kv, lv.vn_kv AS lv_kv, h.name AS hv_name,
               h.lon AS hv_lon, h.lat AS hv_lat, lv.lon AS lv_lon, lv.lat AS lv_lat
        FROM transformers tr
        JOIN buses h  ON tr.hv_bus = h.bus_id
        JOIN buses lv ON tr.lv_bus = lv.bus_id
        WHERE h.lon IS NOT NULL AND lv.lon IS NOT NULL
        """
    )
    loads = _warehouse_query(
        """
        SELECT ld.bus_id, ld.p_mw, b.lon, b.lat
        FROM loads ld
        JOIN buses b ON ld.bus_id = b.bus_id
        WHERE b.lon IS NOT NULL
        """
    )
    for i, ld in enumerate(loads):
        ld["load_id"] = i
    try:
        generators = _warehouse_query(
            """
            SELECT g.request_id, g.bus_id, g.rating_mw, g.technology, g.applicant, b.lon, b.lat
            FROM generators g JOIN buses b ON g.bus_id = b.bus_id
            WHERE b.lon IS NOT NULL
            """
        )
    except Exception:  # warehouse predates the existing-fleet table
        generators = []
    return {"buses": buses, "lines": lines, "transformers": transformers, "loads": loads,
            "generators": generators}


def baseline_id() -> str:
    """The latest model snapshot's content-hash id (used to key the optimize cache)."""
    rows = _warehouse_query("SELECT snapshot_id FROM snapshots ORDER BY created_at DESC LIMIT 1")
    return rows[0]["snapshot_id"] if rows else "baseline"


def _table_exists(name: str) -> bool:
    return bool(_warehouse_query(f"SELECT 1 FROM information_schema.tables WHERE table_name = '{name}'"))


@app.get("/health")
def health() -> dict:
    """Liveness probe: reports whether the warehouse DB is present."""
    return {"ok": True, "warehouse_exists": WAREHOUSE.exists()}


@app.get("/model")
def get_model() -> dict:
    """Serve the geolocated grid model for the map."""
    return baseline_model()


_boundary_cache: dict = {}


@app.get("/boundary")
def boundary() -> dict:
    """The GSP boundary: the export limit to transmission, the region's export today, and the
    transmission-registered projects behind the GSP (not-yet-built ones at the GSP are optional
    registry projects, flagged with their registry id)."""
    if "v" not in _boundary_cache:
        _boundary_cache["v"] = gsp_boundary()
    return _boundary_cache["v"]


# --- versions: snapshot history + what changed between editions -----------------------------
@app.get("/snapshots")
def snapshots() -> dict:
    """The model's version history: one row per content-distinct materialisation of the warehouse
    (`network@<snapshot_id>`), newest first, with the LTDS edition each was built from."""
    rows = _warehouse_query(
        "SELECT snapshot_id, created_at, ltds_edition, buses, lines, transformers, loads, candidates "
        "FROM snapshots ORDER BY created_at DESC"
    ) if _table_exists("snapshots") else []
    return {"current": rows[0]["snapshot_id"] if rows else None, "snapshots": rows}


@app.get("/editions/changes")
def ltds_edition_changes() -> dict:
    """What changed between NGED's previous LTDS edition and the one the model is built from: the
    flagged rows (new / removed / updated circuits, transformers, demand points, busbars), the model
    delta and the physics delta. Computed by the pipeline (`ltds_edition_changes`)."""
    if not _table_exists("ltds_change_summary"):
        raise HTTPException(status_code=404, detail="no edition change-set in the warehouse: re-materialise the pipeline")
    head = _warehouse_query("SELECT * FROM ltds_change_summary ORDER BY computed_at DESC LIMIT 1")[0]
    rows = _warehouse_query(
        "SELECT \"table\", change, \"key\", description, value FROM ltds_changes WHERE ltds_edition = ? "
        .replace("?", f"'{head['ltds_edition']}'")
        + " ORDER BY \"table\", change, \"key\""
    )
    summary = json.loads(head["summary_json"])
    return {
        "ltds_edition": head["ltds_edition"], "computed_at": head["computed_at"],
        "n_changes": {"new": head["n_new"], "removed": head["n_removed"], "updated": head["n_updated"]},
        "status_counts": summary["status_counts"], "model": summary["model"], "physics": summary["physics"],
        "caveats": summary["caveats"], "rows": rows,
    }


@app.get("/registry/changes")
def registry_changes() -> dict:
    """What changed in NGED's Embedded Capacity Register between the last two fetched editions
    (sites added / withdrawn / connected / re-rated). Empty until the `ecr_refresh` job has run."""
    if not _table_exists("ecr_editions"):
        return {"editions": [], "changes": []}
    editions = _warehouse_query(
        "SELECT edition_id, fetched_at, source, source_last_modified, row_count, note FROM ecr_editions ORDER BY fetched_at DESC"
    )
    changes = _warehouse_query(
        "SELECT edition_id, prev_edition_id, computed_at, change, site, energy_source, status, export_mw, "
        "target_energisation_date, detail FROM ecr_changes ORDER BY computed_at DESC, change, site"
    ) if _table_exists("ecr_changes") else []
    latest = editions[0]["edition_id"] if editions else None
    return {"editions": editions, "changes": [c for c in changes if c["edition_id"] == latest]}


@app.get("/forecasts")
def get_forecasts() -> dict:
    """The FES 2025 demand pathways + policy horizons (single source of truth for the UI)."""
    forecasts = [
        {"id": fid, **{k: v for k, v in f.items()}} for fid, f in FORECASTS.items()
    ]
    return {"default": DEFAULT_SCENARIO, "forecasts": forecasts, "horizons": HORIZONS,
            "max_connection_mw": MAX_CONNECTION_MW}


# --- scenarios DB: branches + user-added projects (API read-write) ----------
# A "branch" is a named scenario (demand pathway + ranking weights) plus the projects added on it.
# `main` is the plan of record (today's network until something is merged). A branch's candidate set
# = its added_candidates (copied from its parent on create, plus what's pulled from the registry).
# The warehouse is never mutated.
_ADDED_COLS = (
    "request_id, applicant, bus_id, technology, rating_mw, readiness_score, "
    "strategic_fit, readiness_rationale, status, review_reasons, commissioning_year, scheduled_year, import_mw"
)
_BRANCH_COLS = [
    "branch_id", "name", "parent_id", "scenario", "growth_2030", "growth_2035",
    "w_readiness", "w_need", "w_strategic", "status", "created_at", "merged_at", "created_by",
]


_SCEN_LOCK = threading.RLock()
_SCEN_DB: duckdb.DuckDBPyConnection | None = None


def _init_scenarios_db() -> duckdb.DuckDBPyConnection:
    """Open the scenarios DB once per process and create/migrate its tables under a lock.

    The planner's boot fires several requests at once; with a brand-new DB, two threads each running
    CREATE TABLE IF NOT EXISTS made DuckDB raise a catalog write-write conflict (a 500 on first run).
    Doing the DDL exactly once, serialised, removes that race.
    """
    global _SCEN_DB
    with _SCEN_LOCK:
        if _SCEN_DB is not None:
            return _SCEN_DB
        SCENARIOS.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(SCENARIOS))
        _migrate_scenarios(con)
        _SCEN_DB = con
        return con


@contextmanager
def _scenarios():
    """Serialised access to the scenarios DB: a cursor on the shared connection, under the lock.
    DuckDB cursors are the thread-safe way to share one connection; the lock keeps writers from
    conflicting with each other (these operations take milliseconds, so contention is moot)."""
    con = _init_scenarios_db()
    with _SCEN_LOCK:
        cur = con.cursor()
        try:
            yield cur
        finally:
            cur.close()


def _use_scenarios_db(path: Path) -> None:
    """Test hook: point the API at another scenarios DB file (closing the current connection)."""
    global _SCEN_DB, SCENARIOS
    with _SCEN_LOCK:
        if _SCEN_DB is not None:
            _SCEN_DB.close()
        _SCEN_DB = None
        SCENARIOS = path
    _optimize_cache.clear()
    _compute_cache.clear()


def _migrate_scenarios(con: duckdb.DuckDBPyConnection) -> None:
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
    cols = [r[1] for r in con.execute("PRAGMA table_info('added_candidates')").fetchall()]
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


def _ensure_main_branch(con: duckdb.DuckDBPyConnection) -> None:
    """Seed the 'main' branch (the plan of record) once, with the default demand pathway."""
    if con.execute("SELECT 1 FROM branches WHERE branch_id = 'main'").fetchone():
        return
    con.execute(
        "INSERT INTO branches (branch_id, name, parent_id, scenario, growth_2030, growth_2035, "
        "w_readiness, w_need, w_strategic, status, created_at) "
        "VALUES ('main', 'Main', NULL, ?, ?, ?, NULL, NULL, NULL, 'open', ?)",
        [DEFAULT_SCENARIO, GROWTH_2030, GROWTH_2035, _now()],
    )


def _branch_row(con: duckdb.DuckDBPyConnection, branch_id: str) -> dict | None:
    """One branch as a dict keyed by _BRANCH_COLS, or None if it doesn't exist."""
    r = con.execute(
        f"SELECT {', '.join(_BRANCH_COLS)} FROM branches WHERE branch_id = ?", [branch_id]
    ).fetchone()
    return dict(zip(_BRANCH_COLS, r)) if r else None


def _registry_rows() -> list[dict]:
    """The REGISTRY: the pool of projected connection projects (warehouse), available to add to a
    branch. main does not auto-include these — you pull them onto a branch as they come along."""
    return _warehouse_query("SELECT * FROM candidate_projects")


def _candidate_rows(branch_id: str = "main") -> list[dict]:
    """Projects IN a branch's plan = the ones added to it. 'main' has none until something is merged
    into it — it is the as-is plan of record; projects are pulled onto branches from the registry."""
    with _scenarios() as con:
        cur = con.execute("SELECT * FROM added_candidates WHERE branch_id = ?", [branch_id])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _to_client(r: dict) -> dict:
    """Shape a candidate for the UI: valid/rejected status, non-null applicant."""
    return {
        **r,
        "applicant": r.get("applicant") or "",
        "status": "valid" if r.get("status") == "auto_accept" else "rejected",
    }


def _bus_coords() -> dict[int, tuple[float, float]]:
    """Map every geolocated bus id to its (lon, lat), for attaching coords to queue items."""
    return {
        int(b["bus_id"]): (b["lon"], b["lat"])
        for b in _warehouse_query("SELECT bus_id, lon, lat FROM buses WHERE lon IS NOT NULL")
    }


@app.get("/optimize/candidates")
def optimize_candidates() -> list[dict]:
    """The registry pool (projected projects available to add to a branch), shaped for the client."""
    return [_to_client(r) for r in _registry_rows()]


@app.get("/registry")
def registry() -> list[dict]:
    """The registry of projected connection projects — the pool branches pull from."""
    return [_to_client(r) for r in _registry_rows()]


class NewCandidate(BaseModel):
    """Request body for adding a project via the UI (scored with neutral placeholders)."""

    applicant: str | None = None
    bus_id: int | None = None
    technology: str | None = None
    rating_mw: float | None = None
    readiness_score: float = MANUAL_READINESS_DEFAULT
    strategic_fit: float = MANUAL_STRATEGIC_DEFAULT
    readiness_rationale: str = ""
    commissioning_year: int | None = None  # requested energisation year; derived if omitted
    import_mw: float | None = None  # charging capacity (batteries); defaults to the rating
    branch_id: str = "main"  # which branch to add the project to


def _valid_bus_ids() -> set[int]:
    return {int(b["bus_id"]) for b in _warehouse_query("SELECT bus_id FROM buses")}


def _triage(body: NewCandidate, valid_bus_ids: set[int]) -> tuple[str, str]:
    """Intake triage for a manually added project -> (status, review_reasons)."""
    reasons = []
    if body.bus_id is None:
        reasons.append("missing a bus")
    elif int(body.bus_id) not in valid_bus_ids:
        reasons.append("bus is not in model")
    if body.rating_mw is None:
        reasons.append("missing rating")
    elif not (0 < body.rating_mw <= MAX_CONNECTION_MW):
        reasons.append("rating is out of range")
    if not body.technology:
        reasons.append("missing technology")
    return ("auto_accept" if not reasons else "needs_review"), ", ".join(reasons)


def _insert_candidate(con: duckdb.DuckDBPyConnection, branch_id: str, body: NewCandidate,
                      valid_bus_ids: set[int]) -> dict:
    """Validate + insert a project on a branch; returns the stored row (client fields)."""
    status, review = _triage(body, valid_bus_ids)
    n = con.execute("SELECT count(*) FROM added_candidates").fetchone()[0]
    request_id = f"CR-{ADDED_CANDIDATE_ID_BASE + n}"
    year = body.commissioning_year or _commission_year(
        body.readiness_score, body.technology, body.rating_mw, request_id)
    con.execute(
        f"INSERT INTO added_candidates ({_ADDED_COLS}, branch_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [request_id, body.applicant, body.bus_id, body.technology, body.rating_mw,
         body.readiness_score, body.strategic_fit, body.readiness_rationale, status, review,
         year, None, body.import_mw, branch_id],
    )
    return {
        "request_id": request_id, "applicant": body.applicant, "bus_id": body.bus_id,
        "technology": body.technology, "rating_mw": body.rating_mw,
        "readiness_score": body.readiness_score, "strategic_fit": body.strategic_fit,
        "readiness_rationale": body.readiness_rationale, "status": status,
        "review_reasons": review, "commissioning_year": year, "import_mw": body.import_mw, "branch_id": branch_id,
    }


@app.post("/optimize/candidates")
def add_candidate(body: NewCandidate) -> dict:
    """Add a project to a branch (stored in the API scenarios DB; warehouse untouched)."""
    with _scenarios() as con:
        row = _insert_candidate(con, body.branch_id, body, _valid_bus_ids())
    _optimize_cache.clear()  # candidate set changed
    _compute_cache.clear()
    return _to_client(row)


# --- optimizer ---------------------------------------------------------------
def _summarize(result) -> str:
    """Render the ordered queue as plain text for the LLM narration prompt."""
    rows = []
    for q in result.queue:
        reason = f" — {q.reason.message}" if q.reason else ""
        rows.append(
            f"#{q.rank or '-'} {q.request_id}: {q.status}; {q.technology} {q.rating_mw} MW at bus "
            f"{q.bus_id}; readiness={q.readiness_score}, grid_need={q.grid_need}{reason}"
        )
    return "Connection queue (ordered):\n" + "\n".join(rows)


class OptimizeRequest(BaseModel):
    """Request body for a /optimize run: DFES scenario (or custom growth) + optional weight overrides."""

    # a DFES pathway id drives per-bus growth; growth_2030/2035 are the "Custom (manual)" override
    scenario: str | None = DEFAULT_SCENARIO
    growth_2030: float = GROWTH_2030
    growth_2035: float = GROWTH_2035
    w_readiness: float | None = None
    w_need: float | None = None
    w_strategic: float | None = None
    with_justification: bool = True


class BranchOptimizeRequest(BaseModel):
    """Request body for running a branch (its scenario is the branch's own)."""

    with_justification: bool = False


def _resolve_params(body: OptimizeRequest) -> OptimizeParams:
    """Resolve a request to concrete OptimizeParams (named DFES pathway -> feeder multipliers)."""
    if body.scenario in FORECASTS:
        scenario = body.scenario
        growth_2030 = FORECASTS[scenario]["growth_2030"]
        growth_2035 = FORECASTS[scenario]["growth_2035"]
    else:
        scenario = "custom"
        growth_2030, growth_2035 = body.growth_2030, body.growth_2035
    weights = {
        k: v for k, v in {
            "w_readiness": body.w_readiness, "w_need": body.w_need, "w_strategic": body.w_strategic,
        }.items() if v is not None
    }
    return OptimizeParams(
        growth_2030=growth_2030, growth_2035=growth_2035, scenario=scenario, **weights
    )


def _candidates(branch_id: str = "main") -> list[Candidate]:
    """Build the optimizer's candidate list for a branch (warehouse + the branch's added projects)."""
    return [
        Candidate(
            request_id=r["request_id"],
            bus_id=None if r["bus_id"] is None else int(r["bus_id"]),
            technology=r["technology"],
            rating_mw=None if r["rating_mw"] is None else float(r["rating_mw"]),
            readiness_score=float(r["readiness_score"]),
            strategic_fit=float(r["strategic_fit"]),
            readiness_rationale=r.get("readiness_rationale") or "",
            status=r["status"],
            review_reasons=r.get("review_reasons") or "",
            commissioning_year=(None if r.get("commissioning_year") is None else int(r["commissioning_year"])),
            import_mw=(None if r.get("import_mw") is None else float(r["import_mw"])),
        )
        for r in _candidate_rows(branch_id)
    ]



_ENGINE = engine_fingerprint()  # hash of the engine's source: a code change invalidates every cached result
_JOBS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gridforge-job")  # pandapower is CPU-bound: one at a time
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
# per (parameters, snapshot, engine): the engine's exact trial cache, so a branch that gains one
# project re-solves only the trials whose state changed (see greedy.optimize)
_TRIAL_CACHES: dict[tuple, dict] = {}


def _cand_key(cands: list[Candidate]) -> str:
    """A stable hash of a candidate set, so the compute cache never serves one branch's result for
    another branch with different projects (the highest-risk bug of branch-scoping)."""
    sig = sorted(
        (c.request_id, c.bus_id, c.rating_mw, round(c.readiness_score, 4),
         round(c.strategic_fit, 4), c.status, c.import_mw)
        for c in cands
    )
    return hashlib.md5(json.dumps(sig, default=str).encode()).hexdigest()


def _params_key(params: OptimizeParams) -> tuple:
    return (params.scenario, round(params.growth_2030, 3), round(params.growth_2035, 3),
            params.w_readiness, params.w_need, params.w_strategic)


def _cache_key(kind: str, params: OptimizeParams, cand_key: str, extra: str = "") -> str:
    sig = json.dumps([kind, _params_key(params), cand_key, baseline_id(), _ENGINE, extra], default=str)
    return hashlib.sha256(sig.encode()).hexdigest()[:32]


def _cache_get(key: str) -> str | None:
    with _scenarios() as con:
        row = con.execute("SELECT result_json FROM result_cache WHERE cache_key = ?", [key]).fetchone()
    return row[0] if row else None


def _cache_put(key: str, kind: str, compute_ms: int, result_json: str) -> None:
    with _scenarios() as con:
        con.execute(
            "INSERT OR REPLACE INTO result_cache VALUES (?, ?, ?, ?, ?, ?, ?)",
            [key, kind, baseline_id(), _ENGINE, _now(), compute_ms, result_json],
        )


def _compute(body: OptimizeRequest, cands: list[Candidate], cand_key: str,
             progress=None) -> OptimizeResult:
    """Run the deterministic optimizer for a request + candidate set.

    Three layers: the in-process dict, the durable `result_cache` table (survives restarts and is
    shared by every endpoint that needs the same run), then the engine. Keys include the model
    snapshot, the parameters, the candidate set and the engine's code fingerprint."""
    params = _resolve_params(body)
    key = _cache_key("optimize", params, cand_key)
    if key in _compute_cache:
        return _compute_cache[key]
    cached = _cache_get(key)
    if cached is not None:
        _compute_cache[key] = OptimizeResult.model_validate_json(cached)
        return _compute_cache[key]
    trial_cache = _TRIAL_CACHES.setdefault((_params_key(params), baseline_id(), _ENGINE), {})
    if len(trial_cache) > 50_000:  # bounded: a cold start costs one full run, nothing else
        trial_cache.clear()
    t0 = time.perf_counter()
    result = optimize(cands, params, trial_cache=trial_cache, progress=progress)
    _cache_put(key, "optimize", int((time.perf_counter() - t0) * 1000), result.model_dump_json())
    _compute_cache[key] = result
    return result


def _suggestions_for(req: OptimizeRequest, cands: list[Candidate], cand_key: str, limit: int) -> list:
    """`suggest_unblock` for a branch, through the same two cache layers (it costs dozens of solves)."""
    params = _resolve_params(req)
    base = _compute(req, cands, cand_key)
    key = _cache_key("suggest", params, cand_key, extra=str(limit))
    if key in _compute_cache:
        return _compute_cache[key]
    cached = _cache_get(key)
    if cached is not None:
        from gridforge_optimizer import Suggestion
        _compute_cache[key] = [Suggestion.model_validate(x) for x in json.loads(cached)]
        return _compute_cache[key]
    t0 = time.perf_counter()
    sugs = suggest_unblock(cands, params, base=base, max_suggestions=limit)
    _cache_put(key, "suggest", int((time.perf_counter() - t0) * 1000), json.dumps([x.model_dump() for x in sugs]))
    _compute_cache[key] = sugs
    return sugs


def _optimize_payload(body: OptimizeRequest, branch_id: str = "main", progress=None) -> dict:
    """Run the optimizer for a branch and enrich the result for the map (coords, generators).

    Resolves the DFES scenario to growth, runs the deterministic engine (cached by inputs AND the
    branch's candidate set), then attaches map coordinates + applicant and, optionally, a narrative.
    """
    cands = _candidates(branch_id)
    ckey = _cand_key(cands)
    params = _resolve_params(body)
    key = (_params_key(params), body.with_justification, ckey, baseline_id(), _ENGINE)
    if key in _optimize_cache:
        return _optimize_cache[key]

    result = _compute(body, cands, ckey, progress=progress)
    out = result.model_dump()

    coords = _bus_coords()
    rows_by_id = {r["request_id"]: r for r in _candidate_rows(branch_id)}
    for q in out["queue"]:
        bid = q["bus_id"]
        q["lon"], q["lat"] = coords.get(int(bid), (None, None)) if bid is not None else (None, None)
        row = rows_by_id.get(q["request_id"], {})
        q["applicant"] = row.get("applicant") or ""
        # the operator's chosen energisation year (persisted on the branch) vs the optimizer's
        # recommendation: earlier than recommended, or scheduling a project the grid can't host,
        # goes against the recommendation and is flagged.
        sy = row.get("scheduled_year")
        q["scheduled_year"] = None if sy is None else int(sy)
        rec = q.get("recommended_year")
        q["against_recommendation"] = q["scheduled_year"] is not None and (
            rec is None or q["scheduled_year"] < rec)

    for phase in out["phases"].values():
        gens = []
        for rid in phase["accepted"]:
            qi = next((q for q in out["queue"] if q["request_id"] == rid), None)
            if qi and qi.get("lon") is not None:
                gens.append({
                    "request_id": rid, "bus_id": qi["bus_id"], "lon": qi["lon"], "lat": qi["lat"],
                    "rating_mw": qi["rating_mw"], "technology": qi["technology"],
                })
        phase["generators"] = gens

    out["snapshot_id"] = baseline_id()
    out["branch_id"] = branch_id
    out["justification"] = ""
    if body.with_justification:
        if progress:
            progress("narration", 0.95)
        try:
            out["justification"] = opt_llm.justify(_summarize(result))
        except Exception:
            out["justification"] = ""

    _optimize_cache[key] = out
    return out


@app.post("/optimize")
def run_optimize(body: OptimizeRequest) -> dict:
    """Run the optimizer on the main plan and return the enriched queue + per-phase results."""
    return _optimize_payload(body, "main")


# --- jobs: long runs in the background, with real progress -------------------
def _start_job(kind: str, fn) -> dict:
    """Queue `fn(progress)` on the single engine worker and return the job record."""
    job_id = "job-" + uuid.uuid4().hex[:10]
    rec = {"job_id": job_id, "kind": kind, "status": "queued", "stage": "queued", "fraction": 0.0,
           "created_at": _now(), "started_at": None, "finished_at": None, "elapsed_ms": 0, "result": None, "error": None}
    with _jobs_lock:
        _jobs[job_id] = rec
        if len(_jobs) > 200:  # keep the registry bounded; finished jobs fall off oldest-first
            for old in sorted(_jobs, key=lambda k: _jobs[k]["created_at"])[:50]:
                if _jobs[old]["status"] in ("done", "failed"):
                    _jobs.pop(old, None)

    def progress(stage: str, fraction: float) -> None:
        with _jobs_lock:
            rec["stage"], rec["fraction"] = stage, round(float(fraction), 3)

    def run() -> None:
        t0 = time.perf_counter()
        with _jobs_lock:
            rec["status"], rec["started_at"], rec["stage"] = "running", _now(), "starting"
        try:
            out = fn(progress)
            with _jobs_lock:
                rec.update(status="done", stage="done", fraction=1.0, result=out)
        except Exception as exc:  # the job records its own failure; nothing escapes the worker
            log.exception("job %s failed", job_id)
            with _jobs_lock:
                rec.update(status="failed", stage="failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            with _jobs_lock:
                rec["finished_at"] = _now()
                rec["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)

    _JOBS.submit(run)
    return _job_view(rec)


def _job_view(rec: dict, with_result: bool = False) -> dict:
    out = {k: v for k, v in rec.items() if k != "result"}
    if with_result:
        out["result"] = rec["result"]
    return out


@app.post("/branches/{branch_id}/optimize/jobs")
def start_optimize_job(branch_id: str, body: BranchOptimizeRequest | None = None) -> dict:
    """Start a run of this branch in the background. Poll GET /jobs/{job_id}; a cached run finishes
    at once. The response is the job record (status, stage, fraction)."""
    with _scenarios() as con:
        row = _require_branch(con, branch_id)
    req = OptimizeRequest(with_justification=bool(body and body.with_justification), **_branch_params(row))
    return _start_job("optimize", lambda progress: _optimize_payload(req, branch_id, progress=progress))


@app.get("/jobs/{job_id}")
def get_job(job_id: str, with_result: bool = True) -> dict:
    """A background job's status, stage and (when done) its result."""
    with _jobs_lock:
        rec = _jobs.get(job_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")
        return _job_view(rec, with_result=with_result)


@app.get("/cache")
def cache_stats() -> dict:
    """What the durable result cache holds: runs and suggestion sets per kind, with the engine
    fingerprint they were computed under (a code change retires them)."""
    with _scenarios() as con:
        rows = con.execute(
            "SELECT kind, engine, count(*) AS n, sum(compute_ms) AS compute_ms FROM result_cache GROUP BY kind, engine ORDER BY kind, engine"
        ).fetchall()
    return {"engine": _ENGINE, "entries": [dict(zip(("kind", "engine", "n", "compute_ms_saved"), r)) for r in rows]}


# --- consequence diff --------------------------------------------------------
def _summarize_diff(d) -> str:
    """Render a consequence diff as plain text for the narration prompt (restates figures only)."""
    h = d.headline
    lines = [
        f"Baseline: {d.base_label}",
        f"Proposed: {d.head_label}",
        f"MW connected by 2030: {h['mw_2030_base']} -> {h['mw_2030_head']} ({h['mw_2030_delta']:+})",
        f"MW connected by 2035: {h['mw_2035_base']} -> {h['mw_2035_head']} ({h['mw_2035_delta']:+})",
        f"Projects: {h['n_accelerated']} accelerated, {h['n_slipped']} slipped, "
        f"{h['n_added']} added, {h['n_dropped']} dropped",
    ]
    for p in [p for p in d.projects if p.change != "unchanged"][:5]:
        lines.append(
            f"- {p.request_id} ({p.technology} {p.rating_mw} MW): "
            f"{p.base_status} -> {p.head_status} [{p.change}]"
        )
    for ph in d.phases:
        if ph.newly_overloaded_line_ids or ph.cleared_line_ids:
            lines.append(
                f"Phase {ph.phase}: newly overloaded {ph.newly_overloaded_line_ids}, "
                f"cleared {ph.cleared_line_ids}"
            )
    return "\n".join(lines)


# --- branches ("git for grids") -----------------------------------------------
def _pick(val, fallback):
    """Use `val` unless it is None, else fall back to the parent/branch value."""
    return fallback if val is None else val


def _branch_params(row: dict) -> dict:
    """The scenario fields of a branch row (OptimizeRequest-shaped)."""
    return {
        "scenario": row["scenario"],
        "growth_2030": row["growth_2030"],
        "growth_2035": row["growth_2035"],
        "w_readiness": row["w_readiness"],
        "w_need": row["w_need"],
        "w_strategic": row["w_strategic"],
    }


def _branch_request(row: dict) -> OptimizeRequest:
    """Resolve a branch row to an OptimizeRequest (scenario + growth + weights)."""
    return OptimizeRequest(with_justification=False, **_branch_params(row))


def _branch_to_client(con: duckdb.DuckDBPyConnection, row: dict) -> dict:
    """A branch shaped for the UI (params + added count + status + timestamps)."""
    n_added = con.execute(
        "SELECT count(*) FROM added_candidates WHERE branch_id = ?", [row["branch_id"]]
    ).fetchone()[0]
    return {
        "branch_id": row["branch_id"], "name": row["name"], "parent_id": row["parent_id"],
        **_branch_params(row),
        "status": row["status"], "created_at": row["created_at"], "merged_at": row["merged_at"],
        "n_added": int(n_added),
    }


def _require_branch(con: duckdb.DuckDBPyConnection, branch_id: str) -> dict:
    row = _branch_row(con, branch_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"branch '{branch_id}' not found")
    return row


class BranchCreate(BaseModel):
    """Open a branch off `from_branch` (default main): a scenario + optional projects to add."""

    name: str
    from_branch: str = "main"
    scenario: str | None = None
    growth_2030: float | None = None
    growth_2035: float | None = None
    w_readiness: float | None = None
    w_need: float | None = None
    w_strategic: float | None = None
    added_projects: list[NewCandidate] = []


class MergeRequest(BaseModel):
    into: str = "main"


@app.post("/branches")
def create_branch(body: BranchCreate) -> dict:
    """Create a branch (copy-on-create): snapshot the parent's projects, then apply the change."""
    with _scenarios() as con:
        parent = _require_branch(con, body.from_branch)
        bid = "br-" + uuid.uuid4().hex[:8]
        con.execute(
            "INSERT INTO branches (branch_id, name, parent_id, scenario, growth_2030, growth_2035, "
            "w_readiness, w_need, w_strategic, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)",
            [bid, body.name, parent["branch_id"],
             _pick(body.scenario, parent["scenario"]), _pick(body.growth_2030, parent["growth_2030"]),
             _pick(body.growth_2035, parent["growth_2035"]), _pick(body.w_readiness, parent["w_readiness"]),
             _pick(body.w_need, parent["w_need"]), _pick(body.w_strategic, parent["w_strategic"]), _now()],
        )
        # copy-on-create: snapshot the parent's projects onto the new branch
        con.execute(
            f"INSERT INTO added_candidates ({_ADDED_COLS}, branch_id) "
            f"SELECT {_ADDED_COLS}, ? FROM added_candidates WHERE branch_id = ?",
            [bid, parent["branch_id"]],
        )
        valid = _valid_bus_ids()
        for p in body.added_projects:
            _insert_candidate(con, bid, p, valid)
        out = _branch_to_client(con, _branch_row(con, bid))
    return out


@app.get("/branches")
def list_branches() -> dict:
    """All branches, main first then newest-created."""
    with _scenarios() as con:
        ids = [r[0] for r in con.execute(
            "SELECT branch_id FROM branches ORDER BY (branch_id = 'main') DESC, created_at"
        ).fetchall()]
        branches = [_branch_to_client(con, _branch_row(con, i)) for i in ids]
    return {"branches": branches}


@app.post("/branches/{branch_id}/optimize")
def optimize_branch(branch_id: str, body: BranchOptimizeRequest | None = None) -> dict:
    """Run the optimizer on a branch's scenario + candidate set."""
    with _scenarios() as con:
        row = _require_branch(con, branch_id)
    req = _branch_request(row)
    req.with_justification = bool(body and body.with_justification)
    return _optimize_payload(req, branch_id)


class RegistryAdd(BaseModel):
    request_id: str


@app.post("/branches/{branch_id}/registry")
def add_from_registry(branch_id: str, body: RegistryAdd) -> dict:
    """Pull a projected project from the registry onto a branch (copies it into the branch's plan)."""
    row = {r["request_id"]: r for r in _registry_rows()}.get(body.request_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"registry project '{body.request_id}' not found")
    with _scenarios() as con:
        _require_branch(con, branch_id)
        exists = con.execute(
            "SELECT 1 FROM added_candidates WHERE branch_id = ? AND request_id = ?",
            [branch_id, body.request_id],
        ).fetchone()
        if not exists:
            con.execute(
                f"INSERT INTO added_candidates ({_ADDED_COLS}, branch_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [row["request_id"], row.get("applicant"), row.get("bus_id"), row.get("technology"),
                 row.get("rating_mw"), row.get("readiness_score"), row.get("strategic_fit"),
                 row.get("readiness_rationale"), row.get("status"), row.get("review_reasons"),
                 row.get("commissioning_year"), None, row.get("import_mw"), branch_id],
            )
    _optimize_cache.clear()
    _compute_cache.clear()
    return _to_client({**row, "branch_id": branch_id})


class ScheduleSet(BaseModel):
    """The operator's chosen energisation year for a project on a branch (None = follow the
    optimizer's recommendation)."""

    request_id: str
    year: int | None = None


@app.post("/branches/{branch_id}/schedule")
def set_schedule(branch_id: str, body: ScheduleSet) -> dict:
    """Persist the operator's energisation year for one project on a branch. It's a planning
    decision layered on the optimizer's verdict — it doesn't change accept/defer/rank — so the
    next /optimize just reports it alongside the recommendation (and flags any conflict)."""
    if body.year is not None and not (2026 <= body.year <= 2035):
        raise HTTPException(status_code=422, detail="year must be between 2026 and 2035")
    with _scenarios() as con:
        _require_branch(con, branch_id)
        hit = con.execute(
            "SELECT 1 FROM added_candidates WHERE branch_id = ? AND request_id = ?",
            [branch_id, body.request_id],
        ).fetchone()
        if not hit:
            raise HTTPException(
                status_code=404,
                detail=f"project '{body.request_id}' is not on branch '{branch_id}'",
            )
        con.execute(
            "UPDATE added_candidates SET scheduled_year = ? WHERE branch_id = ? AND request_id = ?",
            [body.year, branch_id, body.request_id],
        )
    _optimize_cache.clear()  # the payload carries scheduled_year; the engine result is unaffected
    return {"branch_id": branch_id, "request_id": body.request_id, "scheduled_year": body.year}


@app.get("/branches/{branch_id}/diff")
def diff_branch(branch_id: str, with_narration: bool = False) -> dict:
    """Consequence diff of a branch (head) vs its parent (base, default main)."""
    with _scenarios() as con:
        head_row = _require_branch(con, branch_id)
        base_row = _branch_row(con, head_row["parent_id"] or "main") or _branch_row(con, "main")
    head_cands = _candidates(branch_id)
    base_cands = _candidates(base_row["branch_id"])
    head = _compute(_branch_request(head_row), head_cands, _cand_key(head_cands))
    base = _compute(_branch_request(base_row), base_cands, _cand_key(base_cands))
    d = diff_results(base, head)
    out = d.model_dump()
    out["base_branch"] = base_row["branch_id"]
    out["head_branch"] = branch_id
    out["narration"] = ""
    if with_narration:
        try:
            out["narration"] = opt_llm.narrate_diff(_summarize_diff(d))
        except Exception:
            out["narration"] = ""
    return out


@app.post("/branches/{branch_id}/merge")
def merge_branch(branch_id: str, body: MergeRequest | None = None) -> dict:
    """Squash-merge a branch into `into` (default main): it adopts the branch's scenario + projects."""
    into = (body.into if body else "main") or "main"
    if branch_id == into:
        raise HTTPException(status_code=400, detail="cannot merge a branch into itself")
    with _scenarios() as con:
        b = _require_branch(con, branch_id)
        _require_branch(con, into)
        if b["status"] != "open":
            raise HTTPException(status_code=409, detail=f"branch is '{b['status']}', not open")
        con.execute(
            "UPDATE branches SET scenario=?, growth_2030=?, growth_2035=?, "
            "w_readiness=?, w_need=?, w_strategic=? WHERE branch_id=?",
            [b["scenario"], b["growth_2030"], b["growth_2035"],
             b["w_readiness"], b["w_need"], b["w_strategic"], into],
        )
        con.execute("DELETE FROM added_candidates WHERE branch_id = ?", [into])
        con.execute(
            f"INSERT INTO added_candidates ({_ADDED_COLS}, branch_id) "
            f"SELECT {_ADDED_COLS}, ? FROM added_candidates WHERE branch_id = ?",
            [into, branch_id],
        )
        con.execute("UPDATE branches SET status='merged', merged_at=? WHERE branch_id=?", [_now(), branch_id])
        out = _branch_to_client(con, _branch_row(con, into))
    _optimize_cache.clear()
    _compute_cache.clear()
    return out


@app.post("/branches/{branch_id}/discard")
def discard_branch(branch_id: str) -> dict:
    """Soft-discard a branch (kept for audit; main cannot be discarded)."""
    if branch_id == "main":
        raise HTTPException(status_code=400, detail="cannot discard main")
    with _scenarios() as con:
        _require_branch(con, branch_id)
        con.execute("UPDATE branches SET status='discarded' WHERE branch_id=?", [branch_id])
        out = _branch_to_client(con, _branch_row(con, branch_id))
    return out


def _summarize_suggestion(s, base) -> str:
    """Plain-text summary of a deterministic suggestion for the narration prompt (figures only)."""
    rating = {q.request_id: q.rating_mw for q in base.queue}
    connects = ", ".join(
        f"{rid} ({rating.get(rid, '?')} MW)" for rid in s.newly_connected_project_ids
    ) or "no additional projects"
    return (
        f"Deferred project(s): {', '.join(s.blocked_project_ids)}.\n"
        f"Binding constraint: {s.target_type} {s.target_element_id}.\n"
        f"Action: {s.action}.\n"
        f"Connects the blocked project: "
        f"{'yes' if s.connects_target else 'no — further reinforcement needed'}.\n"
        f"Frees ~{s.freed_mw_2030} MW by 2030 and ~{s.freed_mw_2035} MW by 2035.\n"
        f"Projects that connect under it: {connects}."
    )


@app.get("/branches/{branch_id}/suggestions")
def branch_suggestions(branch_id: str, limit: int = MAX_SUGGESTIONS, with_narration: bool = False) -> dict:
    """The copilot: concrete, quantified unblocks for the projects this branch defers on the grid."""
    with _scenarios() as con:
        row = _require_branch(con, branch_id)
    cands = _candidates(branch_id)
    ckey = _cand_key(cands)
    req = _branch_request(row)
    base = _compute(req, cands, ckey)
    sugs = _suggestions_for(req, cands, ckey, limit)
    out = []
    for s in sugs:
        d = s.model_dump()
        d["narration"] = ""
        if with_narration:
            try:
                d["narration"] = opt_llm.narrate_suggestion(_summarize_suggestion(s, base))
            except Exception:
                d["narration"] = ""
        out.append(d)
    return {"branch_id": branch_id, "suggestions": out}
