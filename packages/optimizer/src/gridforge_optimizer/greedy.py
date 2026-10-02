"""The deterministic greedy 'ready and needed, first connected' queue optimizer."""

from __future__ import annotations

import pandapower as pp

from .config import MAX_CONNECTION_MW
from .network import (
    apply_growth,
    apply_reinforcement,
    build_base_net,
    bus_voltages,
    drop_sgen,
    feasibility,
    inject_sgen,
    line_loadings,
    n1_screen,
    overloaded_line_ids,
    per_bus_growth,
    voltage_violation_bus_ids,
)
from .scoring import grid_need_from_solved
from .types import (
    Candidate,
    OptimizeParams,
    OptimizeResult,
    PhaseResult,
    QueueItem,
    Reason,
    Reinforcement,
)

_PHASES = [(1, "2030", "growth_2030"), (2, "2035", "growth_2035")]
_STATUS = {1: "Phase1", 2: "Phase2"}
# the year window the grid can actually host each phase's projects: Phase 1 lands by 2030, Phase 2
# across 2031-2035. The optimizer recommends an energisation year inside this window (nudged by the
# developer's requested year); deferred/rejected projects can't be hosted, so they get no year.
_REC_WINDOW = {"Phase1": (2027, 2030), "Phase2": (2031, 2035)}


def _recommended_year(requested: int | None, status: str) -> int | None:
    """The year the optimizer suggests a project energise: the developer's requested year clamped
    into the grid-feasible window for its phase. None when the grid can't host it (deferred/rejected)."""
    window = _REC_WINDOW.get(status)
    if window is None:
        return None
    base = requested if requested is not None else window[0] + 1
    return max(window[0], min(window[1], base))


def _is_valid(c: Candidate) -> bool:
    """A candidate is rankable only if it passed intake triage and has a usable bus + rating."""
    return (
        c.status == "auto_accept"
        and c.bus_id is not None
        and c.rating_mw is not None
        and 0 < c.rating_mw <= MAX_CONNECTION_MW
    )


def _grow(net, m: float, scenario: str, horizon: int) -> None:
    """Apply demand growth: per-bus (DFES pathway) unless scenario is 'custom' (uniform).
    Only demand grows here — no generation is pre-loaded: anything not connected today enters the
    study only as a queue project."""
    if scenario and scenario != "custom":
        apply_growth(net, per_bus_growth(net, m, scenario, horizon))
    else:
        apply_growth(net, m)


