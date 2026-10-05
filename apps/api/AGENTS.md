# AGENTS.md — apps/api (`gridforge_api`)

FastAPI on :8000. Read the root `AGENTS.md` first (domain rules, design, testing stance); this file adds what is specific
to the API and the agent harness. The API table is in the root `README.md`.

## What it owns

### Projects
- `projects.py` (`Projects`): the grids planned on. One built in (`nged-bickerfen`, read through `WarehouseNgedSource`:
  the model, registry and snapshot id from the warehouse, the network from the engine) and any number imported
  (`POST /projects`, a multipart file + the operator's known limits → `sources.source_from_file` → `validate_net`; the
  file is kept under `apps/api/data/projects/<id>/`, `GRIDFORGE_PROJECTS_DIR`).
- Each project has its own main branch (`<id>-main`; NGED's is `main`), baseline (`Projects.baseline`: the snapshot id
  or the file fingerprint, in every cache key), model, element ids (what a proposal may name), boundary card and CIM
  export. The per-baseline caches live here, not in module globals, each computed once under its own lock however many
  requests ask at once.
- The lifespan's warm-up fills the built-in project's model and boundary, then queues main's own run as a real job
  (`routers.optimize.start_branch_run`, keyed by `PlanService.payload_key`) that the planner's first run joins, so it
  shows that run's progress instead of "queued", then the other demand profiles while nobody waits.
- `branches.project_id` says which project a branch belongs to; `/projects/{pid}/...` serves every project and the
  unprefixed `/model`, `/model/cgmes`, `/boundary`, `/registry`, `/optimize` are the NGED project's aliases.

### Storage
- Reads the warehouse **read-only** (`GRIDFORGE_DB_PATH` overrides it). Anything a user does goes to the scenarios store:
  branches, added projects, scheduled years, planned outages (`branch_outages`), simulated reinforcements
  (`branch_reinforcements`, both copied on branch create and merge by `repository.copy_branch_extras`) and the result cache.
- The scenarios store is `apps/api/data/scenarios.duckdb` by default (`GRIDFORGE_SCENARIOS_DB`), or Postgres when
  `GRIDFORGE_SCENARIOS_URL=postgresql://…` is set. `store.Cursor` translates `?`→`%s` and `DOUBLE`→`DOUBLE PRECISION`;
  everything else is common SQL, so write DuckDB-style SQL with `?` placeholders and `ON CONFLICT` upserts, never
  `INSERT OR REPLACE` or `PRAGMA`.
- Schema changes there need a migration (a `con.columns()` check + ALTER, dialect-aware) and, for per-project columns, an
  entry in `_ADDED_COLS` so they copy on branch create/merge.

### Branches, the gate and the ledger
- `GET /model/cgmes` serves the CIM export.
- Every mutation of a branch goes through `repository.require_open` (409 on a closed branch; projects, schedules, works
  and reinforcements also 409 on `main`, which changes only by merging; the demand profile stays editable on `main`).
- `GET /branches/{id}/merge-check` and `POST /branches/{id}/merge` apply the gate (409 `{code: "blocked" |
  "warnings_unacknowledged", message, verdict}`; every attempt lands in `merges`).
- `GET /branches/{id}/findings` and `POST /findings/{id}/ack` serve the ledger, which `PlanService.record_findings` writes
  after every run on the branch's own profile.

### Layout
- `main.py` only assembles the app; `routers/` is the HTTP layer (`model`, `registry`, `optimize`, `branches`, `findings`,
  `studies`, `projects`, `agents`).
- `service.py` (`PlanService`: engine runs, the per-year step, freshness and the merge check, the findings-ledger writes,
  suggestions, `study()`); `repository.py` (branches/projects/outages/reinforcements SQL and the `require_open` guard);
  `ledger.py` (findings and merge-audit SQL); `store.py` (`ScenarioStore`, schema + migrations); `warehouse.py`
  (`Warehouse`, read-only); `cache.py` (`ResultCache`); `narration.py` (`Narrator` protocol + summaries); `schemas.py`
  (request bodies).
- `jobs.py` (`JobRunner`: one worker, and the process-wide `solver_lock` every power flow, an operator's or an agent's,
  runs under; `busy()` lets agents yield to operators).
- `deps.py` is the composition root: the one place instances are built. It requires `OPENROUTER_API_KEY`
  (`config.require_openrouter_key`, a startup failure without it) and builds the `AgentRuntime` with
  `openrouter_model_factory(key)` and the `OpenRouterNarrator`: there is no key-less mode.

### The agent harness (`agents/`)
- `runtime.py`, `AgentRuntime`: the DBOS lifecycle, the queues `steward` (partitioned by project, one at a time) and
  `chat`, the built agents, status and the startup events.
