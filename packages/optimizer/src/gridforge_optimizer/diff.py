"""Consequence diff: turn two `OptimizeResult`s into a human-legible delta.

Git diffs text; GridForge diffs *consequences*. Given a `base` and a `head` run of the
optimizer, this reports:
  - who moved   -> per-project status/rank change (accelerated / slipped / dropped / ...)
  - what unlocked -> MW connected by 2030 / 2035, base vs head
  - what lit up -> per-phase network deltas (lines that newly overload or clear, voltage band)

Pure and deterministic: no I/O, no pandapower. It only reshapes fields already present on the
two results, so it is trivially unit-testable and is the reusable core of the future
branch / pull-request ("git for grids") workflow.
"""

from __future__ import annotations

from pydantic import BaseModel

from .config import LINE_LOADING_MAX_PCT
from .types import OptimizeParams, OptimizeResult, PhaseResult, QueueItem, Reason

# Connection horizon as an ordinal: lower = connects sooner / better. This single mapping is
# what makes "accelerated" vs "slipped" fall out of a plain comparison.
_HORIZON = {"Phase1": 0, "Phase2": 1, "Deferred": 2, "Rejected": 3}
_CONNECTED = {"Phase1", "Phase2"}

# Sort order for the project list: most operationally significant movers first.
_CHANGE_ORDER = {
    "accelerated": 0,
    "slipped": 1,
    "dropped": 2,
    "added": 3,
    "moved_up": 4,
    "moved_down": 5,
    "unchanged": 6,
}

_EPS = 0.1  # loading-% movement below this is treated as noise, not a change
_TOP_LINES = 10  # how many biggest line movers to surface per phase


class ProjectDelta(BaseModel):
    request_id: str
    technology: str | None = None
    rating_mw: float | None = None
    bus_id: int | None = None
    base_status: str | None = None  # None = absent from the base run
    head_status: str | None = None  # None = absent from the head run
    base_rank: int | None = None
    head_rank: int | None = None
    rank_delta: int | None = None  # negative = moved up the queue
    change: str = "unchanged"  # accelerated|slipped|moved_up|moved_down|added|dropped|unchanged
    head_reason: Reason | None = None  # why head defers/rejects it -> the "what would it take" hook


class LineDelta(BaseModel):
    line_id: int
    base_pct: float | None = None
    head_pct: float | None = None
    delta: float = 0.0
    crossed: str = "unchanged"  # newly_overloaded|cleared|worsened|eased|unchanged


class PhaseDelta(BaseModel):
    phase: str
    worst_line_delta: float = 0.0
    worst_trafo_delta: float = 0.0
    min_vm_delta: float = 0.0
    max_vm_delta: float = 0.0
    newly_overloaded_line_ids: list[int] = []
    cleared_line_ids: list[int] = []
    top_line_deltas: list[LineDelta] = []
    mw_connected_base: float = 0.0
    mw_connected_head: float = 0.0
    mw_connected_delta: float = 0.0


class ConsequenceDiff(BaseModel):
    base_label: str
    head_label: str
    headline: dict
    projects: list[ProjectDelta]
    phases: list[PhaseDelta]


def _label(p: OptimizeParams) -> str:
    return (
        f"{p.scenario} · g30={p.growth_2030:.2f}/g35={p.growth_2035:.2f} · "
        f"w r/n/s={p.w_readiness:.2f}/{p.w_need:.2f}/{p.w_strategic:.2f}"
    )


def _by_id(queue: list[QueueItem]) -> dict[str, QueueItem]:
    return {q.request_id: q for q in queue}


def _ratings(queue: list[QueueItem]) -> dict[str, float]:
    return {q.request_id: (q.rating_mw or 0.0) for q in queue}


def _mw_connected(phase: PhaseResult | None, ratings: dict[str, float]) -> float:
    """MW connected at a phase = sum of ratings over that phase's cumulative accepted set."""
    if phase is None:
        return 0.0
    return round(sum(ratings.get(rid, 0.0) for rid in phase.accepted), 1)


def _classify(base: QueueItem | None, head: QueueItem | None) -> str:
    if base is None:
        return "added"
    if head is None:
        return "dropped"
    b, h = _HORIZON[base.status], _HORIZON[head.status]
    if h < b:
        return "accelerated"
    if h > b:
        return "slipped"
    # same horizon -> fall back to rank movement (both ranks may be None for Rejected)
    if base.rank is not None and head.rank is not None:
        if head.rank < base.rank:
            return "moved_up"
        if head.rank > base.rank:
            return "moved_down"
    return "unchanged"


def _project_deltas(base: list[QueueItem], head: list[QueueItem]) -> list[ProjectDelta]:
    b_by, h_by = _by_id(base), _by_id(head)
    deltas: list[ProjectDelta] = []
    for rid in b_by.keys() | h_by.keys():
        b, h = b_by.get(rid), h_by.get(rid)
        ident = h or b  # prefer head's identity fields, fall back to base
        rank_delta = (
            h.rank - b.rank if (b and h and b.rank is not None and h.rank is not None) else None
        )
        deltas.append(
            ProjectDelta(
                request_id=rid,
                technology=ident.technology,
                rating_mw=ident.rating_mw,
                bus_id=ident.bus_id,
                base_status=b.status if b else None,
                head_status=h.status if h else None,
                base_rank=b.rank if b else None,
                head_rank=h.rank if h else None,
                rank_delta=rank_delta,
                change=_classify(b, h),
                head_reason=h.reason if h else None,
            )
        )
    deltas.sort(key=lambda d: (_CHANGE_ORDER.get(d.change, 9), -abs(d.rank_delta or 0), d.request_id))
    return deltas


