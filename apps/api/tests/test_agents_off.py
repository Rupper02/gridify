"""Without OPENROUTER_API_KEY the agents are off and nothing else changes: status says so, the agent
routes answer 503, runs and merges still emit their events into a no-op, and the model factory is None."""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("GRIDFORGE_SCENARIOS_DB", str(Path(tempfile.mkdtemp()) / "scenarios.duckdb"))

import pytest
from fastapi.testclient import TestClient

from gridforge_api import deps
from gridforge_api.agents import events
from gridforge_api.agents.models import openrouter_model_factory
from gridforge_api.config import WAREHOUSE
from gridforge_api.main import app

pytestmark = pytest.mark.skipif(not WAREHOUSE.exists(), reason="pipeline warehouse DB not materialized")

client = TestClient(app)
PROJECT = deps.agents.project_id


@pytest.fixture(autouse=True, scope="module")
def agents_off():
    """The runtime as a key-less deployment builds it: no model factory, never launched."""
    factory, launched = deps.agents.model_factory, deps.agents.launched
    if launched:
        deps.agents.destroy()
    deps.agents.model_factory = None
    yield
    deps.agents.model_factory = factory


def test_no_key_means_no_model_factory(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert openrouter_model_factory() is None


def test_status_is_off_and_the_rest_of_the_api_is_untouched():
    s = client.get(f"/projects/{PROJECT}/agents").json()
    assert s["status"] == "off" and s["enabled"] is False and "OPENROUTER_API_KEY" in s["reason"]
    assert client.get("/projects/nope/agents").status_code == 404
    # agent routes that need the runtime say why; the read-only ones answer empty
    r = client.post(f"/projects/{PROJECT}/threads", json={"title": "x"})
    assert r.status_code == 503 and r.json()["detail"]["agents"] == "off"
    assert client.post(f"/projects/{PROJECT}/events", json={"type": "run.finished", "payload": {}}).status_code == 503
    assert isinstance(client.get(f"/projects/{PROJECT}/threads").json()["threads"], list)  # read-only routes still answer
    assert isinstance(client.get(f"/projects/{PROJECT}/agents/runs").json()["runs"], list)
    assert client.get("/branches/main/reviews").json()["reviews"] == []
    assert client.get("/branches/nope/reviews").status_code == 404


def test_events_are_a_no_op_when_off():
    assert events.emit(deps.agents, "run.finished", {"branch_id": "br-x", "run_key": "k"}) is None
    assert events.emit(deps.agents, "branch.merged", {"branch_id": "br-x"}) is None
    with pytest.raises(KeyError):
        events.emit(deps.agents, "not.a.trigger", {})
    assert deps.agents.emit_startup_events() == []


def test_a_branch_run_and_merge_check_work_with_the_agents_off():
    bid = client.post("/branches", json={"name": "Off"}).json()["branch_id"]
    r = client.post(f"/branches/{bid}/optimize", json={"with_justification": False})
    assert r.status_code == 200 and r.json()["run_key"]
    mc = client.get(f"/branches/{bid}/merge-check")
    assert mc.status_code == 200 and "verdict" in mc.json()
    assert client.get(f"/projects/{PROJECT}/agents").json()["status"] == "off"