- `roster.py`, the `AGENTS` registry (role, prompt, tool groups, typed output, studies in remit) and the output validators.
- `tools.py`, the `TOOL_GROUPS` (`read`, `studies`: one tool per `studies.STUDIES` entry, `proposals`: deferred,
  operator-approved), every call a recorded durable step (a study streams `progress` events as its chunks land, so the
  planner's chip is never silent), and `SolverGate` (operators first, then the process lock).
- `workflows.py`, the DBOS workflows `steward_run` → `specialist_run`, `review_branch`, `answer` / `answer_resume` and the
  `WORKFLOWS` registry.
- `events.py`, the `TRIGGERS` registry and `emit`, the one entry point routers call (`routers/optimize.py` after every run,
  `routers/branches.py` after a merge, the lifespan at startup).
- `streaming.py`, Pydantic AI events → the planner's trace (`STAGE_BY_TOOL_PREFIX`); `models.py`, the only OpenRouter
  import; `prompts.py`; `schemas.py`, the agents' typed outputs; `runs.py`, runs / reviews / approvals / events SQL;
  `evidence.py`, the step ledger every agent figure is bound to; `budget.py`, per-project daily caps and the pause
  switch; `threads.py`, operator conversations.
- `routers/agents.py`: status, pause, events, threads with an SSE stream, approvals, reviews, the audit trail.

### Agent contracts

The current contracts between the harness and the models. Like *Concurrency*, they are new and still being tried:
change them by proposal, not by working around them.

- Every agent run is told where it works: `tools.scope_instructions`, registered on every agent, gives the branch's name
  and id and what it was opened from, and says tools default to that branch. Never leave an agent to guess its branch.
- Agents read names, not indices: every tool payload goes through `name_payload` ("Bicker Fen to Boston 132 kV, circuit 2
  (line 1)", the id in brackets for proposals), and a payload about a branch carries `branch_id` and `branch_name`. The
  evidence ledger keeps the engine's own words.
- The prompt rules (`prompts.py`): answers start with what was found, never name the PLAN/ASSEMBLE/RUN steps (the planner
  shows them as chips), and never write a bare id (rule 7).
- A proposal applies the same engine rule as the study that recommended it: a resize scales a battery's import with
  `Candidate.import_at`, as `connection_options` probed it. When a study recommends a value, the proposal that applies it
  must not apply it differently.
- `agent_runs` is not the final word on a run's status: `AgentRuntime.reconcile` (at startup and on every status poll)
  closes the runs DBOS has already ended.
- The daily caps (`budget.py`, `AGENT_BUDGET_DAILY`) can pause the agents mid-day; one day of QA hit the token cap
  (`docs/reports/findings.md` #17). Check the agents pill before reading a missing answer as a bug.

## Conventions

- **Cache keys include the candidate-set hash, the project's baseline and the engine fingerprint** (`cache.cand_key`,
  `Projects.baseline(pid)` (the warehouse snapshot id for NGED, the file fingerprint for an import), `ResultCache.engine`
  → `ResultCache.key(kind, params, ckey, baseline, extra)`).
  - `BranchInputs` carries the branch's `project_id`, `baseline` and `net_factory` (the project's network with the
    branch's reinforcements), so `PlanService` never reaches for a global network.
  - Results live in the scenarios DB table `result_cache` (durable) and in `ResultCache.compute` / `.payload` (process).
    Any new cached computation must use `ResultCache.key`, or branches serve each other's results / stale physics
    survives a code change. The engine's `trial_cache` dicts are keyed the same way (`ResultCache.trial_cache`).
  - Branch reinforcements join the optimize key (`service.reinf_key`); the per-year results (kind `years`) add the
    outages and the schedule (`service.years_key`), so editing those re-solves the years but not the queue. The diff's
    planned-works study (kind `works`, `PlanService.works_on_plan`) keys the parent's plan with the branch's outages
    swapped in.
  - Every engine result is read through `ResultCache.through` (in-process dict → durable table → compute), and the merge
    gate's freshness is `ResultCache.has` on those same keys (`PlanService.freshness`): never derive it from timestamps.
  - Studies (`PlanService.study`) are cached the same way under `study:<kind>` with the study's parameters in the key, so
    a chunk (a study with its own parameters) caches on its own.
  - The payload's `run_key` is the plan-years key: the identity a review or an agent event refers to. Agent steps store
    the cache key of what they ran; `EvidenceLedger.replay` re-reads it and flags `stale` when the engine has changed.
- **Agent work is DBOS workflows** (`agents/workflows.py`): bounded by `config.AGENT_RUN_BUDGET`, idempotent by workflow
  id (`<workflow>:<dedup id>`, from `events.TRIGGERS`, so a cached re-run or a repeated event never wakes anyone twice),
  every side effect in a step.
  - `Harness.durable(name, fn)` is `DBOS.run_step` inside a workflow and a plain call outside one, so tools, validators
    and tests run without DBOS. Workflow code reads only its arguments and step outputs; collaborators come from the
    runtime (`workflows.RUNTIME`, set by `AgentRuntime.launch`), never from `deps`.
  - Every tool call goes through `tools._recorded` (an `agent_steps` row with its arguments and cache key, a payload that
    always carries `step_id`).
  - Agent solves go through `SolverGate`, taken **per chunk** of a study (`PlanService.study(hold=)`): an operator's job
    gets the solver between chunks, not after a whole hosting-capacity sweep. How solving is shared: see *Concurrency*.
  - A study outside an agent's remit or over its solve budget is refused in the tool's answer (a payload the model
    reads), never raised: a raised retry twice over ends the run. One failed specialist is a line in the steward's brief,
    not the end of the sweep.
  - A review is stored only while its run is still the branch's current one (`freshness().years_key`), so a slow review
    of an earlier run never becomes current.
  - A new agent is one `AgentSpec`, a new trigger one `Trigger`, a new study tool appears by itself from `studies.STUDIES`.
  - The SSE route reads the stream with DBOS's blocking reader in a worker thread, on purpose (the async reader shares
    one executor across event loops).
- **Long computations run on the single job worker** (`JobRunner.start(kind, fn(progress, publish), key=)`,
  `GET /jobs/{id}`); the planner polls.
  - A start whose `key` (what the job computes) matches a queued or running job joins it rather than queueing the same
    work behind it.
  - `publish(partial)` stores a partial result on the job record (`GET /jobs/{id}?partial=true`, `has_partial`): the
    optimize job publishes the queue, then each year as `evaluate_years(on_year=...)` lands, the body's `view_year` first.
  - Keep the sync endpoints too (tests and scripts use them).
  - The engine reports progress through `optimize(progress=...)` and `evaluate_years(progress=...)` (the API maps them to
    0..0.5 and 0.5..0.95, narration at 0.95); new long stages should call it (it is also where cancellation lands:
    `POST /jobs/{id}/cancel` makes the next progress report raise `JobCancelled`).
  - Plan years are cached by `years.year_signature` (`ResultCache.year_cache`), so an edit re-solves only the years it
    touches; a new input to a year's result must go into that signature.
- The agent runtime runs DBOS on `apps/api/data/dbos.sqlite` (`GRIDFORGE_DBOS_URL`; Postgres when the scenarios store is
  Postgres). Recovery after a restart is pinned to `GRIDFORGE_DBOS_APP_VERSION` (default: the engine fingerprint), so set
  it in dev to keep in-flight runs across `--reload` restarts.
- The tests set a placeholder key and swap the narrator for a scripted one (`tests/conftest.py`), and
  `tests/test_agents.py` runs scripted models (`FunctionModel`) on a temp DBOS database: nothing ever reaches OpenRouter
  from a test.

## Concurrency

How the one solver is shared today. These mechanisms are new (October 2026) and still being tried: if one gets in the
way, propose a better one rather than working around it.

- Anything that can solve goes through `ResultCache.through`: on a cache miss it takes the process solver lock and looks
  again once it has it. A route or an agent tool that calls the engine directly solves alongside a job, so both run at
  half speed and often compute the same result twice.
- Never call `through` (or anything that can solve) while holding a store cursor: the store and the solver each have one
  process lock, and a thread waiting for the solver with the store held deadlocks against a job that holds the solver and
  reads the store.
- Agents wait rather than fail: `SolverGate.hold` waits while an operator's job runs, for as long as the agent run's own
  time allows (`AgentDeps.deadline` = `AGENT_RUN_BUDGET.timeout_s` less `AGENT_ANSWER_RESERVE_S`), says so in the trace,
  and past the deadline the tool answers with a refusal the model reads (`SolverBusy`), never a raised timeout.
- A job waiting for another holder says "waiting for the solver" (`JobRunner._solver`), not "starting". The warm-up's
  model and boundary reads never take the lock; its other profiles take it per result like every cache miss, and main's
  first run is a job the planner's first run joins.

## Debugging

- `uvicorn --reload` sometimes misses an edit: if the log shows no "Reloading" after you save, restart the API.
- A stuck or slow solve: `uv tool run py-spy dump --pid <worker pid>`, where the worker is the child of the process
  listening on :8000. Two dumps a few seconds apart show who holds the solver and whether it is moving.
- Agent runs that look stuck: read DBOS's own state read-only (`sqlite3 "file:apps/api/data/dbos.sqlite?mode=ro"`, table
  `workflow_status`) and compare it with `agent_runs`.
