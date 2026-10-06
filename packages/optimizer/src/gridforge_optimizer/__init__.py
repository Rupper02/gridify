"""gridforge_optimizer — the deterministic connection-queue engine.

`optimize(candidates, params)` ranks projects by readiness + grid need + strategic fit and
connects them greedily, gated by a pandapower power flow. Scoring helpers (readiness rubric,
grid need) and the LLM narration wrappers live in the sibling modules; see the package README.
"""

import hashlib as _hashlib
from functools import lru_cache as _lru_cache
from pathlib import Path as _Path

from .diff import (
    ConsequenceDiff,
    LineDelta,
    LoadingDelta,
    PhaseDelta,
    ProjectDelta,
    WorkDelta,
    YearDelta,
    diff_results,
    diff_works,
    diff_year,
    diff_years,
)
from .findings import against_recommendation, extract_findings
from .gate import merge_verdict
from .greedy import optimize
from .network import apply_reinforcement
from .sources import SOURCES, GridSource, NgedSource, SourceSpec, default_source, source_from_file, validate_net
from .studies import STUDIES, StudyContext, chunk_study, merge_chunks, run_study
from .suggest import suggest_unblock
from .types import (
    Candidate,
    ValidationReport,
    Control,
    ImportMeta,
    GridModel,
    OptimizeParams,
    OptimizeResult,
    Curtailment,
    N1During,
    Alert,
    Finding,
    GateFinding,
    MergeVerdict,
    ModelAssumption,
    StudyItem,
    StudyResult,
    Outage,
    OutageStudy,
    PhaseResult,
    QueueItem,
    RegionYear,
    Reason,
    Reinforcement,
    Suggestion,
    WindowOption,
    YearResult,
)
from .years import PLAN_YEARS, energisation_years, evaluate_year, evaluate_years, year_order
from .windows import best_windows

@_lru_cache(maxsize=1)
def engine_fingerprint() -> str:
    """A hash of this package's source and bundled data. Cached results are keyed by it, so any
    change to the physics, the ranking or the pinned network retires every cached answer."""
    h = _hashlib.sha256()
    here = _Path(__file__).resolve().parent
    for p in sorted(list(here.glob("*.py")) + list((here / "data").rglob("*"))):
        if p.is_file():
            h.update(p.relative_to(here).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


__all__ = [
    "engine_fingerprint",
    "optimize",
    "Candidate",
    "OptimizeParams",
    "OptimizeResult",
    "QueueItem",
    "PhaseResult",
    "YearResult",
    "RegionYear",
    "Alert",
    "Outage",
    "OutageStudy",
    "Curtailment",
    "N1During",
    "evaluate_years",
    "best_windows",
    "WindowOption",
    "year_order",
    "PLAN_YEARS",
    "Reason",
    "Reinforcement",
    "Suggestion",
    "apply_reinforcement",
    "suggest_unblock",
    "diff_results",
    "extract_findings",
    "against_recommendation",
    "merge_verdict",
    "SOURCES",
    "GridSource",
    "NgedSource",
    "SourceSpec",
    "default_source",
    "source_from_file",
    "validate_net",
    "GridModel",
    "Control",
    "ImportMeta",
    "ValidationReport",
    "STUDIES",
    "StudyContext",
    "run_study",
    "chunk_study",
    "merge_chunks",
    "ModelAssumption",
    "StudyItem",
    "StudyResult",
    "Finding",
    "GateFinding",
    "MergeVerdict",
    "ConsequenceDiff",
    "ProjectDelta",
    "PhaseDelta",
    "LineDelta",
    "LoadingDelta",
    "YearDelta",
    "WorkDelta",
    "diff_year",
    "diff_years",
    "diff_works",
    "evaluate_year",
    "energisation_years",
]
