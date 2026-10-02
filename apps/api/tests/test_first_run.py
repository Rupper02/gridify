"""First-run smoke test: a brand-new scenarios DB must survive the planner's concurrent boot.

The planner fires /optimize, /branches and the read endpoints together as soon as it loads. On an
empty scenarios DB that used to race on CREATE TABLE and 500 (a DuckDB catalog write-write
conflict), and the 500 carried no CORS headers, so the browser only ever saw a CORS error.
"""

import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gridforge_api import deps, main
from gridforge_api.config import WAREHOUSE

pytestmark = pytest.mark.skipif(
    not WAREHOUSE.exists(), reason="pipeline warehouse DB not materialized"
)


@pytest.fixture
def fresh_db():
    """Point the API at an empty scenarios DB for one test, then restore the suite's DB."""
    original = deps.scenarios.target
    deps.scenarios.use(Path(tempfile.mkdtemp()) / "fresh.duckdb")
    try:
        yield
    finally:
        deps.scenarios.use(original)


def test_concurrent_first_requests_on_an_empty_scenarios_db(fresh_db):
    # no `with`: the lifespan does NOT run, like a cold process whose first requests arrive together
    client = TestClient(app := main.app)
    calls = [
        lambda: client.post("/optimize", json={"with_justification": False}),
        lambda: client.get("/branches"),
        lambda: client.get("/registry"),
        lambda: client.post("/optimize", json={"with_justification": False}),
        lambda: client.get("/branches"),
        lambda: client.post("/branches", json={"name": "race"}),
    ]
    with ThreadPoolExecutor(max_workers=len(calls)) as ex:
        results = list(ex.map(lambda f: f(), calls))
    for r in results:
        assert r.status_code == 200, r.text
    branches = client.get("/branches").json()["branches"]
    assert len([b for b in branches if b["branch_id"] == "main"]) == 1  # seeded exactly once
    assert app is main.app


def test_unhandled_errors_are_json_500s_with_cors_headers(monkeypatch):
    def boom():
        raise RuntimeError("warehouse exploded")

    monkeypatch.setattr(deps.warehouse, "baseline_model", boom)
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.get("/model", headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == "*"  # the browser can read the error
    assert "warehouse exploded" in r.json()["detail"]
