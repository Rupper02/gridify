"""Composition root: the one place the API's collaborators are constructed and wired together.

Routers import these instances; everything they are built from takes its dependencies as arguments,
so tests can build their own.
"""

from gridforge_optimizer import engine_fingerprint

from . import config
from .cache import ResultCache
from .jobs import JobRunner
from .narration import OpenRouterNarrator
from .service import PlanService
from .store import ScenarioStore
from .warehouse import Warehouse

warehouse = Warehouse(config.WAREHOUSE)
scenarios = ScenarioStore(config.SCENARIOS_URL or config.SCENARIOS)
# the engine fingerprint is a hash of the engine's source: a code change invalidates every cached result
cache = ResultCache(scenarios, warehouse, engine_fingerprint())
jobs = JobRunner()
narrator = OpenRouterNarrator()
plans = PlanService(warehouse, scenarios, cache, narrator)