def _crossed(base_pct: float | None, head_pct: float | None, delta: float) -> str:
    b_over = base_pct is not None and base_pct > LINE_LOADING_MAX_PCT
    h_over = head_pct is not None and head_pct > LINE_LOADING_MAX_PCT
    if h_over and not b_over:
        return "newly_overloaded"
    if b_over and not h_over:
        return "cleared"
    if delta > _EPS:
        return "worsened"
    if delta < -_EPS:
        return "eased"
    return "unchanged"


def _line_deltas(base: PhaseResult, head: PhaseResult) -> list[LineDelta]:
    out: list[LineDelta] = []
    for lid in base.line_loading.keys() | head.line_loading.keys():
        bp = base.line_loading.get(lid)
        hp = head.line_loading.get(lid)
        delta = round((hp or 0.0) - (bp or 0.0), 1)
        out.append(LineDelta(line_id=lid, base_pct=bp, head_pct=hp, delta=delta, crossed=_crossed(bp, hp, delta)))
    out.sort(key=lambda d: (-abs(d.delta), d.line_id))
    return out[:_TOP_LINES]


def _phase_deltas(
    base: OptimizeResult, head: OptimizeResult, b_ratings: dict[str, float], h_ratings: dict[str, float]
) -> list[PhaseDelta]:
    phases: list[PhaseDelta] = []
    for key in sorted(base.phases.keys() | head.phases.keys()):
        bp, hp = base.phases.get(key), head.phases.get(key)
        if bp is None or hp is None:
            continue  # only diff phases present on both runs
        b_over, h_over = set(bp.overloaded_line_ids), set(hp.overloaded_line_ids)
        mw_b = _mw_connected(bp, b_ratings)
        mw_h = _mw_connected(hp, h_ratings)
        phases.append(
            PhaseDelta(
                phase=key,
                worst_line_delta=round(hp.worst_line_loading_pct - bp.worst_line_loading_pct, 1),
                worst_trafo_delta=round(hp.worst_trafo_loading_pct - bp.worst_trafo_loading_pct, 1),
                min_vm_delta=round(hp.min_vm_pu - bp.min_vm_pu, 4),
                max_vm_delta=round(hp.max_vm_pu - bp.max_vm_pu, 4),
                newly_overloaded_line_ids=sorted(h_over - b_over),
                cleared_line_ids=sorted(b_over - h_over),
                top_line_deltas=_line_deltas(bp, hp),
                mw_connected_base=mw_b,
                mw_connected_head=mw_h,
                mw_connected_delta=round(mw_h - mw_b, 1),
            )
        )
    return phases


def _mw_by_phase_key(result: OptimizeResult, key: str, ratings: dict[str, float]) -> float:
    return _mw_connected(result.phases.get(key), ratings)


def _n_status(queue: list[QueueItem], statuses: set[str]) -> int:
    return sum(1 for q in queue if q.status in statuses)


def diff_results(base: OptimizeResult, head: OptimizeResult) -> ConsequenceDiff:
    """Diff two optimizer runs into a `ConsequenceDiff` (pure, deterministic)."""
    b_ratings, h_ratings = _ratings(base.queue), _ratings(head.queue)
    projects = _project_deltas(base.queue, head.queue)

    mw2030_b = _mw_by_phase_key(base, "2030", b_ratings)
    mw2030_h = _mw_by_phase_key(head, "2030", h_ratings)
    mw2035_b = _mw_by_phase_key(base, "2035", b_ratings)
    mw2035_h = _mw_by_phase_key(head, "2035", h_ratings)

    headline = {
        "mw_2030_base": mw2030_b,
        "mw_2030_head": mw2030_h,
        "mw_2030_delta": round(mw2030_h - mw2030_b, 1),
        "mw_2035_base": mw2035_b,
        "mw_2035_head": mw2035_h,
        "mw_2035_delta": round(mw2035_h - mw2035_b, 1),
        "n_connected_base": _n_status(base.queue, _CONNECTED),
        "n_connected_head": _n_status(head.queue, _CONNECTED),
        "n_deferred_base": _n_status(base.queue, {"Deferred"}),
        "n_deferred_head": _n_status(head.queue, {"Deferred"}),
        "n_accelerated": sum(1 for d in projects if d.change == "accelerated"),
        "n_slipped": sum(1 for d in projects if d.change == "slipped"),
        "n_added": sum(1 for d in projects if d.change == "added"),
        "n_dropped": sum(1 for d in projects if d.change == "dropped"),
    }

    return ConsequenceDiff(
        base_label=_label(base.params),
        head_label=_label(head.params),
        headline=headline,
        projects=projects,
        phases=_phase_deltas(base, head, b_ratings, h_ratings),
    )
