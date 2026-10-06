"""Shared test setup for the API suite.

* The scenarios DB and the projects directory are throwaway, and the OpenRouter key is a placeholder
  (the app refuses to build without one), all set BEFORE anything imports the app. No test ever sends
  the key anywhere: the agents run scripted models (test_agents.py) and the narrator is swapped below.
* Keep the suite fast: the per-year N-1 screen (ten years per run) is stubbed here; the greedy run's
  N-1 screen still runs, and the engine suite tests the screen itself. What still costs 25-40 s is a
  full solve of a branch that has not been run: share one through a fixture below instead of
  creating a branch per test, and prefer asserting on what a run already returned.
"""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("OPENROUTER_API_KEY", "test-key-never-sent")
os.environ.setdefault("GRIDFORGE_SCENARIOS_DB", str(Path(tempfile.mkdtemp()) / "scenarios.duckdb"))
os.environ.setdefault("GRIDFORGE_PROJECTS_DIR", str(Path(tempfile.mkdtemp()) / "projects"))

import pytest

import gridforge_optimizer.years as years


class ScriptedNarrator:
    """The narration seam in tests: deterministic text, no network."""

    def justify(self, summary: str) -> str:
        return "scripted justification"

    def narrate_diff(self, summary: str) -> str:
        return "scripted diff narration"



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


# --- runs shared across the suite ---------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def project_branch():
    """A branch with one plain project, solved once. Tests may edit it (a schedule, a works window) so long as
    they put it back: an edit re-solves the years it touches, never the queue."""
    from _support import create_branch, project, run

    bid = create_branch("Shared: one project", added_projects=[project()])["branch_id"]
    run(bid)
    return bid