def optimize(
    candidates: list[Candidate],
    params: OptimizeParams | None = None,
    reinforcements: list[Reinforcement] | None = None,
) -> OptimizeResult:
    """Rank candidates by readiness + grid need + strategic fit, then connect them greedily.

    For each phase (2030, then 2035) demand is grown and every ranked project is trialled with a
    power-flow feasibility check; it is accepted only if voltages and line/transformer loadings stay
    within limits, else deferred with the binding constraint. Projects that failed intake triage are
    appended as Rejected. Returns the ordered queue plus per-phase network results.

    `reinforcements` (optional) simulate network upgrades applied to every solved net — the
    "accurate" mode behind the unblock suggestions (see suggest.py).
    """
    params = params or OptimizeParams()
    reinforcements = reinforcements or []

    # one power flow under max growth to read 'need' at every candidate bus
    need_net = build_base_net()
    _grow(need_net, params.growth_2035, params.scenario, 2035)
    for r in reinforcements:
        apply_reinforcement(need_net, r)
    pp.runpp(need_net)
    net_bus_ids = {int(b) for b in need_net.bus.index}

    # a candidate is rankable only if it passed intake AND its connection bus exists in the network.
    # a bus not in the model (e.g. a stale project after a network swap) is rejected, never injected.
    valid = [c for c in candidates if _is_valid(c) and int(c.bus_id) in net_bus_ids]
    valid_ids = {c.request_id for c in valid}
    rejected = [c for c in candidates if c.request_id not in valid_ids]
    need = {c.request_id: grid_need_from_solved(need_net, c.bus_id) for c in valid}

    def rank_score(c: Candidate) -> float:
        """Weighted blend of readiness, grid need, and strategic fit for this candidate."""
        return (
            params.w_readiness * c.readiness_score
            + params.w_need * need[c.request_id]
            + params.w_strategic * c.strategic_fit
        )

    ranked = sorted(
        valid,
        key=lambda c: (-rank_score(c), -c.readiness_score, c.rating_mw, c.request_id),
    )

    accepted_phase: dict[str, int] = {}
    accepted_order: list[Candidate] = []
    last_reason: dict[str, Reason | None] = {}
    worst_line_at_accept: dict[str, float | None] = {}
    phases: dict[str, PhaseResult] = {}

    for phase_num, phase_key, growth_attr in _PHASES:
        growth = getattr(params, growth_attr)
        # build the net ONCE per phase; keep accepted generators, trial the rest in place
        net = build_base_net()
        _grow(net, growth, params.scenario, int(phase_key))
        for r in reinforcements:
            apply_reinforcement(net, r)
        for a in accepted_order:
            inject_sgen(net, a.bus_id, a.rating_mw, a.request_id, a.technology, import_mw=a.import_mw)

        for c in ranked:
            if c.request_id in accepted_phase:
                continue
            idx = inject_sgen(net, c.bus_id, c.rating_mw, c.request_id, c.technology, import_mw=c.import_mw)
            ok, reason, m = feasibility(net)
            if ok:
                accepted_phase[c.request_id] = phase_num
                accepted_order.append(c)
                worst_line_at_accept[c.request_id] = round(m.get("max_line_pct", 0.0), 1)
                last_reason[c.request_id] = None
            else:
                drop_sgen(net, idx)  # roll back the trial; keep eligibility for next phase
                last_reason[c.request_id] = reason

        # snapshot the grid state with all generators accepted so far: the N-1 screen first (it
        # leaves outage results on the net), then the intact envelope the map and metrics read
        n1 = n1_screen(net)
        _, _, m = feasibility(net)
        phases[phase_key] = PhaseResult(
            accepted=[a.request_id for a in accepted_order],
            worst_line_loading_pct=round(m.get("max_line_pct", 0.0), 1),
            worst_trafo_loading_pct=round(m.get("max_trafo_pct", 0.0), 1),
            min_vm_pu=round(m.get("min_vm", 0.0), 4),
            max_vm_pu=round(m.get("max_vm", 0.0), 4),
            overloaded_line_ids=overloaded_line_ids(net),
            line_loading=line_loadings(net),
            bus_vm=bus_voltages(net),
            voltage_violation_bus_ids=voltage_violation_bus_ids(net),
            gsp_export_mw=m.get("gsp_export_mw", 0.0),
            gsp_import_mw=m.get("gsp_import_mw", 0.0),
            gsp_limit_mw=m.get("gsp_limit_mw"),
            n1_screened=n1["screened"],
            n1_violations=n1["violations"],
        )

    queue: list[QueueItem] = []
    for rank, c in enumerate(ranked, start=1):
        phase = accepted_phase.get(c.request_id)
        status = _STATUS.get(phase, "Deferred")
        queue.append(
            QueueItem(
                rank=rank,
                request_id=c.request_id,
                bus_id=c.bus_id,
                technology=c.technology,
                rating_mw=c.rating_mw,
                readiness_score=c.readiness_score,
                strategic_fit=c.strategic_fit,
                grid_need=need[c.request_id],
                rank_score=round(rank_score(c), 4),
                status=status,
                reason=None if status != "Deferred" else last_reason.get(c.request_id),
                commissioning_year=c.commissioning_year,
                recommended_year=_recommended_year(c.commissioning_year, status),
                worst_line_loading_pct=worst_line_at_accept.get(c.request_id),
                readiness_rationale=c.readiness_rationale,
            )
        )

    # rejected projects appear at the end, with a clear reason (intake failure or off-network bus)
    for c in rejected:
        if c.bus_id is None:
            reject_msg = "no point of connection given"
        elif int(c.bus_id) not in net_bus_ids:
            reject_msg = f"connection point bus {c.bus_id} is not in the network model"
        else:
            reject_msg = c.review_reasons or "failed intake validation"
        queue.append(
            QueueItem(
                rank=None,
                request_id=c.request_id,
                bus_id=c.bus_id,
                technology=c.technology,
                rating_mw=c.rating_mw,
                readiness_score=c.readiness_score,
                strategic_fit=c.strategic_fit,
                grid_need=0.0,
                rank_score=None,
                status="Rejected",
                reason=Reason(type="rejected", message=reject_msg),
                commissioning_year=c.commissioning_year,
                readiness_rationale=c.readiness_rationale,
            )
        )

    return OptimizeResult(params=params, queue=queue, phases=phases)
