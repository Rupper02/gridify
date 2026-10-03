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
| **Timeline** | A 2026→2035 slider. Every year of the plan is solved in the run (demand grown to that year, the projects energised by then), so moving the slider only switches between stored results; it never re-runs. |
| **Planned works** | Schedule maintenance, a like-for-like replacement or a repowering on a line, transformer or existing generator in a season of a year on a branch. The next run studies it in that season's case(s) and gives a verdict: feasible, feasible with curtailment, demand at risk, or not feasible. A repowering brings the element back with more capability from the following year. |
| **Energisation year** | The optimiser **recommends** a year for each accepted project. You can set your own: it's saved on the branch, and an earlier-than-recommended year is flagged as *against the recommendation*. |
| **Review** | A consequence diff of the branch against `main`: who connects or slips, MW by 2030/2035, and lines and buses that become newly overloaded or cleared. |
| **Copilot** | A guided **New project** intake, and **Recommendations**: "what would it take" for deferred projects. The engine tests concrete reinforcements (parallel circuits, reactive power, or a new supergrid transformer) and **measures** the MW each would free; a lever can be tried on the branch and the next run measures it against the whole queue. |
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
- The 14 connected generators sit at the substations NGED names for them, at their connection voltage (a site at a double-busbar substation is shared across its sections).
- Every transformer carries its LTDS tap range as an on-load tap changer; the solver regulates the taps so each 33 kV and 11 kV busbar is held near 1.0 pu, as the real AVC relays do.

The result has **139 buses, 128 lines, 44 transformers and 170 MW of demand**. It solves in both study cases with every bus inside its statutory band; the worst element is the pair of 132 kV circuits carrying the Middlemarsh offshore wind to Skegness, at 94% at summer minimum. Today the region **exports ~224 MW up to the transmission system**, because it generates more than it uses.

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

| Case | Demand | Generation | Thermal ratings | Why it matters |
|---|---|---|---|---|
| Winter peak | maximum demand, grown by the NESO FES 2025 pathway | PV and wind at nil (a winter evening); batteries **charging** at their import capacity; other generation firm | winter | demand-driven overloads and low voltage |
| Summer minimum | LTDS minimum-demand factor (~48% of max), *not* grown | everything at full export | summer (~90% of winter) | the **generation**-critical case: the least local load to absorb export |

On top of both cases:
- Every bus must stay inside its **statutory voltage band**: ±10% at 132 kV, ±6% at 33 kV and 11 kV (GB ESQCR). The tap changers are regulated first, so a breach is one the network cannot tap its way out of.
- Every line and transformer must stay at or below 100%.
- **The GSP must not export more than its supergrid transformers allow.** That's 2 × 263.5 MW = 527 MW. With one transformer out it's 263.5 MW; that figure is shown but not enforced.

For this region, the GSP boundary, not the local wires, is usually what fills up first.

**N-1 screen.** After each phase, and in every plan year, every 132 kV circuit and grid transformer is taken out in turn at winter peak and the result is checked for overloads, band breaches and islanded demand. The findings are shown in the planner but do not gate a connection: a firm-connection standard would, and that is a documented next step.

**Technologies.** How a project is dispatched in each case depends on what it is:
- **Solar, wind**: nil at winter peak, full export at summer minimum.
- **Battery, hybrid (solar + battery)**: charging at its import capacity at winter peak, full export at summer minimum.
- **Demand, electrolyser** (import-only): export nothing. They draw their import capacity at winter peak and half of it at summer minimum (a planning assumption, close to the LTDS minimum-demand factors). Intake judges them on import capacity, not export rating.
- **Gas, gas engines, biomass and anything unclassified**: firm, full output in both cases.

**4. Year.** The **recommended** year is the developer's requested date, clamped into the window the grid can host: 2027–30 for Phase 1, 2031–35 for Phase 2. Deferred projects get none.

**Every year, as a fixed plan.** Once the queue is decided, each year from 2026 to 2035 is solved on its own: demand interpolated (today's level in 2026, the pathway's 2030 multiplier in 2030, its 2035 multiplier in 2035), every accepted project whose year (scheduled, else recommended) has arrived, both study cases and the N-1 screen. This never changes who connects; it shows what the network looks like in the year you are viewing. The year in view is solved first, then 2030 and 2035, then the rest, and the planner shows each as it lands.

