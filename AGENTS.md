# AGENTS.md — GridForge

Guidance for AI coding agents (and humans) working in this monorepo. Read it before you change anything.

## What this is

GridForge is a pull-request workflow for grid connections on one real UK network: NGED's **Bicker Fen 132 kV GSP** (Lincolnshire), built only from open data. `main` is the network as it exists today. Not-yet-built projects sit in an optional registry; you branch, pull projects onto the branch, and a deterministic engine (pandapower AC power flow) decides which connect, in what order and year, and why the rest are deferred. The operator reviews a consequence diff and merges or discards it.

Deep docs (they are the spec, so keep them current):
- `README.md`: system, data sources, how a project is judged, API table, limitations
- `packages/optimizer/README.md`: engine algorithm, study cases, per-year evaluation and outages, suggestions, config
- `apps/pipeline/README.md`: Dagster asset graph and checks
- `apps/web/README.md`: planner files and behaviour (Vite + React + TypeScript).

## Repo map: who owns what

| Path | Owns |
|---|---|
| `packages/optimizer` (`gridforge_optimizer`) | **The single source of truth** for the network build (`nged.py`), the physics (`network.py` feasibility), ranking and greedy loop (`greedy.py`), the per-year fixed-plan evaluation with planned outages (`years.py`), "what would it take" (`suggest.py`), the diff (`diff.py`), editions (`editions.py`), the CIM/CGMES export (`cim.py`), the pydantic contract (`types.py`) and every tunable (`config.py`). Bundled open data lives in `src/gridforge_optimizer/data/nged/`. |
| `apps/pipeline` (`grid_simulator`) | Dagster. `defs/nged.py` (group `ltds`): `ltds_tables` (pinned snapshot, passed INTO the builder) → `nged_model_canonical` + `nged_connection_queue` + `ltds_edition_changes` → 3 asset checks → `served_nged` → DuckDB warehouse `apps/pipeline/warehouse/gridforge.duckdb` with an append-only `snapshots` history. `defs/registers.py` (group `registers`): scheduled fetches of the ECR (monthly) and OSM coords (quarterly) into append-only edition tables + `ecr_changes`; `pin_*` assets promote an edition into the bundled snapshot (manual). Warehouse writers carry a retry policy (DuckDB = one writer). |
| `apps/api` (`gridforge_api`) | FastAPI on :8000. Reads the warehouse **read-only**; branches, added projects, scheduled years, planned outages (`branch_outages`), simulated reinforcements (`branch_reinforcements`, both copied on branch create and merge by `repository.copy_branch_extras`) and the result cache go to the scenarios store: `apps/api/data/scenarios.duckdb` by default (`GRIDFORGE_SCENARIOS_DB`), or Postgres when `GRIDFORGE_SCENARIOS_URL=postgresql://…` is set (`store.Cursor` translates `?`→`%s` and `DOUBLE`→`DOUBLE PRECISION`; everything else is common SQL, so write DuckDB-style SQL with `?` placeholders and `ON CONFLICT` upserts, never `INSERT OR REPLACE` or `PRAGMA`). `GRIDFORGE_DB_PATH` overrides the warehouse. `GET /model/cgmes` serves the CIM export; `/branches/{id}/outages` and `/branches/{id}/reinforcements` (GET/POST/DELETE) edit a branch's proposals and answer 409 on `main` or a non-open branch. Layout: `main.py` only assembles the app; `routers/` (HTTP: `model`, `registry`, `optimize`, `branches`), `service.py` (`PlanService`: engine runs, the per-year step, suggestions), `repository.py` (branches/projects/outages/reinforcements SQL), `store.py` (`ScenarioStore`, schema + migrations), `warehouse.py` (`Warehouse`, read-only), `cache.py` (`ResultCache`), `jobs.py` (`JobRunner`), `narration.py` (`Narrator` protocol + summaries), `schemas.py` (request bodies), `deps.py` (composition root: the one place instances are built). |
| `apps/web` | Vite + React 19 + TypeScript single-page planner, "GridForge Glass" (spec: `docs/design/gridforge-glass/`). `src/hooks/usePlanner.ts` composes the hooks in `src/hooks/planner/` (`core`, `slice`, `useRun`, `useBranchFlows`, `useBranchList`, `useRegistry`, `useSelection`, `useProjectEdits`, `useMaintenance`, `useCopilot`, `useDerived`), `src/api.ts` the typed client (re-exports `normReason`), `src/lib/` pure derivations with vitest (`derive`, `intake`, `recs`, `runStages`, `layout`, `geo`, `icons`, `reasons.ts`: the reason normaliser registry), `src/components/` the UI (`Header`, `LeftCards`, `MapView`, `MapMarkers`, `MapControls`, `DetailCards`, `Roadmap`, `SidePanel` → `CopilotTab` / `QueueTab` / `OutagesTab` / `ReviewTab`, `RunOverlay`, `ui`), `MapView.tsx` owns MapLibre (CARTO dark basemap). Icons from `@phosphor-icons/react`. Live-only against the API (`VITE_API_BASE`, default `http://localhost:8000`). |

