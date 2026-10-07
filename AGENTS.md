# AGENTS.md — GridForge

Guidance for AI coding agents (and humans) working in this monorepo. Read it before you change anything.

## What this is

GridForge is an **AI-first grid planning platform**. The loop is three steps:

1. **Import a grid.** Any electricity network we can read (a CIM/CGMES export, a pandapower or MATPOWER file), validated on the way in, with every gap stated as an assumption and never filled silently. Distribution grids are the target. Transmission is an open question: the engine's bands, N-1 scope and demand classes are distribution-shaped today (GB bands, the 132 kV backbone, P2/8-style classes), so don't claim it works there.
2. **Make changes on a branch.** Add or move a project, schedule a year, plan works, simulate a reinforcement. `main` is the network as it exists today; nothing reaches it except a gated merge.
3. **Get analysis of those changes.** A deterministic engine (pandapower AC power flow) judges feasibility, and AI agents explain it, in the way an electrical engineer would read it. The operator reviews a consequence diff and merges or discards.

**The value proposition is understanding, not just a verdict.** The platform should find a grid's vulnerabilities, say how the grid works (what binds, where, in which season and year), and reason the way a planning engineer does: thermal loading, voltage, firm capacity and P2/8, N-1 and what a fault strands, planned outages, headroom, and the next lever to try. Every analysis answers three questions: is it **feasible**, **what limits it**, and **what would it take**. Prefer work that sharpens those answers, makes the grid easier to understand, or lets a new grid be imported and analysed, over polish elsewhere.

The built-in **NGED Bicker Fen 132 kV GSP** (Lincolnshire, open data only) is the reference grid and the demo, not the product's identity. Anything NGED-specific (LTDS, the ECR registry, GSP limits, the pinned snapshot) should live behind the `GridSource` seam; code outside it must work for any imported grid (a few NGED-specific heuristics still leak into the UI: move them behind the seam when you touch them). Not-yet-built projects sit in an optional registry (built-in grid only); you branch, pull projects onto the branch, and the engine decides which connect, in what order and year, and why the rest are deferred.

**We are building the MVP: stay lean.** Ship the smallest thing that makes the value proposition real. Don't add tests, abstractions, options or documentation beyond what the current change needs (see *Testing stance* below).

Deep docs (they are the spec, so keep them current):
- `README.md`: system, data sources, how a project is judged, API table, limitations
- `packages/optimizer/README.md`: engine algorithm, study cases, per-year evaluation and outages, suggestions, config
- `apps/pipeline/README.md`: Dagster asset graph and checks
- `apps/web/README.md`: planner files and behaviour (Vite + React + TypeScript).

## Repo map

Each package has its own `AGENTS.md` with what it owns and its conventions; the one closest to the file you edit adds to this one.

| Path | What it is | Guidance |
|---|---|---|
| `packages/optimizer` (`gridforge_optimizer`) | The engine and **the single source of truth**: the network build, the physics, ranking, the plan years, planned works, the demand side, "what would it take", the diff, element names, editions, the CIM export, where a grid comes from (`sources.py`), the pydantic contract and every tunable | `packages/optimizer/AGENTS.md` |
| `apps/pipeline` (`grid_simulator`) | Dagster: the pinned LTDS snapshot into the DuckDB warehouse, the ECR and OSM register fetches, pinning | `apps/pipeline/AGENTS.md` |
| `apps/api` (`gridforge_api`) | FastAPI on :8000: projects (built-in and imported), branches, the merge gate and the findings ledger, the job runner and solver lock, the agent harness (DBOS) | `apps/api/AGENTS.md` |
| `apps/web` | The planner: Vite + React 19 + TypeScript, "GridForge Glass" | `apps/web/AGENTS.md` |

Both Python apps consume `packages/optimizer` as an editable uv path dependency. Never duplicate network-building or physics logic in the pipeline, the API or the client; import it from the engine.

## Setup and commands

Prereqs: Node 22 + pnpm 10, Python 3.11+ with `uv`, and `OPENROUTER_API_KEY` in `apps/pipeline/.env` (the API does not start without it).

