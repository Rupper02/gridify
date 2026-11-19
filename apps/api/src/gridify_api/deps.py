"""Composition root: the one place the API's collaborators are constructed and wired together.

Routers import these instances; everything they are built from takes its dependencies as arguments, so tests can
build their own.
"""

import threading

from gridify_optimizer import engine_fingerprint
from gridify_optimizer.runs import RunFiles

from . import config
from .branches import BranchService
from .compute.cache import ResultCache
from .compute.jobs import JobRunner
from .compute.plans import PlanService
from .compute.year_runs import RunViews, YearRuns
from .grid import Grid, WarehouseNgedSource
from .storage.scenarios import ScenarioStore
from .storage.warehouse import Warehouse

warehouse = Warehouse(config.WAREHOUSE)
scenarios = ScenarioStore(config.SCENARIOS_URL or config.SCENARIOS)
# one power flow at a time in this process: jobs and every cache miss share the lock
solver_lock = threading.RLock()
# the engine fingerprint is a hash of the engine's source: a code change invalidates every cached result
engine = engine_fingerprint()
cache = ResultCache(scenarios, engine, solver_lock)
grid = Grid(WarehouseNgedSource(warehouse))
jobs = JobRunner(solver_lock)
plans = PlanService(grid, scenarios, cache, jobs)
branches = BranchService(scenarios, grid)
# the year view's run files, under the grid's own catalogue and network
run_files = RunFiles(config.RUNS_DIR, grid.source.run_catalogue(), grid.build_net)
run_views = RunViews(run_files, engine)
year_runs = YearRuns(plans, grid, cache, run_files, jobs)
