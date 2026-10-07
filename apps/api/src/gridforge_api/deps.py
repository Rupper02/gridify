"""Composition root: the one place the API's collaborators are constructed and wired together.

Routers import these instances; everything they are built from takes its dependencies as arguments,
so tests can build their own.
"""

import threading

from gridforge_optimizer import engine_fingerprint

from . import config
from .agents.spend import SpendMeter
from .agents.evidence import EvidenceLedger
from .agents.models import openrouter_model_factory
from .agents.runtime import AgentRuntime
from .cache import ResultCache
from .jobs import JobRunner
from .projects import Projects
from .service import PlanService
from .store import ScenarioStore
from .warehouse import Warehouse

# the key every model call needs: GridForge does not start without it (no degraded, key-less mode)
openrouter_key = config.require_openrouter_key()
warehouse = Warehouse(config.WAREHOUSE)
scenarios = ScenarioStore(config.SCENARIOS_URL or config.SCENARIOS)
# one power flow at a time in this process: operator jobs, agent studies and every cache miss share the lock
solver_lock = threading.RLock()
# the engine fingerprint is a hash of the engine's source: a code change invalidates every cached result
cache = ResultCache(scenarios, engine_fingerprint(), solver_lock)
# the grids planned on: the built-in NGED project from the warehouse, and every imported file
projects = Projects(scenarios, warehouse, config.PROJECTS_DIR, config.NGED_PROJECT_ID)
jobs = JobRunner(solver_lock)
plans = PlanService(projects, scenarios, cache)
evidence = EvidenceLedger(scenarios, cache)
spend = SpendMeter(scenarios)
agents = AgentRuntime(store=scenarios, cache=cache, plans=plans, jobs=jobs, warehouse=warehouse, projects=projects, evidence=evidence, spend=spend,
                      model_factory=openrouter_model_factory(openrouter_key), system_db_url=config.DBOS_URL, app_version=config.AGENTS_APP_VERSION,
                      project_id=config.NGED_PROJECT_ID)