```bash
pnpm install                                      # repo root

# build the warehouse (the only way; there is no seed script)
cd apps/pipeline
uv run dagster asset materialize -m grid_simulator.definitions --select 'ltds_tables*'   # keep the quotes; offline
uv run dagster asset materialize -m grid_simulator.definitions --select 'ecr_register_fetch,ecr_editions,ecr_changes'  # live ECR fetch + diff
# never select 'pin_*' unless you mean to replace the pinned snapshot in packages/optimizer/.../data/nged/

# run (two terminals, repo root)
pnpm --filter @gridforge/api dev                  # http://localhost:8000
pnpm --filter web dev                             # http://localhost:3000

# existing suites (optional until the MVP is final: see Testing stance)
pnpm test                                         # everything, via Turborepo
cd packages/optimizer && uv run pytest -q         # engine
cd apps/api && uv run --with pytest pytest tests -q   # API (uses a temp scenarios DB)
cd apps/web && pnpm test && pnpm typecheck        # UI unit tests + tsc
GRIDFORGE_TEST_PG_URL=postgresql://user@host:5499/db  cd apps/api && uv run --with pytest pytest tests -q   # + the Postgres store test
```


- `uv run dg dev` (Dagster UI) also binds **port 3000**: don't run it alongside the web app.
- Re-materialise after changing `nged.py` or bundled data, and restart the API: it caches optimize results and the GSP boundary in memory.
- The agents are not optional: `OPENROUTER_API_KEY=...` in `apps/pipeline/.env` (the API loads it from there) is required, and the API refuses to start without it (`config.require_openrouter_key`). Never commit `.env`. How the agent runtime runs (DBOS, recovery across restarts) and how the tests avoid OpenRouter: `apps/api/AGENTS.md`.

Windows / Git Bash:
- Multi-line `python -c "..."` breaks; write a temp `.py` in your scratch dir and run it with `uv run python`. Long inline shell commands (roughly over 6 kB, e.g. a big heredoc) get truncated and fail with "unexpected EOF": write them to a file too.
- Don't shell-grep or `find` from the repo root: `node_modules` is huge. Use the Grep/Glob tools or scope to a package.
- `--select '*'` can still shell-expand here; use `'ltds_tables*'`, which already selects the full graph.

## Testing instructions

- **Testing stance (MVP).** Don't write new tests until the owner says the MVP is final: they are not the priority now, and the value is in the analysis, not in coverage. Keep the existing suites small and honest: if you change behaviour a test covers, update or delete that test in the same change, and delete tests for features that no longer exist. Don't add fixtures that assume a physical outcome (that a project connects or defers) or a particular grid; if a test is ever needed again it must work on any grid, derive ids from the model (`packages/optimizer/tests/_grid.py`), never hardcode bus ids, and keep NGED data rules in `tests/test_nged.py`. Real verification is the browser check below plus reading the engine's own output.
- Run suites one at a time, not alongside browser sessions. Stop the dev API (or pause its agents) first: its agents solve on the same CPU and can triple the API suite's time. The engine suite is ~2 min on 4 xdist workers and the API suite ~6 min (a solve of a branch nobody has run yet is 25-40 s); the web suite takes seconds.

## Domain rules (non-negotiable; set by the owner)

These apply to every grid. The NGED specifics named below (the GSP boundary, the LTDS, the 132 kV backbone, the ECR) describe the built-in reference grid; an imported grid meets the same rules through `sources.py`, with whatever it lacks stated as an assumption.

