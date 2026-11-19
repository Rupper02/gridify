# AGENTS.md — Gridify

Guidance for AI coding agents (and humans) working in this monorepo. Read it before you change anything.

## What this is

Gridify is, today, a **grid planning backbone**: a real distribution network, AC power flow through the plan years, and
branches to try changes on. The loop:

1. **`main` is the network as it exists today**, built from open data (NGED's Bicker Fen 132 kV GSP, Lincolnshire).
2. **Make changes on a branch.** Connect generation, storage or demand at a busbar and give it the year it energises (by
   hand, or pulled from the registry of not-yet-built projects). Nothing reaches `main` except a merge.
3. **Simulate the plan years** (2026 to 2035): demand grown to each year, the connections in service by then, both study
   cases. Every year reports every loading, voltage and breach; a branch is compared with its parent year by year.

The owner removed the AI layer (agents, the connection-queue optimizer, N-1, works windows, capacity studies, imports, the
merge gate) on 2026-10-16 to get a clean backbone. What makes the product special comes next, deliberately and one step at
a time; a learned demand and generation model is being explored in `forecast/` (a standalone experiment that imports nothing from the product), and would plug in here as the
profiles a year is solved on. Don't re-add any of the removed features unless the owner asks.

**We are building the MVP: stay lean.** Ship the smallest thing that makes the backbone real. Don't add tests,
abstractions, options or documentation beyond what the current change needs (see *Testing stance*).

The built-in NGED grid is the reference grid, not the product's identity. Anything NGED-specific (LTDS, the ECR registry,
GSP limits, the pinned snapshot) lives behind the `GridSource` seam; code outside it must work for any grid.

Deep docs (they are the spec, so keep them current):
- `README.md`: purpose, status, roadmap, the system, data sources, how a year is solved, limitations
- `docs/sources-and-assumptions.md`: the register of every source and assumption, and the comparison with NGED's flows
- `apps/api/README.md`: the endpoint table
- `packages/optimizer/README.md`: the engine
- `apps/pipeline/README.md`: the Dagster asset graph and checks
- `apps/web/README.md`: the planner (Vite + React + TypeScript)

## Repo map

Each package has its own `AGENTS.md`; the one closest to the file you edit adds to this one.

| Path | What it is | Guidance |
|---|---|---|
| `packages/optimizer` (`gridify_optimizer`) | The engine and **the single source of truth**: the network build, the physics, the plan years, the comparison, element names, editions, the CIM export, where a grid comes from (`sources.py`), the pydantic contract and every tunable | `packages/optimizer/AGENTS.md` |
| `apps/pipeline` (`grid_simulator`) | Dagster: the pinned LTDS snapshot into the DuckDB warehouse, the ECR and OSM register fetches, pinning | `apps/pipeline/AGENTS.md` |
| `apps/api` (`gridify_api`) | FastAPI on :8000: the grid, branches and their connections, runs as jobs, the result cache, the comparison | `apps/api/AGENTS.md` |
| `apps/web` | The planner: Vite + React 19 + TypeScript, "Gridify Glass" | `apps/web/AGENTS.md` |
| `forecast` | Standalone research: day-ahead demand forecasting at a primary substation; its own uv project, data git-ignored | `forecast/README.md` (sections 7 and 12 fix the method; never touch a spent or held-out test set) |

Both Python apps consume `packages/optimizer` as an editable uv path dependency. Never duplicate network-building or
physics logic in the pipeline, the API or the client; import it from the engine.

## Setup and commands

Prereqs: Node 22 + pnpm 10, Python 3.11+ with `uv`. No API key is needed.

```bash
pnpm install                                      # repo root

# build the warehouse (the only way; there is no seed script)
cd apps/pipeline
uv run dagster asset materialize -m grid_simulator.definitions --select 'ltds_tables*'   # keep the quotes; offline
# never select 'pin_*' unless you mean to replace the pinned snapshot in packages/optimizer/.../data/nged/

# run (two terminals, repo root)
pnpm --filter @gridify/api dev                  # http://localhost:8000
pnpm --filter web dev                             # http://localhost:3000

pnpm test                                         # everything, via Turborepo
cd packages/optimizer && uv run pytest -q         # engine (~1 min)
cd apps/api && uv run --with pytest pytest tests -q   # API (~1 min, a temp scenarios DB)
cd apps/web && pnpm typecheck && pnpm build       # the planner has no unit tests
```

