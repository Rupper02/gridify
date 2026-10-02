# GridForge

**A pull-request workflow for grid connections, run on a real UK distribution network.**

GridForge models one real Grid Supply Point — **Bicker Fen 132 kV, Lincolnshire**, operated by National Grid Electricity Distribution (NGED) — built entirely from open data. `main` is the network **as it exists today**. Every project that isn't built yet sits in a registry of optional projects. You branch `main`, pull projects onto the branch, and the engine works out which of them the grid can take, in what order and in which year. Each answer is checked with AC power flow, and every "no" names the element that blocks it and what it would take to fix. You review the consequence against `main` and merge it, or throw it away.

The physics is deterministic and reproducible. An LLM is used only to phrase results in plain English, and it is optional.

---

## Contents

- [What you can do](#what-you-can-do)
- [The network and the data](#the-network-and-the-data)
- [How a project is judged](#how-a-project-is-judged)
- [Architecture](#architecture)
- [HTTP API](#http-api)
- [Quickstart](#quickstart)
- [Refreshing the data](#refreshing-the-data)
- [Repository layout](#repository-layout)
- [Tests](#tests)
- [Limitations](#limitations)

---

## What you can do

| | |
|---|---|
| **`main` = today** | The as-is network: 14 connected generators (376.5 MW), 49 demand points and the GSP. Nothing is pre-loaded for future years. Anything not built yet counts only once you add it. |
| **Registry** | 20 optional projects (1,691.5 MW): every site NGED lists as *accepted to connect* at this GSP, plus one transmission-registered project that would connect at the GSP itself. |
| **Branch** | Create a branch, pull projects onto it, and run the optimiser. Phase 1 (by 2030), Phase 2 (2031–35), Deferred or Rejected, with the binding constraint for every deferral. |
| **Timeline** | A 2026→2035 slider. Projects appear in the year they energise, and the demand lens switches at 2030. |
| **Energisation year** | The optimiser **recommends** a year for each accepted project. You can set your own: it's saved on the branch, and an earlier-than-recommended year is flagged as *against the recommendation*. |
| **Review** | A consequence diff of the branch against `main`: who connects or slips, MW by 2030/2035, and lines and buses that become newly overloaded or cleared. |
| **Copilot** | "What would it take": for deferred projects, the engine tests concrete reinforcements (parallel circuits, reactive power, or a new supergrid transformer) and **measures** the MW each would free. |
| **Merge / Discard** | Merging adopts the branch as the new plan of record. |

---

## The network and the data

All inputs are public. Each source is fetched by a script and bundled under `packages/optimizer/src/gridforge_optimizer/data/nged/`.

| Data | Source | Used for |
|---|---|---|
| Circuits, transformers, demand, nodes, generation | NGED **Long Term Development Statement** (LTDS) tabular model, via the Connected Data Portal CKAN API | The pandapower network |
| Accepted-to-connect sites | NGED **Embedded Capacity Register** (ECR) | The project registry: location, connection voltage, export capacity, target date |
| Supergrid transformer limits | NGED *Bicker Fen Td Limits* (asset limits, transmission–distribution) | The GSP export limit |
| Transmission projects at Bicker Fen | NESO **TEC Register** and **Interconnector Register** | Context, and one optional project that connects at the GSP |
| Substation positions | **OpenStreetMap**, © OpenStreetMap contributors, ODbL | Real coordinates for 29 of 68 substations. The rest (mostly line tee-points) sit between their neighbours |

NGED's own substation-location datasets are access-restricted, which is why positions come from OpenStreetMap.

**Building today's network** (`gridforge_optimizer/nged.py`):
- Rows the LTDS marks **Removed** are dropped. The LTDS flags every row against NGED's previous edition, and a replaced transformer appears once as *Removed* and once as *New*.
- Switches and zero-impedance links are merged into single buses.
- Impedances are converted from %Z on a 100 MVA base.
- Demand is LTDS maximum demand × 0.55 (an after-diversity peak).
- The 132 kV busbar is the transmission infeed.

The result has **139 buses, 128 lines, 44 transformers and 170 MW of demand**. It solves with every voltage in band and the worst line at 58%. Today the region **exports ~226 MW up to the transmission system**, because it generates more than it uses.

---

## How a project is judged

**1. Intake.** A project needs a bus that exists in the model and a rating between 0 and 300 MW. That cap is a plausibility check: NGED has accepted 248 MW at 132 kV here. Anything else is *Rejected*, with the reason.

**2. Ranking: "first ready and needed, first connected".**
```
rank_score = 0.5 · readiness + 0.35 · grid_need + 0.15 · strategic_fit
```
- **Readiness** is a deterministic rubric over published facts: land rights 0.30, planning 0.30, connection agreement 0.20, financing 0.10, timeline 0.10. An ECR "accepted to connect" entry is a signed connection agreement. The ECR doesn't publish land, planning or financing, so those earn no credit, and the rationale says so.
- **Grid need** comes from a power-flow solve: local demand plus voltage depression at the bus.
- **Strategic fit** is a simple per-technology prior. Storage scores higher at an export-constrained GSP.

**3. The feasibility gate.** Projects are trialled greedily in rank order for each phase. A project is accepted only if the network passes **both planning study cases**:

| Case | Demand | Thermal ratings | Why it matters |
|---|---|---|---|
| Winter peak | maximum demand, grown by the NESO FES 2025 pathway | winter | demand-driven overloads and low voltage |
| Summer minimum | LTDS minimum-demand factor (~48% of max), *not* grown | summer (~90% of winter) | the **generation**-critical case: the least local load to absorb export |

On top of both cases:
- Voltages must stay in [0.9, 1.1] pu.
- Every line and transformer must stay at or below 100%.
- **The GSP must not export more than its supergrid transformers allow.** That's 2 × 263.5 MW = 527 MW. With one transformer out it's 263.5 MW; that figure is shown but not enforced.

For this region, the GSP boundary, not the local wires, is usually what fills up first.

**4. Year.** The **recommended** year is the developer's requested date, clamped into the window the grid can host: 2027–30 for Phase 1, 2031–35 for Phase 2. Deferred projects get none.

**5. "What would it take".** For each deferred project, the engine tests a concrete lever and re-solves to measure the MW it frees:
- **Line or transformer bottleneck**: chain parallel circuits.
- **Voltage limit**: absorb reactive power at a lower power factor.
- **GSP export limit**: add a supergrid transformer (+263.5 MW). This is transmission work, outside the distribution operator's control. The caveat says so, and suggests flexible connections or storage instead.

Engine details: [`packages/optimizer/README.md`](packages/optimizer/README.md).

---

## Architecture

```
  NGED LTDS + ECR + Td limits ─┐                     apps/pipeline (Dagster)
  NESO TEC register           ├─► ltds_tables ─► nged_model_canonical ─► 3 asset checks ─► served_nged
  OpenStreetMap substations   ┘                  nged_connection_queue (registry) ──────┘       │
                                                                                                 ▼
                                                                    DuckDB warehouse: buses · lines ·
                                                                    transformers · loads · generators ·
                                                                    candidate_projects · snapshots
                                                                                                 │ read-only
  packages/optimizer (gridforge_optimizer): the engine,                                          ▼
  shared by pipeline + API    ◄────────────────────────────────  apps/api (FastAPI) ── scenarios.duckdb
                                                                   branches · added projects ·
                                                                   scheduled years
                                                                                                 │
                                                                                                 ▼
                                                                  apps/web (Vite + React): MapLibre map,
                                                                  queue, timeline, review, copilot
```

- **The warehouse is never mutated by the app.** Branches, added projects and chosen years live in a separate scenarios DB.
- **`main` is a branch row too.** Merging squashes a branch into it, last write wins.
- **Results are cached** by inputs plus a hash of the branch's candidate set, so two branches can never serve each other's queue.

---

## HTTP API

`apps/api`, FastAPI on port 8000.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness, and whether the warehouse exists |
| `GET /model` | Buses, lines, transformers, loads and the existing fleet, with coordinates |
| `GET /boundary` | GSP export limit, export today, and transmission projects (with registry ids where optional) |
| `GET /forecasts` | NESO FES 2025 demand pathways, plus the intake cap |
| `GET /registry` | The optional projects |
| `POST /optimize` | Run `main` |
| `POST /branches` · `GET /branches` | Create and list branches |
| `POST /branches/{id}/registry` | Pull a registry project onto a branch |
| `POST /optimize/candidates` | Add a hand-entered project |
| `POST /branches/{id}/optimize` | Run a branch: queue, per-phase results, GSP exchange, recommended and scheduled years |
| `POST /branches/{id}/schedule` | Set or clear a project's energisation year (`against_recommendation` is reported back) |
| `GET /branches/{id}/diff` | Consequence diff against the parent branch |
| `GET /branches/{id}/suggestions` | "What would it take" levers with measured MW freed |
| `POST /branches/{id}/merge` · `/discard` | Adopt into `main`, or drop |

Narration (`with_justification`, `with_narration`) calls an LLM through OpenRouter if `OPENROUTER_API_KEY` is set. Without a key, everything else works and the narration is simply empty.

---

## Quickstart

**Prerequisites:** Node 22 + pnpm 10, Python 3.11+ with [uv](https://docs.astral.sh/uv/). No API key is needed.

```bash
pnpm install                                   # JS deps (monorepo root)

# build the warehouse from the bundled data (runs the Dagster asset graph + checks)
cd apps/pipeline
uv run dagster asset materialize -m grid_simulator.definitions --select 'ltds_tables*'
cd ../..

# run the app — two terminals, from the repo root
pnpm --filter @gridforge/api dev               # API on http://localhost:8000
pnpm --filter web dev                          # planner on http://localhost:3000
```

Open **http://localhost:3000**. You land on `main`, today's network. Open **Review → New branch**, then **Browse registry** and add projects. The plan re-runs as you add.

- **Shell quoting:** quote `'ltds_tables*'`, or the shell may expand it. It selects the root asset and everything downstream.
- **Dagster UI:** `uv run dg dev` shows lineage and check results. It also uses port 3000, so don't run it alongside the web app.
- **Narration (optional):** put `OPENROUTER_API_KEY=…` in `apps/pipeline/.env`.

---

## Refreshing the data

The bundled data is a snapshot. Each refresh script writes into `packages/optimizer/src/gridforge_optimizer/data/nged/`:

```bash
cd apps/api
uv run python ../pipeline/scripts/fetch_nged_ecr.py          # Embedded Capacity Register -> ecr.json (no personal data kept)
uv run python ../pipeline/scripts/fetch_osm_substations.py   # OpenStreetMap substations -> coords.csv
```

Then re-materialise the pipeline.

The LTDS tables (`circuit`, `t2a`, `demand`, `node`, `gen`) were pulled from the Connected Data Portal's `datastore_search` API. The GSP limits and transmission projects are recorded, with their resource ids, in `nged.py` (`GSP_BOUNDARY`, `TRANSMISSION_PROJECTS`).

---

## Repository layout

```
grid-simulator/                    pnpm workspace + Turborepo
├─ apps/
│  ├─ pipeline/                    Dagster: bundled data → canonical model → checks → warehouse
│  │  ├─ src/grid_simulator/defs/nged.py   the asset graph
│  │  └─ scripts/                  fetch_nged_ecr · fetch_osm_substations (data refresh)
│  ├─ api/                         FastAPI: model, registry, branches, optimize, diff, suggestions
│  └─ web/                         Vite + React + TypeScript planner: src/hooks/usePlanner.ts (controller), src/api.ts, src/components/
└─ packages/
   └─ optimizer/                   gridforge_optimizer: network build, feasibility, greedy, suggest, diff
      └─ src/gridforge_optimizer/data/nged/   bundled open data
```

The Python apps have thin `package.json`s whose turbo tasks shell out to `uv`. Both consume `packages/optimizer` as an editable path dependency.

---

## Tests

```bash
pnpm test                                     # everything, via Turborepo
# or individually
cd packages/optimizer && uv run pytest -q     # engine: 30 tests
cd apps/api && uv run --with pytest pytest tests -q   # API: 11 tests (each run uses its own temp scenarios DB)
cd apps/web && pnpm test                      # UI: 13 vitest unit tests (reason wording, timeline/queue/alert derivations)
```

The engine tests are **grid-agnostic**: fixtures are derived from whatever network `build_base_net()` returns, never from hard-coded bus ids. `test_nged.py` adds the NGED data rules:
- removed equipment is excluded;
- every live MW of demand is modelled;
- no registry project is pre-loaded into today's network.

---

## Limitations

- **The GSP export limit is the only transmission constraint modelled.** The 400 kV network and wider transmission boundaries are not; the 400 kV projects are context only.
- **Fault levels are not checked.** NGED publishes them, but the units are undocumented and some breaker ratings sit below the calculated fault current, so they can't be used safely as-is.
- **Generation is studied at full export in both cases.** That includes batteries, which could also import. This is conservative.
- **Demand growth comes from a NESO FES pathway, spread per bus** with a seeded spread, distance from the GSP and hotspots. The LTDS's own 5-year substation forecasts are not used yet.
- **The GSP limit's direction is an assumption.** NGED's dataset doesn't document its sign convention; we read "export" as distribution → transmission.