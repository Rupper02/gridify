"""GridForge API.

Serves the grids GridForge plans on (the built-in NGED model, read-only from the pipeline's DuckDB
warehouse, and any grid imported as a project) and runs the connection-queue optimizer on their
branches. Everything a user does is stored in a separate scenarios DB, so the pipeline baseline is
never mutated.

This module only assembles the app: the work lives in `routers/` (HTTP), `service` (engine runs),
`repository` + `ledger` + `store` (scenarios DB), `warehouse` (read-only baseline), `cache`, `jobs`
and `narration`; `deps` wires them together.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import NGED_PROJECT_ID, log
from .deps import agents, jobs, plans, projects, scenarios, warehouse
from .routers import agents as agents_router
from .routers import branches, findings, model, optimize, registry, studies
from .routers import projects as projects_router  # aliased: `projects` here is the deps instance the warm-up uses


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Startup: open + migrate the scenarios DB once (so the planner's first, concurrent requests
    never race on DDL), then compute the built-in project's model and boundary card (the planner's first
    reads; the boundary's power flow warms pandapower's numba JIT) and pre-compute main on every demand profile."""
    scenarios.init()
    # the durable runtime: workflows interrupted by the last shutdown resume from their last step
    await asyncio.to_thread(agents.launch)  # off the event loop: DBOS's sync calls (register_queue, ...) refuse a running loop

    def _warm_reads() -> None:
        try:
            if warehouse.exists():
                # the planner's first reads, ready before it asks: the built-in project's model, then its boundary
                # card (a full power flow, which also warms pandapower's numba JIT)
                projects.model(NGED_PROJECT_ID)
                projects.boundary(NGED_PROJECT_ID)
            else:
                from gridforge_optimizer.network import build_base_net, feasibility
                feasibility(build_base_net())  # nothing to serve yet: still warm the JIT
        except Exception:  # warming is best-effort; a broken network surfaces on the first real call
            log.exception("warm-up failed")

    def _warm_rest() -> None:
        try:
            plans.warm_profiles("main", idle=jobs.idle)  # the other demand profiles, while nobody is waiting
            agents.emit_startup_events()  # a new snapshot since the last start wakes the steward
        except Exception:
            log.exception("warm-up failed")

    # the worker takes these in order: the reads, then main's run as a real job (the planner's first run asks for
    # the same and joins it, so it shows the run's progress rather than "queued" until a cached copy), then the rest
    jobs.submit(_warm_reads)
    if warehouse.exists():
        try:
            optimize.start_branch_run("main", with_justification=True)
        except Exception:
            log.exception("could not queue main's first run")
    jobs.submit(_warm_rest)
    yield
    await asyncio.to_thread(agents.destroy)
    jobs.shutdown()


app = FastAPI(title="GridForge API", lifespan=_lifespan)


@app.middleware("http")
async def _json_errors(request: Request, call_next):
    """Turn an unhandled exception into a JSON 500. Registered BEFORE the CORS middleware so it sits
    inside it: the browser then sees CORS headers plus the reason, not an opaque CORS error."""
    try:
        return await call_next(request)
    except Exception as exc:  # the one place a blind except is right: it's the last line of defence
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


# dev: permissive CORS so the planner works from any local host. Lock down in prod.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for _router in (model.router, registry.router, optimize.router, branches.router, findings.router, studies.router, projects_router.router, agents_router.router):
    app.include_router(_router)
