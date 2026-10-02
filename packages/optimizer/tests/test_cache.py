"""The trial cache is exact: cached and uncached runs give the same answer, and a re-run after one
project is added solves only the trials whose state changed."""

import pytest

from _grid import base_net, saturating_candidates, stiff_bus
from gridforge_optimizer import Candidate, OptimizeParams, engine_fingerprint, optimize
import gridforge_optimizer.greedy as greedy


@pytest.fixture
def count_feasibility(monkeypatch):
    calls = {"n": 0}
    real = greedy.feasibility

    def counting(net):
        calls["n"] += 1
        return real(net)

    monkeypatch.setattr(greedy, "feasibility", counting)
    return calls


def _strip(result):
    return result.model_dump(exclude={"params"})


def test_trial_cache_is_exact_and_reuses_the_unchanged_prefix(count_feasibility):
    net = base_net()
    cands = saturating_candidates(net, n=6)
    extra = Candidate(request_id="late_small", bus_id=stiff_bus(net), technology="solar", rating_mw=3.0,
                      readiness_score=0.05, strategic_fit=0.1)  # ranks last: every earlier trial is unchanged

    fresh = optimize(cands, OptimizeParams())
    n_fresh = count_feasibility["n"]

    cache: dict = {}
    count_feasibility["n"] = 0
    first = optimize(cands, OptimizeParams(), trial_cache=cache)
    assert _strip(first) == _strip(fresh)  # filling the cache changes nothing
    assert cache

    count_feasibility["n"] = 0
    again = optimize(cands, OptimizeParams(), trial_cache=cache)
    assert _strip(again) == _strip(fresh)
    # every trial came from the cache: only the two end-of-phase intact solves per phase remain
    assert count_feasibility["n"] <= 2 * len(greedy._PHASES)

    count_feasibility["n"] = 0
    grown = optimize(cands + [extra], OptimizeParams(), trial_cache=cache)
    n_grown = count_feasibility["n"]
    count_feasibility["n"] = 0
    grown_fresh = optimize(cands + [extra], OptimizeParams())
    assert _strip(grown) == _strip(grown_fresh)  # the incremental answer is the full answer
    assert n_grown < count_feasibility["n"]  # ...for fewer solves than starting over
    assert n_fresh > n_grown


def test_progress_is_reported_in_order():
    stages = []
    optimize(saturating_candidates(base_net(), n=2), OptimizeParams(), progress=lambda s, f: stages.append((s, f)))
    assert stages[0][0] == "ranking" and stages[-1] == ("done", 1.0)
    fractions = [f for _, f in stages]
    assert fractions == sorted(fractions)
    assert any("phase 2030" in s for s, _ in stages) and any("N-1" in s for s, _ in stages)


def test_engine_fingerprint_is_stable():
    a = engine_fingerprint()
    assert a == engine_fingerprint() and len(a) == 12 and int(a, 16) >= 0
