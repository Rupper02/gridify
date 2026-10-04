import pytest

from _grid import base_net, grid_deferred, saturating_candidates, stiff_bus
from gridforge_optimizer import Candidate, OptimizeParams, optimize, suggest_unblock
from gridforge_optimizer.suggest import discover_chain, phase_net


@pytest.fixture(scope="module")
def run():
    """One base run + one suggestion pass for the whole module (both are expensive)."""
    net = base_net()
    cands = [Candidate(request_id="ready_small", bus_id=stiff_bus(net), technology="solar",
                       rating_mw=5.0, readiness_score=0.9, strategic_fit=0.5)] + saturating_candidates(net, n=5)
    base = optimize(cands, OptimizeParams())
    return cands, base, suggest_unblock(cands, OptimizeParams(), base=base)


def _base():  # kept for readability in the tests below
    raise RuntimeError("use the `run` fixture")


def test_fixture_defers_on_the_grid(run):
    _, base, _ = run
    assert grid_deferred(base.queue), "saturating the weakest buses must produce a grid-constrained deferral"


def test_suggests_for_grid_deferred_only(run):
    _, base, sugs = run
    assert sugs
    deferred_ids = {q.request_id for q in base.queue if q.status == "Deferred"}
    for s in sugs:
        assert s.target_type in ("line", "trafo", "voltage")
        assert s.freed_mw_2035 >= 0.0
        assert s.extra_solves > 0
        assert set(s.blocked_project_ids) <= deferred_ids       # motivated by real deferrals
        assert set(s.newly_connected_project_ids) <= deferred_ids  # only ever frees deferred projects


def test_suggestions_propose_a_concrete_action(run):
    _, _, sugs = run
    # every suggestion proposes a concrete lever: a reinforcement chain or a voltage (reactive) action
    assert sugs and all(s.reinforcements or s.target_type == "voltage" for s in sugs)


def test_suggest_is_deterministic(run):
    cands, base, sugs = run
    again = [s.model_dump() for s in suggest_unblock(cands, OptimizeParams(), base=base)]
    assert [s.model_dump() for s in sugs] == again


def test_phase_net_and_the_chain_are_public_seams_for_the_studies(run):
    cands, base, _ = run
    accepted = base.phases["2035"].accepted
    assert accepted
    with_all = phase_net(cands, OptimizeParams(), base, "2035")
    without = phase_net(cands, OptimizeParams(), base, "2035", exclude=accepted[0])
    assert accepted[0] in set(with_all.sgen["name"]) and accepted[0] not in set(without.sgen["name"])
    assert len(without.sgen) == len(with_all.sgen) - 1
    reinf, connected, last, solves = discover_chain(cands, OptimizeParams(), base, grid_deferred(base.queue)[0].request_id)
    assert solves > 0 and (connected or last is not None)
    assert all(r.action == "add_parallel" for r in reinf)


def test_no_suggestions_when_nothing_deferred():
    net = base_net()
    cands = [Candidate(request_id="tiny", bus_id=stiff_bus(net), technology="solar",
                       rating_mw=1.0, readiness_score=0.9, strategic_fit=0.5)]
    base = optimize(cands, OptimizeParams())
    assert all(q.status != "Deferred" for q in base.queue)
    assert suggest_unblock(cands, OptimizeParams(), base=base) == []
