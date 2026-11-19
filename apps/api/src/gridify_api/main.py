"""Gridify API.

Serves the grid Gridify plans on (NGED Bicker Fen, read-only from the pipeline's DuckDB warehouse) and simulates its
branches through the plan years. Everything a user does is stored in a separate scenarios DB, so the pipeline
baseline is never mutated.

This module only assembles the app: `routers/` is the HTTP, `branches` the branch rules, `grid` the read-only grid,
`storage/` every SQL (the scenarios store and the warehouse), `compute/` everything that solves (plan runs, year runs,
the result cache, the job worker); `deps` wires them together.
"""

import math
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import MAIN_ID, log
from .deps import grid, jobs, plans, scenarios, warehouse
from .errors import DomainError, status_of
from .routers import branches, jobs as jobs_router, model, runs
from .storage.warehouse import LOCK_MEMORY_S, WarehouseBusy, request_state


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Startup: open + migrate the scenarios DB once (so the planner's first, concurrent requests never race on DDL),
    then warm the planner's first read (the model) and queue main's run as a real job the planner's first run joins (its
    first power flow also warms pandapower's numba JIT)."""
    scenarios.init()

    def _warm() -> None:
        try:
            if warehouse.exists():
                grid.model()
        except Exception:  # warming is best-effort; a broken network surfaces on the first real call
            log.exception("warm-up failed")

    jobs.submit(_warm)
    if warehouse.exists():
        try:
            plans.start_run(MAIN_ID)
        except Exception:
            log.exception("could not queue main's first run")
    yield
    jobs.shutdown()


app = FastAPI(title="Gridify API", lifespan=_lifespan)

SLOW_REQUEST_S = 0.5  # a request slower than this is logged: the planner feels it as a stall


@app.exception_handler(DomainError)
async def _domain_error(_request: Request, exc: DomainError) -> JSONResponse:
    """A domain layer's refusal (errors.py), answered with its status: the one place they meet HTTP."""
    return JSONResponse({"detail": exc.detail}, status_code=status_of(exc))


@app.middleware("http")
async def _json_errors(request: Request, call_next):
    """Turn an unhandled exception into a JSON 500. Registered BEFORE the CORS middleware so it sits inside it: the
    browser then sees CORS headers plus the reason, not an opaque CORS error."""
    state = request_state()  # which warehouse version this request read, and whether it was the fallback
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
        if state.get("snapshot"):
            response.headers["X-Warehouse-Snapshot"] = state["snapshot"]
            if state.get("stale"):
                response.headers["X-Warehouse-Stale"] = "1"  # one write behind: the pipeline was writing a new version
        took = time.perf_counter() - t0
        if took > SLOW_REQUEST_S:
            log.warning("slow request: %s %s took %.1f s", request.method, request.url.path, took)
        return response
    except WarehouseBusy as exc:  # the pipeline is writing and nothing was read before: a moment, not a failure
        return JSONResponse({"detail": str(exc)}, status_code=503, headers={"Retry-After": str(math.ceil(LOCK_MEMORY_S))})
    except Exception as exc:  # the one place a blind except is right: it's the last line of defence
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


# dev: permissive CORS so the planner works from any local host. Lock down in prod.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Warehouse-Snapshot", "X-Warehouse-Stale"])

for _router in (model.router, branches.router, jobs_router.router, runs.router):
    app.include_router(_router)
