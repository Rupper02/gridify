"""Consequence diff: turn two `OptimizeResult`s into a human-legible delta.

Git diffs text; GridForge diffs *consequences*. Given a `base` and a `head` run of the
optimizer, this reports:
  - who moved   -> per-project status/rank change (accelerated / slipped / dropped / ...)
  - what unlocked -> MW connected by 2030 / 2035, base vs head
  - what lit up -> per-phase network deltas (lines that newly overload or clear, voltage band)
  - year by year -> the same network deltas for every plan year both runs solved (lines AND
    transformers, voltages, GSP export, N-1 findings, who is energised), so the planner can show
    the effect of the year it is looking at
  - planned works -> each of head's windows, its verdict on head against its verdict on the base
    plan (the same window studied on base's energised network), and the plain-English consequence

Pure and deterministic: no I/O, no pandapower. It only reshapes fields already present on the
two results (and, for the works, a list of studies the caller ran), so it is trivially
unit-testable and is the core of the branch / pull-request ("git for grids") workflow.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from .config import DIFF_NOISE, LINE_LOADING_MAX_PCT, TRAFO_LOADING_MAX_PCT
from .findings import n1_key
from .types import (
    VERDICT_SEVERITY,
    OptimizeParams,
    OptimizeResult,
    OutageStudy,
    PhaseResult,
    QueueItem,
    Reason,
    YearResult,
)

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

_TOP_LINES = 10  # how many biggest line (and transformer) movers to surface per phase / year
_TOP_N1 = 10  # how many new / cleared N-1 findings to list per year


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


class LoadingDelta(BaseModel):
    """One line's or transformer's loading in a year, base vs head (the kind is the list it sits in)."""

    element_id: int
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


class YearDelta(BaseModel):
    """The network effect of head against base in one plan year (both solved as fixed plans)."""

    year: int
    worst_line_base: float = 0.0
    worst_line_head: float = 0.0
    worst_line_delta: float = 0.0
    worst_trafo_base: float = 0.0
    worst_trafo_head: float = 0.0
    worst_trafo_delta: float = 0.0
    min_vm_delta: float = 0.0
    max_vm_delta: float = 0.0
    gsp_export_base: float = 0.0
    gsp_export_head: float = 0.0
    gsp_export_delta: float = 0.0
    gsp_limit_mw: float | None = None
    n1_findings_base: int = 0
    n1_findings_head: int = 0
    n1_findings_delta: int = 0
    # outages with no credible post-fault steady state (network.N1_COLLAPSE_VM_PU): one finding each, however many
    # elements the collapsed voltages take with them, so the counts above understate them
    n1_collapse_base: int = 0
    n1_collapse_head: int = 0
    n1_new: list[dict] = []  # head's N-1 findings absent on base (capped at _TOP_N1)
    n1_cleared: list[dict] = []  # base's N-1 findings head no longer has (capped at _TOP_N1)
    newly_overloaded_line_ids: list[int] = []
    cleared_line_ids: list[int] = []
    newly_overloaded_trafo_ids: list[int] = []
    cleared_trafo_ids: list[int] = []
    top_line_deltas: list[LoadingDelta] = []
    top_trafo_deltas: list[LoadingDelta] = []
    energised_only_head: list[str] = []  # in service this year on head but not on base
    energised_only_base: list[str] = []


class WorkDelta(BaseModel):
    """One of head's planned works windows: its verdict on head's plan against the same window
    studied on base's plan, and what that means in plain English."""

    outage_id: str
    year: int
    work: str = "maintenance"
    with_ids: list[str] = []
    verdict_on_main: str | None = None  # None = not studied on the base plan
    verdict_on_branch: str
    curtailed_mw_main: float | None = None
    curtailed_mw_branch: float = 0.0
    demand_at_risk_mw_main: float | None = None
    demand_at_risk_mw_branch: float = 0.0
    n1_findings_main: int | None = None  # second faults during the window on main's plan; None = not screened there
    n1_findings_branch: int | None = None
    n1_new: list[dict] = []  # second-fault findings the branch adds during the window (by n1_key), worst first
    n1_cleared: list[dict] = []  # second-fault findings main's plan has during the window and the branch's does not
    change: str = "unchanged"  # worse|better|unchanged|unstudied: what the branch's projects do to the window
    on_base: bool = True  # base schedules this window too; False = the branch adds it (its risk is new, whatever `change` says)
    consequence: str = ""
    message: str = ""  # the branch study's own summary


