"""Regenerate the planner's OFFLINE mock data from the NGED model.

Writes apps/web/public/planner/data/{model.json, candidates.json} so offline mode (config.mock
= true) shows the real NGED Bicker Fen network + queue instead of the old mv_oberrhein one. Live
mode (the default) does not use these — it calls the FastAPI backend. The offline power flow is the
planner's own crude radial approximation, so offline results are indicative, not authoritative.

Run: `uv run --directory apps/api python ../pipeline/scripts/gen_planner_mock.py`
"""
import json
from pathlib import Path

from gridforge_optimizer.config import MAX_CONNECTION_MW
from gridforge_optimizer.nged import nged_candidates, nged_model

DST = Path(__file__).resolve().parents[3] / "apps" / "web" / "public" / "planner" / "data"
DST.mkdir(parents=True, exist_ok=True)

model = nged_model()
(DST / "model.json").write_text(json.dumps(model), encoding="utf-8")


def _client(c: dict) -> dict:
    return {
        "request_id": c["request_id"], "applicant": c["applicant"], "bus_id": c["bus_id"],
        "technology": c["technology"], "rating_mw": c["rating_mw"],
        "readiness_score": c["readiness_score"], "strategic_fit": c["strategic_fit"],
        "status": "valid" if c["status"] == "auto_accept" else "rejected",
        "review_reasons": c["review_reasons"], "readiness_rationale": c["readiness_rationale"],
    }


cands = [_client(c) for c in nged_candidates(MAX_CONNECTION_MW)]
(DST / "candidates.json").write_text(json.dumps(cands), encoding="utf-8")

print(f"wrote {DST/'model.json'} ({len(model['buses'])} buses, {len(model['lines'])} lines)")
print(f"wrote {DST/'candidates.json'} ({len(cands)} candidates)")
