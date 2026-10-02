"""The deterministic greedy 'ready and needed, first connected' queue optimizer."""

from __future__ import annotations

from typing import Any, Callable

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
    set_tap_positions,
    tap_positions,
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


Progress = Callable[[str, float], None]
NetFactory = Callable[[], Any]  # builds a fresh base network (default: today's NGED network)


def _sig(c: Candidate) -> tuple:
    """What a trial's outcome depends on, per project."""
    return (c.request_id, c.bus_id, c.rating_mw, c.import_mw, c.technology)


class _Run:
    """One greedy run: rank the candidates, then trial them phase by phase against the power flow.

    The steps are separate methods (`rank`, `run_phase`, `_trial`, `build_queue`) that share the
    run's state; `optimize()` just sequences them."""

    def __init__(self, candidates: list[Candidate], params: OptimizeParams,
                 reinforcements: list[Reinforcement], net_factory: NetFactory,
                 trial_cache: dict | None, report: Progress):
        self.candidates = candidates
        self.params = params
        self.reinforcements = reinforcements
        self.net_factory = net_factory
        self.trial_cache = trial_cache
        self.report = report
        self.reinf_key = tuple((r.kind, r.element_id, r.action, r.factor) for r in reinforcements)

        self.ranked: list[Candidate] = []
        self.rejected: list[Candidate] = []
        self.net_bus_ids: set[int] = set()
        self.need: dict[str, float] = {}
        self.accepted_phase: dict[str, int] = {}
        self.accepted_order: list[Candidate] = []
        self.last_reason: dict[str, Reason | None] = {}
        self.worst_line_at_accept: dict[str, float | None] = {}

    def _study_net(self, growth: float, horizon: int):
        """A fresh network grown to `horizon` with the simulated reinforcements applied."""
        net = self.net_factory()
        _grow(net, growth, self.params.scenario, horizon)
        for r in self.reinforcements:
            apply_reinforcement(net, r)
        return net

    def rank_score(self, c: Candidate) -> float:
        """Weighted blend of readiness, grid need, and strategic fit for this candidate."""
        return (
            self.params.w_readiness * c.readiness_score
            + self.params.w_need * self.need[c.request_id]
            + self.params.w_strategic * c.strategic_fit
        )

    def rank(self) -> None:
        """Order the rankable candidates; set aside the rest as rejected."""
        # one power flow under max growth to read 'need' at every candidate bus
        need_net = self._study_net(self.params.growth_2035, 2035)
        pp.runpp(need_net)
        self.net_bus_ids = {int(b) for b in need_net.bus.index}

        # a candidate is rankable only if it passed intake AND its connection bus exists in the network.
        # a bus not in the model (e.g. a stale project after a network swap) is rejected, never injected.
        valid = [c for c in self.candidates if _is_valid(c) and int(c.bus_id) in self.net_bus_ids]
        valid_ids = {c.request_id for c in valid}
        self.rejected = [c for c in self.candidates if c.request_id not in valid_ids]
        self.need = {c.request_id: grid_need_from_solved(need_net, c.bus_id) for c in valid}
        self.ranked = sorted(
            valid,
            key=lambda c: (-self.rank_score(c), -c.readiness_score, c.rating_mw, c.request_id),
        )

    def _trial(self, net, c: Candidate, phase_key: str, settled: bool) -> tuple[bool, Reason | None, float, bool]:
        """Try one project on `net`: (accepted, reason, worst line %, whether a real solve ran).

        The outcome is a function of (phase, what was accepted before it, the project, the
        scenario), so it is looked up in the trial cache before solving. An accepted trial leaves its
        generator and settled taps on the net; a rejected one leaves no trace."""
        tkey = (phase_key, self.reinf_key, tuple(_sig(a) for a in self.accepted_order), _sig(c))
        hit = self.trial_cache.get(tkey) if self.trial_cache is not None else None
        if hit is not None and (settled or not hit[0]):
            ok, reason, max_line, taps_after = hit
            if ok:
                inject_sgen(net, c.bus_id, c.rating_mw, c.request_id, c.technology, import_mw=c.import_mw)
                set_tap_positions(net, taps_after)
            return ok, reason, max_line, False

        taps_before = tap_positions(net)
        idx = inject_sgen(net, c.bus_id, c.rating_mw, c.request_id, c.technology, import_mw=c.import_mw)
        ok, reason, m = feasibility(net)
        max_line = round(m.get("max_line_pct", 0.0), 1)
        if ok:
            taps_after = tap_positions(net)
        else:
            drop_sgen(net, idx)  # roll back the trial; keep eligibility for next phase
            set_tap_positions(net, taps_before)  # a rejected trial leaves no trace
            taps_after = taps_before
        if self.trial_cache is not None:
            self.trial_cache[tkey] = (ok, reason, max_line, taps_after)
        return ok, reason, max_line, True

    def run_phase(self, phase_i: int, phase_num: int, phase_key: str, growth_attr: str) -> PhaseResult:
        """Trial every not-yet-accepted project at this phase's demand; snapshot the resulting grid."""
        n_phases = len(_PHASES)
        # build the net ONCE per phase; keep accepted generators, trial the rest in place
        net = self._study_net(getattr(self.params, growth_attr), int(phase_key))
        for a in self.accepted_order:
            inject_sgen(net, a.bus_id, a.rating_mw, a.request_id, a.technology, import_mw=a.import_mw)
        settled = False  # taps are regulated by the first real solve of the phase

        todo = [c for c in self.ranked if c.request_id not in self.accepted_phase]
        for i, c in enumerate(todo):
            self.report(f"phase {phase_key}: trial {i + 1}/{len(todo)}",
                        (phase_i + 0.1 + 0.7 * i / max(len(todo), 1)) / n_phases)
            ok, reason, max_line, solved = self._trial(net, c, phase_key, settled)
            settled = settled or solved
            if ok:
                self.accepted_phase[c.request_id] = phase_num
                self.accepted_order.append(c)
                self.worst_line_at_accept[c.request_id] = max_line
                self.last_reason[c.request_id] = None
            else:
                self.last_reason[c.request_id] = reason

        # snapshot the grid state with all generators accepted so far: the N-1 screen first (it
        # leaves outage results on the net), then the intact envelope the map and metrics read
        self.report(f"phase {phase_key}: intact state", (phase_i + 0.82) / n_phases)
        feasibility(net)  # settles taps for the final state (also when every trial was cached)
        self.report(f"phase {phase_key}: N-1 screen", (phase_i + 0.86) / n_phases)
        n1 = n1_screen(net)
        _, _, m = feasibility(net)
        return PhaseResult(
            accepted=[a.request_id for a in self.accepted_order],
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

    def build_queue(self) -> list[QueueItem]:
        """The ranked projects with their verdicts, then the rejected ones with a clear reason."""
        queue: list[QueueItem] = []
        for rank, c in enumerate(self.ranked, start=1):
            phase = self.accepted_phase.get(c.request_id)
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
                    grid_need=self.need[c.request_id],
                    rank_score=round(self.rank_score(c), 4),
                    status=status,
                    reason=None if status != "Deferred" else self.last_reason.get(c.request_id),
                    commissioning_year=c.commissioning_year,
                    recommended_year=_recommended_year(c.commissioning_year, status),
                    worst_line_loading_pct=self.worst_line_at_accept.get(c.request_id),
                    readiness_rationale=c.readiness_rationale,
                )
            )

        # rejected projects appear at the end, with a clear reason (intake failure or off-network bus)
        for c in self.rejected:
            if c.bus_id is None:
                reject_msg = "no point of connection given"
            elif int(c.bus_id) not in self.net_bus_ids:
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
        return queue


