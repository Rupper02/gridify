"""Helpers every API test file shares: one TestClient, grid-agnostic fixtures derived from the live /model (never a
hardcoded bus id), and branch / run / job calls. Import after conftest has pointed the app at its throwaway store."""

import time

import pytest
from fastapi.testclient import TestClient

from gridforge_optimizer.config import PLAN_START_YEAR

from gridforge_api.config import WAREHOUSE
from gridforge_api.main import app

requires_warehouse = pytest.mark.skipif(not WAREHOUSE.exists(), reason="pipeline warehouse DB not materialized")

client = TestClient(app)


def buses() -> list[dict]:
    return client.get("/model").json()["buses"]


def stiff_bus():
    """The highest-voltage bus: found from the model, never hardcoded."""
    return max(buses(), key=lambda b: b["vn_kv"])["bus_id"]


def connection(**kw) -> dict:
    """A plain connection at the grid's top-voltage bus. What it does to the grid is the engine's to say: no test
    asserts it."""
    return {"name": "Acme", "bus_id": stiff_bus(), "technology": "solar", "rating_mw": 1.0, "year": PLAN_START_YEAR + 2, **kw}


def add_connection(branch_id: str, body: dict) -> dict:
    r = client.post(f"/branches/{branch_id}/connections", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def create_branch(name: str, from_branch: str = "main") -> dict:
    r = client.post("/branches", json={"name": name, "from_branch": from_branch})
    assert r.status_code == 200, r.text
    return r.json()


def branch(branch_id: str) -> dict:
    return client.get(f"/branches/{branch_id}").json()


def run(branch_id: str) -> dict:
    """Run a branch synchronously: every plan year."""
    r = client.post(f"/branches/{branch_id}/simulate")
    assert r.status_code == 200, r.text
    return r.json()


def wait_job(job: dict, timeout_s: float = 600.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while job["status"] in ("queued", "running"):
        assert time.monotonic() < deadline, "the job did not finish"
        time.sleep(0.25)
        job = client.get(f"/jobs/{job['job_id']}").json()
    assert job["status"] == "done", job.get("error")
    return job
