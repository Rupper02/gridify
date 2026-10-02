from _grid import base_net, grid_deferred, invalid_bus, saturating_candidates, stiff_bus
from gridforge_optimizer import Candidate, OptimizeParams, optimize
from gridforge_optimizer.config import MAX_CONNECTION_MW


def _cands():
    net = base_net()
    sb = stiff_bus(net)
    extras = [
        Candidate(request_id="small_a", bus_id=sb, technology="solar", rating_mw=5.0, readiness_score=0.9, strategic_fit=0.8),
        Candidate(request_id="no_bus", bus_id=invalid_bus(net), technology="battery", rating_mw=2.0, status="needs_review", review_reasons="bus is not in model"),
        Candidate(request_id="too_big", bus_id=sb, technology="wind", rating_mw=MAX_CONNECTION_MW * 2, status="needs_review", review_reasons="rating is out of range"),
    ]
    return extras + saturating_candidates(net, n=8)


def test_optimize_accepts_small_defers_big_rejects_invalid():
    res = optimize(_cands(), OptimizeParams())
    by_id = {q.request_id: q for q in res.queue}
    assert by_id["small_a"].status in ("Phase1", "Phase2")  # a small project at the stiff infeed connects
    assert grid_deferred(res.queue)                          # saturating the weakest buses forces grid deferrals
    assert by_id["no_bus"].status == "Rejected"              # invalid bus -> intake reject
    assert by_id["too_big"].status == "Rejected"             # over the connection cap -> intake reject
    assert "2030" in res.phases and "2035" in res.phases


def test_off_network_bus_is_rejected_not_crashed():
    # a stale auto_accept project at a bus not in the network must reject cleanly, never crash inject_sgen
    net = base_net()
    cands = [Candidate(request_id="stale", bus_id=invalid_bus(net), technology="solar",
                       rating_mw=10.0, readiness_score=0.9, strategic_fit=0.8, status="auto_accept")]
    q = {x.request_id: x for x in optimize(cands, OptimizeParams()).queue}["stale"]
    assert q.status == "Rejected"
    assert q.reason and "not in the network model" in q.reason.message


def test_ranking_is_deterministic_and_sorted():
    order1 = [q.request_id for q in optimize(_cands(), OptimizeParams()).queue]
    order2 = [q.request_id for q in optimize(_cands(), OptimizeParams()).queue]
    assert order1 == order2
    ranked = [q for q in optimize(_cands(), OptimizeParams()).queue if q.rank_score is not None]
    scores = [q.rank_score for q in ranked]
    assert scores == sorted(scores, reverse=True)


def test_recommended_year_is_clamped_to_the_phase_window_and_none_when_blocked():
    from gridforge_optimizer.greedy import _recommended_year

    assert _recommended_year(2028, "Phase1") == 2028  # an early request the grid can meet stands
    assert _recommended_year(2033, "Phase1") == 2030  # Phase 1 lands by 2030
    assert _recommended_year(2028, "Phase2") == 2031  # Phase 2 can't energise before 2031
    assert _recommended_year(None, "Phase2") in range(2031, 2036)
    assert _recommended_year(2030, "Deferred") is None and _recommended_year(2030, "Rejected") is None


def test_queue_items_carry_a_recommended_year_only_when_accepted():
    res = optimize(saturating_candidates(base_net()), OptimizeParams())
    for q in res.queue:
        if q.status in ("Phase1", "Phase2"):
            assert q.recommended_year is not None
        else:
            assert q.recommended_year is None