def optimize(
    candidates: list[Candidate],
    params: OptimizeParams | None = None,
    reinforcements: list[Reinforcement] | None = None,
    *,
    trial_cache: dict | None = None,
    progress: Progress | None = None,
    net_factory: NetFactory = build_base_net,
) -> OptimizeResult:
    """Rank candidates by readiness + grid need + strategic fit, then connect them greedily.

    For each phase (2030, then 2035) demand is grown and every ranked project is trialled with a
    power-flow feasibility check; it is accepted only if voltages and line/transformer loadings stay
    within limits, else deferred with the binding constraint. Projects that failed intake triage are
    appended as Rejected. Returns the ordered queue plus per-phase network results.

    `reinforcements` (optional) simulate network upgrades applied to every solved net — the
    "accurate" mode behind the unblock suggestions (see suggest.py).

    `trial_cache` (optional, a dict the caller keeps) memoises each trial's outcome by
    (phase, the projects accepted before it, the project). A trial is a pure function of that
    state, so when a branch gains one project every trial up to its rank is served from the cache
    and only the suffix is solved again: "re-trial what changed", exactly. The caller must key the
    dict by network snapshot, parameters and engine version. `progress(stage, fraction)` is called
    as the run advances.

    `net_factory` supplies the base network (default: the bundled NGED network); pass another to
    run the same algorithm on a different grid.
    """
    params = params or OptimizeParams()
    report = progress or (lambda _s, _f: None)
    run = _Run(candidates, params, reinforcements or [], net_factory, trial_cache, report)

    report("ranking", 0.02)
    run.rank()
    phases = {
        phase_key: run.run_phase(phase_i, phase_num, phase_key, growth_attr)
        for phase_i, (phase_num, phase_key, growth_attr) in enumerate(_PHASES)
    }
    queue = run.build_queue()
    report("done", 1.0)
    return OptimizeResult(params=params, queue=queue, phases=phases)
