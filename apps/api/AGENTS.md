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
- A warehouse read runs on one read-only connection (one committed version); a route that reads several things reads
  them together (`Warehouse.read(key, fn)`). While the pipeline writes, a read retries ~1.5 s, then serves the last
  consistent read of the same thing (kept with its `snapshot_id`, one write behind at most) or 503 when there is none;
  every response that read the warehouse says which version (`X-Warehouse-Snapshot`) and whether it was the previous
  one (`X-Warehouse-Stale: 1`), and the planner's result stamp says so. Never catch an error as "older warehouse":
  check the table or column.
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
  (`Warehouse`, read-only); `cache.py` (`ResultCache`); `schemas.py`
  (request bodies).
- `jobs.py` (`JobRunner`: one worker, and the process-wide `solver_lock` every power flow, an operator's or an agent's,
  runs under; `busy()` lets agents yield to operators).
- `deps.py` is the composition root: the one place instances are built. It requires `OPENROUTER_API_KEY`
  (`config.require_openrouter_key`, a startup failure without it) and builds the `AgentRuntime` with
  `openrouter_model_factory(key)`: there is no key-less mode.

### The agent harness (`agents/`)
- `runtime.py`, `AgentRuntime`: the DBOS lifecycle, the queues `digest` (partitioned by project: one note at a time) and
  `chat`, the built agents, status and the startup events.
- `roster.py`, the `AGENTS` registry: two roles. `answerer` (read, study and proposal tools, free text or deferred
  proposals) and `digest` (no tools, free text: the engineer's note from the engine's digest).
