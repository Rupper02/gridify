"""Keep the API suite fast: the per-year N-1 screen (ten years per run) is stubbed here; the greedy
run's N-1 screen still runs, and the engine suite tests the screen itself."""

import pytest

import gridforge_optimizer.years as years


@pytest.fixture(autouse=True)
def fast_year_n1(monkeypatch):
    monkeypatch.setattr(years, "n1_screen", lambda net, *a, **k: {"case": "winter_peak", "screened": 0, "violations": []})
