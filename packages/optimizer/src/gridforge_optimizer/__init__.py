"""gridforge_optimizer — the deterministic connection-queue engine.

`optimize(candidates, params)` ranks projects by readiness + grid need + strategic fit and
connects them greedily, gated by a pandapower power flow. Scoring helpers (readiness rubric,
grid need) and the LLM narration wrappers live in the sibling modules; see the package README.
"""

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

__all__ = [
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