- `tools.py`, the `TOOL_GROUPS` (`read`: `limits` first, then the overview, queue, plan years, findings and the merge
  check; `studies`: one tool per `studies.STUDIES` entry; `proposals`: deferred, operator-approved), every call a recorded
  durable step (a study streams `progress` events as its chunks land, so the planner's chip is never silent),
  and `SolverGate` (operators first, then the process lock).
- `workflows.py`, the DBOS workflows `digest_run`, `answer` / `answer_resume` and the `WORKFLOWS` registry.
- `events.py`, the `TRIGGERS` registry and `emit`, the one entry point routers call (`routers/optimize.py` after every run,
  `routers/branches.py` after a merge, the lifespan at startup). Only `run.finished` starts work.
- `streaming.py`, Pydantic AI events → the planner's trace (`STAGE_BY_TOOL_PREFIX`); `models.py`, the only OpenRouter
  import; `prompts.py`; `citations.py`, one citation shape; `runs.py`, runs / notes / approvals / events SQL;
  `evidence.py`, the step ledger an answer's figures are checked against; `spend.py`, what the agents spent per project
  and day (OpenRouter's billed cost from each response's `provider_details["cost"]`) and the pause switch; `threads.py`,
  operator conversations.
- `routers/agents.py`: status, pause, events, threads with an SSE stream, approvals, the note, the audit trail.

### Agent contracts

The contracts between the harness and the models. Change them by proposal, not by working around them.

- **The model never reads a table.** The engine solves; `gridforge_optimizer.analysis` reduces a run to the binding set,
  the chains, the clusters and the digest; the model phrases a digest (the note) or plans typed queries (the answerer).
  Anything that looks like a model summarising rows is a bug: reduce first, in the engine, deterministically.
- **The note** (`digest_run`): woken by `run.finished` (main's runs included; a run whose physics is its parent's,
  `run_key == parent_run_key`, wakes nobody), deduplicated by `run:{branch}:{run_key}`. Its one step computes
  `PlanService.digest` under the solver gate (the parent's side may need solving), one model call writes at most 150
  words, `check_numbers(note, [digest])` flags every digit figure the digest does not hold, and the note is stored in
  `run_notes` for the branch's current `run_key`, superseding the previous one; a note whose run the branch moved past
  is never stored, and a note still being written when a newer run lands is cancelled (`runs.open_runs_of`).
- Every answer run is told where it works: `tools.scope_instructions` gives the branch's name and id and what it was
  opened from, and says tools default to that branch. Never leave an agent to guess its branch.
- Agents read names, not indices: every tool payload goes through `name_payload` ("Bicker Fen to Boston 132 kV, circuit 2
  (line 1)", the id in brackets for proposals), and a payload about a branch carries `branch_id` and `branch_name`. The
  evidence ledger keeps the engine's own words.
- The prompt rules (`prompts.py`): answers start with what was found, read `limits` before any study, never name the
  PLAN/ASSEMBLE/RUN steps (the planner shows them as chips), and never write a bare id (rule 7).
- Citations are one shape: `[step <full step_id>]` inline after the figure, or `[same step]`. Every stored text goes
  through `citations.normalize_citations` with the run's step ids: an abbreviated id is completed, a bracket that cites
  nothing recorded is dropped. The planner renders the chips (`lib/markdown.ts`), so never store a raw bracket of another
  shape. Run summaries are stripped of citations (`strip_citations`).
- A reply's proposals are its approval rows (tool and arguments); the planner phrases them as one card to approve or deny
  (`lib/ask.ts` `PROPOSAL_TEXT`), so the message keeps only the model's own words. A proposal applies the same engine
  rule as the study that recommended it: a resize scales a battery's import with `Candidate.import_at`, as
  `connection_options` probed it.
- `agent_runs` is not the final word on a run's status: `AgentRuntime.reconcile` (at startup and on every status poll)
  closes the runs DBOS has ended, and cancels and closes the ones left pending under another application version.
- No daily cap: whoever runs GridForge pays with their own OpenRouter key, so spend is recorded and shown ("spent $X today
  · $Y in all"), never a stop. Only the operator's Pause stops the agents. Per run, `AGENT_RUN_BUDGET` ends a looping run
  (tool calls, solves, tokens, wall time) and each model response is capped at `max_output_tokens`. Token events stream
  only for a run someone reads (an answer, through the SSE route): the note's tokens go nowhere (`streaming.on_event`).
- `events.emit` enqueues workflows: call it from workflow code, never inside a step (DBOS refuses a child workflow
  from a step; the event row it writes is idempotent by its dedup id).

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
    a chunk (a study with its own parameters) caches on its own. A study of the network alone (`needs_plan` false:
    hosting capacity) is keyed without the candidates, the profile or the schedule (`PlanService.study_key`), so
    branches with the same reinforcements share it; `study(..., solve=False)` (the route's `?cached=true`) only reads.
  - The payload's `run_key` is the plan-years key: the identity a note or an agent event refers to. Agent steps store
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
    reads), never raised: a raised retry twice over ends the run.
  - A note is stored only while its run is still the branch's current one (`freshness().years_key`), so a slow note
    on an earlier run never becomes current.
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
    0..0.5 and 0.5..0.95, then "writing findings" at 0.96); new long stages should call it (it
    is also where cancellation lands: `POST /jobs/{id}/cancel` makes the next progress report raise `JobCancelled`).
    The ledger write is one transaction (`Cursor.transaction`) of multi-row INSERTs (`ledger._BATCH`: DuckDB pays
    ~15 ms a statement, and 1,400 single-row upserts held the store's lock, and every read of it, for 20 s), and a
    poll that names the partial it has (`?since=`) is not sent it again. Never loop `execute`/`executemany` over hundreds of rows under the store's lock.
  - Plan years are cached by `years.year_signature` (`ResultCache.year_cache`), so an edit re-solves only the years it
    touches; a new input to a year's result must go into that signature.
- The agent runtime runs DBOS on `apps/api/data/dbos.sqlite` (`GRIDFORGE_DBOS_URL`; Postgres when the scenarios store is
  Postgres). Recovery after a restart is pinned to `GRIDFORGE_DBOS_APP_VERSION` (default: the engine fingerprint), so set
  it in dev to keep in-flight runs across `--reload` restarts. A run whose workflow was left pending under another version
  is cancelled and closed at launch (`AgentRuntime.reconcile`): nothing shows as running for ever after a restart on new code.
- The tests set a placeholder key (`tests/conftest.py`), and
  `tests/test_agents.py` runs scripted models (`FunctionModel`) on a temp DBOS database: nothing ever reaches OpenRouter
  from a test.

## Concurrency

How the one solver is shared today. These mechanisms are new (October 2026) and still being tried: if one gets in the
way, propose a better one rather than working around it.

- Anything that can solve goes through `ResultCache.through`: on a cache miss it takes the process solver lock and looks
  again once it has it. A route or an agent tool that calls the engine directly solves alongside a job, so both run at
  half speed and often compute the same result twice. The one exception is an agent study behind `SolverGate`
  (`through(locked=False)`): its gate takes the lock per chunk, and must never wait for an operator while the lock is
  already held (that deadlocked a queued job until the agent's deadline: findings #21).
- Never call `through` (or anything that can solve) while holding a store cursor: the store and the solver each have one
  process lock, and a thread waiting for the solver with the store held deadlocks against a job that holds the solver and
  reads the store.
- A GET the planner issues around every run (`/diff`, `/merge-check`) never solves the branch's own plan and never queues
  behind a run: `through(solve=False)` / `through(wait=False)` raise `errors.NotSolved` (409 `{code: "not_solved", retry}`;
  `retry: true` when the engine was merely busy) and the planner asks again when its run has finished, retrying a refusal a few
  times (about half a minute: an agent's study holding the solver as the run ends) before it shows Retry. `?solve=1` is the
  blocking read for scripts. The agents' tools and the note's digest keep solving, behind the `SolverGate`.
- Agents wait rather than fail: `SolverGate.hold` waits while an operator's job runs, for as long as the agent run's own
  time allows (`AgentDeps.deadline` = `AGENT_RUN_BUDGET.timeout_s` less `AGENT_ANSWER_RESERVE_S`), says so in the trace,
  and past the deadline the tool answers with a refusal the model reads (`SolverBusy`), never a raised timeout.
- A job waiting for another holder says "waiting for the solver" (`JobRunner._solver`), not "starting". The warm-up's
  model and boundary reads never take the lock; its other profiles take it per result like every cache miss, and main's
  first run is a job the planner's first run joins.

## Debugging

- The API log (`config.log`, the `gridforge_api` logger: INFO by default, `GRIDFORGE_LOG_LEVEL` to change) says when a job
  starts and ends and how long it took, what the cache computed and in how long, who waited for the solver, what every
  agent run cost (status, $, tokens, solves), and any request over `main.SLOW_REQUEST_S` (0.5 s). Read it before py-spy.
- `uvicorn --reload` sometimes misses an edit: if the log shows no "Reloading" after you save, restart the API.
- A stuck or slow solve: `uv tool run py-spy dump --pid <worker pid>`, where the worker is the child of the process
  listening on :8000. Two dumps a few seconds apart show who holds the solver and whether it is moving.
- Agent runs that look stuck: read DBOS's own state read-only (`sqlite3 "file:apps/api/data/dbos.sqlite?mode=ro"`, table
  `workflow_status`) and compare it with `agent_runs`.
