"""The scenarios store on Postgres: the same API, the same SQL, a different engine.

Runs only when GRIDFORGE_TEST_PG_URL points at a Postgres database the test may write to, e.g.
    GRIDFORGE_TEST_PG_URL=postgresql://gridforge@127.0.0.1:5499/gridforge_test
Everything the API persists (branches, added projects, schedules, the durable result cache) goes
through the same `_scenarios()` cursor, so a short end-to-end pass is a real check of the dialect.
"""

import os

import pytest
from fastapi.testclient import TestClient

from gridforge_api import main

PG_URL = os.getenv("GRIDFORGE_TEST_PG_URL")
pytestmark = [
    pytest.mark.skipif(not PG_URL, reason="set GRIDFORGE_TEST_PG_URL to a writable Postgres database"),
    pytest.mark.skipif(not main.WAREHOUSE.exists(), reason="pipeline warehouse DB not materialized"),
]


@pytest.fixture
def pg_store():
    original = main.SCENARIOS_URL or main.SCENARIOS
    main._use_scenarios_db(PG_URL)
    # start from a clean slate in the test database
    with main._scenarios() as con:
        for t in ("result_cache", "added_candidates", "branches"):
            con.execute(f"DROP TABLE IF EXISTS {t}")
    main._SCEN_DB.close()
    main._SCEN_DB = None
    try:
        yield
    finally:
        main._use_scenarios_db(original)


def test_branch_workflow_and_cache_on_postgres(pg_store):
    client = TestClient(main.app)
    assert client.get("/health").json()["scenarios_store"] == "postgres"
    branches = client.get("/branches").json()["branches"]
    assert [b["branch_id"] for b in branches] == ["main"]  # seeded on first use

    stiff = max(client.get("/model").json()["buses"], key=lambda b: b["vn_kv"])["bus_id"]
    b = client.post("/branches", json={"name": "pg branch", "added_projects": [
        {"applicant": "Acme", "bus_id": stiff, "technology": "battery", "rating_mw": 5.0, "readiness_score": 0.9, "import_mw": 4.0},
    ]}).json()
    bid = b["branch_id"]
    assert b["n_added"] == 1

    q = client.post(f"/branches/{bid}/optimize", json={"with_justification": False}).json()
    item = next(x for x in q["queue"] if x["status"] in ("Phase1", "Phase2"))
    rid = item["request_id"]
    assert client.post(f"/branches/{bid}/schedule", json={"request_id": rid, "year": item["recommended_year"]}).status_code == 200
    again = client.post(f"/branches/{bid}/optimize", json={"with_justification": False}).json()
    assert next(x for x in again["queue"] if x["request_id"] == rid)["scheduled_year"] == item["recommended_year"]

    # the durable cache lives in Postgres too
    with main._scenarios() as con:
        assert con.dialect == "postgres"
        assert con.execute("SELECT count(*) FROM result_cache").fetchone()[0] >= 1
        assert "import_mw" in con.columns("added_candidates")
        assert con.execute("SELECT import_mw FROM added_candidates WHERE request_id = ?", [rid]).fetchone()[0] == 4.0

    merged = client.post(f"/branches/{bid}/merge", json={"into": "main"}).json()
    assert merged["branch_id"] == "main" and merged["n_added"] == 1
