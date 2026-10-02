"""gridforge_optimizer — the deterministic connection-queue engine.

`optimize(candidates, params)` ranks projects by readiness + grid need + strategic fit and
connects them greedily, gated by a pandapower power flow. Scoring helpers (readiness rubric,
grid need) and the LLM narration wrappers live in the sibling modules; see the package README.
"""

import hashlib as _hashlib
from functools import lru_cache as _lru_cache
from pathlib import Path as _Path

from .diff import ConsequenceDiff, LineDelta, PhaseDelta, ProjectDelta, diff_results
from .greedy import optimize
from .network import apply_reinforcement
from .suggest import suggest_unblock
from .types import (
    Candidate,
    OptimizeParams,
    OptimizeResult,
    PhaseResult,
    QueueItem,
    Reason,
    Reinforcement,
    Suggestion,
)

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
    "Reason",
    "Reinforcement",
    "Suggestion",
    "apply_reinforcement",
    "suggest_unblock",
    "diff_results",
    "ConsequenceDiff",
    "ProjectDelta",
    "PhaseDelta",
    "LineDelta",
]