**The demand side, every year.** Customers are who the network protects, so each plan year also judges every demand group: one per live LTDS Table 3 row (a primary substation, or a bulk supply point's own 33 kV group per grid transformer). For each group the engine reports its peak demand that year (the row's own maximum demand grown with the pathway, plus any plan project drawing power there at winter peak), what the power flow carries for it (after the GSP diversity factor), its firm capacity and headroom, its demand class under ENA EREC P2/8 (A up to 1 MW, B to 12, C to 60, D to 300, E to 1500, F above), the most demand a single 132 kV outage cuts off in it (from the N-1 screen), its load buses outside the statutory voltage band, and a first-order (≈) room for new demand: the smaller of the firm headroom and the spare winter-peak capacity of the transformers feeding it. Four checks turn that into alerts (`warn` or `breach`): demand above firm capacity, N-1 cutting off demand in a class C or larger group beyond what P2/8 lets wait for restoration, customers' buses outside the voltage band, and firm headroom under 10% of the firm capacity. This is a simplified P2/8-style check, not a P2/8 assessment (see Limitations).

**Planned works.** A branch can carry works windows on a line, transformer or existing generator in one season of one year: maintenance (out of service, or derated to 50%), a like-for-like replacement, or a repowering (out for the window, then back from the following year uprated by a factor or with a parallel circuit). Each is studied in that year's network in the case its season stresses: winter peak in winter, summer minimum (summer ratings) in summer, both in spring and autumn with the LTDS intermediate-warm ratings. Windows in the same season and year are studied together. The verdict is *feasible*; *feasible with curtailment* (a thermal, export or overvoltage breach that constraining nearby generation clears, with the MW per generator); *demand at risk* (demand cut off, or left outside the voltage band); or *not feasible*. With the window in place the 132 kV backbone is also N-1 screened, to show what a second fault would do. A repowering changes the years after it; the queue itself is still decided on the network as it is. Like N-1, the result is reported per year and never gates a connection.

**5. "What would it take".** For each deferred project, the engine tests a concrete lever and re-solves to measure the MW it frees:
- **Line or transformer bottleneck**: chain parallel circuits.
- **Voltage limit**: absorb reactive power at a lower power factor.
- **GSP export limit**: add a supergrid transformer (+263.5 MW). This is transmission work, outside the distribution operator's control. The caveat says so, and suggests flexible connections or storage instead.

**Try a lever on a branch.** A lever can be stored on a branch as a simulated reinforcement. Every later run of that branch applies it before the greedy loop, so its effect is measured against the whole queue, not just the one project; suggestions on that branch are then trialled on the reinforced network. Reinforcements, like outages, are proposals: `main` changes only by merging.

Engine details: [`packages/optimizer/README.md`](packages/optimizer/README.md).

---

## Architecture

```
  NGED LTDS + ECR + Td limits ─┐                     apps/pipeline (Dagster)
  NESO TEC register           ├─► ltds_tables ─► nged_model_canonical ─► 3 asset checks ─► served_nged
  OpenStreetMap substations   ┘       │          nged_connection_queue (registry) ──────┘       │
                                      └────────► ltds_edition_changes (previous vs current) ────┤
  live registers (scheduled): ecr_register_fetch ─► ecr_editions ─► ecr_changes                 ▼
                              osm_substations_fetch ─► coords_editions      DuckDB warehouse: buses · lines ·
                                                                            transformers · loads · generators ·
                                                                            candidate_projects · ltds_changes ·
                                                                            snapshots (append-only versions) ·
                                                                            ecr_editions · ecr_changes
                                                                                                 │ read-only
  packages/optimizer (gridforge_optimizer): the engine,                                          ▼
  shared by pipeline + API    ◄────────────────────────────────  apps/api (FastAPI) ── scenarios.duckdb
                                                                   branches · added projects ·
                                                                   scheduled years · outages ·
                                                                   reinforcements · result cache
                                                                                                 │
                                                                                                 ▼
                                                                  apps/web (Vite + React): MapLibre map,
                                                                  queue, outages, roadmap, review, copilot
```