class ConsequenceDiff(BaseModel):
    base_label: str
    head_label: str
    headline: dict
    projects: list[ProjectDelta]
    phases: list[PhaseDelta]
    years: dict[str, YearDelta] = {}  # plan year -> its network delta (years solved on both runs)
    works: list[WorkDelta] = []  # head's planned works, verdict on base vs head


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


def _crossed(base_pct: float | None, head_pct: float | None, delta: float, limit: float = LINE_LOADING_MAX_PCT) -> str:
    b_over = base_pct is not None and base_pct > limit
    h_over = head_pct is not None and head_pct > limit
    if h_over and not b_over:
        return "newly_overloaded"
    if b_over and not h_over:
        return "cleared"
    if delta > DIFF_NOISE:
        return "worsened"
    if delta < -DIFF_NOISE:
        return "eased"
    return "unchanged"


def _line_deltas(base: PhaseResult, head: PhaseResult) -> list[LineDelta]:
    return [LineDelta(line_id=d.element_id, **d.model_dump(exclude={"element_id"}))
            for d in _loading_deltas(base.line_loading, head.line_loading, LINE_LOADING_MAX_PCT)]


def _loading_deltas(base: dict[int, float], head: dict[int, float], limit: float) -> list[LoadingDelta]:
    """The biggest movers between two loading maps (top _TOP_LINES by |delta|), plus every element
    that crosses the limit either way, so no new overload is ever cut off the list."""
    out: list[LoadingDelta] = []
    for eid in base.keys() | head.keys():
        bp, hp = base.get(eid), head.get(eid)
        delta = round((hp or 0.0) - (bp or 0.0), 1)
        out.append(LoadingDelta(element_id=int(eid), base_pct=bp, head_pct=hp, delta=delta,
                                crossed=_crossed(bp, hp, delta, limit)))
    out.sort(key=lambda d: (-abs(d.delta), d.element_id))
    top = out[:_TOP_LINES]
    top += [d for d in out[_TOP_LINES:] if d.crossed in ("newly_overloaded", "cleared")]
    return top


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
                top_line_deltas=_line_deltas(bp, hp)[:_TOP_LINES],
                mw_connected_base=mw_b,
                mw_connected_head=mw_h,
                mw_connected_delta=round(mw_h - mw_b, 1),
            )
        )
    return phases


# --- year by year ---------------------------------------------------------------------------------
def _over(loading: dict[int, float], limit: float) -> set[int]:
    return {int(i) for i, v in loading.items() if v is not None and v > limit}


