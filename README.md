# GridForge

**An automated connection-queue planner for distribution grids — it decides which generation and storage projects connect, in what order, and in which year, gated by real power-flow physics.**

GridForge simulates Great Britain's [connection-queue reform](https://www.neso.energy/industry-information/connections-reform) — *"first ready and needed, first connected."* You feed it a queue of proposed generation/storage projects; it ranks them by **readiness**, **grid need**, and **strategic fit**, then connects them greedily — accepting a project only if an AC power flow on the (demand-grown) network stays inside voltage and thermal limits, and otherwise **deferring** it with the exact binding constraint. Every project lands in **Phase 1 (connect by 2030)**, **Phase 2 (by 2035)**, **Deferred**, or **Rejected at intake**. You don't place projects by hand — the system computes the queue.

It's built around the data reality of a GB distribution network operator (DNO/DSO): a versioned, auditable source-of-truth for the grid model, with an LLM used only at the messy edges and never allowed to bypass the physics.

The sample network is `mv_oberrhein`, a real 20 kV distribution feeder (≈179 buses); after geolocation the served model exposes **174 buses, 170 lines, 2 HV/MV transformers, and 142 loads totalling ≈62 MW**.

---

## Contents

- [The idea: right tool for each job](#the-idea-right-tool-for-each-job)
- [How it works, end to end](#how-it-works-end-to-end)
- [The optimizer engine](#the-optimizer-engine)
- [The data pipeline](#the-data-pipeline)
- [HTTP API](#http-api)
- [The planner UI](#the-planner-ui)
- [Quickstart](#quickstart)
- [Repository layout](#repository-layout)
- [Tech stack & tests](#tech-stack--tests)

---

## The idea: right tool for each job

The design principle is that different sub-questions want different machinery, and conflating them is where these systems go wrong:

| Question | Who answers it | Why |
|---|---|---|
| *Can the grid physically take this?* | **pandapower AC power flow** (deterministic) | Safety-critical physics. Never guessed. |
| *Is this project ready?* | **A deterministic rubric** over LLM-**extracted facts** | Readiness is a factual Gate-2 checklist (land, consent, connection agreement, financing, timeline). Auditable — every point traces to a milestone an engineer could verify. |
| *Is this the right addition to the grid?* | **Jev**, a typed **decisions model** (TypeSafe, via OpenRouter) | Genuine judgment, grounded in the measured grid signal — and it returns a **calibrated confidence** (the act-vs-defer knob). |
| *Pull the structured facts out of a free-text application* | **Claude Sonnet** (strict JSON schema) | Extraction from messy text is what LLMs are reliable at. |
| *Explain the finished queue* | **Claude Sonnet** (narration) | Prose over a decision that's already been made deterministically. |

The LLM never self-scores readiness and never decides feasibility. It extracts facts and writes prose; a transparent rubric and a power flow do the deciding; a decisions model makes the one genuinely judgmental call and tells you how sure it is.

---

## How it works, end to end

```
 ┌─────────────────────── apps/pipeline (Dagster) ───────────────────────┐
 │                                                                       │
 │  pandapower mv_oberrhein ┐                                            │
 │  substations.geojson     ├─► canonical model ─► 5 asset checks ─► served_model
 │  asset_register.csv      ┘   (buses/lines/trafos/loads)              │     │
 │                                                                       │     ▼
 │  connection_requests/*.txt ─► extracted_connections (Sonnet)         │  DuckDB
 │        │                           │                                  │  warehouse
 │        │                           ▼                                  │  ├ buses/lines/
 │        │                     scored_connections ──► served_candidates │  │  trafos/loads
 │        │   • deterministic readiness rubric  ◄─ extract checklist (Sonnet)│  ├ snapshots (hash)
 │        │   • Jev strategic fit  ◄─ grid signal from a power-flow solve │  └ candidate_projects
 │        └───────────────────────────────────────────────────────────► │     │
 └───────────────────────────────────────────────────────────────────────┘     │
                                                                                 ▼
 ┌───────────────── apps/api (FastAPI) ─────────────────┐   reads warehouse (read-only)
 │  GET /model          grid geometry for the map        │
 │  GET /optimize/candidates   the queued projects       │
 │  GET /forecasts      DFES demand pathways              │
 │  POST /optimize      run the greedy optimizer ─────────┼─► packages/optimizer
 │     (deterministic ranking + power flow; LLM only      │   (shared engine)
 │      for the closing narrative)                        │
 └────────────────────────────┬──────────────────────────┘
                              ▼
 ┌──────────── apps/web ───────────┐
 │  /planner  MapLibre map + queue │  pick a DFES scenario → Run → see the ordered
 │  table + timeline + alerts      │  queue, the phased build-out on the map, and the
 └─────────────────────────────────┘  loading heat overlay
```

**Nondeterministic work (the LLM/Jev calls) happens once, in the pipeline, and is persisted to the warehouse.** The API's `/optimize` re-runs only the deterministic ranking + power flow at request time (plus one optional narration call), so it's fast and reproducible: the same inputs always give the same queue.

---

## The optimizer engine

`packages/optimizer` (`gridforge_optimizer`) is a standalone, tested Python package — the single source of truth for the physics and the scoring, shared by both the pipeline and the API via a local editable path dependency. **See [`packages/optimizer/README.md`](packages/optimizer/README.md) for the full deep-dive.** In brief:

**Ranking.** Valid projects are ordered by
`rank_score = 0.5·readiness + 0.35·grid_need + 0.15·strategic_fit`
(weights in `config.py`), tie-broken by readiness, then smaller rating, then id.

- **readiness** — deterministic rubric (`readiness.py`) over an LLM-extracted Gate-2 checklist. Weights: land rights 0.30, planning consent 0.30, connection agreement 0.20, financing 0.10, commissioning timeline 0.10. Returns the score **plus a per-milestone breakdown**, so it's fully auditable.
- **grid_need** — computed from a power-flow solve (`scoring.py`): local demand served + voltage depression at the connection bus, under the 2035 growth scenario. Weak, demand-heavy buses score higher ("first *needed*").
- **strategic_fit** — the **Jev** decisions model judges `{high, medium, low}` grounded in the project + its grid signal; the score is the expected value over Jev's probability distribution, and its **calibrated confidence** is persisted.

**Greedy feasibility gate.** For each phase (2030, then 2035) the engine builds the network once, grows demand, keeps every already-accepted generator connected, and trials each ranked project in turn with a `create_sgen` injection (PQ, so it does *not* regulate voltage — violations surface honestly). It runs `pp.runpp` and accepts the project only if **all bus voltages stay in [0.9, 1.1] pu and every line & transformer loading stays ≤ 100%**; otherwise it rolls the injection back and records the binding constraint. A project deferred in 2030 remains eligible in 2035 — higher demand can open thermal headroom for local generation that had none before.

**Two realistic outcomes the demo is built to show:**
- **Rejected at intake** — e.g. a request at a bus that doesn't exist, or 850 MW on a 20 kV feeder (> the 20 MW plausibility cap). Never injected.
- **Ready but Deferred** — a project with high readiness that the grid physically can't absorb yet. That gap — *ready ≠ connectable* — is the entire reason the reform exists.

Demand growth is **per-bus and average-preserving** (`network.per_bus_growth`): a NESO FES 2025 pathway sets the feeder-wide multiplier, but growth is distributed spatially — residential "MV/LV Station" loads surge (EVs + heat pumps), directly-connected industrial "MV Load" crawls, with seeded hotspots — so the feeder total lands exactly on the scenario figure while *which lines bind first* reflects real heterogeneity.

---

## The data pipeline

`apps/pipeline` is a [Dagster](https://dagster.io) project of software-defined assets — lineage is inferred from function parameters and visible in the Dagster UI. It ingests four mismatched sources, reconciles them into one validated canonical model, serves it to DuckDB with a content-hash snapshot, and turns free-text applications into scored candidates. **Full write-up in [`apps/pipeline/README.md`](apps/pipeline/README.md).** The asset graph:

- **Bronze** — `raw_network` (pandapower `mv_oberrhein`), `raw_geojson` (substation coords, 5 deliberately missing), `raw_register` (a messy line-rating CSV), `raw_connection_requests` (10 free-text `.txt` applications).
- **Canonical** — `canonical_buses` / `canonical_lines` / `canonical_transformers` / `canonical_loads` (reconcile + clean).
- **Checks (5)** — coords present (WARN), ratings positive (ERROR), no phantom lines (WARN), network connected across lines *and* transformers (ERROR), power flow converges within voltage band (WARN).
- **Serve** — `served_model` → DuckDB warehouse tables + a `snapshots` row (SHA-256 content fingerprint; same data → same id).
- **LLM edge** — `extracted_connections` (Sonnet, strict JSON → typed fields + confidence), `triaged_connections` (validate each extraction **against the canonical model**, not against its self-reported confidence).
- **Optimizer inputs** — `scored_connections` (intake triage + deterministic readiness + Jev strategic fit, grounded in a power-flow grid signal) → `served_candidates` writes the `candidate_projects` table the API reads.

---

## HTTP API

`apps/api` (FastAPI) serves the validated model read-only from the warehouse and runs the optimizer on demand. User-added projects go to a separate scenarios DB, so the pipeline baseline is never mutated.

| Method & path | Purpose |
|---|---|
| `GET /health` | liveness + whether the warehouse exists |
| `GET /model` | buses / lines / transformers / loads with coordinates, for the map |
| `GET /forecasts` | the DFES demand pathways (default + `growth_2030/2035`) |
| `GET /optimize/candidates` | the queued projects (baseline + any added via the UI) |
| `POST /optimize/candidates` | add a project (stored in the scenarios DB; clears the result cache) |
| `POST /optimize` | run the optimizer → ordered queue, per-phase results (incl. per-line `line_loading` for the heat overlay), and an LLM narrative |

`POST /optimize` takes `{ scenario, growth_2030, growth_2035, w_*, with_justification }`. A named `scenario` (`ht`/`ee`/`he`/`fb`) resolves to that DFES pathway's per-bus growth; `scenario: "custom"` uses the posted scalars as uniform growth. Results are cached by `(scenario, growths, weights, snapshot)`.

---

## The planner UI

`apps/web` is a Next.js app; `/` redirects to `/planner`, a self-contained MapLibre planner (served from `public/planner/`) wired live to the API. Pick a DFES scenario, hit **Run**, and you get: the ranked connection queue with status chips and the binding constraint for every deferral; the phased build-out drawn on a real basemap (Phase 1 / Phase 2 / deferred / rejected markers); a 2030↔2035 toggle; an **exact per-line loading heat overlay**; and alerts for overloaded or near-limit lines. The same page runs fully offline against a built-in mock client (`gridforge-api.js`, `mock` flag) that mirrors the API shapes.

---

## Quickstart

**Prerequisites:** Node 22 + pnpm 10, Python 3.11+ with [uv](https://docs.astral.sh/uv/), and an [OpenRouter](https://openrouter.ai) API key.

```bash
# 1. install JS deps (monorepo root)
pnpm install

# 2. add your key where the pipeline and API both read it
#    apps/pipeline/.env   →   OPENROUTER_API_KEY=sk-or-...

# 3. populate the warehouse (runs the pipeline: extraction + readiness + Jev + serve)
cd apps/pipeline
uv run dagster asset materialize -m grid_simulator.definitions --select "*"
#   …or `uv run dg dev` and click “Materialize all” in the Dagster UI (http://localhost:3000)

# 4. run the demo — two terminals, from the repo root
pnpm --filter @gridforge/api dev     # FastAPI on http://localhost:8000
pnpm --filter web dev                # planner on http://localhost:3000
```

Open **http://localhost:3000** and hit **Run**.

> **Port note:** the Dagster UI (`dg dev`) and the web app (`next dev`) both default to port **3000**. Run them at different times — for the demo you only need the API + web. The deterministic parts (power flow, ranking) need no API key; only the pipeline's extraction + readiness-checklist + Jev calls do (~25 cheap calls per full materialize).

---

## Repository layout

```
grid-simulator/                 pnpm workspace + Turborepo
├─ apps/
│  ├─ pipeline/                 Dagster: ingest → canonical → checks → serve → score
│  │  ├─ src/grid_simulator/defs/   raw · canonical · checks · serve · connections · optimizer_inputs
│  │  ├─ data/raw/              mv_oberrhein-derived sources + 10 connection_requests/*.txt
│  │  └─ warehouse/             DuckDB (gitignored)
│  ├─ api/                      FastAPI: /model, /forecasts, /optimize, …
│  └─ web/                      Next.js; public/planner = the live MapLibre planner
└─ packages/
   └─ optimizer/                gridforge_optimizer — the deterministic engine + scoring
      └─ src/gridforge_optimizer/   config · types · network · scoring · readiness · greedy · llm
```

The Python apps carry thin `package.json`s whose turbo tasks shell to `uv`, so one `pnpm` command drives the polyglot monorepo. `packages/optimizer` is consumed by both Python apps via `[tool.uv.sources] gridforge-optimizer = { path = "../../packages/optimizer", editable = true }`.

---

## Tech stack & tests

**Dagster** 1.13 · **pandapower** 3.5 (+ numba JIT) · **DuckDB** · **FastAPI** · **pydantic** · **Next.js** 16 + **MapLibre GL** · **Claude Sonnet** (extraction, readiness-checklist, narration) and **TypeSafe Jev** (strategic-fit decision), both via **OpenRouter** · **pnpm** + **Turborepo** + **uv**.

```bash
# optimizer engine (9 tests: feasibility, greedy ranking/deferral, per-bus growth, readiness rubric)
cd packages/optimizer && uv run pytest -q

# pipeline
pnpm --filter @gridforge/pipeline test
```

---

*A portfolio project. The network is a real feeder; the connection applications and asset-register mess are synthetic fixtures crafted to exercise every path — including the two cases that matter most: an implausible request rejected at intake, and a genuinely ready project the grid can't yet absorb.*
