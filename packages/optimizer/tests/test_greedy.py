from gridforge_optimizer import Candidate, OptimizeParams, optimize


def _cands():
    return [
        Candidate(request_id="small_a", bus_id=120, technology="solar", rating_mw=4.5, readiness_score=0.9, strategic_fit=0.8),
        Candidate(request_id="small_b", bus_id=200, technology="solar", rating_mw=3.0, readiness_score=0.5, strategic_fit=0.6),
        Candidate(request_id="big_weak", bus_id=155, technology="wind", rating_mw=18.0, readiness_score=0.6, strategic_fit=0.7),
        Candidate(request_id="no_bus", bus_id=250, technology="battery", rating_mw=2.0, status="needs_review", review_reasons="bus is not in model"),
        Candidate(request_id="too_big", bus_id=42, technology="wind", rating_mw=850.0, status="needs_review", review_reasons="rating is out of range"),
    ]


def test_optimize_accepts_small_defers_big_rejects_invalid():
    res = optimize(_cands(), OptimizeParams())
    by_id = {q.request_id: q for q in res.queue}
    assert by_id["small_a"].status in ("Phase1", "Phase2")
    assert by_id["big_weak"].status == "Deferred"
    assert by_id["big_weak"].reason is not None
    assert by_id["no_bus"].status == "Rejected"
    assert by_id["too_big"].status == "Rejected"
    assert "2030" in res.phases and "2035" in res.phases


def test_ranking_is_deterministic_and_sorted():
    order1 = [q.request_id for q in optimize(_cands(), OptimizeParams()).queue]
    order2 = [q.request_id for q in optimize(_cands(), OptimizeParams()).queue]
    assert order1 == order2
    ranked = [q for q in optimize(_cands(), OptimizeParams()).queue if q.rank_score is not None]
    scores = [q.rank_score for q in ranked]
    assert scores == sorted(scores, reverse=True)
