"""Shared test setup for the API suite: the scenarios DB is throwaway, set BEFORE anything imports the app. A solve of
a branch that has not been run costs 20-30 s: share one through the fixture below, and prefer asserting on what a run
already returned."""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("GRIDIFY_SCENARIOS_DB", str(Path(tempfile.mkdtemp()) / "scenarios.duckdb"))

import pytest


@pytest.fixture(scope="session")
def solved_branch():
    """A branch with one plain connection, solved once."""
    from _support import add_connection, connection, create_branch, run

    bid = create_branch("Shared: one connection")["branch_id"]
    add_connection(bid, connection())
    run(bid)
    return bid