- **The warehouse is never mutated by the app.** Branches, added projects, chosen years, planned outages and simulated reinforcements live in a separate scenarios DB. Outages and reinforcements are copied when a branch is created and when it is merged.
- **Versions, not overwrites.** Every content-distinct materialisation appends a `snapshots` row (`network@<snapshot_id>`, tagged with the LTDS edition it was built from). The pipeline also diffs NGED's previous LTDS edition against the current one and stores the change-set, and keeps every fetched edition of the Embedded Capacity Register with a site-level diff between the last two. See [`apps/pipeline/README.md`](apps/pipeline/README.md).
- **`main` is a branch row too.** Merging squashes a branch into it, last write wins.
- **Results are cached durably.** A run is a pure function of the model snapshot, the parameters, the branch's candidate set, its reinforcements and the engine's code, so every result is stored in the scenarios DB under that key: the same run never happens twice, not even after a restart, and two branches can never serve each other's queue. The per-year results are cached separately, under a key that adds the outages and the schedule, so changing a year or a maintenance window re-solves the years but not the queue. Inside a run, the engine keeps an exact trial cache: when a branch gains one project, only the trials whose state changed are solved again.
- **Runs are background jobs that publish as they go.** The planner starts a job and polls it; the overlay shows the engine's real stage (ranking, each phase's trials, the N-1 screen, each year). Once the queue is decided the job publishes partial results (the queue plus the years solved so far, the viewed year first), so the planner fills in before the run finishes. `main` is precomputed when the API starts.
- **The model speaks CIM.** `gridforge_optimizer.cim` serialises the network to CGMES 2.4.15 (equipment, topology, steady-state hypothesis and geography profiles) with deterministic identifiers, so two exports diff like any other versioned artefact. The pipeline writes one per edition (`nged_model_cgmes`); the API serves it at `GET /model/cgmes`. The export is verified by re-importing it with pandapower's CGMES importer: same elements, same ratings, same tap steps, same power-flow solution.
- **Postgres or DuckDB for the scenarios store.** Branches, added projects, schedules and the result cache live in a DuckDB file by default; set `GRIDFORGE_SCENARIOS_URL=postgresql://…` and they live in Postgres instead, through the same SQL (one small dialect layer). The warehouse stays DuckDB.

---

## HTTP API

`apps/api`, FastAPI on port 8000.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness, and whether the warehouse exists |
| `GET /model` | Buses, lines, transformers, loads (each with its `region_id`) and the existing fleet, with coordinates; `regions`: the demand groups (LTDS Table 3 rows) with their buses, firm capacity, demand today and P2/8 class |
| `GET /model/cgmes` | Today's network as a CIM/CGMES 2.4.15 exchange (EQ, TP, SSH, GL in one zip); re-imports with pandapower's CGMES importer to the same power flow |
| `GET /boundary` | GSP export limit, export today, and transmission projects (with registry ids where optional) |
| `GET /forecasts` | NESO FES 2025 demand pathways, plus the intake cap |
| `GET /snapshots` | The model's version history (`network@<snapshot_id>`, newest first, with the LTDS edition of each) |
| `GET /editions/changes` | What changed between NGED's previous LTDS edition and this one: flagged rows, model delta, physics delta |
| `GET /registry/changes` | What changed in the Embedded Capacity Register between the last two fetched editions |
| `GET /registry` | The optional projects |
| `POST /optimize` | Run `main` |
| `POST /branches` · `GET /branches` | Create and list branches |
| `POST /branches/{id}/registry` | Pull a registry project onto a branch |
| `POST /optimize/candidates` | Add a hand-entered project |
| `POST /branches/{id}/optimize` | Run a branch: queue, per-phase results, per-year results (`years`, with outage studies and the demand side: `regions` and `alerts`), GSP exchange, N-1 findings, recommended and scheduled years. Body: `view_year` (solved first), `with_justification` |
| `POST /branches/{id}/optimize/jobs` · `GET /jobs/{id}` | The same run as a background job, with stage and fraction while it runs; `?partial=true` returns the queue plus the years solved so far (`has_partial` says whether there are any) |
| `GET /cache` | What the durable result cache holds, per kind and engine fingerprint |
| `POST /branches/{id}/schedule` | Set or clear a project's energisation year (`against_recommendation` is reported back) |
| `POST /branches/{id}/scenario` | Change a branch's demand profile (pathway and growth); takes effect on the next run |
| `GET` · `POST /branches/{id}/outages` · `DELETE /branches/{id}/outages/{outage_id}` | Planned works windows (line, transformer or existing generator; season, year, outage or derate; `work` maintenance / replacement / repowering, with `repower` uprate + `factor` (1 < factor ≤ 4) or add_parallel for repowering only). 409 on `main` or a branch that isn't open; 422 for an unknown element or season, or a work/repower/factor combination that doesn't fit |
| `GET` · `POST /branches/{id}/reinforcements` · `DELETE /branches/{id}/reinforcements/{reinforcement_id}` | Simulated reinforcements (a Copilot lever tried on the branch), applied by every later run. 409 on `main` or a branch that isn't open |
| `GET /branches/{id}/diff` | Consequence diff against the parent branch |
| `GET /branches/{id}/suggestions` | "What would it take" levers with measured MW freed, trialled on the branch's reinforced network; `?request_id=` narrows it to one deferred project |
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