1. **`main` = only what physically exists today.** Every not-yet-built project, and any future network asset, is an OPTIONAL registry item that counts only once it is added to a branch. Never pre-load, inject in the background, or reserve capacity for it.
2. **Physics is deterministic.** Feasibility comes from power flow only. An LLM never computes, scores or adjusts physics or ranking. A model never reads the engine's tables either: `gridforge_optimizer.analysis` reduces a run to its binding set, chains, clusters and digest first, deterministically. What an LLM may do, all of it in the API and all through OpenRouter (`apps/api/src/gridforge_api/agents/`): write the engineer's note on a run from that digest (`digest_run`: one tool-less call) and, as the answerer, **plan typed queries over the engine's reads and studies, call them, compare their outputs and phrase them**. Every digit figure a note or an answer states is checked by value against the digest or the tool outputs it read (its own run's and the earlier replies' in its thread) (`check_numbers`: digit figures, not plan years, counts up to 12 or numbers written as words; soft flags on the message, the text is shown as written). Findings come from the engine, never from a model. Agents never merge, discard or edit `main`; their proposals are deferred tools the operator approves (a branch, a reinforcement, a works window, a project or a change to one, a run of the branch). The key is mandatory: without `OPENROUTER_API_KEY` the API does not start, and nothing degrades to a key-less substitute (no scripted chats, no "agents off" state; `starting` is the only non-answering state, while the runtime launches).
3. **Parameters are set by the flows, not the operator.** No ranking-weight sliders or physics knobs in the UI; weights stay engine defaults in `config.py`.
4. **Two study cases plus the boundary.** Every accepted project must pass `winter_peak` (grown demand, winter ratings, PV/wind at nil, batteries charging at `import_mw`) AND `summer_min` (LTDS minimum-demand factor, not grown, summer ratings, everything at full export), plus the GSP export limit. Voltage limits are the statutory bands by level (`VOLTAGE_BANDS`), judged after the tap changers have settled (`_solve` regulates them; taps persist on the net). Every `Reason` carries the element, the value, the `limit` and the `case`. The N-1 screen (`n1_screen_cases`: the 132 kV backbone in each case of `config.N1_CASES`, winter peak and summer minimum, every finding carrying its `case`, islanded demand on the first case only; each outage the post-fault steady state: taps re-regulated, transformer loading against the LTDS emergency rating) is reported on `PhaseResult`, never a gate. Lines carry their LTDS charging (B1); the ranking's grid-need solve is the regulated, dispatched winter-peak case (`_run_case`), never a raw `pp.runpp`. Once the queue is decided, `years.evaluate_years` solves every plan year (2026..2035) as a fixed plan: demand interpolated to the year, the projects energised by then, both cases, N-1 in each of its cases and that year's planned outages (studied in their season's case(s), `config.SEASON_STUDY`). It never changes who connects; planned outages, like N-1, are reported, never a connection gate. **Merging is gated** (`gate.merge_verdict`, registry `MERGE_CHECKS`, every level in `config.MERGE_GATE_LEVELS`): a branch is refused when its result is stale, or when it introduces or worsens a problem relative to its parent in the same plan year (new or worsened overloads, new voltage breaches, the GSP newly over its limit, new N-1 findings, new demand-side breaches, works windows that become infeasible, a year that stops converging, a parent that moved on); what the parent already carries is context, never a blocker; warnings need `acknowledge`. The gate is a pure policy over existing results and never solves. Connections stay ungated.
5. **Real data, real units.**
   - Never hardcode a voltage or ratio: line MVA comes from `voltage_kv`, transformer ratios from `hv_kv`/`lv_kv`.
   - LTDS rows with Status `Removed` are excluded (the LTDS is a change-log against NGED's previous edition).
   - Cite sources (resource ids live next to the constants in `nged.py`).
   - Bundled ECR data: the fetch drops the register's customer-name, address, postcode and MPAN/MSID columns (`ECR_KEEP`). `customer_site` is kept as NGED publishes it; for small sites it is often a property name or an address.
   - **Imported grids are simulated as they run, or not at all.** They go through `sources.normalise_net` → `apply_import_meta` → `inspect_net` → `validate_net`. Nothing the network's own description needs is assumed: what a file lacks for a real simulation (an infeed, a line rating, a generator's technology, rating, voltage setpoint, reactive limits, minimum output or cost, a tap-changer type for a tap range, buses the infeed cannot reach) is a gap, and the import is refused with the list to complete; never add a fallback that fills one. What the file states is kept as stated (voltage-controlled generators stay voltage-controlled, fixed transformer ratios stay fixed). Its power stations follow the merit order (`dispatch.py`). The study basis (the summer case, the export limit, GB bands, the N-1 scope) is listed as `ModelAssumption`s with a key in `sources._GENERIC` (or `nged._ASSUMPTION_TEXT` for the builder, whose open data cannot be asked); a new one needs its text there and a line in the README register.
6. **Reasons are human-readable and actionable**: why it's blocked, and what to do. The engine emits typed reasons (`line`/`trafo`/`voltage`/`gsp`/`rejected`, ...); `normReason` (`apps/web/src/lib/reasons.ts`, re-exported from `src/api.ts`) turns them into `{kind, element, short, why, action}`. To add a reason type: a check in `network.LIMIT_CHECKS`, a lever in `suggest.LEVERS` (and a reinforcer in `network.REINFORCERS` if it needs a new kind of upgrade), and a normaliser in `reasons.ts`'s `NORMALISERS`.
7. **Honesty over fake precision.** State limitations instead of modelling them badly: fault levels are not checked, the 400 kV network is context only, the GSP limit's sign convention is assumed, the tap step (1.25%), the tap-changer target (1.02 pu, chosen as the lowest that keeps today's network in band) and the per-case dispatch factors are planning assumptions (including demand and electrolyser projects drawing `DEMAND_PROJECT_MIN_FACTOR` = 50% of `import_mw` at summer minimum), N-1 is informational, planned works windows are reported without placing their weeks in the calendar (same-season windows are studied together), their curtailment is a bounded first-order search (`maintenance.py`, not an optimal re-dispatch), and a repowering changes only the later years, never the queue run, and the derate factor (50%) is assumed. A lever's "freed MW" is first-order (≈), and `connection_options` probes the plan's hardest phase, not every year, and says nothing about the works or cost of a new point of connection. Don't tune constants (e.g. `MAX_REINFORCE_STEPS`) for nicer-looking output. Every source and assumption is listed in the root README's *Sources and assumptions* register: a new or changed constant updates it in the same change.

