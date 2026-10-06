"""Deterministic readiness rubric.

'Ready' in the connection reform is a *factual* checklist -- land rights, planning consent,
a connection agreement, financing, a credible timeline -- not a judgment call. The facts come from
published registers (e.g. an ECR "accepted to connect" entry = a signed connection agreement), and
this module turns them into a score where every point is traceable to a milestone an engineer
could verify.
"""

from __future__ import annotations

from .config import (
    PLAN_START_YEAR,
    READINESS_COMMISSIONING_FAR_CREDIT,
    READINESS_COMMISSIONING_MID_CREDIT,
    READINESS_COMMISSIONING_MID_YEARS,
    READINESS_COMMISSIONING_NEAR_CREDIT,
    READINESS_COMMISSIONING_NEAR_YEARS,
    READINESS_WEIGHTS,
)

# level label -> credit in 0..1, per milestone. The lowest label is the silent/default case.
_LEVELS = {
    "land_rights": {"secured": 1.0, "in_progress": 0.5, "none": 0.0},
    "planning_status": {"granted": 1.0, "submitted": 0.5, "pre_application": 0.1, "none": 0.0},
    "grid_connection_agreement": {"signed": 1.0, "offered": 0.5, "none": 0.0},
    "financing": {"committed": 1.0, "in_progress": 0.5, "none": 0.0},
}

_LABELS = {
    "land_rights": "land rights",
    "planning_status": "planning consent",
    "grid_connection_agreement": "connection agreement",
    "financing": "financing",
    "commissioning_year": "commissioning timeline",
}


def _commissioning_credit(year: int | None, reference_year: int) -> float:
    """Sooner-energising projects are readier. Unknown year -> treated as distant/uncertain."""
    if year is None:
        return READINESS_COMMISSIONING_FAR_CREDIT
    years_out = int(year) - reference_year
    if years_out <= READINESS_COMMISSIONING_NEAR_YEARS:
        return READINESS_COMMISSIONING_NEAR_CREDIT
    if years_out <= READINESS_COMMISSIONING_MID_YEARS:
        return READINESS_COMMISSIONING_MID_CREDIT
    return READINESS_COMMISSIONING_FAR_CREDIT


def score_from_checklist(checklist: dict, reference_year: int | None = None) -> dict:
    """Deterministic readiness score in 0..1 from a Gate-2 checklist of published facts.

    Returns {readiness_score, readiness_rationale, readiness_breakdown}, where the breakdown
    records, per milestone, the level read, the credit it earned, its weight, and the points
    contributed -- so the score is fully auditable.
    """
    reference_year = reference_year or PLAN_START_YEAR  # the plan's first year, never the wall clock: a score must not move on 1 January
    breakdown: dict[str, dict] = {}

    for crit, levels in _LEVELS.items():
        level = str(checklist.get(crit) or "none").lower()
        credit = levels.get(level, 0.0)
        weight = READINESS_WEIGHTS[crit]
        breakdown[crit] = {
            "level": level,
            "credit": credit,
            "weight": weight,
            "points": round(weight * credit, 4),
        }

    cy = checklist.get("commissioning_year")
    cy_credit = _commissioning_credit(cy, reference_year)
    cy_weight = READINESS_WEIGHTS["commissioning_year"]
    breakdown["commissioning_year"] = {
        "level": str(int(cy)) if cy else "unknown",
        "credit": cy_credit,
        "weight": cy_weight,
        "points": round(cy_weight * cy_credit, 4),
    }

    score = round(sum(b["points"] for b in breakdown.values()), 4)

    have = [_LABELS[c] for c, b in breakdown.items() if b["credit"] >= 1.0]
    partial = [_LABELS[c] for c, b in breakdown.items() if 0.0 < b["credit"] < 1.0]
    missing = [_LABELS[c] for c, b in breakdown.items() if b["credit"] <= 0.0]
    bits = []
    if have:
        bits.append("secured: " + ", ".join(have))
    if partial:
        bits.append("in progress: " + ", ".join(partial))
    if missing:
        bits.append("outstanding: " + ", ".join(missing))
    rationale = "; ".join(bits) if bits else "no readiness evidence in application"

    return {
        "readiness_score": score,
        "readiness_rationale": rationale,
        "readiness_breakdown": breakdown,
    }