def diff_year(base: YearResult, head: YearResult) -> YearDelta:
    """The network delta of one plan year, head against base (pure)."""
    b_over, h_over = set(base.overloaded_line_ids), set(head.overloaded_line_ids)
    bt_over = _over(base.trafo_loading, TRAFO_LOADING_MAX_PCT)
    ht_over = _over(head.trafo_loading, TRAFO_LOADING_MAX_PCT)
    b_n1 = {n1_key(v): v for v in base.n1_violations}
    h_n1 = {n1_key(v): v for v in head.n1_violations}
    return YearDelta(
        year=head.year,
        worst_line_base=base.worst_line_loading_pct,
        worst_line_head=head.worst_line_loading_pct,
        worst_line_delta=round(head.worst_line_loading_pct - base.worst_line_loading_pct, 1),
        worst_trafo_base=base.worst_trafo_loading_pct,
        worst_trafo_head=head.worst_trafo_loading_pct,
        worst_trafo_delta=round(head.worst_trafo_loading_pct - base.worst_trafo_loading_pct, 1),
        min_vm_delta=round(head.min_vm_pu - base.min_vm_pu, 4),
        max_vm_delta=round(head.max_vm_pu - base.max_vm_pu, 4),
        gsp_export_base=round(base.gsp_export_mw, 1),
        gsp_export_head=round(head.gsp_export_mw, 1),
        gsp_export_delta=round(head.gsp_export_mw - base.gsp_export_mw, 1),
        gsp_limit_mw=head.gsp_limit_mw,
        n1_findings_base=len(base.n1_violations),
        n1_findings_head=len(head.n1_violations),
        n1_findings_delta=len(head.n1_violations) - len(base.n1_violations),
        n1_collapse_base=sum(1 for v in base.n1_violations if v.get("type") == "collapse"),
        n1_collapse_head=sum(1 for v in head.n1_violations if v.get("type") == "collapse"),
        n1_new=[h_n1[k] for k in sorted(h_n1.keys() - b_n1.keys(), key=str)][:_TOP_N1],
        n1_cleared=[b_n1[k] for k in sorted(b_n1.keys() - h_n1.keys(), key=str)][:_TOP_N1],
        newly_overloaded_line_ids=sorted(h_over - b_over),
        cleared_line_ids=sorted(b_over - h_over),
        newly_overloaded_trafo_ids=sorted(ht_over - bt_over),
        cleared_trafo_ids=sorted(bt_over - ht_over),
        top_line_deltas=_loading_deltas(base.line_loading, head.line_loading, LINE_LOADING_MAX_PCT),
        top_trafo_deltas=_loading_deltas(base.trafo_loading, head.trafo_loading, TRAFO_LOADING_MAX_PCT),
        energised_only_head=sorted(set(head.energised) - set(base.energised)),
        energised_only_base=sorted(set(base.energised) - set(head.energised)),
    )


def diff_years(base_years: dict[str, YearResult], head_years: dict[str, YearResult]) -> dict[str, YearDelta]:
    """`diff_year` for every plan year solved on both runs (a year missing on either is skipped)."""
    return {k: diff_year(base_years[k], head_years[k]) for k in sorted(base_years.keys() & head_years.keys())}


# --- planned works --------------------------------------------------------------------------------
# what a verdict means, in words that finish "... on main" / "... on this branch"
_VERDICT_TEXT: dict[str, Callable[[OutageStudy], str]] = {
    "feasible": lambda s: "feasible",
    "curtailment": lambda s: f"needs {s.curtailed_mw:.1f} MW of curtailment",
    "demand_at_risk": lambda s: f"puts {s.demand_at_risk_mw:.1f} MW of demand at risk",
    "not_feasible": lambda s: "not feasible even with curtailment",
    "unstudied": lambda s: "not studied (the element is not in the network model)",
}


# the same, finishing "... on main's plan it would ..." (a window main does not schedule)
_VERDICT_WOULD: dict[str, Callable[[OutageStudy], str]] = {
    "feasible": lambda s: "be feasible",
    "curtailment": lambda s: f"need {s.curtailed_mw:.1f} MW of curtailment",
    "demand_at_risk": lambda s: f"put {s.demand_at_risk_mw:.1f} MW of demand at risk",
    "not_feasible": lambda s: "not be feasible even with curtailment",
    "unstudied": lambda s: "not be studied (the element is not in the network model)",
}


def _verdict_text(s: OutageStudy) -> str:
    return _VERDICT_TEXT.get(s.verdict, lambda _s: s.verdict.replace("_", " "))(s)


def _burden(s: OutageStudy) -> float:
    """Within one verdict, how much it costs: MW curtailed or MW of demand at risk."""
    return s.curtailed_mw + s.demand_at_risk_mw


