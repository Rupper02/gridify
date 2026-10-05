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
- [Sources and assumptions](#sources-and-assumptions)
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
| **Review** | A consequence diff of the branch against `main`: who connects or slips, MW by 2030/2035, and for the year on the timeline the lines and transformers that become newly overloaded or cleared, voltage, GSP export and N-1 changes. Each planned works window is studied on `main`'s plan too, so the diff says what the branch's projects do to it ("feasible on main, but needs 40 MW of curtailment on this branch"). Diff mode shows the viewed year's loading changes on the map. **Merge readiness** shows the gate's verdict: what the branch introduces or worsens in any plan year blocks, warnings need acknowledging, what main already carries is context. A **Findings** tab lists everything the last run found, year by year. |
| **Ask the agents** | The side panel's first tab and the planner's only conversation: a question in plain words to the answerer agent on the branch, streamed with its planning stages as chips, citing the steps it ran (click a study chip for the evidence), digit figures no step produced flagged. It runs the engine's studies, among them **connection options** for a deferred project (what its own busbar takes of it as a firm or flexible connection, how far parallel circuits get it, which higher-voltage busbars take its full MW) and the **best window** for a planned work, and proposes what to do: add a project, move or resize one, a reinforcement, a works window, a run of the branch. Every proposal waits for your approval; a reply on its way can be stopped. The picker suggests questions from what is in view. The reviewer's comment appears under *Merge readiness*; agent findings in the Findings tab carry an evidence link. |
| **Projects** | NGED's Bicker Fen GSP is the built-in project. Import any other grid as a project: a CIM/CGMES zip, a pandapower JSON or a MATPOWER case, with the limits you know (an export limit, a minimum-demand factor, seasonal rating ratios) entered at import and recorded as yours. The import is validated (counts, islands, a converging base case; a non-convergent or slackless file is refused with the report), what the file does not carry is listed, and the same engine, branches, gate, ledger and agents work on it. |
| **Agents** | With an OpenRouter key, a small roster of long-lived agents is tied to the project: a **steward** that wakes on events (a run finished, a merge, a new model or LTDS edition) and sends specialists (thermal, voltage, demand security, boundary, data quality, works, connections: how the projects a run deferred could connect) to run deterministic studies; a **reviewer** that comments on every branch run like a PR bot, restating the merge gate's verdict; and an **answerer** for your questions, streamed, citing the tool steps it ran, with digit figures no step produced flagged. They plan the study and phrase the result; the engine does the physics. They never merge; what they propose waits for your approval. The OpenRouter key is required: the API does not start without it, and nothing falls back to a key-less substitute. |
| **Merge / Discard** | Merging adopts the branch as the new plan of record, through a gate: it is refused while the branch's result is stale, or while the branch would introduce or worsen a problem in any plan year (what main already carries is context); warnings must be acknowledged. Every run also writes a **findings ledger** per branch. |

---

## The network and the data

All inputs are public. Each source is fetched by a script and bundled under `packages/optimizer/src/gridforge_optimizer/data/nged/`. [Sources and assumptions](#sources-and-assumptions) lists every figure the engine uses and where it comes from.

| Data | Source | Used for |
|---|---|---|
| Circuits, transformers, demand, nodes, generation | NGED **Long Term Development Statement** (LTDS) tabular model, via the Connected Data Portal CKAN API | The pandapower network |
| Accepted-to-connect sites | NGED **Embedded Capacity Register** (ECR) | The project registry: location, connection voltage, export capacity, target date |
| Supergrid transformer limits | NGED *Bicker Fen Td Limits* (asset limits, transmission–distribution) | The GSP export limit |
| Bicker Fen's demand at the GB winter peak | NESO **FES 2024 regional breakdown** (GSP `BICF_1`) | Today's winter-peak demand: 149.2 MW |
| Transmission projects at Bicker Fen | NESO **TEC Register** and **Interconnector Register** | Context, and one optional project that connects at the GSP |
| Substation positions | **OpenStreetMap**, © OpenStreetMap contributors, ODbL | Real coordinates for 29 of 68 substations. The rest (mostly line tee-points) sit between their neighbours |

NGED's own substation-location datasets are access-restricted, which is why positions come from OpenStreetMap.

**Building today's network** (`gridforge_optimizer/nged.py`):
- Rows the LTDS marks **Removed** are dropped. The LTDS flags every row against NGED's previous edition, and a replaced transformer appears once as *Removed* and once as *New*.
- Switches and zero-impedance links are merged into single buses.
- Impedances are converted from %Z on a 100 MVA base.
- Demand is each substation's LTDS maximum, scaled to what is on at the GSP's winter peak by two published figures: each BSP's own maximum (its primaries don't all peak together) and NESO's peak for Bicker Fen GSP, 149.2 MW. No assumed diversity factor. A BSP's own Table 3 rows ("Sleaford (GT1)", "(GT2)") are the group demand its 132/33 kV transformers carry, the same customers as the primaries listed under it, so they add no load: they become the BSP's demand group instead. The summer minimum is each row's maximum × its LTDS minimum-demand factor.
- The 132 kV busbar is the transmission infeed.
- The 14 connected generators sit at the substations NGED names for them, at their connection voltage (a site at a double-busbar substation is shared across its sections; the sections themselves are joined only where the LTDS lists a connector, see *Sources and assumptions*).
- Every transformer carries its LTDS tap range as an on-load tap changer; the solver regulates the taps so each 33 kV and 11 kV busbar is held near 1.02 pu, as the real AVC relays do (the target is an assumption: LTDS doesn't publish it).

The result has **139 buses, 128 lines, 44 transformers and 149 MW of demand at winter peak**. It solves in both study cases with every bus inside its statutory band; the worst element is the pair of 132 kV circuits carrying the Middlemarsh offshore wind to Skegness, at 93% at summer minimum, and the lowest voltage is Horncastle 33 kV at the end of a long feeder, 0.96 pu at winter peak. Today the region **exports ~291 MW up to the transmission system** at summer minimum, because it generates more than it uses.

---

## How a project is judged

**1. Intake.** A project needs a bus that exists in the model and a rating between 0 and 300 MW. That cap is a plausibility check: NGED has accepted 248 MW at 132 kV here. Anything else is *Rejected*, with the reason.

**2. Ranking: "first ready and needed, first connected".**
```
rank_score = 0.5 · readiness + 0.35 · grid_need + 0.15 · strategic_fit
```
- **Readiness** is a deterministic rubric over published facts: land rights 0.30, planning 0.30, connection agreement 0.20, financing 0.10, timeline 0.10. An ECR "accepted to connect" entry is a signed connection agreement. The ECR doesn't publish land, planning or financing, so those earn no credit, and the rationale says so.
- **Grid need** comes from the same power flow as every verdict: the network grown to 2035 at winter peak, the case's dispatch applied, the tap changers settled; the score blends the demand grown at the bus with the voltage depression the relays cannot remove.
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

**N-1 screen.** After each phase, and in every plan year, every 132 kV circuit and grid transformer is taken out in turn in each study case (`config.N1_CASES`: winter peak, where demand binds, and summer minimum, where export binds) and the result is checked for overloads, band breaches and islanded demand; each finding names its case, and islanded demand is reported once, on the winter-peak screen the customer checks read. The findings are shown in the planner but do not gate a connection: a firm-connection standard would, and that is a documented next step.

**Technologies.** How a project is dispatched in each case depends on what it is:
- **Solar, wind**: nil at winter peak, full export at summer minimum.
- **Battery, hybrid (solar + battery)**: charging at its import capacity at winter peak, full export at summer minimum.
- **Demand, electrolyser** (import-only): export nothing. They draw their import capacity at winter peak and half of it at summer minimum (a planning assumption, close to the LTDS minimum-demand factors). Intake judges them on import capacity, not export rating.
- **Gas, gas engines, biomass and anything unclassified**: firm, full output in both cases.

**4. Year.** The **recommended** year is the developer's requested date, clamped into the window the grid can host: 2027–30 for Phase 1, 2031–35 for Phase 2. Deferred projects get none.

**Every year, as a fixed plan.** Once the queue is decided, each year from 2026 to 2035 is solved on its own: demand interpolated (today's level in 2026, the pathway's 2030 multiplier in 2030, its 2035 multiplier in 2035), every accepted project whose year (scheduled, else recommended) has arrived, both study cases and the N-1 screen. This never changes who connects; it shows what the network looks like in the year you are viewing. The year in view is solved first, then 2030 and 2035, then the rest, and the planner shows each as it lands.

**The demand side, every year.** Customers are who the network protects, so each plan year also judges every demand group: one per live LTDS Table 3 primary substation (or a customer's own connection), and one per bulk supply point over the primaries it feeds (at its 33 kV busbars, with its published maximum demand and the firm capacity of its 132/33 kV transformers; its demand is its primaries', never counted twice). For each group the engine reports its peak demand that year (the row's own maximum demand grown with the pathway, plus any plan project drawing power there at winter peak), what the power flow carries for it (its share of the GSP's coincident peak), its firm capacity and headroom, its demand class under ENA EREC P2/8 (A up to 1 MW, B to 12, C to 60, D to 300, E to 1500, F above), the most demand a single 132 kV outage cuts off in it (from the N-1 screen), its load buses outside the statutory voltage band, and a first-order (≈) room for new demand: the smaller of the firm headroom and the spare winter-peak capacity of the transformers feeding it. Four checks turn that into alerts (`warn` or `breach`): demand above firm capacity, N-1 cutting off demand in a class C or larger group beyond what P2/8 lets wait for restoration, customers' buses outside the voltage band, and firm headroom under 10% of the firm capacity. This is a simplified P2/8-style check, not a P2/8 assessment (see Limitations).

**Planned works.** A branch can carry works windows on a line, transformer or existing generator in one season of one year: maintenance (out of service, or derated to 50%), a like-for-like replacement, or a repowering (out for the window, then back from the following year uprated by a factor or with a parallel circuit). Each is studied in that year's network in the case its season stresses: winter peak in winter, summer minimum (summer ratings) in summer, both in spring and autumn with the LTDS intermediate-warm ratings. Windows in the same season and year are studied together. The verdict is *feasible*; *feasible with curtailment* (a thermal, export or overvoltage breach that constraining nearby generation clears, with the MW per generator); *demand at risk* (demand cut off, or left outside the voltage band); or *not feasible*. With the window in place the 132 kV backbone is also N-1 screened, to show what a second fault would do: every second fault that adds a problem the window does not cause on its own is listed by name, worst first (demand cut off, then the highest overload), on the window's card and in the engine's message. A repowering changes the years after it; the queue itself is still decided on the network as it is. Like N-1, the result is reported per year and never gates a connection.

**5. "What would it take".** For each deferred project, the engine tests a concrete lever and re-solves to measure the MW it frees:
- **Line or transformer bottleneck**: chain parallel circuits (one per element; the chain stops when an element binds again).
- **Voltage limit**: absorb reactive power at a lower power factor.
- **GSP export limit**: add a supergrid transformer (+263.5 MW). This is transmission work, outside the distribution operator's control. The caveat says so, and suggests flexible connections or storage instead.

**Connection options** (`studies.connection_options`: the agents' tool for "how could this project connect?"). Probed in the plan's hardest phase on the branch's reinforced network: what the project's own busbar takes of it in each study case (a firm size, or a flexible connection firm to that MW and curtailed above), how far the parallel-circuit chain gets it, and which higher-voltage busbars nearby (nearest first by network steps, `CONNECTION_OPTION_BUSES` of them) take its full MW and what binds there. A 200 MW solar farm on a 33 kV feeder is told so: what the feeder takes of it, where the chain stops, and the nearest 132 kV busbar that takes it. Not studied: the works a new point of connection needs and their cost, transmission works, curtailment hours, fault levels.

**Reinforcements on a branch.** A lever (an agent's approved proposal, or one you add) is stored on the branch as a simulated reinforcement. Every later run of that branch applies it before the greedy loop, so its effect is measured against the whole queue, not just the one project; suggestions and studies on that branch are then trialled on the reinforced network. Reinforcements, like outages and project changes, are proposals: `main` changes only by merging.

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
                                                                   reinforcements · result cache ·
                                                                   findings · merges · threads ·
                                                                   agent runs/steps · approvals · reviews
                                                                 agents/ (DBOS workflows, Pydantic AI,
                                                                   OpenRouter) ── dbos.sqlite
                                                                                                 │
                                                                                                 ▼
                                                                  apps/web (Vite + React): MapLibre map,
                                                                  queue, outages, roadmap, review, ask
```

- **The warehouse is never mutated by the app.** Branches, added projects, chosen years, planned outages and simulated reinforcements live in a separate scenarios DB. Outages and reinforcements are copied when a branch is created and when it is merged.
- **Versions, not overwrites.** Every content-distinct materialisation appends a `snapshots` row (`network@<snapshot_id>`, tagged with the LTDS edition it was built from). The pipeline also diffs NGED's previous LTDS edition against the current one and stores the change-set, and keeps every fetched edition of the Embedded Capacity Register with a site-level diff between the last two. See [`apps/pipeline/README.md`](apps/pipeline/README.md).
- **Every project has a main.** The built-in project's is `main`; an import's is `<project id>-main`. A branch belongs to one project (`branches.project_id`) and runs on that project's network; results are cached under the project's baseline (the warehouse snapshot id, or the imported file's fingerprint), so two projects never serve each other's results and the same file imported twice shares them.
- **`main` is a branch row too.** Merging squashes a branch into it, last write wins, and it is the only way main changes: projects, schedules, works and reinforcements are refused on main (409); its demand profile stays editable.
- **Results are cached durably.** A run is a pure function of the model snapshot, the parameters, the branch's candidate set, its reinforcements and the engine's code, so every result is stored in the scenarios DB under that key: the same run never happens twice, not even after a restart, and two branches can never serve each other's queue. The per-year results are cached separately, under a key that adds the outages and the schedule, so changing a year or a maintenance window re-solves the years but not the queue. Inside a run, the engine keeps an exact trial cache: when a branch gains one project, only the trials whose state changed are solved again.
- **Runs are background jobs that publish as they go.** The planner starts a job and polls it; the overlay shows the engine's real stage (ranking, each phase's trials, the N-1 screen, each year). Once the queue is decided the job publishes partial results (the queue plus the years solved so far, the viewed year first), so the planner fills in before the run finishes. `main` is precomputed when the API starts.
- **The model speaks CIM.** `gridforge_optimizer.cim` serialises the network to CGMES 2.4.15 (equipment, topology, steady-state hypothesis and geography profiles) with deterministic identifiers, so two exports diff like any other versioned artefact. The pipeline writes one per edition (`nged_model_cgmes`); the API serves it at `GET /model/cgmes`. The export is verified by re-importing it with pandapower's CGMES importer: same elements, same ratings, same tap steps, same power-flow solution.
- **Agents are durable workflows inside the API process.** A steward per project, specialists, a reviewer and an answerer (`apps/api/src/gridforge_api/agents/`), run by DBOS on its own small database (SQLite in dev, Postgres when the scenarios store is), so a run interrupted by a restart resumes from its last completed step and the same event never runs twice. Their tools are the engine's studies and the API's own reads, each recorded as a step with the cache key of what it ran; the server copies every figure a finding carries from that cached study, a review must restate the gate's blockers exactly, and digit figures in a free-text answer (or alongside its proposals) that no tool produced are flagged, by value: not plan years, counts up to 12 or numbers written as words. Agent studies wait for operator jobs and never run two power flows at once. What the agents spend is recorded per project and day from OpenRouter's billed cost and shown in the planner; there is no cap (you pay with your own key), only the operator's pause switch. Without `OPENROUTER_API_KEY` the runtime is never launched.
- **Postgres or DuckDB for the scenarios store.** Branches, added projects, schedules and the result cache live in a DuckDB file by default; set `GRIDFORGE_SCENARIOS_URL=postgresql://…` and they live in Postgres instead, through the same SQL (one small dialect layer). The warehouse stays DuckDB.

---

## HTTP API

`apps/api`, FastAPI on port 8000.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness, and whether the warehouse exists |
| `GET /model` | Buses, lines, transformers, loads (each with its `region_id`) and the existing fleet, with coordinates; `regions`: the demand groups (LTDS Table 3 primaries, and each BSP over its primaries, by `level`) with their buses, firm capacity, demand today and P2/8 class |
| `GET /model/cgmes` | Today's network as a CIM/CGMES 2.4.15 exchange (EQ, TP, SSH, GL in one zip); re-imports with pandapower's CGMES importer to the same power flow |
| `GET /boundary` | GSP export limit, export today, and transmission projects (with registry ids where optional); a power flow, computed once per baseline and warmed at startup |
| `GET /forecasts` | NESO FES 2025 demand pathways, the plan's years (`plan_years`) and the policy horizons its two phases end at, plus the intake cap |
| `GET /snapshots` | The model's version history (`network@<snapshot_id>`, newest first, with the LTDS edition of each) |
| `GET /editions/changes` | What changed between NGED's previous LTDS edition and this one: flagged rows, model delta, physics delta |
| `GET /registry/changes` | What changed in the Embedded Capacity Register between the last two fetched editions |
| `GET /registry` | The optional projects |
| `POST /optimize` | Run `main` |
| `POST /branches` · `GET /branches` | Create and list branches |
| `POST /branches/{id}/registry` | Pull a registry project onto a branch |
| `POST /optimize/candidates` | Add a hand-entered project |
| `GET /branches/{id}/candidates` · `PATCH /branches/{id}/candidates/{request_id}` | A branch's projects as stored (what its next run ranks), and a change to one: its `bus_id`, `rating_mw`, `import_mw` or `commissioning_year` (an agent's approved proposal or the operator's edit; re-triaged, the next run measures it). 404 when the project is not on the branch, 409 on `main` or a branch that isn't open |
| `POST /branches/{id}/optimize` | Run a branch: queue, per-phase results, per-year results (`years`, with outage studies and the demand side: `regions` and `alerts`), GSP exchange, N-1 findings, recommended and scheduled years. Body: `view_year` (solved first), `with_justification`. The payload carries `run_key`, the identity of its physics (the plan-years cache key): the same for a re-run with the same inputs |
| `POST /branches/{id}/optimize/jobs` · `GET /jobs/{id}` | The same run as a background job, with stage and fraction while it runs; `?partial=true` returns the queue plus the years solved so far (`has_partial` says whether there are any); `POST /jobs/{id}/cancel` stops a job a newer edit supersedes (what it solved stays cached) |
| `GET /cache` | What the durable result cache holds, per kind and engine fingerprint |
| `GET /studies` · `POST /branches/{id}/studies/{kind}` | The study catalogue (`studies.STUDIES`: description, parameter schema with its `required` fields, cost in solves at the defaults, `null` for a study about one project or element) and a study run on a branch's plan as a background job; the result is a `StudyResult` (items with the engine's figures and stable fingerprints, what it did not study), cached by the branch's inputs and the parameters (kind `study:<kind>`). 422 for bad parameters or a plan-reading study on a branch that has not run |
| `POST /branches/{id}/schedule` | Set or clear a project's energisation year (`against_recommendation` is reported back) |
| `POST /branches/{id}/scenario` | Change a branch's demand profile (pathway and growth); takes effect on the next run |
| `GET` · `POST /branches/{id}/outages` · `DELETE /branches/{id}/outages/{outage_id}` | Planned works windows (line, transformer or existing generator; season, year, outage or derate; `work` maintenance / replacement / repowering, with `repower` uprate + `factor` (1 < factor ≤ 4) or add_parallel for repowering only). 409 on `main` or a branch that isn't open; 422 for an unknown element or season, or a work/repower/factor combination that doesn't fit |
| `POST /branches/{id}/works/best-window` | Find the best window for a planned work (`element_kind`, `element_id`, `work`, `kind`, `repower`, `factor`, `weeks`, optional `years: [from, to]` and `seasons`): a background job (progress per year; poll `GET /jobs/{id}`) whose result is `{branch_id, element_kind, element_id, work, options}`, each option `{rank, year, season, verdict, curtailed_mw, demand_at_risk_mw, n1_findings (null = not screened), worst_line_loading_pct, worst_trafo_loading_pct, message, study}`. Studied against the branch's plan (queue, schedule, reinforcements, other windows); read-only, so `main` may be searched. Cached by `ResultCache.key` (kind `windows`). 404 unknown branch, 422 unknown element, bad range or work combination |
| `GET` · `POST /branches/{id}/reinforcements` · `DELETE /branches/{id}/reinforcements/{reinforcement_id}` | Simulated reinforcements (an agent's approved proposal, or one added by hand), applied by every later run. 409 on `main` or a branch that isn't open |
| `GET /branches/{id}/diff` | Consequence diff against the parent branch: `projects`, `headline` (MW by 2030/2035), `phases`, `years` (per plan year: worst line/transformer, voltage, GSP export and N-1 deltas, lines and transformers newly over 100% or cleared, top movers) `works` (each of the branch's planned windows, its verdict on the parent's plan vs the branch's, the second faults during the window the branch adds or clears (`n1_new` / `n1_cleared`, compared as lists, never as counts), and the consequence in words) and `on_merge` (the planned works and reinforcements a merge adds to or removes from the parent, since merge replaces the parent's with the branch's). Solves either side's years if not cached, plus the branch's windows on the parent's plan (only the years with a window, without the year's own N-1 screen but with the screen during the windows); all cached by `ResultCache.key`. `?with_narration=1` adds an LLM summary of the figures |
| `GET /branches/{id}/suggestions` | "What would it take" levers with measured MW freed, trialled on the branch's reinforced network; `?request_id=` narrows it to one deferred project |
| `GET /branches/{id}/merge-check` | The merge gate's verdict against the parent (`?into=` another branch): `fresh` / `stale_reasons`, `verdict` (`ok`, `blockers`, `warnings`, `context`, `years_compared`, `summary`), `requires_acknowledgement`, and the evidence it was judged on (cache keys, snapshot, engine). Solves the parent's plan if it is not cached yet, never the branch's |
| `POST /branches/{id}/merge` · `/discard` | Adopt into `main` (its scenario, projects, planned works and reinforcements replace main's), or drop. Merging is gated: a stale branch, or one that introduces or worsens a problem in any plan year, is refused with 409 `{code: "blocked", message, verdict}`; warnings are refused with `code: "warnings_unacknowledged"` until the body carries `acknowledge: true`. Every attempt is recorded in `merges`. Discard answers 409 unless the branch is open |
| `GET /branches/{id}/findings` | The findings ledger: everything the branch's last run found (overloads, voltage breaches, the GSP margin, N-1 findings, demand alerts, works verdicts, deferred and rejected projects, schedules against the recommendation), one row per finding with a stable fingerprint, its status, and the evidence (the cached study's key, snapshot and engine). `?status=open\|acknowledged\|resolved`, `?year=` |
| `POST /findings/{id}/ack` | Acknowledge a finding (default), resolve it by hand, or reopen it: `{status, note}` |
| `GET` · `POST /projects` | The projects: the built-in NGED one and every import. `POST` is a multipart upload (`file`: .zip CGMES, .json pandapower, .mat MATPOWER; `name`; optional `gsp_export_limit_mw`, `gsp_name`, `min_demand_factor`, `summer_rating_ratio`, `intermediate_rating_ratio`): 415 for another file type, 413 over 50 MB, 422 with the validation report when the engine cannot plan on it; otherwise the project with its report, capabilities and `main_id` |
| `GET` · `DELETE /projects/{pid}` · `GET /projects/{pid}/model` · `/model/cgmes` · `/boundary` · `/registry` · `/assumptions` · `/branches` · `POST /projects/{pid}/optimize` | One project: its row, its geolocated model (`crs` = `wgs84` or `synthetic`), its CIM export, its boundary card (404 when it models none), its registry (empty for an import), what it assumes, its branches, and a run of its main. `/model`, `/model/cgmes`, `/boundary`, `/registry` and `POST /optimize` are the NGED project's aliases. Deleting an import removes its branches, records, cached results and file; the built-in project answers 409 |
| `GET /projects/{pid}/agents` · `POST …/agents/pause` · `POST …/agents/resume` | The agents' status for the project (`nged-bickerfen` today): `off` (no key, 200 with the reason), `idle`, `running` or `paused` (by the operator), what the agents spent (today and in all, OpenRouter's billed credits), the last events. Pause stops new work; resume lets it start again |
| `POST /projects/{pid}/events` | An event for the agents: `{type, payload, dedup_id?}` with `type` one of `events.TRIGGERS` (`run.finished`, `branch.merged`, `project.imported`, `edition.changed`, `operator.asked`). The API emits the first two itself (a `run.finished` carries `n_works` and `works_flagged`, the windows the run studied and those not simply feasible or with second faults, so the steward can send the works specialist); a pipeline may post the next two. Deduplicated by id: the answer says `deduplicated`, `paused` or the workflow ids started |
| `GET` · `POST /projects/{pid}/threads` · `GET /projects/{pid}/threads/{tid}` | Operator conversations (optionally on a branch), with their messages and pending approvals; the project's health thread (`kind: health`) is where the steward's briefs land |
| `POST /projects/{pid}/threads/{tid}/messages` · `GET …/threads/{tid}/stream?message_id=&after=` | Ask the model: the question is stored, a reply queued, the answer workflow started (409 while a reply is already streaming in the thread, or while the agents are paused). The stream is server-sent events: `tool_call` (tool, planning stage, `step_id`), `progress` (a running study's stage and fraction: each chunk as it lands, and the study's own stages), `tool_result`, `token`, then `final` (text, approvals, flags) or `error`; `after` or `Last-Event-ID` resumes from a position |
| `POST /projects/{pid}/threads/{tid}/cancel` | Stop the reply on its way: its message is marked `cancelled` at once (the thread takes the next question) and its workflow is cancelled at its next step; what it had computed stays cached. 409 when nothing is on its way |
| `GET /projects/{pid}/approvals` · `POST /projects/{pid}/approvals/{aid}` | Actions an answer proposed (a branch off main, a reinforcement, a works window, a project or a change to one, a run of the branch) and the operator's `{decision: approve \| deny, note}`. A decision is recorded at once; the answer continues (the approved tools run on the branch, the denied ones are refused to the model) once every proposal of that reply is decided, and until then the response's `waiting_for` lists the open ones with `workflow_id: null`. A second decision on the same proposal answers 409. A thread's view lists every proposal of the thread with its status |
| `GET /branches/{id}/reviews` | The reviewer's comment on the branch's current run (`prepared_for_review`): the gate's verdict restated, blockers and warnings by kind, element and fingerprint, what was not studied; `?all=true` includes superseded reviews |
| `GET /projects/{pid}/agents/runs` · `GET …/agents/runs/{rid}/steps` · `GET …/agents/steps/{step_id}` | The audit trail: every agent run (kind, agent, model, status, tokens, cost, solves), a run's recorded tool steps next to DBOS's own step list, and the evidence behind one step (the study re-read from the durable cache, `stale` when the engine has changed since) |

Narration (`with_justification`, `with_narration`) and the agents call LLMs through OpenRouter. `OPENROUTER_API_KEY` is required: the API refuses to start without it, and there is no key-less mode. The agent routes answer 503 `starting` only while the runtime launches.

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

Open **http://localhost:3000**. You land on `main`, today's network. Create a branch (**New branch** in the header or the Review tab), then add projects from the registry in the Queue tab, or ask the agents to add one (the Ask tab). Added projects show as *Preliminary* until you **Run**; the result is marked out of date (**Re-run**) whenever the demand profile, outages, reinforcements, schedule or projects change.

- **Shell quoting:** quote `'ltds_tables*'`, or the shell may expand it. It selects the root asset and everything downstream.
- **Dagster UI:** `uv run dg dev` shows lineage and check results. It also uses port 3000, so don't run it alongside the web app.
- **OpenRouter key (required):** put `OPENROUTER_API_KEY=…` in `apps/pipeline/.env`; the API loads it from there and does not start without it.
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
cd packages/optimizer && uv run pytest -q     # engine: 153 tests, 4 workers (pytest-xdist); the N-1 screen is stubbed except where it is under test
cd apps/api && uv run --with pytest pytest tests -q   # API (each run uses its own temp scenarios DB; the per-year N-1 screen is stubbed; +1 against Postgres if GRIDFORGE_TEST_PG_URL is set): the branch/PR flow, the gate and the ledger, the harness plumbing, and the agents end to end with scripted models on a temp DBOS database (test_agents.py)
cd apps/web && pnpm test                      # UI: 83 vitest unit tests of the logic behind the screens (reason normalisation, derivations, demand regions, the merge gate and findings, the agents' trace, the suggested questions, projects, run stages, planned works)
```

The engine tests are **grid-agnostic**: fixtures are derived from whatever network `build_base_net()` returns, never from hard-coded bus ids. `test_nged.py` adds the NGED data rules:
- removed equipment is excluded;
- every live MW of demand is modelled;
- no registry project is pre-loaded into today's network.

`test_editions.py` covers the edition logic: the previous edition keeps Removed rows and drops New ones, the change-set agrees with NGED's flags, and the ECR diff reports added / withdrawn / connected / re-rated sites.

---

## Sources and assumptions

Every number the engine uses is one of five kinds, and this register lists them all. The code keeps the full citation next to each constant (resource ids included); this is the index. **Published** and **standard** values come from someone else. **Derived** values are computed from published data by a stated method. **Assumptions** and **heuristics** are our choices: each is listed with why, and none is tuned to make results look better. Change one only with a source, and update this table in the same commit.

### Published data

| What | Source | Where |
|---|---|---|
| Circuits (impedance, seasonal ratings, length), transformers (impedance, rating, tap range), demand per substation (maximum, power factor, minimum-demand factor, firm capacity), nodes, connected generation | NGED **Long Term Development Statement** (LTDS) tabular model for Bicker Fen, Connected Data Portal (CKAN) | `data/nged/*.json`, built by `nged.build_nged_net` |
| Accepted-to-connect sites (location, voltage, export capacity, target energisation date) | NGED **Embedded Capacity Register** (ECR); the customer-name, address, postcode and MPAN columns are dropped at fetch, the site name is kept as published (it can name a property) | `data/nged/ecr.json`, `nged.ecr_candidates` |
| Supergrid transformer limits: 263.5 MW export per SGT (every season), 160.1 MW / 110.8 MW import (winter / summer) | NGED *Bicker Fen Td Limits*, resource `288e7abd-a45d-4592-b257-064d85d99d8b` | `nged.GSP_BOUNDARY` |
| Bicker Fen's demand at the GB winter peak today: **149.235 MW** (mean of 150.491 EE, 150.249 HE, 146.965 HT, fiscal year 2024/25) | NESO *Regional Breakdown of 2024 FES: Demand (Active Power)*, resource `7bd643c0-6aad-41ac-aa59-92b68992d9a4`, GSP `BICF_1`, DemandPk summed over demand types | `nged.GSP_PEAK_DEMAND_MW` |
| Transmission projects at Bicker Fen | NESO **TEC Register** and **Interconnector Register** (Sep 2026) | `nged.TRANSMISSION_PROJECTS` |
| GB peak demand growth: ×1.08 by 2030, ×1.35 by 2035 (Holistic Transition, underlying peak) | NESO **Future Energy Scenarios 2025**; baseline NESO Winter Outlook 2024/25 (59.8 GW ACS) | `config.FORECASTS["ht"]` |
| Substation positions (29 of 68 substations) | **OpenStreetMap**, © OpenStreetMap contributors, ODbL | `data/nged/coords.csv` |

### Published standards

| What | Value | Source | Where |
|---|---|---|---|
| Statutory voltage bands | ±10% at 132 kV, ±6% above 1 kV | ESQCR 2002, regulation 27 | `config.VOLTAGE_BANDS` |
| Demand classes and what may wait after a first circuit outage | Classes by group demand: A ≤ 1, B ≤ 12, C ≤ 60, D ≤ 300, E ≤ 1500 MW, F above. After a first circuit outage, C may lose max(12 MW, ⅓ of the group), D 20 MW, E and F nothing; A and B may wait for restoration | ENA EREC P2/8 (2019), Table 1, applied in simplified form | `config.P2_8_CLASSES` |
| Policy horizons | 2030 (Clean Power 2030), 2035 (strategic-need window) | DESNZ Clean Power 2030 Action Plan (Dec 2024); Ofgem connections reform (TMO4+, Apr 2025) | `config.HORIZONS` |

### Derived from published data

| What | Method | Where |
|---|---|---|
| Line impedance in ohms | LTDS %Z on a 100 MVA base × the circuit's own voltage² / 100 | `nged._add_lines` |
| Line charging | LTDS B1 (positive-sequence susceptance, % on 100 MVA): B = B1 / kV², C = B / 2πf over the circuit, as nF/km for pandapower (medians 12 nF/km at 132 kV, 42 at 33 kV); 9 circuits with no B1 carry none (`charging_blank`) | `nged._add_lines` |
| Transformer emergency rating | LTDS Table 2a's emergency rating over the nominal one (1.0 to 2.0 on Bicker Fen): what post-fault loading is judged against in the N-1 screen and the contingency ranking; planned works keep the nominal rating | `net.trafo.emergency_ratio`, `network.outage_results` |
| Transformer impedance | LTDS X1, R1 on 100 MVA rescaled to the unit's rating; vk clamped to 0.1 to 25% to keep the solver stable on bad rows | `nged._add_transformers` |
| Seasonal line ratings | LTDS Winter / Intermediate Warm / Summer ratings as ratios of winter | `net.line` ratio columns |
| A BSP's own demand rows are not extra load | They equal the sum of the primaries under the BSP (e.g. Sleaford 61.6 vs 66.2 MW), so they become the BSP's demand group, not load | `nged._bsp_aggregates` |
| Coincidence at each BSP | The BSP's published maximum ÷ the sum of its primaries' maxima (0.78 Grantham, 0.89 Sleaford, 1.02 Skegness) | `nged._bsp_membership` (`bsp_coincidence`) |
| Coincidence at the GSP | NESO's GSP peak ÷ the BSP-coincident total (0.959), so today's winter-peak demand is exactly 149.235 MW | `nged._coincidence` |
| Summer-minimum demand | Each row's maximum × its LTDS minimum-demand factor (not grown) | `min_scale` in `nged._add_loads` |
| Firm capacity in MW | LTDS "Firm Capacity of Substation" read as MVA (the table gives no unit) × the row's power factor | `nged._add_loads` |
| Existing fleet | LTDS Table 5 rows with status Connected or Energised, at the substation NGED names, at their connection voltage | `nged._add_existing_fleet` |
| The previous LTDS edition | Reconstructed from the New / Removed flags (Updated rows keep current values; the old ones aren't published) | `nged.EDITION_PREVIOUS` |
| Positions of the 39 substations OSM lacks | Each placed at the mean of its placed neighbours | `nged._bus_coords` |

### Planning assumptions (chosen, with the reason)

| What | Value | Why | Where |
|---|---|---|---|
| **Tap-changer target voltage** | **1.02 pu** | LTDS publishes no AVC targets, and GB DNOs set them above nominal so feeder ends stay in band at peak. 1.02 is the lowest value at which today's network meets the statutory band at winter peak (at 1.00 Horncastle 33 kV sits at 0.932 pu). Chosen, not sourced. | `config.OLTC_SETPOINT_PU` |
| Tap-changer deadband | ±0.01 pu | A typical AVC relay deadband | `config.OLTC_DEADBAND_PU` |
| Tap step | 1.25% per tap | LTDS gives each tap range but not the step; a typical GB value | `config.OLTC_TAP_STEP_PERCENT` |
| Generation at winter peak | PV and wind 0; batteries and hybrids charging at full import; gas, biomass and unclassified firm | A conservative demand study: an evening winter peak has no sun and can't rely on wind | `config.GENERATION_FACTORS` |
| Generation at summer minimum | Everything at full export | A conservative generation study | `config.GENERATION_FACTORS` |
| Demand and electrolyser projects at summer minimum | 50% of import capacity | Close to the LTDS minimum-demand factors (~0.5); not a measured profile | `config.DEMAND_PROJECT_MIN_FACTOR` |
| Power factor where LTDS leaves it blank | 0.95 | A typical lagging demand power factor | `nged._pf` |
| Line rating where LTDS leaves it blank | 1.0 / 0.7 / 0.6 / 0.5 / 0.4 kA at 132 / 66 / 33 / 20 / 11 kV | Conservative typical ratings by voltage | `nged._RATING_FALLBACK_KA` |
| Every element a builder fallback touched | Recorded on the network (`net["assumptions"]`: blank ratings, defaulted lengths, median seasonal ratios, assumed tap steps, fixed taps, default power factors) | Stated, never hidden; the `data_quality` study lists them with their element ids | `nged._assume`, `studies.data_quality` |
| GSP limit direction | "Export" = distribution to transmission | NGED's dataset doesn't document its sign convention | `nged.GSP_BOUNDARY` |
| Spring and autumn ratings | LTDS Intermediate Warm (the lower intermediate rating) | Conservative for the shoulder seasons | `config.SEASON_STUDY` |
| Derated element in a works window | 50% of rating | No published derate profile | `config.OUTAGE_DERATE_FACTOR` |
| N-1 screen scope | 132 kV backbone, in each study case (winter peak and summer minimum); outages islanding < 1 MW ignored; islanded demand reported on the winter-peak screen only | Export binds at summer minimum on a net-exporting GSP (today's network already fails N-1 there: losing one Bicker Fen to Boston circuit loads the other to 135% of its summer rating), demand at winter peak; an island is topology, the same in both. Bounded cost (about 3 s per case per year); spurs and tees aren't supply losses | `config.N1_CASES`, `N1_MIN_KV`, `N1_ISLAND_MIN_MW` |
| 132 kV bus sections | Run split, as the LTDS lists them: separate nodes with no coupler or section circuit between them (Boston 603/503, Skegness 103/203, Middlemarsh 103/203, Grantham North, Sleaford 103/203 with their tees, Grantham 303/403) | NGED publishes the connectivity, not the running arrangement, and a coupler is not invented. After a fault a circuit is therefore not picked up by its pair through the substation, which is what the N-1 screen reads; each such busbar is flagged `bus_sections_split` in the model's assumptions | `nged._assume_structure` |
| 33 kV running arrangement | A closed mesh: every LTDS 33 kV circuit in service, no normal-open points (11 independent loops on Bicker Fen) | None are published, and opening points would be a guess. A 132 kV outage therefore routes power through 33 kV paths (with one Bicker Fen to Boston circuit out at summer minimum, Skegness GT2 reads 244% of its rating and Horncastle to Spilsby 33 kV 109%), so post-fault 33 kV figures are what that mesh carries, likely above a DNO's running arrangement; each looped circuit is flagged `mv_mesh_closed` | `nged._assume_structure` |
| Firm-headroom warning | Below 10% of firm capacity | An early-warning margin, not from P2/8 | `config.HEADROOM_WARN_FRACTION` |
| Single-connection cap | 300 MW | Beyond this a generator connects to transmission; the ECR's largest Bicker Fen site is 248 MW | `config.MAX_CONNECTION_MW` |
| Connection options: higher-voltage busbars probed | 4, nearest first by network steps from the project's bus | Bounds the study's cost; each is probed with the project's full MW in every case | `config.CONNECTION_OPTION_BUSES` |
| Smallest ECR site modelled | 1 MW export | Sub-MW sites connect at LV, below the model's 11 kV floor | `nged.ECR_MIN_EXPORT_MW` |
| An ECR project's id | A hash of its location, energy source, voltage and acceptance date (not its name or capacity) | The ECR publishes no stable reference: a re-rated or renamed project keeps its id; a corrected location or date gives a new one | `nged._ecr_id` |
| An ECR site's identity between editions | Name, location, energy source and voltage | Keeps an accepted site that connects as the same site; a corrected name or location reads as withdrawn + added, and redacted sites without a location are not told apart (served as `caveats` by `GET /registry/changes`) | `editions.ECR_SITE_KEY` |
| Growth for the other FES pathways | EE ×1.10 / ×1.42, FB ×1.04 / ×1.15, HE ×1.07 / ×1.28 | Only Holistic Transition is firmly cited; the others are a directional spread around it | `config.FORECASTS` |
| Curtailment search | ≤ 8 extra solves per case, 3 refining, steps under 1% relief put back | A bounded first-order estimate, not an optimal re-dispatch | `config.CURTAIL_*` |
| Reinforcement levers | A parallel circuit (×2 rating, ½ impedance) or an uprate; reactive absorption at 0.98 / 0.95 / 0.90 pf | Standard first options for thermal and voltage limits | `network.REINFORCERS`, `config.VOLTAGE_ABSORB_PF_STEPS` |
| **Merge gate policy** | A branch is refused when it **introduces or worsens** a problem relative to its parent in any plan year: new or worsened overloads, new voltage breaches, the GSP newly over its limit, new N-1 findings, new demand-side breaches, works windows that become infeasible, a year that stops converging, a stale or incomplete result, a parent that moved on. Worsened voltage, GSP export near its limit, new warnings, more curtailment, a works window the branch adds that needs curtailment or has second faults during it, a schedule against the recommendation, a changed demand profile and removed proposals warn. What the parent already carries is context. | "No merge while the grid would be broken in any plan year", read against the parent because main is not perfect either (otherwise nothing could ever merge). A policy, chosen; each kind's level is one line | `config.MERGE_GATE_LEVELS`, `gate.MERGE_CHECKS` |
| Worsening margins for the merge gate | 1 loading point, 1 MW of GSP export, 0.005 pu | Below these, an element already past its limit on the parent is not counted as worsened by the branch | `config.GATE_WORSEN_PTS`, `GATE_GSP_WORSEN_MW`, `GATE_VM_WORSEN_PU` |
| GSP near-limit warning | Export above 90% of the export limit | An early warning; the planner's gauge turns amber at the same point | `config.GSP_NEAR_LIMIT_FRACTION` |
| Hosting-capacity study | Bisection to 5 MW between 0 and the intake cap, on today's network, buses at 33 kV and above, at most 24 per study; the probe is a firm generator (export) or a demand connection (import) | Bounded cost; a firm probe is the conservative generator in both cases | `config.HOSTING_STEP_MW`, `HOSTING_MIN_KV`, `HOSTING_MAX_BUSES` |
| Contingency-ranking scope | Every circuit and transformer at 33 kV and above, in both study cases | The N-1 screen's mechanics, wider; bounded by the element count | `config.CONTINGENCY_MIN_KV` |
| Tap-margin warning | At a tap stop, or one step from it | No voltage control left there | `config.TAP_MARGIN_MIN_STEPS` |
| GSP margin warning | Export margin under 10% of the limit | The near-limit warning read as a margin, year by year | `config.GSP_MARGIN_WARN_FRACTION` |
| Agent models | Claude Sonnet 5.5 for the steward, the reviewer and the answerer; Claude Haiku 4.5 for the specialists | The roles that plan and phrase get the stronger model; the specialists follow a fixed remit and run tools | `config.AGENT_MODELS` |
| Agent run limits | Per run: 12 tool calls, 600 solves, 10 minutes (no daily cap: spend is recorded and shown, never a stop) | Bounds, not tuning: a run that hits them says what it did not study | `config.AGENT_RUN_BUDGET` |
| Solver order | An agent study waits while an operator's job is queued or running, for as long as its own run's time allows (`AGENT_RUN_BUDGET.timeout_s` less a 60 s reserve to write the answer), saying so in its trace; past that its tool answers that the study is waiting, never an error. Every cache miss takes the one solver lock | Operators first; one power flow at a time in the process; the 60 s reserve is chosen | `config.AGENT_ANSWER_RESERVE_S`, `agents.tools.SolverGate`, `jobs.solver_lock` |
| Agent recovery version | The engine fingerprint, unless `GRIDFORGE_DBOS_APP_VERSION` is set | A code change that retires cached physics also retires in-flight agent runs | `config.AGENTS_APP_VERSION` |
| Imported grid: completeness | Refused, with the list, when it lacks an infeed, a line rating, a generator's technology, rating, voltage setpoint, reactive limits, minimum output or cost, a tap-changer type for a tap range, or reaches buses the infeed cannot | A grid is simulated as it runs or not at all: a filled-in value would give a false outlook (owner rule, 2026-10-05) | `sources.normalise_net` (`net["gaps"]`), `validate_net` |
| Imported grid: generators | Voltage-controlled units stay voltage-controlled (their setpoint, within their reactive limits); an inverter unit rated only by its nominal power is rated at it | Removing voltage control made a grid that solves (IEEE 39) never converge; an inverter's AC rating caps its export | `sources.normalise_net`, `network._runpp` (`enforce_q_lims`), `inverter_rating` |
| Imported grid: dispatch | Power stations (voltage-controlled, not solar, wind or storage) share each case's demand by merit order from the file's costs, every available unit synchronised; embedded generation, solar, wind and storage follow the case; the external grid balances | Real power stations are dispatched to balance demand; which units an operator keeps on for security is not modelled, and switching one off for cost alone stripped the voltage support IEEE 39 runs on | `dispatch.merit_order` (`merit_order_dispatch`) |
| Imported grid: the slack | The file's external grid, or the generator it marks as its slack | A power flow needs one; without it the import is refused | `sources.normalise_net` (`slack_from_generator`) |
| Imported grid: limits and cases | GB statutory bands, the 33 kV N-1 scope and the intake cap apply as they stand; the summer-minimum case and the export limit exist only when the operator enters a minimum-demand factor, a summer rating ratio or a limit at import | Stated as assumptions rather than made configurable this round; the engine never invents a seasonal rating or a boundary | `sources.inspect_net`, `apply_import_meta`, `ImportMeta` |
| Imported grid: positions | Positions the file carries (CGMES GL, pandapower `geo`), the rest interpolated between neighbours; none at all gives a deterministic Kamada-Kawai layout marked `synthetic` | A map needs positions; a synthetic layout is labelled as such, never shown on a basemap | `geometry.py` |

### Heuristics (ranking and growth shape)

These order and spread things. They never decide feasibility, which only the power flow does.

| What | Value | Where |
|---|---|---|
| Ranking weights | readiness 0.5, grid need 0.35, strategic fit 0.15 | `config.W_*` |
| Readiness rubric | land 0.30, planning 0.30, connection agreement 0.20, financing 0.10, commissioning 0.10; levels and credits next to the logic | `config.READINESS_WEIGHTS`, `readiness.py` |
| Readiness of LTDS Table 5 projects | By connection status (accepted 0.9, offered 0.7, quotation 0.55, budget estimate 0.45, scoping 0.2) | `nged._STATUS_READINESS` |
| ECR projects | A signed connection agreement plus the published target date; land, planning and financing aren't published, so they earn no credit | `nged.ecr_candidates` |
| Requested energisation year for LTDS Table 5 projects | 2027 to 2035 from readiness, technology, size and a deterministic jitter; not a developer's date | `nged.commission_year` |
| Strategic fit | A per-technology prior (storage 0.72 to 0.78, wind 0.72 to 0.75, others 0.66 to 0.68) | `nged.py` registry builders |
| Grid need | Local demand (as grown to 2035) saturating at 5 MW, blended 50 / 50 with the voltage depression left after the tap changers settle, read from the winter-peak solve at 2035 demand | `config.GRID_NEED_*`, `greedy._Run.rank` |
| Per-bus growth shape | Residential ×1.0 vs industrial ×0.25, ±60% seeded spread, +30% tilt toward feeder ends, top 20% as hotspots ×1.8; the GSP total always equals the pathway's figure | `config.GROWTH_*`, `network.per_bus_growth` |
| Contingency severity index | islanded MW × 1 + thermal excess MVA × 1 + worst voltage shortfall pu × 100; the components are reported with it | `config.CONTINGENCY_SEVERITY_WEIGHTS`, `studies.contingency_ranking` |

---

## Limitations

- **The GSP export limit is the only transmission constraint modelled.** The 400 kV network and wider transmission boundaries are not; the 400 kV projects are context only.
- **Fault levels are not checked.** NGED publishes them, but the units are undocumented and some breaker ratings sit below the calculated fault current, so they can't be used safely as-is.
- **Generation dispatch per case is a planning assumption.** PV and wind at nil and batteries (and hybrids) charging at winter peak; everything at full export at summer minimum. Gas, gas engines, biomass and technologies the data doesn't classify are treated as firm in both.
- **Demand projects and electrolysers draw a fixed share.** Their full import capacity at winter peak and 50% of it at summer minimum; that 50% is an assumption, not a measured profile.
- **Planned works are reported, not enforced.** A works window is studied in its season's case(s) and its verdict is shown, but it never blocks a connection. The weeks are recorded but not placed in specific calendar weeks (the season stands in for them), so every window in the same season and year is studied as overlapping. The curtailment figure is a first-order estimate from a bounded search (nearest generators first, at most 8 extra solves per case), not an optimal re-dispatch; no other re-dispatch or switching is modelled. The N-1 screen during a window is informational. A repowering changes only the years after its window, and the queue run does not count it (add the upgrade as a reinforcement for that).
- **Every year is a fixed plan.** The per-year solves show the network in each year; they don't change who connects, which is still decided at the two phase horizons. Demand between them is interpolated linearly.
- **Tap-changer settings are assumed.** The LTDS gives each transformer's tap range but not its step or its target voltage; 1.25% per tap is used, and taps are regulated towards 1.02 pu with a ±0.01 pu deadband. The target was chosen as the lowest value at which today's network meets the statutory band at winter peak (at 1.00 pu Horncastle 33 kV sits at 0.932 pu); real targets vary by site, and line-drop compensation is not modelled.
- **N-1 is reported, not enforced.** The single-outage screen covers the 132 kV backbone in each study case; it does not yet apply a security-of-supply standard or take 33 kV elements out (their post-fault loading is checked, as every element's is). Each outage is judged as the post-fault steady state: the tap changers re-regulate (the relays act within a minute) and transformer loading is read against the LTDS emergency rating, so what remains is what the relays and the short-term rating cannot absorb; the instant after the fault, before the relays act, is not studied.
- **Bus sections run split and the 33 kV network meshed, as the LTDS lists them.** NGED publishes the connectivity, not the running arrangement: a substation's 132 kV bars are separate nodes with no coupler row, and no 33 kV normal-open point is listed. Neither is invented, so after a 132 kV fault power finds its way through the 33 kV mesh rather than through a coupler, and the post-fault 33 kV and grid-transformer loadings (and the second faults a works window reports) are what that reading gives. Both are flagged per element in the model's assumptions (`bus_sections_split`, `mv_mesh_closed`) and listed by the `data_quality` study.
- **The demand-side alerts are a simplified P2/8-style check.** Restoration times, switching, transfer capacity between groups and second circuit outages are not modelled, so a group P2/8 would pass by switching can still be flagged, and the classes are applied to each LTDS row as published (a two-transformer site fed from two BSPs appears as two groups). Everything is MW of demand: the open data has no customer counts.
- **Firm capacity units are read, not stated.** LTDS Table 3's "Firm Capacity of Substation" has no unit in the data; we read it as MVA and convert it to MW at the row's own power factor. A firm capacity of 0 (single-transformer sites and customers' own connections) is reported as is; such a group is only alerted on once it reaches class C. Firm capacity is compared with the group's own peak, not the GSP-coincident share the power flow carries. The "room for new demand" is first-order (≈): no power-flow probe is run for it.
- **Demand growth comes from a NESO FES pathway, spread per bus** with a seeded spread, distance from the GSP and hotspots. The LTDS's own 5-year substation forecasts are not used yet.
- **The GSP limit's direction is an assumption.** NGED's dataset doesn't document its sign convention; we read "export" as distribution → transmission.
- **Imported grids are checked for what they carry, no more.** A CGMES zip, a pandapower JSON or a MATPOWER `.mat` becomes a network the same engine plans on, but a file rarely carries seasonal ratings, a minimum-demand factor, firm capacities or an export limit: without them the summer case is not studied, there are no customer alerts and export is reported, never limited; an operator may enter the limits at import and they are recorded as entered. Unrated lines are not checked (and flagged); voltage-controlled generators become PQ injections; GB statutory bands and the N-1 scope apply as they stand. A base case that already breaks a limit is reported and then defers every project for it, which is true and shown.
- **Agents are advisory and bounded.** Their findings carry figures copied from cached studies and their reviews restate the gate; the prose around those figures is the model's, and the soft number check on free-text answers flags, it does not block. Each specialist has a fixed remit of studies and a solve budget per run (a hosting-capacity sweep of the default scope is a few hundred solves and takes minutes); the steward chooses among them, never outside. Operators keep the solver first between study chunks, so an agent sweep can still delay a run by one chunk. On the SQLite system database the queue pickup and the event streams poll at about one second (Postgres for live use). A project the operator paused runs nothing until it is resumed.
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
