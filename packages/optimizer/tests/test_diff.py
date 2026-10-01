from _grid import base_net, stiff_bus
from gridforge_optimizer import (
    Candidate,
    OptimizeParams,
    OptimizeResult,
    PhaseResult,
    QueueItem,
    Reason,
    diff_results,
    optimize,
)


# --- synthetic results: exercise the classification logic exactly, no power flow ----------
def _qi(request_id, status, rank, rating, reason=None):
    return QueueItem(
        rank=rank,
        request_id=request_id,
        bus_id=1,
        technology="solar",
        rating_mw=rating,
        readiness_score=0.5,
        strategic_fit=0.5,
        grid_need=0.5,
        rank_score=0.5,
        status=status,
        reason=reason,
    )


def _phase(accepted, worst_line, worst_trafo, min_vm, max_vm, overloaded, line_loading):
    return PhaseResult(
        accepted=accepted,
        worst_line_loading_pct=worst_line,
        worst_trafo_loading_pct=worst_trafo,
        min_vm_pu=min_vm,
        max_vm_pu=max_vm,
        overloaded_line_ids=overloaded,
        line_loading=line_loading,
    )


def _synthetic_pair():
    base = OptimizeResult(
        params=OptimizeParams(),
        queue=[
            _qi("A", "Phase1", 1, 5.0),
            _qi("B", "Phase1", 2, 4.0),
            _qi("C", "Deferred", 3, 10.0, reason=Reason(type="voltage", message="weak bus")),
            _qi("D", "Phase2", 4, 3.0),
        ],
        phases={
            "2030": _phase(["A", "B"], 80.0, 70.0, 0.98, 1.02, [], {10: 80.0, 11: 50.0}),
            "2035": _phase(["A", "B", "D"], 95.0, 85.0, 0.96, 1.03, [11], {10: 90.0, 11: 105.0}),
        },
    )
    head = OptimizeResult(
        params=OptimizeParams(w_readiness=0.1, w_need=0.1, w_strategic=0.8),
        queue=[
            _qi("A", "Phase1", 2, 5.0),
            _qi("B", "Deferred", 3, 4.0, reason=Reason(type="line", message="line 12 over")),
            _qi("C", "Phase1", 1, 10.0),
            _qi("E", "Phase2", 4, 2.0),
        ],
        phases={
            "2030": _phase(["A", "C"], 85.0, 72.0, 0.97, 1.025, [12], {10: 82.0, 11: 48.0, 12: 101.0}),
            "2035": _phase(["A", "C", "E"], 92.0, 80.0, 0.95, 1.035, [], {10: 88.0, 11: 70.0, 12: 60.0}),
        },
    )
    return base, head


def test_classifies_every_kind_of_move():
    d = diff_results(*_synthetic_pair())
    by_id = {p.request_id: p for p in d.projects}
    assert by_id["A"].change == "moved_down"   # Phase1 both, rank 1 -> 2
    assert by_id["B"].change == "slipped"       # Phase1 -> Deferred
    assert by_id["C"].change == "accelerated"   # Deferred -> Phase1
    assert by_id["D"].change == "dropped"       # present in base, absent in head
    assert by_id["E"].change == "added"         # absent in base, present in head
    # the deferral reason is carried through for the "what would it take" hook
    assert by_id["B"].head_reason is not None and by_id["B"].head_reason.type == "line"
    assert by_id["C"].head_reason is None


def test_headline_counts_and_mw():
    d = diff_results(*_synthetic_pair())
    h = d.headline
    assert h["mw_2030_base"] == 9.0 and h["mw_2030_head"] == 15.0 and h["mw_2030_delta"] == 6.0
    assert h["mw_2035_base"] == 12.0 and h["mw_2035_head"] == 17.0 and h["mw_2035_delta"] == 5.0
    assert h["n_accelerated"] == 1 and h["n_slipped"] == 1
    assert h["n_added"] == 1 and h["n_dropped"] == 1


def test_phase_network_deltas():
    d = diff_results(*_synthetic_pair())
    phases = {p.phase: p for p in d.phases}
    assert 12 in phases["2030"].newly_overloaded_line_ids  # line 12 crosses 100% in head
    assert phases["2030"].cleared_line_ids == []
    assert 11 in phases["2035"].cleared_line_ids           # line 11 drops back under 100%
    # newly-overloaded and cleared are always disjoint
    for p in d.phases:
        assert not (set(p.newly_overloaded_line_ids) & set(p.cleared_line_ids))
    # biggest mover in 2030 is line 12 (0 -> 101), flagged newly_overloaded
    top = phases["2030"].top_line_deltas[0]
    assert top.line_id == 12 and top.crossed == "newly_overloaded"


# --- real optimizer runs: invariants + determinism ----------------------------------------
def _cands():
    # small projects at the stiff infeed bus so they connect; differing readiness vs strategic so
    # flipping the ranking weights reorders them (grid-agnostic).
    sb = stiff_bus(base_net())
    return [
        Candidate(request_id="ready_x", bus_id=sb, technology="solar", rating_mw=5.0, readiness_score=0.9, strategic_fit=0.1),
        Candidate(request_id="strat_y", bus_id=sb, technology="solar", rating_mw=5.0, readiness_score=0.1, strategic_fit=0.9),
        Candidate(request_id="mid_z", bus_id=sb, technology="battery", rating_mw=3.0, readiness_score=0.5, strategic_fit=0.5),
    ]


def _reweighted_pair():
    # same grid + scenario; only the ranking weights differ -> reordering is guaranteed
    b = optimize(_cands(), OptimizeParams(w_readiness=1.0, w_need=0.0, w_strategic=0.0))
    h = optimize(_cands(), OptimizeParams(w_readiness=0.0, w_need=0.0, w_strategic=1.0))
    return b, h


def test_reweighting_produces_movers_and_holds_invariants():
    b, h = _reweighted_pair()
    d = diff_results(b, h)
    # flipping readiness vs strategic weights must move at least one project
    assert any(p.change != "unchanged" for p in d.projects)
    # cumulative connected capacity never shrinks from 2030 to 2035
    assert d.headline["mw_2035_base"] >= d.headline["mw_2030_base"]
    assert d.headline["mw_2035_head"] >= d.headline["mw_2030_head"]
    # headline delta is internally consistent
    assert d.headline["mw_2030_delta"] == round(d.headline["mw_2030_head"] - d.headline["mw_2030_base"], 1)
    # overloaded/cleared stay disjoint on real data too
    for p in d.phases:
        assert not (set(p.newly_overloaded_line_ids) & set(p.cleared_line_ids))


def test_diff_is_deterministic():
    b, h = _reweighted_pair()
    assert diff_results(b, h).model_dump() == diff_results(b, h).model_dump()
