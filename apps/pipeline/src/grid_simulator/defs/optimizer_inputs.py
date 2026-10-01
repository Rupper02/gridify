"""Score connection requests for readiness (LLM) and persist the candidate project
list the connection-queue optimizer consumes."""

import dagster as dg
import duckdb
import pandas as pd

from gridforge_optimizer.llm import score_readiness

from grid_simulator.config import DB_PATH, MAX_CONNECTION_MW


@dg.asset
def scored_connections(
    context: dg.AssetExecutionContext,
    extracted_connections: pd.DataFrame,
    raw_connection_requests: pd.DataFrame,
    canonical_buses: pd.DataFrame,
) -> pd.DataFrame:
    """Candidate generation projects: extracted fields + triage status + LLM readiness scores."""
    valid_bus_ids = set(canonical_buses["bus_id"])
    text_by_id = dict(zip(raw_connection_requests["request_id"], raw_connection_requests["text"]))

    rows = []
    for r in extracted_connections.itertuples(index=False):
        tech = None if pd.isna(r.technology) else str(r.technology)

        reasons = []
        if pd.isna(r.bus_id):
            reasons.append("missing a bus")
        elif int(r.bus_id) not in valid_bus_ids:
            reasons.append("bus is not in model")
        if pd.isna(r.rating_mw):
            reasons.append("missing rating")
        elif not (0 < r.rating_mw <= MAX_CONNECTION_MW):
            reasons.append("rating is out of range")
        if tech is None:
            reasons.append("missing technology")
        elif tech.lower() == "load":
            reasons.append("demand connection, not generation")
        status = "auto_accept" if not reasons else "needs_review"

        score = score_readiness(text_by_id.get(r.request_id, ""))

        rows.append({
            "request_id": r.request_id,
            "applicant": None if pd.isna(r.applicant) else str(r.applicant),
            "bus_id": None if pd.isna(r.bus_id) else int(r.bus_id),
            "technology": tech,
            "rating_mw": None if pd.isna(r.rating_mw) else float(r.rating_mw),
            "readiness_score": float(score["readiness_score"]),
            "strategic_fit": float(score["strategic_fit"]),
            "readiness_rationale": str(score["readiness_rationale"]),
            "status": status,
            "review_reasons": ", ".join(reasons),
        })

    df = pd.DataFrame(rows)
    context.add_output_metadata({
        "candidates": len(df),
        "auto_accept": int((df["status"] == "auto_accept").sum()),
    })
    return df


@dg.asset(deps=["served_model"])
def served_candidates(
    context: dg.AssetExecutionContext,
    scored_connections: pd.DataFrame,
) -> dg.MaterializeResult:
    """Write candidate_projects into the warehouse (after served_model, same DuckDB file)."""
    conn = duckdb.connect(str(DB_PATH))
    try:
        conn.register("df_view", scored_connections)
        conn.execute("CREATE OR REPLACE TABLE candidate_projects AS SELECT * FROM df_view")
    finally:
        conn.close()
    return dg.MaterializeResult(metadata={"rows": len(scored_connections)})
