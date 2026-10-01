from _grid import base_net, grid_deferred, saturating_candidates, stiff_bus
from gridforge_optimizer import Candidate, OptimizeParams, optimize, suggest_unblock


def _cands():
    net = base_net()
    return ([Candidate(request_id="ready_small", bus_id=stiff_bus(net), technology="solar",
                       rating_mw=5.0, readiness_score=0.9, strategic_fit=0.5)]
            + saturating_candidates(net, n=10))


def _base():
    cands = _cands()
    return cands, optimize(cands, OptimizeParams())


def test_fixture_defers_on_the_grid():
    _, base = _base()
    assert grid_deferred(base.queue), "saturating the weakest buses must produce a grid-constrained deferral"


def test_suggests_for_grid_deferred_only():
    cands, base = _base()
    sugs = suggest_unblock(cands, OptimizeParams(), base=base)
    assert sugs
    deferred_ids = {q.request_id for q in base.queue if q.status == "Deferred"}
    for s in sugs:
        assert s.target_type in ("line", "trafo", "voltage")
        assert s.freed_mw_2035 >= 0.0
        assert s.extra_solves > 0
        assert set(s.blocked_project_ids) <= deferred_ids       # motivated by real deferrals
        assert set(s.newly_connected_project_ids) <= deferred_ids  # only ever frees deferred projects


def test_suggestions_propose_a_concrete_action():
    cands, base = _base()
    sugs = suggest_unblock(cands, OptimizeParams(), base=base)
    # every suggestion proposes a concrete lever: a reinforcement chain or a voltage (reactive) action
    assert sugs and all(s.reinforcements or s.target_type == "voltage" for s in sugs)


def test_suggest_is_deterministic():
    cands, base = _base()
    a = [s.model_dump() for s in suggest_unblock(cands, OptimizeParams(), base=base)]
    b = [s.model_dump() for s in suggest_unblock(cands, OptimizeParams(), base=base)]
    assert a == b


def test_no_suggestions_when_nothing_deferred():
    net = base_net()
    cands = [Candidate(request_id="tiny", bus_id=stiff_bus(net), technology="solar",
                       rating_mw=1.0, readiness_score=0.9, strategic_fit=0.5)]
    base = optimize(cands, OptimizeParams())
    assert all(q.status != "Deferred" for q in base.queue)
    assert suggest_unblock(cands, OptimizeParams(), base=base) == []
