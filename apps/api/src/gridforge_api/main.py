"""GridForge API.

Serves the validated canonical grid model (read-only, from the pipeline's DuckDB
warehouse) and runs the connection-queue optimizer. Projects added via the UI are
stored in a separate scenarios DB, so the pipeline baseline is never mutated.
"""

import hashlib
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from gridforge_optimizer import (
    Candidate,
    OptimizeParams,
    OptimizeResult,
    diff_results,
    optimize,
    suggest_unblock,
)
from gridforge_optimizer import llm as opt_llm
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

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Warm pandapower's numba JIT at startup so the first /optimize isn't slow."""
    try:
        from gridforge_optimizer.network import build_base_net, feasibility
        feasibility(build_base_net())
    except Exception:
        pass
    yield


app = FastAPI(title="GridForge API", lifespan=_lifespan)
# dev: permissive CORS so the planner works from any local host. Lock down in prod.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# intake cap is shared with the optimizer (imported above) so the UI and engine agree.
# placeholder scores for a manually added project — it bypasses the pipeline's rubric + Jev scoring.
MANUAL_READINESS_DEFAULT = 0.5
MANUAL_STRATEGIC_DEFAULT = 0.5
ADDED_CANDIDATE_ID_BASE = 2056  # user-added projects are numbered CR-2056, CR-2057, …
_optimize_cache: dict = {}


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
        SELECT tr.trafo_id, tr.name, tr.sn_mva,
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
    return {"buses": buses, "lines": lines, "transformers": transformers, "loads": loads}


def baseline_id() -> str:
    """The latest model snapshot's content-hash id (used to key the optimize cache)."""
    rows = _warehouse_query("SELECT snapshot_id FROM snapshots ORDER BY created_at DESC LIMIT 1")
    return rows[0]["snapshot_id"] if rows else "baseline"


@app.get("/health")
def health() -> dict:
    """Liveness probe: reports whether the warehouse DB is present."""
    return {"ok": True, "warehouse_exists": WAREHOUSE.exists()}


@app.get("/model")
def get_model() -> dict:
    """Serve the geolocated grid model for the map."""
    return baseline_model()


@app.get("/forecasts")
def get_forecasts() -> dict:
    """The FES 2025 demand pathways + policy horizons (single source of truth for the UI)."""
    forecasts = [
        {"id": fid, **{k: v for k, v in f.items()}} for fid, f in FORECASTS.items()
    ]
    return {"default": DEFAULT_SCENARIO, "forecasts": forecasts, "horizons": HORIZONS}


# --- scenarios DB: branches + user-added projects (API read-write) ----------
# A "branch" is a named scenario (demand pathway + ranking weights) plus the projects added on it.
# `main` is the plan of record. A branch's candidate set = warehouse candidate_projects (immutable)
# ∪ its added_candidates − its withdrawals. The warehouse is never mutated.
_ADDED_COLS = (
    "request_id, applicant, bus_id, technology, rating_mw, readiness_score, "
    "strategic_fit, readiness_rationale, status, review_reasons"
)
_BRANCH_COLS = [
    "branch_id", "name", "parent_id", "scenario", "growth_2030", "growth_2035",
    "w_readiness", "w_need", "w_strategic", "status", "created_at", "merged_at", "created_by",
]


def _scenarios_con() -> duckdb.DuckDBPyConnection:
    """Open the scenarios DB, creating/migrating its tables and seeding the 'main' branch."""
    SCENARIOS.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(SCENARIOS))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS added_candidates (
            request_id VARCHAR, applicant VARCHAR, bus_id INTEGER, technology VARCHAR,
            rating_mw DOUBLE, readiness_score DOUBLE, strategic_fit DOUBLE,
            readiness_rationale VARCHAR, status VARCHAR, review_reasons VARCHAR
        )
        """
    )
    # migrate the pre-branch schema: existing global rows become main's (idempotent)
    cols = [r[1] for r in con.execute("PRAGMA table_info('added_candidates')").fetchall()]
    if "branch_id" not in cols:
        con.execute("ALTER TABLE added_candidates ADD COLUMN branch_id VARCHAR DEFAULT 'main'")
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
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS branch_withdrawals (
            branch_id VARCHAR, request_id VARCHAR, PRIMARY KEY (branch_id, request_id)
        )
        """
    )
    con.execute("CREATE TABLE IF NOT EXISTS baseline (name VARCHAR, params VARCHAR)")
    _ensure_main_branch(con)
    return con


