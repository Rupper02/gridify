"""gridify_optimizer: the deterministic grid engine.

`simulate(connections, params)` builds the network for every plan year (demand grown to the year, the connections
energised by then), solves it in both study cases with AC power flow and reports every loading, voltage and breach;
`diff_plans` compares two runs year by year. See the package README.
"""

import hashlib as _hashlib
from functools import lru_cache as _lru_cache
from pathlib import Path as _Path

from .diff import LoadingDelta, PlanDiff, YearDelta, diff_plans, diff_year
from .sources import GridSource, NgedSource, Pathway, default_source
from .types import Connection, Control, GridModel, ModelAssumption, PlanParams, PlanResult, Reason, YearResult
from .years import PLAN_YEARS, evaluate_year, simulate, year_order


@_lru_cache(maxsize=1)
def engine_fingerprint() -> str:
    """A hash of this package's source and bundled data. Cached results are keyed by it, so any change to the physics
    or the pinned network retires every cached answer."""
    h = _hashlib.sha256()
    here = _Path(__file__).resolve().parent
    for p in sorted(list(here.glob("*.py")) + list((here / "data").rglob("*"))):
        if p.is_file():
            h.update(p.relative_to(here).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


__all__ = [
    "engine_fingerprint",
    "simulate",
    "evaluate_year",
    "year_order",
    "PLAN_YEARS",
    "diff_plans",
    "diff_year",
    "PlanDiff",
    "YearDelta",
    "LoadingDelta",
    "Connection",
    "Control",
    "PlanParams",
    "PlanResult",
    "YearResult",
    "Reason",
    "GridModel",
    "ModelAssumption",
    "GridSource",
    "NgedSource",
    "Pathway",
    "default_source",
]