Open **http://localhost:3000**. You land on `main`, today's network. Create a branch (**New branch** in the header or the Review tab), then add projects from the registry in the Queue tab, or describe one to the Copilot. Added projects show as *Preliminary* until you **Run**; the result is marked out of date (**Re-run**) whenever the demand profile, outages, reinforcements, schedule or projects change.

- **Shell quoting:** quote `'ltds_tables*'`, or the shell may expand it. It selects the root asset and everything downstream.
- **Dagster UI:** `uv run dg dev` shows lineage and check results. It also uses port 3000, so don't run it alongside the web app.
- **Narration (optional):** put `OPENROUTER_API_KEY=…` in `apps/pipeline/.env`.
- **Postgres (optional):** `GRIDFORGE_SCENARIOS_URL=postgresql://user@host:5432/dbname` before starting the API moves the scenarios store to Postgres (tables are created on first use). The API tests run the same workflow against Postgres when `GRIDFORGE_TEST_PG_URL` is set.

---

## Refreshing the data

The bundled data is a **pinned snapshot**. The live registers are fetched by scheduled Dagster assets (`registers` group: the ECR monthly, OpenStreetMap quarterly), stored as append-only editions in the warehouse and diffed edition-to-edition. Adopting a new edition into the model is a deliberate step:

```bash
cd apps/pipeline
uv run dagster asset materialize -m grid_simulator.definitions --select 'ecr_register_fetch,ecr_editions,ecr_changes'   # fetch + diff
uv run dagster asset materialize -m grid_simulator.definitions --select 'pin_ecr_edition'                               # promote it into data/nged/ecr.json
uv run dagster asset materialize -m grid_simulator.definitions --select 'ltds_tables*'                                  # rebuild the model from it
```

Review the git diff of the bundled file, then commit. `osm_substations_fetch` / `coords_editions` / `pin_osm_coords` do the same for substation positions.

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
   └─ optimizer/                   gridforge_optimizer: network build, feasibility, greedy, years, suggest, diff
      └─ src/gridforge_optimizer/data/nged/   bundled open data
