"""Composition root: the one place the API's collaborators are constructed and wired together.

Routers import these instances; everything they are built from takes its dependencies as arguments,
so tests can build their own.
"""

import os
import threading

from gridforge_optimizer import engine_fingerprint

from . import config
from .agents.budget import BudgetMeter
from .agents.evidence import EvidenceLedger
from .agents.models import openrouter_model_factory
from .agents.runtime import AgentRuntime
from .cache import ResultCache
from .jobs import JobRunner
from .narration import NoNarrator, OpenRouterNarrator
from .service import PlanService
from .store import ScenarioStore
from .warehouse import Warehouse

warehouse = Warehouse(config.WAREHOUSE)
scenarios = ScenarioStore(config.SCENARIOS_URL or config.SCENARIOS)
# the engine fingerprint is a hash of the engine's source: a code change invalidates every cached result
cache = ResultCache(scenarios, warehouse, engine_fingerprint())
# one power flow at a time in this process: operator jobs and agent studies share the lock
solver_lock = threading.RLock()
jobs = JobRunner(solver_lock)
# without a key there is no narration and there are no agents: the substitute implementations, not exceptions swallowed
narrator = OpenRouterNarrator() if os.getenv("OPENROUTER_API_KEY") else NoNarrator()
plans = PlanService(warehouse, scenarios, cache, narrator)
evidence = EvidenceLedger(scenarios, cache)
budget = BudgetMeter(scenarios)
agents = AgentRuntime(store=scenarios, cache=cache, plans=plans, jobs=jobs, warehouse=warehouse, evidence=evidence, budget=budget,
                      model_factory=openrouter_model_factory(), system_db_url=config.DBOS_URL, app_version=config.AGENTS_APP_VERSION,
                      project_id=config.NGED_PROJECT_ID)
