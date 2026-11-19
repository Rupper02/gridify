# AGENTS.md — apps/api (`gridify_api`)

FastAPI on :8000. Read the root `AGENTS.md` first (domain rules, design, testing stance); this file adds what is specific
to the API. The endpoint table is in `apps/api/README.md`.

## Layout

```
gridify_api/
  main.py  deps.py  config.py  errors.py  schemas.py  grid.py  branches.py
  routers/   model.py  branches.py  jobs.py  runs.py
  storage/   scenarios.py  repository.py  warehouse.py
  compute/   plans.py  year_runs.py  cache.py  jobs.py
```

- `main.py` only assembles the app (the lifespan warm-up, error mapping, CORS); `deps.py` is the composition root: the one
  place instances are built.
- `routers/` is HTTP only: each handler parses the request and calls one service method. No SQL, no scheduling.
- `branches.py` (`BranchService`): the branch rules (open, connections, profile, merge, discard; main is read-only).
- `grid.py` (`Grid`, `WarehouseNgedSource`): the grid every branch is on. The model, the registry and the snapshot id come
  from the pipeline's warehouse (the lineage is real); the network and the assumptions from the engine.
- `storage/` is the only code that runs SQL: `scenarios.py` (`ScenarioStore`, the `Cursor` dialect adapter, the schema and
  its migration), `repository.py` (branches and connections SQL, `require_open`, validation of a connection),
  `warehouse.py` (`Warehouse`, read-only).
- `compute/` is everything that solves or schedules a solve, under the one solver lock: `plans.py` (`PlanService`: a
  branch's inputs, starting or joining its run, the run through the cache, the payload, the diff), `year_runs.py`
  (`YearRuns`, a branch's whole year as a job; `RunViews`, the run files read-only), `cache.py` (`ResultCache`),
  `jobs.py` (`JobRunner`: one worker).
- `schemas.py` (request bodies); `errors.py` (domain refusals, mapped to a status once in `main.py`).

## Conventions

- **Storage.** The warehouse is read **read-only** (`GRIDIFY_DB_PATH`); a warehouse read runs on one read-only connection
  (one committed version), retries briefly while the pipeline writes, then serves the last consistent read or 503.
  Everything a user does goes to the scenarios store: `apps/api/data/scenarios.duckdb` (`GRIDIFY_SCENARIOS_DB`), or
  Postgres with `GRIDIFY_SCENARIOS_URL=postgresql://…`. `storage.scenarios.Cursor` translates `?`→`%s` and `DOUBLE`→`DOUBLE
  PRECISION`, so write DuckDB-style SQL with `?` placeholders and `ON CONFLICT` upserts, never `INSERT OR REPLACE` or
  `PRAGMA`. A schema change needs a migration in `storage.scenarios.migrate` (dialect-aware). Several writes that must land together
  go in `con.transaction()`.
- **Main is read-only.** Every connection edit goes through `storage.repository.require_open(..., allow_main=False)` (409 on
  `main` or a branch that is not open); the demand profile stays editable on `main`. Every connection change bumps the
  branch's `version`; a branch records its parent's at opening, and a merge is refused (409) once they differ.
- **Cache keys** include the demand profile, the connections (`compute.cache.connections_key`: every field the physics reads, and
  the year), the grid's baseline (the warehouse snapshot id) and the engine fingerprint (`ResultCache.key`). Every engine
  result is read through `ResultCache.through` (in-process dict → durable `result_cache` table → compute); plan years are
  also cached one by one (`ResultCache.year_cache`, by `years.year_signature`), so an edit re-solves only the years it
  touches. Any new cached computation must use `ResultCache.key`, or branches serve each other's results.
- **Long computations run on the single job worker** (`JobRunner.start(kind, fn(progress, publish), key=)`, polled at
  `GET /jobs/{id}`). A start whose `key` matches a queued or running job joins it. `publish(partial)` stores the years
  solved so far (`?partial=true&since=`). `POST /jobs/{id}/cancel` makes the next progress report raise `JobCancelled`.
  Keep the sync `POST /branches/{id}/simulate` for scripts and tests.
- **Solving is shared through one lock.** Anything that can solve goes through `ResultCache.through`, which takes the solver
  lock on a miss. A GET the planner issues around every run (`/result`, `/diff`) never solves the branch's own plan and
  never queues behind a run: `through(solve=False)` / `through(wait=False)` raise `errors.NotSolved` (409
  `{code: "not_solved", retry}`). Never call `through` while holding a store cursor (the store and the solver each have
  one lock).
- The log (`config.log`, INFO by default, `GRIDIFY_LOG_LEVEL`) says when a job starts and ends, what the cache computed
  and in how long, and any request slower than 0.5 s. Read it before reaching for py-spy.
