"""Helpers every API test file shares: one TestClient, grid-agnostic fixtures derived from the live
/model (never a hardcoded bus id), and branch / run / job calls. Import after conftest has pointed the
app at its throwaway stores (pytest loads conftest first)."""

import time

import pytest
from fastapi.testclient import TestClient

from gridforge_api.config import WAREHOUSE
from gridforge_api.main import app

requires_warehouse = pytest.mark.skipif(not WAREHOUSE.exists(), reason="pipeline warehouse DB not materialized")

client = TestClient(app)


def buses() -> list[dict]:
    return client.get("/model").json()["buses"]


def stiff_bus():
    """The highest-voltage bus: found from the model, never hardcoded."""
    return max(buses(), key=lambda b: b["vn_kv"])["bus_id"]


def project(**kw) -> dict:
    """A plain connection project at the grid's top-voltage bus. Its outcome (accepted, deferred, when) is the
    engine's to decide: no test asserts it."""
    return {"applicant": "Acme", "bus_id": stiff_bus(), "technology": "solar", "rating_mw": 1.0, "readiness_score": 0.9, **kw}


def projects(n: int) -> list[dict]:
    """`n` plain projects on the `n` highest-voltage buses (outcomes are the engine's to decide)."""
    top = sorted(buses(), key=lambda b: (-b["vn_kv"], b["bus_id"]))[:n]
    return [project(applicant=f"P-{i}", bus_id=b["bus_id"]) for i, b in enumerate(top)]


def another_bus(than) -> int:
    return next(b["bus_id"] for b in sorted(buses(), key=lambda b: (-b["vn_kv"], b["bus_id"])) if b["bus_id"] != than)


def broken_project(**kw) -> dict:
    """A project at a bus that is not in the model: intake rejects it on any grid, whatever the physics."""
    return project(bus_id=max(b["bus_id"] for b in buses()) + 10_000, **kw)


def add_project(branch_id: str, body: dict) -> dict:
    r = client.post("/optimize/candidates", json={**body, "branch_id": branch_id})
    assert r.status_code == 200, r.text
    return r.json()


def create_branch(name: str, **kw) -> dict:
    r = client.post("/branches", json={"name": name, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def branch(branch_id: str) -> dict:
    return next(b for b in client.get("/branches").json()["branches"] if b["branch_id"] == branch_id)


def run(branch_id: str) -> dict:
    """Run a branch synchronously: the queue and every plan year (what the merge gate judges)."""
    path = "/optimize" if branch_id == "main" else f"/branches/{branch_id}/optimize"
    r = client.post(path, json={"with_justification": False})
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


def run_job(branch_id: str, **body) -> dict:
    """Run a branch as a background job and wait for it (the planner's path); returns the result."""
    job = client.post(f"/branches/{branch_id}/optimize/jobs", json={"with_justification": False, **body}).json()
    return wait_job(job)["result"]


def first_line() -> str:
    """The highest-voltage line's id, as the outage endpoints take it."""
    return str(max(client.get("/model").json()["lines"], key=lambda ln: ln["voltage_kv"])["line_id"])