- `uv run dg dev` (Dagster UI) also binds **port 3000**: don't run it alongside the web app.
- Re-materialise after changing `nged.py` or bundled data, and restart the API: it caches results and the boundary in
  memory.

Windows / Git Bash:
- Multi-line `python -c "..."` breaks; write a temp `.py` in your scratch dir and run it with `uv run python`. Long inline
  shell commands (roughly over 6 kB, e.g. a big heredoc) get truncated and fail with "unexpected EOF": write them to a file.
- Don't shell-grep or `find` from the repo root: `node_modules` and the `.venv`s are huge. Use the Grep/Glob tools or
  scope to a package's `src`.

## Testing instructions

- **Testing stance (MVP).** Don't write new tests until the owner says the MVP is final. Keep the existing suites small
  and honest: if you change behaviour a test covers, update or delete that test in the same change, and delete tests for
  features that no longer exist. Tests must work on any grid: derive ids from the model (`packages/optimizer/tests/_grid.py`),
  never hardcode bus ids, and keep NGED data rules in `tests/test_nged.py`. Real verification is the browser check below
  plus reading the engine's own output.
- Run suites one at a time, not alongside browser sessions or a running API (they share the CPU with the solver).

## Domain rules (non-negotiable; set by the owner)

1. **`main` = only what physically exists today.** Every not-yet-built project, and any future network asset, is an
   OPTIONAL registry item or a connection someone places on a branch. Never pre-load, inject in the background, or reserve
   capacity for it. `main` changes only by merging a branch into it; its demand profile stays editable (it is how today's
   network is studied, not a change to it).
2. **Physics is deterministic.** Feasibility comes from AC power flow only (pandapower, `network.feasibility`), the same
   inputs always giving the same result. Nothing in the product guesses a physical figure.
3. **Parameters are set by the data, not the operator.** No physics knobs in the UI; tunables live in `config.py`, each in
   the register (`docs/sources-and-assumptions.md`). The operator chooses what to connect, where and when, and the demand pathway.
4. **Two study cases.** The two planning conditions the SQSS sets at the interface with a distribution network (forecast
   group demand, forecast minimum demand), which are also the two headroom studies every DNO's Network Development Plan
   publishes (peak against capacity; all generation at minimum demand). `winter_peak`: grown demand, winter ratings, PV and
   wind at nil, batteries charging at `import_mw`. `summer_min`: the LTDS minimum-demand factor, not grown, summer ratings,
   everything at full export. A change to the study basis needs a source in the register first. Voltage limits are the
   statutory bands by level (`VOLTAGE_BANDS`), judged after the tap changers have settled (`_solve` regulates them). Every
   `Reason` carries the element, the value, the `limit` and the `case`. Every plan year is reported as it stands, every
   breach listed; nothing is a gate.
