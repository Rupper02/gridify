"""The scenarios store on Postgres: the same API, the same SQL, a different engine.

Runs only when GRIDIFY_TEST_PG_URL points at a Postgres database the test may write to, e.g.
    GRIDIFY_TEST_PG_URL=postgresql://gridify@127.0.0.1:5499/gridify_test
"""

import os

import pytest
from fastapi.testclient import TestClient

from gridify_api import deps, main
from _support import connection, requires_warehouse

PG_URL = os.getenv("GRIDIFY_TEST_PG_URL")
pytestmark = [
    pytest.mark.skipif(not PG_URL, reason="set GRIDIFY_TEST_PG_URL to a writable Postgres database"),
    requires_warehouse,
]


@pytest.fixture
def pg_store():
    original = deps.scenarios.target
    deps.scenarios.use(PG_URL)
    with deps.scenarios.cursor() as con:  # start from a clean slate in the test database
        for t in ("result_cache", "connections", "branches"):
            con.execute(f"DROP TABLE IF EXISTS {t}")
    deps.scenarios.close()
    try:
        yield
    finally:
        deps.scenarios.use(original)


def test_branch_workflow_and_cache_on_postgres(pg_store):
    client = TestClient(main.app)
    assert client.get("/health").json()["scenarios_store"] == "postgres"
    assert [b["branch_id"] for b in client.get("/branches").json()["branches"]] == ["main"]  # seeded on first use
    bid = client.post("/branches", json={"name": "pg branch", "from_branch": "main"}).json()["branch_id"]
    c = client.post(f"/branches/{bid}/connections", json=connection(technology="battery", rating_mw=5.0, import_mw=4.0)).json()
    assert client.post(f"/branches/{bid}/simulate").status_code == 200
    with deps.scenarios.cursor() as con:
        assert con.dialect == "postgres"
        assert con.execute("SELECT count(*) FROM result_cache").fetchone()[0] >= 1
        assert con.execute("SELECT import_mw FROM connections WHERE request_id = ?", [c["request_id"]]).fetchone()[0] == 4.0
    assert client.post(f"/branches/{bid}/merge").status_code == 200
    assert c["request_id"] in {x["request_id"] for x in client.get("/branches/main/connections").json()}
