"""Composition root: the one place the API's collaborators are constructed and wired together.

Routers import these instances; everything they are built from takes its dependencies as arguments, so tests can
build their own.
"""

import threading

from gridify_optimizer import engine_fingerprint

from . import config
from .cache import ResultCache
from .grid import Grid, WarehouseNgedSource
from .jobs import JobRunner
from .service import PlanService
from .store import ScenarioStore
from .warehouse import Warehouse

warehouse = Warehouse(config.WAREHOUSE)
scenarios = ScenarioStore(config.SCENARIOS_URL or config.SCENARIOS)
# one power flow at a time in this process: jobs and every cache miss share the lock
solver_lock = threading.RLock()
# the engine fingerprint is a hash of the engine's source: a code change invalidates every cached result
cache = ResultCache(scenarios, engine_fingerprint(), solver_lock)
grid = Grid(WarehouseNgedSource(warehouse))
jobs = JobRunner(solver_lock)
plans = PlanService(grid, scenarios, cache)