5. **Real data, real units.**
   - Never hardcode a voltage or ratio: line MVA comes from `voltage_kv`, transformer ratios from `hv_kv`/`lv_kv`.
   - LTDS rows with Status `Removed` are excluded (the LTDS is a change-log against NGED's previous edition).
   - Cite sources (resource ids live next to the constants in `nged.py`).
   - Bundled ECR data: the fetch drops the register's customer-name, address, postcode and MPAN/MSID columns (`ECR_KEEP`).
     `customer_site` is kept as NGED publishes it; for small sites it is often a property name or an address.
6. **Honesty over fake precision.** State limitations instead of modelling them badly: the 400 kV network is context only,
   the GSP limit's sign convention is assumed, the tap step (1.25%), the tap-changer target (1.02 pu) and the per-case
   dispatch factors (including demand projects at 50% of `import_mw` at summer minimum) are planning assumptions, a year is
   two snapshot cases, not a time series. Don't tune constants for nicer-looking output. Every source and assumption is in
   the *Sources and assumptions* register (`docs/sources-and-assumptions.md`): a new or changed constant updates it in the same change.

## Code style and design

### SOLID

SOLID is a standing rule, applied when you write or change code; say so in review when a change bends it.

- **S: one reason to change.** HTTP routing, SQL, caching, job scheduling and the engine are separate modules. If a
  function needs "and" to describe it, or passes ~100 lines, split it.
- **O: extend by adding, not editing.** Variation points are data or registries, not `if kind == ...` ladders: study cases
  are `network.CASE_SPECS` entries, limit checks `network.LIMIT_CHECKS`, technologies `config.GENERATION_FACTORS` and the
  web's `theme.TECH` / `ui.tsx` `TECH_ICON` (typed `Record<Tech, …>`, so a new technology fails to compile until it has an
  entry), the side panel's tabs `SidePanel.TABS`.
- **L: substitutable implementations.** Anything behind a `Protocol` (`GridSource`) or a callable seam (`net_factory`,
  `progress`) must work with any implementation that honours the contract.
- **I: small, role-shaped interfaces.** A function takes a cursor, not the store.
- **D: depend on abstractions, wire in one place.** Collaborators (warehouse, store, cache, grid) are passed in. Only
  `deps.py` (API) and the entry points construct concrete instances. Engine functions take `net_factory=`.

Pragmatism: don't add an interface for something with one implementation and no need to vary it. A refactor must not
change engine output (compare a run before and after, or run the engine suite).

### Conventions across packages

- **Change the output shape in one pass:** `types.py` → the API (`service.py`) → `apps/web/src/types.ts` + `src/api.ts` →
  the component that renders it.
- Delete dead code rather than keeping it "not wired". Update the READMEs in the same change when behaviour, endpoints or
  commands change.

## Security considerations

- Never commit `.env`.
- The ECR fetch drops customer names, addresses, postcodes and MPANs (`ECR_KEEP`); never add a personal column back.
- The API's CORS is permissive for local development (`main.py`); lock it down before deploying anywhere.

## Commits and PRs

- **Don't commit or push unless asked.** The owner's usual flow is a feature branch fast-forwarded into `main`; ask before
  pushing, and never force-push `main`.
- Check `git status` shows new frontend files before committing (the root `.gitignore` ignores every `lib/` except
  `apps/web/src/lib/`).

## Working agreements

- **Verify in a real browser** before saying UI work is done; a typecheck and a build aren't enough.
- **Stay lean (MVP).** Smallest change that makes the backbone better. No speculative options, no new tests, no docs beyond
  keeping the existing ones true. Reports and audits go in `docs/reports/`.
- **Agent guidance lives only in `AGENTS.md` files**: this one and one per package. Don't add `CLAUDE.md`, `.cursorrules`
  or other tool-specific copies.
- Keep the Turborepo block below committed and unedited; turbo re-adds it.

# This is NOT the Turborepo you know

Turborepo configuration, task behavior, and CLI commands can vary between installed versions and may differ from your training data. Resolve the `turbo` package from this file's directory or relevant workspace; in monorepos, it may not be visible from the repository root. For example, run `node -p "require.resolve('turbo/package.json')"` from a workspace that depends on `turbo`.

Read `docs/README.md` inside that installed package first, then read the relevant pages from its `docs/` directory before changing Turborepo configuration or commands. Heed deprecation notices. These bundled docs match the installed package version and are available without network access.

This block is written and re-added by `turbo` before repository-scoped commands when an AI agent is detected. In the Turborepo source repository, its template is defined in `crates/turborepo-cli/src/cli/agent_guidance.rs`. Removing the managed block while updates are enabled means a later qualifying invocation will add it again. Set `"agentGuidance": false` in the root `turbo.json` or `turbo.jsonc` to opt out; this does not remove an existing block. Keep the block committed with your work to avoid an uncommitted change on the next agent invocation.
<!-- END:turborepo-agent-rules -->
