"""Shared test setup for the API suite.

* The OpenRouter key is mandatory for the app (deps refuses to build without it), so the suite sets a
  placeholder BEFORE the app is imported; no test ever sends it anywhere: the agents run scripted
  models (test_agents.py) and the narrator is swapped for a scripted one below.
* Keep the suite fast: the per-year N-1 screen (ten years per run) is stubbed here; the greedy run's
  N-1 screen still runs, and the engine suite tests the screen itself.
"""

import os

os.environ.setdefault("OPENROUTER_API_KEY", "test-key-never-sent")

import pytest

import gridforge_optimizer.years as years


class ScriptedNarrator:
    """The narration seam in tests: deterministic text, no network."""

    def justify(self, summary: str) -> str:
        return "scripted justification"

    def narrate_diff(self, summary: str) -> str:
        return "scripted diff narration"

    def narrate_suggestion(self, summary: str) -> str:
        return "scripted suggestion narration"


@pytest.fixture(autouse=True, scope="session")
def scripted_narrator():
    from gridforge_api import deps

    real = deps.plans.narrator
    deps.plans.narrator = ScriptedNarrator()
    yield
    deps.plans.narrator = real


@pytest.fixture(autouse=True)
def fast_year_n1(monkeypatch):
    monkeypatch.setattr(years, "n1_screen", lambda net, *a, **k: {"case": "winter_peak", "screened": 0, "violations": []})
    monkeypatch.setattr(years, "n1_screen_cases", lambda net, *a, **k: {"cases": [], "screened": 0, "violations": []})