def _ensure_main_branch(con: duckdb.DuckDBPyConnection) -> None:
    """Seed the 'main' branch once, from a legacy pinned baseline if present, else config defaults."""
    if con.execute("SELECT 1 FROM branches WHERE branch_id = 'main'").fetchone():
        return
    legacy = con.execute("SELECT params FROM baseline WHERE name = 'main'").fetchone()
    if legacy:
        p = json.loads(legacy[0])
        scenario = p.get("scenario") or DEFAULT_SCENARIO
        g30, g35 = p.get("growth_2030", GROWTH_2030), p.get("growth_2035", GROWTH_2035)
        w_r, w_n, w_s = p.get("w_readiness"), p.get("w_need"), p.get("w_strategic")
    else:
        scenario, g30, g35, w_r, w_n, w_s = DEFAULT_SCENARIO, GROWTH_2030, GROWTH_2035, None, None, None
    con.execute(
        "INSERT INTO branches (branch_id, name, parent_id, scenario, growth_2030, growth_2035, "
        "w_readiness, w_need, w_strategic, status, created_at) "
        "VALUES ('main', 'Main', NULL, ?, ?, ?, ?, ?, ?, 'open', ?)",
        [scenario, g30, g35, w_r, w_n, w_s, _now()],
    )


def _branch_row(con: duckdb.DuckDBPyConnection, branch_id: str) -> dict | None:
    """One branch as a dict keyed by _BRANCH_COLS, or None if it doesn't exist."""
    r = con.execute(
        f"SELECT {', '.join(_BRANCH_COLS)} FROM branches WHERE branch_id = ?", [branch_id]
    ).fetchone()
    return dict(zip(_BRANCH_COLS, r)) if r else None


def _candidate_rows(branch_id: str = "main") -> list[dict]:
    """Candidate rows for a branch: warehouse baseline ∪ the branch's adds − its withdrawals."""
    rows = _warehouse_query("SELECT * FROM candidate_projects")
    con = _scenarios_con()
    try:
        cur = con.execute("SELECT * FROM added_candidates WHERE branch_id = ?", [branch_id])
        cols = [c[0] for c in cur.description]
        added = [dict(zip(cols, r)) for r in cur.fetchall()]
        withdrawn = {
            r[0]
            for r in con.execute(
                "SELECT request_id FROM branch_withdrawals WHERE branch_id = ?", [branch_id]
            ).fetchall()
        }
    finally:
        con.close()
    rows = [r for r in rows if r["request_id"] not in withdrawn]
    return rows + added


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
    """List the queued projects (baseline warehouse + any added via the UI), shaped for the client."""
    return [_to_client(r) for r in _candidate_rows()]


class NewCandidate(BaseModel):
    """Request body for adding a project via the UI (scored with neutral placeholders)."""

    applicant: str | None = None
    bus_id: int | None = None
    technology: str | None = None
    rating_mw: float | None = None
    readiness_score: float = MANUAL_READINESS_DEFAULT
    strategic_fit: float = MANUAL_STRATEGIC_DEFAULT
    readiness_rationale: str = ""
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
    con.execute(
        f"INSERT INTO added_candidates ({_ADDED_COLS}, branch_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [request_id, body.applicant, body.bus_id, body.technology, body.rating_mw,
         body.readiness_score, body.strategic_fit, body.readiness_rationale, status, review, branch_id],
    )
    return {
        "request_id": request_id, "applicant": body.applicant, "bus_id": body.bus_id,
        "technology": body.technology, "rating_mw": body.rating_mw,
        "readiness_score": body.readiness_score, "strategic_fit": body.strategic_fit,
        "readiness_rationale": body.readiness_rationale, "status": status,
        "review_reasons": review, "branch_id": branch_id,
    }


@app.post("/optimize/candidates")
def add_candidate(body: NewCandidate) -> dict:
    """Add a project to a branch (stored in the API scenarios DB; warehouse untouched)."""
    con = _scenarios_con()
    try:
        row = _insert_candidate(con, body.branch_id, body, _valid_bus_ids())
    finally:
        con.close()
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
            strategic_rationale=r.get("strategic_rationale") or "",
            strategic_confidence=(
                None if r.get("strategic_confidence") is None else float(r["strategic_confidence"])
            ),
            status=r["status"],
            review_reasons=r.get("review_reasons") or "",
        )
        for r in _candidate_rows(branch_id)
    ]


_compute_cache: dict = {}


def _cand_key(cands: list[Candidate]) -> str:
    """A stable hash of a candidate set, so the compute cache never serves one branch's result for
    another branch with different projects (the highest-risk bug of branch-scoping)."""
    sig = sorted(
        (c.request_id, c.bus_id, c.rating_mw, round(c.readiness_score, 4),
         round(c.strategic_fit, 4), c.status)
        for c in cands
    )
    return hashlib.md5(json.dumps(sig, default=str).encode()).hexdigest()