def _n1_during(s: OutageStudy | None) -> dict[tuple, dict] | None:
    """A window's second-fault findings by identity, or None when the study ran without the screen."""
    if s is None or s.n1_during is None:
        return None
    return {n1_key(v): v for v in s.n1_during.violations}


def _work_n1(on_main: OutageStudy | None, on_branch: OutageStudy) -> tuple[list[dict], list[dict]]:
    """The second-fault findings the branch adds during the window and those it clears, when both
    sides were screened; the branch's own list stands when main's plan was not."""
    b, h = _n1_during(on_main), _n1_during(on_branch)
    if h is None:
        return [], []
    if b is None:
        return list(h.values()), []
    return [h[k] for k in h if k not in b], [b[k] for k in b if k not in h]


def _work_change(on_main: OutageStudy | None, on_branch: OutageStudy) -> str:
    """Worse or better by verdict first, then by MW curtailed or at risk, then by the second faults the
    branch adds or clears during the window (both sides screened)."""
    if on_main is None:
        return "unstudied"
    b, h = VERDICT_SEVERITY.get(on_main.verdict, 0), VERDICT_SEVERITY.get(on_branch.verdict, 0)
    if h != b:
        return "worse" if h > b else "better"
    step = _burden(on_branch) - _burden(on_main)
    if abs(step) >= DIFF_NOISE:
        return "worse" if step > 0 else "better"
    if _n1_during(on_main) is None or on_branch.n1_during is None:
        return "unchanged"
    new, cleared = _work_n1(on_main, on_branch)
    if new:
        return "worse"
    return "better" if cleared else "unchanged"


def _second_faults_text(new: list[dict], cleared: list[dict]) -> str:
    """What the branch does to the second faults during the window, in words (ids; the planner names them)."""
    parts = []
    if new:
        worst = new[0]
        parts.append(f"a second fault during the window adds {len(new)} problem{'s' if len(new) != 1 else ''} on this branch"
                     f" (the worst: {worst.get('outage_type')} {worst.get('outage_id')} out as well, {worst.get('message', '')})")
    if cleared:
        parts.append(f"this branch clears {len(cleared)} second-fault problem{'s' if len(cleared) != 1 else ''} main's plan has during the window")
    return "; ".join(parts)


def _new_window_consequence(on_main: OutageStudy | None, on_branch: OutageStudy, change: str) -> str:
    """A window only the branch schedules: its own cost leads (main does not carry it), then what the same
    window would cost on main's plan, i.e. what the branch's projects add to it."""
    here = _verdict_text(on_branch)
    faults = on_branch.n1_during.findings if on_branch.n1_during else 0
    lead = f"New on this branch: {here}" + (f", and a second fault during it finds {faults} problem{'s' if faults != 1 else ''}" if faults else "") + "."
    if on_main is None:
        return lead
    there = _VERDICT_WOULD.get(on_main.verdict, lambda s: f"be {_verdict_text(s)}")(on_main)
    if change == "unchanged":
        return f"{lead} Main does not schedule it; on main's plan it would {there} too, so the cost is the window's, not the projects'."
    return f"{lead} Main does not schedule it; on main's plan it would {there}, so the branch's projects make it {change}."


def _consequence(on_main: OutageStudy | None, on_branch: OutageStudy, change: str, new: list[dict] = (), cleared: list[dict] = ()) -> str:
    here = _verdict_text(on_branch)
    if on_main is None:
        return f"{here[:1].upper()}{here[1:]} on this branch (not studied on main's plan)."
    there = _verdict_text(on_main)
    there = there[:1].upper() + there[1:]
    faults = _second_faults_text(list(new), list(cleared))
    tail = f" {faults[:1].upper()}{faults[1:]}." if faults else ""
    if change == "unchanged":
        if on_branch.verdict == "feasible":
            return "Feasible on main and on this branch: the branch does not change this window."
        return f"{there}, on main and on this branch alike."
    same_verdict = on_main.verdict == on_branch.verdict and abs(_burden(on_branch) - _burden(on_main)) < DIFF_NOISE
    if same_verdict:
        return f"{there} on main and on this branch alike, but {faults}." if change == "worse" else f"{there} on main and on this branch alike; {faults}."
    if change == "worse":
        return f"{there} on main, but {here} on this branch.{tail}"
    return f"{there} on main; {here} on this branch.{tail}"