```

The Python apps have thin `package.json`s whose turbo tasks shell out to `uv`. Both consume `packages/optimizer` as an editable path dependency.

---

## Tests

```bash
pnpm test                                     # everything, via Turborepo
# or individually
cd packages/optimizer && uv run pytest -q     # engine: 79 tests, 4 workers (pytest-xdist); the N-1 screen is stubbed except where it is under test
cd apps/api && uv run --with pytest pytest tests -q   # API: 26 tests (each run uses its own temp scenarios DB; the per-year N-1 screen is stubbed; +1 against Postgres if GRIDFORGE_TEST_PG_URL is set)
cd apps/web && pnpm test                      # UI: 28 vitest unit tests (reason wording, queue/timeline derivations, Copilot intake and recommendations, run stages)
```

The engine tests are **grid-agnostic**: fixtures are derived from whatever network `build_base_net()` returns, never from hard-coded bus ids. `test_nged.py` adds the NGED data rules:
- removed equipment is excluded;
- every live MW of demand is modelled;
- no registry project is pre-loaded into today's network.

`test_editions.py` covers the edition logic: the previous edition keeps Removed rows and drops New ones, the change-set agrees with NGED's flags, and the ECR diff reports added / withdrawn / connected / re-rated sites.

---

## Limitations

- **The GSP export limit is the only transmission constraint modelled.** The 400 kV network and wider transmission boundaries are not; the 400 kV projects are context only.
- **Fault levels are not checked.** NGED publishes them, but the units are undocumented and some breaker ratings sit below the calculated fault current, so they can't be used safely as-is.
- **Generation dispatch per case is a planning assumption.** PV and wind at nil and batteries (and hybrids) charging at winter peak; everything at full export at summer minimum. Gas, gas engines, biomass and technologies the data doesn't classify are treated as firm in both.
- **Demand projects and electrolysers draw a fixed share.** Their full import capacity at winter peak and 50% of it at summer minimum; that 50% is an assumption, not a measured profile.
- **Planned works are reported, not enforced.** A works window is studied in its season's case(s) and its verdict is shown, but it never blocks a connection. The weeks are recorded but not placed in specific calendar weeks (the season stands in for them), so every window in the same season and year is studied as overlapping. The curtailment figure is a first-order estimate from a bounded search (nearest generators first, at most 8 extra solves per case), not an optimal re-dispatch; no other re-dispatch or switching is modelled. The N-1 screen during a window is informational. A repowering changes only the years after its window, and the queue run does not count it (add the upgrade as a reinforcement for that).
- **Every year is a fixed plan.** The per-year solves show the network in each year; they don't change who connects, which is still decided at the two phase horizons. Demand between them is interpolated linearly.
- **Tap-changer steps are assumed.** The LTDS gives each transformer's tap range but not its step; 1.25% per tap is used. Taps are regulated towards 1.0 pu with a ±0.01 pu deadband.
- **N-1 is reported, not enforced.** The single-outage screen covers the 132 kV backbone at winter peak only; it does not yet apply a security-of-supply standard or screen the 33 kV network.
- **The demand-side alerts are a simplified P2/8-style check.** Restoration times, switching, transfer capacity between groups and second circuit outages are not modelled, so a group P2/8 would pass by switching can still be flagged, and the classes are applied to each LTDS row as published (a two-transformer site fed from two BSPs appears as two groups). Everything is MW of demand: the open data has no customer counts.
- **Firm capacity units are read, not stated.** LTDS Table 3's "Firm Capacity of Substation" has no unit in the data; we read it as MVA and convert it to MW at the row's own power factor. A firm capacity of 0 (single-transformer sites and customers' own connections) is reported as is; such a group is only alerted on once it reaches class C. Firm capacity is compared with the group's own peak, not the GSP-diversified share the power flow carries. The "room for new demand" is first-order (≈): no power-flow probe is run for it.
- **Demand growth comes from a NESO FES pathway, spread per bus** with a seeded spread, distance from the GSP and hotspots. The LTDS's own 5-year substation forecasts are not used yet.
- **The GSP limit's direction is an assumption.** NGED's dataset doesn't document its sign convention; we read "export" as distribution → transmission.
- **The previous LTDS edition is reconstructed, not fetched.** NGED's New/Removed flags give it exactly, but Updated rows carry their current values in both editions because the old values aren't published.

---

## How this was built

GridForge was built in about a week by one person working with Claude Code as a pair, and the commit history says so: every commit carries a `Co-Authored-By: Claude` trailer. It would be odd to hide that from a company that lists "AI-assisted software development" as a skill it hires for, so here is how the division of labour actually worked.

**What the human did.** Chose the problem and the data (one real GSP, open data only, NGED because it is the launch customer's network), set the rules the agent works under (`AGENTS.md`: `main` is only what exists today, the LLM never touches physics, honesty over fake precision), made every product decision (the pull-request framing, the registry of optional projects, "parameters are set by the flows, not the operator", recommend-then-override for energisation years), and reviewed the result in the browser after each slice. The pivots (restoration → data pipeline → connection-queue optimiser → PR workflow on a real network) were human calls, as was the decision to throw away a working manual-editing frontend.

**What the agent did.** Wrote most of the code, the tests and the docs, in slices that the human directed and inspected. Then, asked to review the project as the hiring team would, it produced a critique of its own work and worked through the fixes one at a time.

**What that review caught, because this is the part that matters.** A fresh clone 500'd on first load (two concurrent table creations on an empty database). The frontend was a Next.js shell redirecting to a 1,600-line template-dialect file that compiled JSX in the browser; it was rebuilt as a plain Vite + React + TypeScript app. The Dagster lineage was decorative (assets ignored their inputs) and the snapshot table was overwritten on every run. Voltage limits were 0.9–1.1 pu everywhere instead of the statutory ±6 % below 132 kV, which only became a sensible rule once the tap changers were modelled. The existing fleet was placed round-robin rather than at its real substations. PV ran at full output at the winter evening peak. The Python `.gitignore` template was silently keeping the planner's `src/lib` folder out of git. Tests took ten minutes because every one paid for an N-1 screen it was not testing.

**What the agent got wrong along the way, and how it was caught.** pandapower 3 ignores transformer taps unless a changer type is declared, so the first tap-regulation loop moved taps that did nothing; a probe of the busbar voltages exposed it. The LTDS tap ranges (−12..+4) are HV-winding taps where a lower tap raises the LV voltage; the first implementation tapped the wrong winding and hit the stop. The first React port dropped the coalesced re-run after rapid adds because it read React state that had not flushed yet; a headless browser run that added four projects and found one caught it. In every case the fix came from measuring (a power-flow probe, a request log, a screenshot), not from re-reading the code, and each is now a test.

**Commit discipline.** The early commits are large because the project was built in large slices. From the review onward each change is its own commit with a message that states what was measured. That is the practice going forward.

**Honesty about scope.** This is a planning toy on one GSP built from open data, not a product. The limitations above are real; the numbers are only as good as the LTDS tables and the assumptions written next to them.