def _compute(body: OptimizeRequest, cands: list[Candidate], cand_key: str) -> OptimizeResult:
    """Run the deterministic optimizer for a request + candidate set, cached by both."""
    params = _resolve_params(body)
    key = (
        params.scenario, round(params.growth_2030, 3), round(params.growth_2035, 3),
        params.w_readiness, params.w_need, params.w_strategic, cand_key, baseline_id(),
    )
    if key not in _compute_cache:
        _compute_cache[key] = optimize(cands, params)
    return _compute_cache[key]


def _optimize_payload(body: OptimizeRequest, branch_id: str = "main") -> dict:
    """Run the optimizer for a branch and enrich the result for the map (coords, generators).

    Resolves the DFES scenario to growth, runs the deterministic engine (cached by inputs AND the
    branch's candidate set), then attaches map coordinates + applicant and, optionally, a narrative.
    """
    cands = _candidates(branch_id)
    ckey = _cand_key(cands)
    params = _resolve_params(body)
    key = (
        params.scenario, round(params.growth_2030, 3), round(params.growth_2035, 3),
        params.w_readiness, params.w_need, params.w_strategic,
        body.with_justification, ckey, baseline_id(),
    )
    if key in _optimize_cache:
        return _optimize_cache[key]

    result = _compute(body, cands, ckey)
    out = result.model_dump()

    coords = _bus_coords()
    applicant_by_id = {r["request_id"]: (r.get("applicant") or "") for r in _candidate_rows(branch_id)}
    for q in out["queue"]:
        bid = q["bus_id"]
        q["lon"], q["lat"] = coords.get(int(bid), (None, None)) if bid is not None else (None, None)
        q["applicant"] = applicant_by_id.get(q["request_id"], "")

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


class DiffRequest(BaseModel):
    """Two scenarios to compare: `base` (e.g. the plan of record) vs `head` (the proposed option)."""

    base: OptimizeRequest
    head: OptimizeRequest
    with_narration: bool = False


@app.post("/optimize/diff")
def run_diff(body: DiffRequest) -> dict:
    """Diff two ad-hoc scenarios on the main candidate set (legacy A-vs-B compare)."""
    cands = _candidates("main")
    ckey = _cand_key(cands)
    d = diff_results(_compute(body.base, cands, ckey), _compute(body.head, cands, ckey))
    out = d.model_dump()
    out["narration"] = ""
    if body.with_narration:
        try:
            out["narration"] = opt_llm.narrate_diff(_summarize_diff(d))
        except Exception:
            out["narration"] = ""
    return out


# --- baseline ("main") shim + branches ("git for grids") --------------------
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


@app.get("/baseline")
def get_baseline() -> dict:
    """The 'main' plan-of-record scenario params (compat shim over the main branch)."""
    con = _scenarios_con()
    try:
        row = _branch_row(con, "main")
    finally:
        con.close()
    return {"exists": bool(row), "params": _branch_params(row) if row else None}


@app.post("/baseline")
def set_baseline(body: OptimizeRequest) -> dict:
    """Pin the given scenario onto 'main' (compat shim over the main branch)."""
    con = _scenarios_con()
    try:
        con.execute(
            "UPDATE branches SET scenario=?, growth_2030=?, growth_2035=?, "
            "w_readiness=?, w_need=?, w_strategic=? WHERE branch_id='main'",
            [body.scenario, body.growth_2030, body.growth_2035,
             body.w_readiness, body.w_need, body.w_strategic],
        )
    finally:
        con.close()
    _optimize_cache.clear()
    _compute_cache.clear()
    return {"exists": True, "params": body.model_dump()}


# --- branches ---------------------------------------------------------------
class BranchCreate(BaseModel):
    """Open a branch off `from_branch` (default main): a scenario + optional added/withdrawn projects."""

    name: str
    from_branch: str = "main"
    scenario: str | None = None
    growth_2030: float | None = None
    growth_2035: float | None = None
    w_readiness: float | None = None
    w_need: float | None = None
    w_strategic: float | None = None
    added_projects: list[NewCandidate] = []
    withdraw: list[str] = []


class MergeRequest(BaseModel):
    into: str = "main"


class BranchOptimizeRequest(BaseModel):
    with_justification: bool = False