Both Python apps consume `packages/optimizer` as an editable uv path dependency. Never duplicate network-building or physics logic in the pipeline, the API or the client; import it from the engine.

## Commands

Prereqs: Node 22 + pnpm 10, Python 3.11+ with `uv`. No API key needed.

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

# test
pnpm test                                         # everything, via Turborepo
cd packages/optimizer && uv run pytest -q         # engine
cd apps/api && uv run --with pytest pytest tests -q   # API (uses a temp scenarios DB)
cd apps/web && pnpm test && pnpm typecheck        # UI unit tests + tsc
GRIDFORGE_TEST_PG_URL=postgresql://user@host:5499/db  cd apps/api && uv run --with pytest pytest tests -q   # + the Postgres store test
```

Keep suites fast: the engine suite stubs the N-1 screen (`tests/conftest.py`, opt in with `@pytest.mark.n1`), shares expensive runs per module and runs on 4 xdist workers (~2 min); the API suite uses small saturating fixtures (~2 min). Run suites one at a time, not alongside browser sessions.

- `uv run dg dev` (Dagster UI) also binds **port 3000**: don't run it alongside the web app.
- Re-materialise after changing `nged.py` or bundled data, and restart the API: it caches optimize results and the GSP boundary in memory.
- Optional narration: `OPENROUTER_API_KEY=...` in `apps/pipeline/.env` (the API loads it from there). Never commit `.env`.

Windows / Git Bash:
- Multi-line `python -c "..."` breaks; write a temp `.py` in your scratch dir and run it with `uv run python`. Long inline shell commands (roughly over 6 kB, e.g. a big heredoc) get truncated and fail with "unexpected EOF": write them to a file too.
- Don't shell-grep or `find` from the repo root: `node_modules` is huge. Use the Grep/Glob tools or scope to a package.
- `--select '*'` can still shell-expand here; use `'ltds_tables*'`, which already selects the full graph.

## Domain rules (non-negotiable; set by the owner)

1. **`main` = only what physically exists today.** Every not-yet-built project, and any future network asset, is an OPTIONAL registry item that counts only once it is added to a branch. Never pre-load, inject in the background, or reserve capacity for it.
2. **Physics is deterministic.** Feasibility comes from power flow only. An LLM never decides, scores or adjusts physics or ranking. The only LLM use is optional narration in the API (`justify`, `narrate_diff`, `narrate_suggestion` via OpenRouter); it must restate engine figures, never invent them, and the app must work fully with no key.
3. **Parameters are set by the flows, not the operator.** No ranking-weight sliders or physics knobs in the UI; weights stay engine defaults in `config.py`.
4. **Two study cases plus the boundary.** Every accepted project must pass `winter_peak` (grown demand, winter ratings, PV/wind at nil, batteries charging at `import_mw`) AND `summer_min` (LTDS minimum-demand factor, not grown, summer ratings, everything at full export), plus the GSP export limit. Voltage limits are the statutory bands by level (`VOLTAGE_BANDS`), judged after the tap changers have settled (`_solve` regulates them; taps persist on the net). Every `Reason` carries the element, the value, the `limit` and the `case`. The N-1 screen (`n1_screen`, 132 kV backbone, winter peak) is reported on `PhaseResult`, never a gate. Once the queue is decided, `years.evaluate_years` solves every plan year (2026..2035) as a fixed plan: demand interpolated to the year, the projects energised by then, both cases, N-1 and that year's planned outages (studied in their season's case(s), `config.SEASON_STUDY`). It never changes who connects; planned outages, like N-1, are reported, never a gate.
5. **Real data, real units.**
   - Never hardcode a voltage or ratio: line MVA comes from `voltage_kv`, transformer ratios from `hv_kv`/`lv_kv`.
   - LTDS rows with Status `Removed` are excluded (the LTDS is a change-log against NGED's previous edition).
   - Cite sources (resource ids live next to the constants in `nged.py`).
   - Bundled ECR data must contain **no personal data** (customer names, addresses, MPANs are dropped by the fetch script).
6. **Reasons are human-readable and actionable**: why it's blocked, and what to do. The engine emits typed reasons (`line`/`trafo`/`voltage`/`gsp`/`rejected`, ...); `normReason` (`apps/web/src/lib/reasons.ts`, re-exported from `src/api.ts`) turns them into `{kind, element, short, why, action}` (unit-tested in `src/api.test.ts`). To add a reason type: a check in `network.LIMIT_CHECKS`, a lever in `suggest.LEVERS` (and a reinforcer in `network.REINFORCERS` if it needs a new kind of upgrade), and a normaliser in `reasons.ts`'s `NORMALISERS`.
7. **Honesty over fake precision.** State limitations instead of modelling them badly: fault levels are not checked, the 400 kV network is context only, the GSP limit's sign convention is assumed, the tap step (1.25%) and the per-case dispatch factors are planning assumptions (including demand and electrolyser projects drawing `DEMAND_PROJECT_MIN_FACTOR` = 50% of `import_mw` at summer minimum), N-1 is informational, planned outages are reported without curtailment or re-dispatch and without placing their weeks in the calendar, and the derate factor (50%) is assumed. Copilot "freed MW" is first-order (shown as ≈). Don't tune constants (e.g. `MAX_REINFORCE_STEPS`) for nicer-looking output.

## Design principle: SOLID

SOLID is a standing rule for all code here, not a cleanup pass. Apply it when you write or change code, and say so in review when a change bends it.

- **S: one reason to change.** A module or class owns one concern. HTTP routing, SQL, caching, job scheduling and narration are separate modules (see the `apps/api` layout above); the engine's ranking, trialling and queue-building are separate steps (`greedy._Run`). If a function needs "and" to describe it, or passes ~100 lines, split it.
- **O: extend by adding, not editing.** Variation points are data or registries, not `if kind == ...` ladders. Study cases are `network.CASE_SPECS` entries; a new case is one entry plus its dispatch factors in `config.py`. When you add a branch on a type string in a second place, make it a registry instead. Registries in place: `CASE_SPECS`, `LIMIT_CHECKS`, `REINFORCERS`, `OUTAGE_APPLIERS`, `config.SEASON_STUDY`, `suggest.LEVERS`, the web `NORMALISERS`, and the per-technology tables `theme.TECH` and `ui.tsx`'s `TECH_ICON` (typed `Record<Tech, …>`, so a new technology fails to compile until it has an entry).
- **L: substitutable implementations.** Anything behind a `Protocol` (`Narrator`) or a callable seam (`net_factory`, `progress`) must work with any implementation that honours the contract, including a no-op one (`NoNarrator`). Don't add `isinstance` checks or special cases for one implementation.
- **I: small, role-shaped interfaces.** Depend on the narrowest thing you use: a function takes a cursor, not the store; a component takes the props it renders, not the whole planner state. Don't grow `PlannerState` or a Protocol for one caller's convenience.
- **D: depend on abstractions, wire in one place.** Collaborators (warehouse, store, cache, narrator, net factory) are passed in as arguments. Only `deps.py` (API) and the entry points construct concrete instances. Engine functions take `net_factory=` rather than calling `build_base_net()` directly; new engine code must do the same. No new module-level mutable state outside `deps.py` (the two read-through caches in `routers/model.py` are the existing exception).

Pragmatism: SOLID serves the code, not the other way round. Don't add an interface for something with one implementation and no test or deployment need to vary it (a Protocol earns its place at an LLM, network or database boundary). Prefer a small function over a class hierarchy. Keep the physics and ranking rules in Domain rules above untouched by refactors: a SOLID change must not change engine output (the suites prove it).

## Engineering conventions

- **Tests are grid-agnostic.** Derive fixtures from `build_base_net()` via `packages/optimizer/tests/_grid.py` (`stiff_bus`, `weak_buses`, `saturating_candidates`, `grid_deferred`, `invalid_bus`). Never hardcode bus ids, and never size fixtures from policy caps like `MAX_CONNECTION_MW` (only use the cap to test the cap itself). NGED-specific data rules go in `tests/test_nged.py`.
- **API cache keys include the candidate-set hash, the model snapshot and the engine fingerprint** (`cache.cand_key`, `Warehouse.baseline_id()`, `ResultCache.engine` → `ResultCache.key`). Results live in the scenarios DB table `result_cache` (durable) and in `ResultCache.compute` / `.payload` (process). Any new cached computation must use `ResultCache.key`, or branches serve each other's results / stale physics survives a code change. The engine's `trial_cache` dicts are keyed the same way (`ResultCache.trial_cache`). Branch reinforcements join the optimize key (`service.reinf_key`); the per-year results (kind `years`) add the outages and the schedule (`service.years_key`), so editing those re-solves the years but not the queue.
- **Long computations run on the single job worker** (`JobRunner.start(kind, fn(progress, publish))`, `GET /jobs/{id}`); the planner polls. `publish(partial)` stores a partial result on the job record (`GET /jobs/{id}?partial=true`, `has_partial`): the optimize job publishes the queue, then each year as `evaluate_years(on_year=...)` lands, the body's `view_year` first. Keep the sync endpoints too (tests and scripts use them). The engine reports progress through `optimize(progress=...)` and `evaluate_years(progress=...)` (the API maps them to 0..0.5 and 0.5..0.95, narration at 0.95); new long stages should call it.
- **The warehouse is read-only to the API.** Anything a user does goes to the scenarios DB. Schema changes there need a migration (PRAGMA check + ALTER) and, for per-project columns, an entry in `_ADDED_COLS` so they copy on branch create/merge.
- **Change the output shape in one pass:** `types.py` → API enrichment in `apps/api/src/gridforge_api/service.py` → `apps/web/src/types.ts` + `src/api.ts` → the component that renders it. Add an API test for new endpoints.
- Engine functions (`optimize`, `evaluate_years`, `suggest_unblock`, `diff_results`) make no network calls; keep it that way. Network/LLM calls belong in `llm.py` and the API only.
- Delete dead code rather than keeping it "not wired". Update the READMEs in the same change when behaviour, endpoints or commands change.
- pandapower gotchas: generation is injected as PQ `sgen` (not `gen`) so voltage problems show; use `pandapower.toolbox.drop_buses`; avoid `deepcopy` of nets in hot loops (build once per phase, inject/roll back); in pandapower 3 a transformer's taps are inert unless `tap_changer_type="Ratio"` is set; the LTDS tap ranges (e.g. -12..+4) are HV-winding taps where a lower tap raises the LV voltage, so model them with `tap_side="hv"`; `sgen` rows carry `p_rated_mw` and `import_mw` (set by `inject_sgen`) that `dispatch_for_case` reads.
- The root `.gitignore` is a Python template that ignores every `lib/`; `apps/web/src/lib/` is explicitly un-ignored. Check `git status` shows new frontend files before committing.

## Planner (`apps/web`)

- State lives in one object (`PlannerState`, `hooks/planner/core.ts`; `patch` merges partial updates; `ref.current` is the latest state for async flows). `usePlanner` only composes the hooks under `hooks/planner/` (`useRun`, `useBranchList`, `useBranchFlows`, `useRegistry`, `useSelection`, `useProjectEdits`, `useMaintenance`, `useCopilot`, `useDerived`), each of which takes the shared `Core` plus only the other hooks' actions it needs. Put a new flow in the hook that owns its concern, or a new hook; don't grow `usePlanner`. Components never take the whole `Planner`: each declares the slice it reads with `PlannerSlice<state keys, action keys, derived keys>` (+ `WithPatch` / `WithMap` / `WithFormInvalid` when needed, `hooks/planner/slice.ts`) and exports it as e.g. `QueueTabPlanner`; a parent's slice is the intersection of its children's (`SidePanelPlanner`, `MapViewPlanner`). Reading a field outside the slice fails to compile, so add the key to the slice when you use a new field. Only `App.tsx` (the composition root) sees the full `Planner`. Known limit: `patch` is still a free-form setter, so what a component may write is not narrowed. Actions that need state React hasn't flushed yet take an explicit override (e.g. `run({ activeBranch })`) instead of reading it back.
- Engine runs take ~20 s (two study cases) before the years. `run()` keeps its in-flight flag in a ref and coalesces overlapping requests into one re-run; a failed call clears the flag and toasts. Keep that pattern for any long call; never drop requests silently.
- Runs are explicit. Adding a project (registry or Copilot) makes it Preliminary until the next run; changing the demand profile, outages, reinforcements or the schedule marks the shown result stale (**Re-run**) instead of running. The year slider **never** starts a run: every run solves all years, and the slider only switches between them (years still arriving as partial results show as solving).
- Pure logic goes in `src/lib/` or `src/api.ts` with a vitest next to it; components stay thin. Styles are classes in `src/styles.css`; inline styles only for data-driven colours.
- `MapView.tsx` owns the MapLibre instance: layers/icons are added once on `load`, data is pushed with `setData` from the memoised GeoJSON in `App.tsx`, and the HTML overlay (`MapMarkers`: project markers, substation names, loading/diff/outage tags) is re-projected on each `move`.
- Verify before claiming done: `pnpm --filter web typecheck && pnpm --filter web test && pnpm --filter web build`, then load the dev server against a running API in a headless browser (Playwright in a scratch dir, not the repo; MapLibre needs `--use-gl=swiftshader`) and require **zero page errors**. Exercise the flow you changed (branch → add project → run → scrub the years → review).

## Data refresh

Bundled snapshots live in `packages/optimizer/src/gridforge_optimizer/data/nged/` (LTDS tables, `ecr.json`, `coords.csv`) and are the pinned edition the engine runs on. Live fetches are Dagster assets in `defs/registers.py` (ECR via CKAN, OSM via Overpass) that store editions in the warehouse and diff them; `pin_ecr_edition` / `pin_osm_coords` promote the latest edition into the bundled files. After pinning: re-materialise `ltds_tables*`, review the git diff of the bundled file, commit. Every builder entry point in `gridforge_optimizer.nged` takes `tables=` (and `edition=` current/previous); the pipeline passes its bronze tables through so lineage is real. Keep the ECR fetch free of personal data (`ECR_KEEP`).

OSM data is ODbL: keep the "© OpenStreetMap contributors" credit wherever positions are shown or documented. NGED's own substation-location datasets are access-restricted; don't add a dependency on them.

## Working agreements

- **Verify in a real browser** before saying UI work is done; tests and `node --check` aren't enough.
- **Don't commit or push unless asked.** The owner's usual flow is a feature branch fast-forwarded into `main`; ask before pushing, and never force-push `main`.
- **`AGENTS.md` is the only agent-guidance file, for every kind of agent.** Don't add `CLAUDE.md`, `.cursorrules` or other tool-specific copies; put guidance here.
- Keep the Turborepo block below committed and unedited; turbo re-adds it.
- When several agents work in parallel, stay inside the files you were assigned.

<!-- BEGIN:turborepo-agent-rules -->

# This is NOT the Turborepo you know

Turborepo configuration, task behavior, and CLI commands can vary between installed versions and may differ from your training data. Resolve the `turbo` package from this file's directory or relevant workspace; in monorepos, it may not be visible from the repository root. For example, run `node -p "require.resolve('turbo/package.json')"` from a workspace that depends on `turbo`.

Read `docs/README.md` inside that installed package first, then read the relevant pages from its `docs/` directory before changing Turborepo configuration or commands. Heed deprecation notices. These bundled docs match the installed package version and are available without network access.

This block is written and re-added by `turbo` before repository-scoped commands when an AI agent is detected. In the Turborepo source repository, its template is defined in `crates/turborepo-cli/src/cli/agent_guidance.rs`. Removing the managed block while updates are enabled means a later qualifying invocation will add it again. Set `"agentGuidance": false` in the root `turbo.json` or `turbo.jsonc` to opt out; this does not remove an existing block. Keep the block committed with your work to avoid an uncommitted change on the next agent invocation.
<!-- END:turborepo-agent-rules -->
