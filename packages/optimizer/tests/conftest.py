"""Shared test setup: keep the suite fast without weakening it.

The N-1 screen costs ~2 s per phase inside every `optimize()` call and is tested in its own right
(`test_physics.py`); everywhere else it is stubbed so the greedy/suggest/diff/cache tests pay for
the solves they are actually about. Mark a test `@pytest.mark.n1` to run the real screen.
"""

import pytest

import gridforge_optimizer.greedy as greedy
import gridforge_optimizer.years as years


@pytest.fixture(autouse=True)
def fast_n1(request, monkeypatch):
    if request.node.get_closest_marker("n1"):
        return
    stub = lambda net: {"case": "winter_peak", "screened": 0, "violations": []}  # noqa: E731
    monkeypatch.setattr(greedy, "n1_screen", stub)
    monkeypatch.setattr(years, "n1_screen", stub)