## Code style and design

### SOLID

SOLID is a standing rule for all code here, not a cleanup pass. Apply it when you write or change code, and say so in review when a change bends it.

- **S: one reason to change.** A module or class owns one concern. HTTP routing, SQL, caching, job scheduling and the agent harness are separate modules (see the `apps/api` layout above); the engine's ranking, trialling and queue-building are separate steps (`greedy._Run`). If a function needs "and" to describe it, or passes ~100 lines, split it.
- **O: extend by adding, not editing.** Variation points are data or registries, not `if kind == ...` ladders. Study cases are `network.CASE_SPECS` entries; a new case is one entry plus its dispatch factors in `config.py`. When you add a branch on a type string in a second place, make it a registry instead. Registries in place: `CASE_SPECS`, `LIMIT_CHECKS`, `REINFORCERS`, `OUTAGE_APPLIERS`, `maintenance.WORKS` / `REPOWERERS`, `demand.ALERT_CHECKS`, `config.SEASON_STUDY`, `suggest.LEVERS`, `gate.MERGE_CHECKS` (levels in `config.MERGE_GATE_LEVELS`), `findings.EXTRACTORS`, `studies.STUDIES`, `sources.SOURCES` (a new file format is one `SourceSpec`), the harness's `roster.AGENTS`, `events.TRIGGERS`, `tools.TOOL_GROUPS`, `workflows.WORKFLOWS` (each with its queue and time limit), `streaming.STAGE_BY_TOOL_PREFIX` (every tool event carries its stage: the planner never derives it), the web `NORMALISERS`, `ask.PROPOSAL_EFFECT` (what an approved proposal refreshes, by tool) and `SidePanel`'s `TABS`, and the per-technology tables `theme.TECH` and `ui.tsx`'s `TECH_ICON` (typed `Record<Tech, …>`, so a new technology fails to compile until it has an entry).
- **L: substitutable implementations.** Anything behind a `Protocol` (`GridSource`) or a callable seam (`net_factory`, `progress`, the agents' `model_factory`) must work with any implementation that honours the contract, including a scripted one (the tests' scripted models in `apps/api/tests/test_agents.py`). Don't add `isinstance` checks or special cases for one implementation.
- **I: small, role-shaped interfaces.** Depend on the narrowest thing you use: a function takes a cursor, not the store; a component takes the props it renders, not the whole planner state. Don't grow `PlannerState` or a Protocol for one caller's convenience.
- **D: depend on abstractions, wire in one place.** Collaborators (warehouse, store, cache, net factory) are passed in as arguments. Only `deps.py` (API) and the entry points construct concrete instances. Engine functions take `net_factory=` rather than calling `build_base_net()` directly; new engine code must do the same. No new module-level mutable state outside `deps.py`.