def diff_works(on_main: list[OutageStudy], on_branch: list[OutageStudy], scheduled_on_base: set[str] | None = None) -> list[WorkDelta]:
    """Each branch window (by outage id and year) against the same window studied on main's plan.
    `scheduled_on_base` is the outage ids main schedules itself (None = not known: every window counts
    as main's too); a window outside it is one the branch adds, and its consequence says so."""
    main_by = {(s.outage_id, s.year): s for s in on_main}
    out: list[WorkDelta] = []
    for s in sorted(on_branch, key=lambda s: (s.year, s.outage_id)):
        m = main_by.get((s.outage_id, s.year))
        change = _work_change(m, s)
        new, cleared = _work_n1(m, s)
        on_base = scheduled_on_base is None or s.outage_id in scheduled_on_base
        out.append(
            WorkDelta(
                outage_id=s.outage_id,
                year=s.year,
                work=s.work,
                with_ids=s.with_ids,
                verdict_on_main=m.verdict if m else None,
                verdict_on_branch=s.verdict,
                curtailed_mw_main=m.curtailed_mw if m else None,
                curtailed_mw_branch=s.curtailed_mw,
                demand_at_risk_mw_main=m.demand_at_risk_mw if m else None,
                demand_at_risk_mw_branch=s.demand_at_risk_mw,
                n1_findings_main=m.n1_during.findings if m and m.n1_during else None,
                n1_findings_branch=s.n1_during.findings if s.n1_during else None,
                n1_new=new,
                n1_cleared=cleared,
                change=change,
                on_base=on_base,
                consequence=_consequence(m, s, change, new, cleared) if on_base else _new_window_consequence(m, s, change),
                message=s.message,
            )
        )
    return out


def _studies(years: dict[str, YearResult]) -> list[OutageStudy]:
    return [s for y in years.values() for s in y.outage_studies]


# --- the diff -------------------------------------------------------------------------------------
def _mw_by_phase_key(result: OptimizeResult, key: str, ratings: dict[str, float]) -> float:
    return _mw_connected(result.phases.get(key), ratings)


def _n_status(queue: list[QueueItem], statuses: set[str]) -> int:
    return sum(1 for q in queue if q.status in statuses)


def diff_results(
    base: OptimizeResult, head: OptimizeResult, *, works_on_base: list[OutageStudy] | None = None
) -> ConsequenceDiff:
    """Diff two optimizer runs into a `ConsequenceDiff` (pure, deterministic).

    The per-year section covers the years present on both results (`OptimizeResult.years`). The
    works section lists head's windows; each is compared with `works_on_base` (head's windows
    studied on base's plan, which the caller solves) or, when that is not given, with the windows
    of the same id that base itself studied."""
    b_ratings, h_ratings = _ratings(base.queue), _ratings(head.queue)
    projects = _project_deltas(base.queue, head.queue)
    # the windows base schedules itself are the ones its own years studied (unknown when it has no years)
    scheduled_on_base = {s.outage_id for s in _studies(base.years)} if base.years else None
    works = diff_works(_studies(base.years) if works_on_base is None else works_on_base, _studies(head.years), scheduled_on_base)

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
        "n_works_worse": sum(1 for w in works if w.change == "worse"),
        "n_works_better": sum(1 for w in works if w.change == "better"),
        "n_works_new": sum(1 for w in works if not w.on_base),
    }

    return ConsequenceDiff(
        base_label=_label(base.params),
        head_label=_label(head.params),
        headline=headline,
        projects=projects,
        phases=_phase_deltas(base, head, b_ratings, h_ratings),
        years=diff_years(base.years, head.years),
        works=works,
    )
