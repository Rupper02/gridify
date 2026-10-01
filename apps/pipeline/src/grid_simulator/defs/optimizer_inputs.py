"""Score connection requests and persist the candidate project list the optimizer consumes.

Readiness is deterministic: the LLM only *extracts* the Gate-2 milestones from each application,
and a transparent rubric turns them into a score. Strategic fit -- the genuine judgment of whether
a project is the right addition -- is made by the Jev decisions model, grounded in the measured
local grid signal (grid_need) from a power-flow solve. Both are persisted so ranking is reproducible.
"""

import json

import dagster as dg
import duckdb
import pandapower as pp
import pandas as pd

from gridforge_optimizer.config import GROWTH_2035
from gridforge_optimizer.llm import extract_readiness_checklist, score_strategic_fit
from gridforge_optimizer.network import apply_growth, build_base_net
from gridforge_optimizer.readiness import score_from_checklist
from gridforge_optimizer.scoring import grid_need_from_solved

from grid_simulator.config import DB_PATH, MAX_CONNECTION_MW


@dg.asset
def scored_connections(
    context: dg.AssetExecutionContext,
    extracted_connections: pd.DataFrame,
    raw_connection_requests: pd.DataFrame,
    canonical_buses: pd.DataFrame,
) -> pd.DataFrame:
    """Candidate generation projects: extracted fields + triage + deterministic readiness + Jev fit."""
    valid_bus_ids = set(canonical_buses["bus_id"])
    text_by_id = dict(zip(raw_connection_requests["request_id"], raw_connection_requests["text"]))

    # one solved network under the 2035 horizon, to read the local grid signal at each bus
    need_net = build_base_net()
    apply_growth(need_net, GROWTH_2035)
    pp.runpp(need_net)

    rows = []
    for r in extracted_connections.itertuples(index=False):
        tech = None if pd.isna(r.technology) else str(r.technology)
        bus_ok = (not pd.isna(r.bus_id)) and int(r.bus_id) in valid_bus_ids

        reasons = []
        if pd.isna(r.bus_id):
            reasons.append("missing a bus")
        elif not bus_ok:
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

        # readiness: LLM extracts the facts, the rubric scores them (deterministic + auditable)
        checklist = extract_readiness_checklist(text_by_id.get(r.request_id, ""))
        rdy = score_from_checklist(checklist)

        # strategic fit: Jev judges 'right addition', grounded in grid_need -- but only for
        # projects that passed intake (a bad bus has no meaningful grid signal)
        if status == "auto_accept":
            grid_need = grid_need_from_solved(need_net, int(r.bus_id))
            strat = score_strategic_fit({
                "technology": tech,
                "rating_mw": float(r.rating_mw),
                "bus_id": int(r.bus_id),
                "grid_need": grid_need,
            })
        else:
            strat = {
                "strategic_fit": 0.5,
                "strategic_confidence": None,
                "strategic_rationale": "not assessed (failed intake validation)",
            }

        conf = strat.get("strategic_confidence")
        rows.append({
            "request_id": r.request_id,
            "applicant": None if pd.isna(r.applicant) else str(r.applicant),
            "bus_id": None if pd.isna(r.bus_id) else int(r.bus_id),
            "technology": tech,
            "rating_mw": None if pd.isna(r.rating_mw) else float(r.rating_mw),
            "readiness_score": float(rdy["readiness_score"]),
            "readiness_rationale": str(rdy["readiness_rationale"]),
            "readiness_breakdown": json.dumps(rdy["readiness_breakdown"]),
            "land_rights": checklist["land_rights"],
            "planning_status": checklist["planning_status"],
            "grid_connection_agreement": checklist["grid_connection_agreement"],
            "financing": checklist["financing"],
            "commissioning_year": checklist["commissioning_year"],
            "strategic_fit": float(strat["strategic_fit"]),
            "strategic_confidence": None if conf is None else float(conf),
            "strategic_rationale": str(strat["strategic_rationale"]),
            "status": status,
            "review_reasons": ", ".join(reasons),
        })

    df = pd.DataFrame(rows)
    context.add_output_metadata({
        "candidates": len(df),
        "auto_accept": int((df["status"] == "auto_accept").sum()),
        "mean_readiness": round(float(df["readiness_score"].mean()), 3) if len(df) else 0.0,
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
