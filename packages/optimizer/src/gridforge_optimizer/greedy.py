"""The deterministic greedy 'ready and needed, first connected' queue optimizer."""

from __future__ import annotations

import pandapower as pp

from .config import MAX_CONNECTION_MW
from .network import (
    apply_growth,
    build_base_net,
    drop_sgen,
    feasibility,
    inject_sgen,
    overloaded_line_ids,
)
from .scoring import grid_need_from_solved
from .types import Candidate, OptimizeParams, OptimizeResult, PhaseResult, QueueItem, Reason

_PHASES = [(1, "2030", "growth_2030"), (2, "2035", "growth_2035")]
_STATUS = {1: "Phase1", 2: "Phase2"}


def _is_valid(c: Candidate) -> bool:
    return (
        c.status == "auto_accept"
        and c.bus_id is not None
        and c.rating_mw is not None
        and 0 < c.rating_mw <= MAX_CONNECTION_MW
    )


def optimize(candidates: list[Candidate], params: OptimizeParams | None = None) -> OptimizeResult:
    params = params or OptimizeParams()
    valid = [c for c in candidates if _is_valid(c)]
    rejected = [c for c in candidates if not _is_valid(c)]

    # one power flow under max growth to read 'need' at every candidate bus
    need_net = build_base_net()
    apply_growth(need_net, params.growth_2035)
    pp.runpp(need_net)
    need = {c.request_id: grid_need_from_solved(need_net, c.bus_id) for c in valid}

    def rank_score(c: Candidate) -> float:
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
        apply_growth(net, growth)
        for a in accepted_order:
            inject_sgen(net, a.bus_id, a.rating_mw, a.request_id, a.technology)

        for c in ranked:
            if c.request_id in accepted_phase:
                continue
            idx = inject_sgen(net, c.bus_id, c.rating_mw, c.request_id, c.technology)
            ok, reason, m = feasibility(net)
            if ok:
                accepted_phase[c.request_id] = phase_num
                accepted_order.append(c)
                worst_line_at_accept[c.request_id] = round(m.get("max_line_pct", 0.0), 1)
                last_reason[c.request_id] = None
            else:
                drop_sgen(net, idx)  # roll back the trial; keep eligibility for next phase
                last_reason[c.request_id] = reason

        # snapshot the grid state with all generators accepted so far
        _, _, m = feasibility(net)
        phases[phase_key] = PhaseResult(
            accepted=[a.request_id for a in accepted_order],
            worst_line_loading_pct=round(m.get("max_line_pct", 0.0), 1),
            worst_trafo_loading_pct=round(m.get("max_trafo_pct", 0.0), 1),
            min_vm_pu=round(m.get("min_vm", 0.0), 4),
            max_vm_pu=round(m.get("max_vm", 0.0), 4),
            overloaded_line_ids=overloaded_line_ids(net),
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
                worst_line_loading_pct=worst_line_at_accept.get(c.request_id),
            )
        )

    # rejected-at-triage projects appear at the end, with their triage reason
    for c in rejected:
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
                reason=Reason(type="rejected", message=c.review_reasons or "failed intake validation"),
            )
        )

    return OptimizeResult(params=params, queue=queue, phases=phases)
