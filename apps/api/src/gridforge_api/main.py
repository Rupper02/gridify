"""GridForge API.

Serves the validated canonical grid model (read-only, from the pipeline's DuckDB
warehouse) and runs the connection-queue optimizer. Projects added via the UI are
stored in a separate scenarios DB, so the pipeline baseline is never mutated.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import duckdb
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from gridforge_optimizer import Candidate, OptimizeParams, optimize
from gridforge_optimizer import llm as opt_llm

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
    # warm pandapower's numba JIT so the first /optimize isn't slow
    try:
        from gridforge_optimizer.network import build_base_net, feasibility
        feasibility(build_base_net())
    except Exception:
        pass
    yield


app = FastAPI(title="GridForge API", lifespan=_lifespan)
# dev: permissive CORS so the planner works from any local host. Lock down in prod.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

MAX_CONNECTION_MW = 20.0
_optimize_cache: dict = {}


# --- read-only baseline (pipeline warehouse) --------------------------------
def _warehouse_query(sql: str) -> list[dict]:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        cur = con.execute(sql)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        con.close()


def baseline_model() -> dict:
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
    rows = _warehouse_query("SELECT snapshot_id FROM snapshots ORDER BY created_at DESC LIMIT 1")
    return rows[0]["snapshot_id"] if rows else "baseline"


@app.get("/health")
def health() -> dict:
    return {"ok": True, "warehouse_exists": WAREHOUSE.exists()}


@app.get("/model")
def get_model() -> dict:
    return baseline_model()


# --- candidate projects (baseline + user-added) -----------------------------
def _added_candidates_con() -> duckdb.DuckDBPyConnection:
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
    return con


def _candidate_rows() -> list[dict]:
    """Baseline candidates (pipeline warehouse) + projects added via the API."""
    rows = _warehouse_query("SELECT * FROM candidate_projects")
    con = _added_candidates_con()
    try:
        cur = con.execute("SELECT * FROM added_candidates")
        cols = [c[0] for c in cur.description]
        rows += [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()
    return rows


def _to_client(r: dict) -> dict:
    """Shape a candidate for the UI: valid/rejected status, non-null applicant."""
    return {
        **r,
        "applicant": r.get("applicant") or "",
        "status": "valid" if r.get("status") == "auto_accept" else "rejected",
    }


def _bus_coords() -> dict[int, tuple[float, float]]:
    return {
        int(b["bus_id"]): (b["lon"], b["lat"])
        for b in _warehouse_query("SELECT bus_id, lon, lat FROM buses WHERE lon IS NOT NULL")
    }


@app.get("/optimize/candidates")
def optimize_candidates() -> list[dict]:
    return [_to_client(r) for r in _candidate_rows()]


class NewCandidate(BaseModel):
    applicant: str | None = None
    bus_id: int | None = None
    technology: str | None = None
    rating_mw: float | None = None
    readiness_score: float = 0.5
    strategic_fit: float = 0.7
    readiness_rationale: str = ""


@app.post("/optimize/candidates")
def add_candidate(body: NewCandidate) -> dict:
    """Add a project to the plan (stored in the API scenarios DB; warehouse untouched)."""
    valid_bus_ids = {int(b["bus_id"]) for b in _warehouse_query("SELECT bus_id FROM buses")}
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
    status = "auto_accept" if not reasons else "needs_review"

    con = _added_candidates_con()
    try:
        n = con.execute("SELECT count(*) FROM added_candidates").fetchone()[0]
        request_id = f"CR-{2056 + n}"
        con.execute(
            "INSERT INTO added_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [request_id, body.applicant, body.bus_id, body.technology, body.rating_mw,
             body.readiness_score, body.strategic_fit, body.readiness_rationale, status, ", ".join(reasons)],
        )
    finally:
        con.close()

    _optimize_cache.clear()  # candidate set changed
    return _to_client({
        "request_id": request_id, "applicant": body.applicant, "bus_id": body.bus_id,
        "technology": body.technology, "rating_mw": body.rating_mw,
        "readiness_score": body.readiness_score, "strategic_fit": body.strategic_fit,
        "readiness_rationale": body.readiness_rationale, "status": status,
        "review_reasons": ", ".join(reasons),
    })


# --- optimizer ---------------------------------------------------------------
def _summarize(result) -> str:
    rows = []
    for q in result.queue:
        reason = f" — {q.reason.message}" if q.reason else ""
        rows.append(
            f"#{q.rank or '-'} {q.request_id}: {q.status}; {q.technology} {q.rating_mw} MW at bus "
            f"{q.bus_id}; readiness={q.readiness_score}, grid_need={q.grid_need}{reason}"
        )
    return "Connection queue (ordered):\n" + "\n".join(rows)


class OptimizeRequest(BaseModel):
    growth_2030: float = 1.10
    growth_2035: float = 1.25
    w_readiness: float | None = None
    w_need: float | None = None
    w_strategic: float | None = None
    with_justification: bool = True


@app.post("/optimize")
def run_optimize(body: OptimizeRequest) -> dict:
    key = (
        round(body.growth_2030, 3), round(body.growth_2035, 3),
        body.w_readiness, body.w_need, body.w_strategic,
        body.with_justification, baseline_id(),
    )
    if key in _optimize_cache:
        return _optimize_cache[key]

    cands = [
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
        )
        for r in _candidate_rows()
    ]

    weights = {
        k: v for k, v in {
            "w_readiness": body.w_readiness, "w_need": body.w_need, "w_strategic": body.w_strategic,
        }.items() if v is not None
    }
    params = OptimizeParams(growth_2030=body.growth_2030, growth_2035=body.growth_2035, **weights)

    result = optimize(cands, params)
    out = result.model_dump()

    coords = _bus_coords()
    applicant_by_id = {r["request_id"]: (r.get("applicant") or "") for r in _candidate_rows()}
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
    out["justification"] = ""
    if body.with_justification:
        try:
            out["justification"] = opt_llm.justify(_summarize(result))
        except Exception:
            out["justification"] = ""

    _optimize_cache[key] = out
    return out