Pragmatism: SOLID serves the code, not the other way round. Don't add an interface for something with one implementation and no test or deployment need to vary it (a Protocol earns its place at an LLM, network or database boundary). Prefer a small function over a class hierarchy. Keep the physics and ranking rules in Domain rules above untouched by refactors: a SOLID change must not change engine output (compare a run before and after, or run the engine suite).

### Conventions across packages

- **Change the output shape in one pass:** `types.py` → API enrichment in `apps/api/src/gridforge_api/service.py` → `apps/web/src/types.ts` + `src/api.ts` → the component that renders it.
- Delete dead code rather than keeping it "not wired". Update the READMEs in the same change when behaviour, endpoints or commands change.

## Security considerations

- Never commit `.env` (it holds `OPENROUTER_API_KEY`).
- The ECR fetch drops customer names, addresses, postcodes and MPANs as columns (`ECR_KEEP`), but `customer_site` is kept as published and can name a property: see Domain rule 5. When you touch the ECR fetch, the bundled `ecr.json` or the pipeline's asset checks, never add a personal column back.
- Agents never merge, discard or edit `main`; everything they change is a proposal the operator approves (Domain rule 2).
- The API's CORS is permissive for local development (`main.py`); lock it down before deploying anywhere.

## Commits and PRs

- **Don't commit or push unless asked.** The owner's usual flow is a feature branch fast-forwarded into `main`; ask before pushing, and never force-push `main`.
- Check `git status` shows new frontend files before committing (the root `.gitignore` ignores every `lib/` except `apps/web/src/lib/`).

## Working agreements

- **Verify in a real browser** before saying UI work is done; a typecheck and a build aren't enough.
- **Stay lean (MVP).** Smallest change that makes the value proposition real. No speculative options, no new tests (see *Testing stance*), no docs beyond keeping the existing ones true. Reports and audits go in `docs/reports/` and cover bugs and improvements in the product, not test coverage.
- **Agent guidance lives only in `AGENTS.md` files**, for every kind of agent: this one and one per package (the closest to the file you edit adds to this one). Don't add `CLAUDE.md`, `.cursorrules` or other tool-specific copies.
- Keep the Turborepo block below committed and unedited; turbo re-adds it.
- When several agents work in parallel, stay inside the files you were assigned.

<!-- BEGIN:turborepo-agent-rules -->

# This is NOT the Turborepo you know

Turborepo configuration, task behavior, and CLI commands can vary between installed versions and may differ from your training data. Resolve the `turbo` package from this file's directory or relevant workspace; in monorepos, it may not be visible from the repository root. For example, run `node -p "require.resolve('turbo/package.json')"` from a workspace that depends on `turbo`.

Read `docs/README.md` inside that installed package first, then read the relevant pages from its `docs/` directory before changing Turborepo configuration or commands. Heed deprecation notices. These bundled docs match the installed package version and are available without network access.

This block is written and re-added by `turbo` before repository-scoped commands when an AI agent is detected. In the Turborepo source repository, its template is defined in `crates/turborepo-cli/src/cli/agent_guidance.rs`. Removing the managed block while updates are enabled means a later qualifying invocation will add it again. Set `"agentGuidance": false` in the root `turbo.json` or `turbo.jsonc` to opt out; this does not remove an existing block. Keep the block committed with your work to avoid an uncommitted change on the next agent invocation.
<!-- END:turborepo-agent-rules -->
