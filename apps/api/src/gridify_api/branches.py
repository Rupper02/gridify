"""Branches and the connections on them: open, edit, set the demand profile, merge and discard.

The rules (main is read-only, a registry project is placed with its own facts, a profile must be a known pathway) live
here; the SQL is `storage.repository`'s and the HTTP is `routers.branches`'s. A model read never happens under the store
lock, so the bus ids a connection is checked against are read before the cursor is taken."""

from __future__ import annotations

from .compute.plans import plan_params
from .config import now
from .errors import Invalid, NotFound
from .grid import Grid
from .storage import repository
from .storage.scenarios import ScenarioStore

_FROM_REGISTRY = ("name", "bus_id", "technology", "rating_mw", "import_mw", "year")  # what a registry project brings


class BranchService:
    def __init__(self, store: ScenarioStore, grid: Grid):
        self.store = store
        self.grid = grid

    def list(self) -> list[dict]:
        """Every branch, main first."""
        with self.store.cursor() as con:
            return repository.list_branches(con)

    def get(self, branch_id: str) -> dict:
        with self.store.cursor() as con:
            return repository.branch_to_client(con, repository.require_branch(con, branch_id))

    def open(self, name: str, from_branch: str) -> dict:
        """Open a branch off another (copy-on-create: its connections and demand profile come along)."""
        with self.store.cursor() as con:
            parent = repository.require_branch(con, from_branch)
            return repository.branch_to_client(con, repository.open_branch(con, parent, name))

    # --- connections ---------------------------------------------------------------------------------------------
    def connections(self, branch_id: str) -> list[dict]:
        with self.store.cursor() as con:
            repository.require_branch(con, branch_id)
            return [repository.to_client(r) for r in repository.connection_rows(con, branch_id)]

    def add_connection(self, branch_id: str, fields: dict, from_registry: str | None = None) -> dict:
        """Place a connection: by hand, or a registry project with any field given here overriding its own."""
        request_id, source = None, "manual"
        if from_registry:
            reg = next((r for r in self.grid.registry() if r["request_id"] == from_registry), None)
            if reg is None:
                raise NotFound(f"'{from_registry}' is not in the registry")
            fields = {**{k: reg[k] for k in _FROM_REGISTRY if reg.get(k) is not None}, **fields}
            request_id, source = reg["request_id"], "registry"
        bus_ids = self.grid.bus_ids()
        with self.store.cursor() as con:
            repository.require_open(con, branch_id, allow_main=False)
            return repository.insert_connection(con, branch_id, fields, bus_ids, source=source, request_id=request_id)

    def change_connection(self, branch_id: str, request_id: str, changes: dict) -> dict:
        bus_ids = self.grid.bus_ids()
        with self.store.cursor() as con:
            repository.require_open(con, branch_id, allow_main=False)
            return repository.update_connection(con, branch_id, request_id, changes, bus_ids)

    def remove_connection(self, branch_id: str, request_id: str) -> None:
        with self.store.cursor() as con:
            repository.require_open(con, branch_id, allow_main=False)
            repository.delete_connection(con, branch_id, request_id)

    # --- demand profile ------------------------------------------------------------------------------------------
    def set_profile(self, branch_id: str, scenario: str, growth_2030: float | None, growth_2035: float | None) -> dict:
        """A pathway, or `custom` with both anchors. Editable on main too: it is how today's network is studied, not a
        change to it."""
        if scenario == "custom" and (growth_2030 is None or growth_2035 is None):
            raise Invalid("a custom profile needs both anchors (growth_2030, growth_2035)")
        with self.store.cursor() as con:
            row = repository.require_open(con, branch_id)
            profile = {"scenario": scenario,
                       "growth_2030": growth_2030 if growth_2030 is not None else row["growth_2030"],
                       "growth_2035": growth_2035 if growth_2035 is not None else row["growth_2035"]}
            plan_params(profile)  # an unknown pathway is refused here, by the same rule a run reads it with
            repository.set_profile(con, branch_id, profile)
            return repository.branch_to_client(con, repository.require_branch(con, branch_id))

    # --- merge and discard ---------------------------------------------------------------------------------------
    def merge(self, branch_id: str) -> dict:
        """The parent adopts the branch's connections and demand profile, and the branch closes."""
        with self.store.cursor() as con:
            head = repository.require_open(con, branch_id, allow_main=False)
            parent = repository.require_open(con, head["parent_id"])
            repository.merge_into(con, head, parent)
        return {"merged": branch_id, "into": parent["branch_id"], "at": now()}

    def discard(self, branch_id: str) -> dict:
        with self.store.cursor() as con:
            repository.require_open(con, branch_id, allow_main=False)
            repository.set_status(con, branch_id, "discarded")
        return {"discarded": branch_id}