@app.post("/branches")
def create_branch(body: BranchCreate) -> dict:
    """Create a branch (copy-on-create): snapshot the parent's projects, then apply the change."""
    con = _scenarios_con()
    try:
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
        # copy-on-create: snapshot the parent's added projects + withdrawals onto the new branch
        con.execute(
            f"INSERT INTO added_candidates ({_ADDED_COLS}, branch_id) "
            f"SELECT {_ADDED_COLS}, ? FROM added_candidates WHERE branch_id = ?",
            [bid, parent["branch_id"]],
        )
        con.execute(
            "INSERT INTO branch_withdrawals (branch_id, request_id) "
            "SELECT ?, request_id FROM branch_withdrawals WHERE branch_id = ?",
            [bid, parent["branch_id"]],
        )
        valid = _valid_bus_ids()
        for p in body.added_projects:
            _insert_candidate(con, bid, p, valid)
        for rid in dict.fromkeys(body.withdraw):  # dedupe, preserve order
            con.execute("INSERT INTO branch_withdrawals (branch_id, request_id) VALUES (?, ?)", [bid, rid])
        out = _branch_to_client(con, _branch_row(con, bid))
    finally:
        con.close()
    return out


@app.get("/branches")
def list_branches() -> dict:
    """All branches, main first then newest-created."""
    con = _scenarios_con()
    try:
        ids = [r[0] for r in con.execute(
            "SELECT branch_id FROM branches ORDER BY (branch_id = 'main') DESC, created_at"
        ).fetchall()]
        branches = [_branch_to_client(con, _branch_row(con, i)) for i in ids]
    finally:
        con.close()
    return {"branches": branches}


@app.get("/branches/{branch_id}")
def get_branch(branch_id: str) -> dict:
    """One branch, with its added + withdrawn project ids."""
    con = _scenarios_con()
    try:
        row = _require_branch(con, branch_id)
        added = [r[0] for r in con.execute(
            "SELECT request_id FROM added_candidates WHERE branch_id = ?", [branch_id]).fetchall()]
        withdrawn = [r[0] for r in con.execute(
            "SELECT request_id FROM branch_withdrawals WHERE branch_id = ?", [branch_id]).fetchall()]
        out = _branch_to_client(con, row)
    finally:
        con.close()
    out["added_project_ids"] = added
    out["withdrawn_project_ids"] = withdrawn
    return out


@app.post("/branches/{branch_id}/optimize")
def optimize_branch(branch_id: str, body: BranchOptimizeRequest | None = None) -> dict:
    """Run the optimizer on a branch's scenario + candidate set."""
    con = _scenarios_con()
    try:
        row = _require_branch(con, branch_id)
    finally:
        con.close()
    req = _branch_request(row)
    req.with_justification = bool(body and body.with_justification)
    return _optimize_payload(req, branch_id)


@app.get("/branches/{branch_id}/diff")
def diff_branch(branch_id: str, with_narration: bool = False) -> dict:
    """Consequence diff of a branch (head) vs its parent (base, default main)."""
    con = _scenarios_con()
    try:
        head_row = _require_branch(con, branch_id)
        base_row = _branch_row(con, head_row["parent_id"] or "main") or _branch_row(con, "main")
    finally:
        con.close()
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
    con = _scenarios_con()
    try:
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
        con.execute("DELETE FROM branch_withdrawals WHERE branch_id = ?", [into])
        con.execute(
            "INSERT INTO branch_withdrawals (branch_id, request_id) "
            "SELECT ?, request_id FROM branch_withdrawals WHERE branch_id = ?",
            [into, branch_id],
        )
        con.execute("UPDATE branches SET status='merged', merged_at=? WHERE branch_id=?", [_now(), branch_id])
        out = _branch_to_client(con, _branch_row(con, into))
    finally:
        con.close()
    _optimize_cache.clear()
    _compute_cache.clear()
    return out


@app.post("/branches/{branch_id}/discard")
def discard_branch(branch_id: str) -> dict:
    """Soft-discard a branch (kept for audit; main cannot be discarded)."""
    if branch_id == "main":
        raise HTTPException(status_code=400, detail="cannot discard main")
    con = _scenarios_con()
    try:
        _require_branch(con, branch_id)
        con.execute("UPDATE branches SET status='discarded' WHERE branch_id=?", [branch_id])
        out = _branch_to_client(con, _branch_row(con, branch_id))
    finally:
        con.close()
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
    con = _scenarios_con()
    try:
        row = _require_branch(con, branch_id)
    finally:
        con.close()
    cands = _candidates(branch_id)
    ckey = _cand_key(cands)
    req = _branch_request(row)
    base = _compute(req, cands, ckey)
    sugs = suggest_unblock(cands, _resolve_params(req), base=base, max_suggestions=limit)
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
