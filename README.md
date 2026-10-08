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
| **Review** | A consequence diff of the branch against `main`: who connects or slips, MW by 2030/2035, and for the year on the timeline the lines and transformers that become newly overloaded or cleared, voltage, GSP export and N-1 changes. Each planned works window is studied on `main`'s plan too, so the diff says what the branch's projects do to it ("feasible on main, but needs 40 MW of curtailment on this branch"). Diff mode shows the viewed year's loading changes on the map. **Merge readiness** shows the gate's verdict: what the branch introduces or worsens in any plan year blocks, warnings need acknowledging, what main already carries is context; the engineer's **note** on the run sits under it. A **Limits** tab shows what limits the branch: first its character (export-bound, demand-bound or both: which planning condition sets the limits, so the reader knows whether new generation or demand growth moves them), then the binding set ranked (each element with its envelope over the plan years and its case, the first year it comes near its limit, the headroom left, the projects it holds back, the outages that breach it), the deferrals with their chains, the N-1 rows folded into causes, the works; the raw findings ledger only on demand, never as a list to read. |
| **Ask the agents** | The side panel's first tab and the planner's only conversation: a question in plain words to the answerer on the branch, streamed with its planning stages as chips, citing the steps it ran (click a study chip for the evidence), digit figures no step produced flagged. It reads the engine's **limits** first (what binds, the deferrals' chains, the clusters) and runs a study only when that does not answer: among them **connection options** for a deferred project (what its own busbar takes of it as a firm or flexible connection, how far parallel circuits get it, which higher-voltage busbars take its full MW) and the **best window** for a planned work. It proposes what to do (add a project, move or resize one, a reinforcement, a works window, a run of the branch); every proposal waits for your approval; a reply on its way can be stopped. The picker suggests questions from what is in view. |
| **Projects** | NGED's Bicker Fen GSP is the built-in project. Import any other grid as a project: a CIM/CGMES zip, a pandapower JSON or a MATPOWER case, with its study basis (demand forecast, N-1 floor, voltage limits), its summer data unless the file carries it, and the limits you know (an export limit, a supergrid transformer's rating) entered at import and recorded as yours. The import is validated (a file missing anything a real simulation needs is refused with the list; a base case that does not converge is reported), what the file does not carry is listed, and the same engine, branches, gate, ledger and agents work on it. |
| **Agents** | With an OpenRouter key, two roles are tied to the project, both bound to the engine's figures. The **note**: after every run the engine reduces the result to a digest (`gridforge_optimizer.analysis`: the binding set, the deferrals with their chains, the N-1 rows folded into causes, the works verdicts, what changed against the parent and the gate), and one model call turns it into a 150-word engineer's note, every figure checked by value against the digest and flagged when it is not there; it appears under *Merge readiness* and under main's result stamp. The **answerer** for your questions (above). The model never computes, ranks or files findings; the engine does the physics and the analytics, the model phrases and asks. The OpenRouter key is required: the API does not start without it, and nothing falls back to a key-less substitute. |
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

**Checked against NGED's observed flows.** NGED publishes derived half-hourly net flows per substation node and branch for the Bicker Fen group (its curtailment datasets, 2024). The engine's two planning cases against them:

| Quantity | Observed 2024 | Engine, planning case |
|---|---|---|
| Net flow at the Bicker Fen 132 kV busbar | 278 MW export max, 49 MW import max | 301 MW export at summer minimum, 138 MW import at winter peak |
| Bicker Fen to Boston circuit, flow towards the GSP | 85 MW max | 106 MW at summer minimum |
| Bicker Fen to Boston circuit, flow towards Boston | 27 MW max | 26 MW at winter peak |

The demand side matches the observation; the export side is the planning extreme (every generator at full output at the measured minimum), 8% above the observed GSP maximum and 25% above the observed circuit maximum; the winter import is the SQSS security condition (no wind credited), a third of which is what the GSP actually imported at the 2024 peak with 180 MW of wind on the group. Fault levels: the model's IEC 60909 currents sit within 3% of NGED's published figure at the GSP busbar, 1.0 to 1.2 × at 132 kV and up to 2 × at 11 kV (the DNO decrements its break currents), which is why the screen scales the published figure rather than reporting the model's absolute. Sources and method: `docs/reports/study-basis-2026-10-07.md`.

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

**3. The feasibility gate.** Projects are trialled greedily in rank order for each phase. A project is accepted only if, together with the projects accepted before it in the phase, it introduces or worsens no breach in **both planning study cases** against the same phase's network before its trials: the branch's reinforcements applied, and the projects accepted in earlier phases connected (none in Phase 1; Phase 2 inherits Phase 1's, already judged at 2030 and committed by then). A limit that network already breaks (a 33 kV busbar that sags below its band by 2035 whatever connects) is reported in every plan year but defers nobody; a project that pushes it further than the worsening margins (see the register) is deferred for it. Judging a phase's projects together against the network before any of them, rather than before this one, stops a pre-existing breach creeping up one margin at a time.

| Case | Demand | Generation | Thermal ratings | Why it matters |
|---|---|---|---|---|
| Winter peak | maximum demand, grown per primary on NGED's DFES 2025 pathway | PV and wind at nil (a winter evening); batteries **charging** at their import capacity; other generation firm | winter | demand-driven overloads and low voltage |
| Summer minimum | LTDS minimum-demand factor (~48% of max), *not* grown | everything at full export | summer (~90% of winter) | the **generation**-critical case: the least local load to absorb export |

These are the two planning conditions the GB transmission standard sets at the interface with a distribution network (the SQSS: 1.05 pu to be achievable at forecast group demand, 1.00 pu at forecast minimum demand, intermittent generation excluded from the peak security condition) and the two headroom studies every DNO's Network Development Plan publishes per substation: forecast peak demand against firm capacity, and all generation at full output at minimum demand. Minimum demand is a measured figure in the LTDS (the heatmap model's `demandMinimum` is "calculated using historic measured values"), which is why the summer case is not grown. Sources in [Sources and assumptions](#sources-and-assumptions).

The limits, in both cases:
- Every bus inside its **statutory voltage band**: ±10% at 132 kV, ±6% at 33 kV and 11 kV (GB ESQCR). The tap changers are regulated first, so a breach is one the network cannot tap its way out of.
- Every line and transformer at or below 100%.
- **The GSP exporting no more than its supergrid transformers allow.** That's 2 × 263.5 MW = 527 MW. With one transformer out it's 263.5 MW; that figure is shown but not enforced.

For this region, the GSP boundary, not the local wires, is usually what fills up first.

**N-1 screen.** After each phase, and in every plan year, every 132 kV circuit and grid transformer is taken out in turn in each study case (`config.N1_CASES`: winter peak, where demand binds, and summer minimum, where export binds) and the result is checked for overloads, band breaches and islanded demand; each finding names its case, and islanded demand is reported once, on the winter-peak screen the customer checks read. A breach the intact network already carries in that case is the intact state's, not the outage's: it is a finding only where the outage worsens it beyond the worsening margins. The findings are shown in the planner but do not gate a connection: a firm-connection standard would, and that is a documented next step.

**Technologies.** How a project is dispatched in each case depends on what it is:
- **Solar, wind**: nil at winter peak, full export at summer minimum.
- **Battery, hybrid (solar + battery)**: charging at its import capacity at winter peak, full export at summer minimum.
- **Demand, electrolyser** (import-only): export nothing. They draw their import capacity at winter peak and half of it at summer minimum (a planning assumption, close to the LTDS minimum-demand factors). Intake judges them on import capacity, not export rating.
- **Gas, gas engines, biomass and anything unclassified**: firm, full output in both cases.

**4. Year.** The **recommended** year is the developer's requested date, clamped into the window the grid can host: 2027–30 for Phase 1, 2031–35 for Phase 2. Deferred projects get none.

**Every year, as a fixed plan.** Once the queue is decided, each year from 2026 to 2035 is solved on its own: demand at NGED's DFES projection for that year at each primary (an imported grid: the forecast entered at import), every accepted project whose year (scheduled, else recommended) has arrived, both study cases and the N-1 screen. This never changes who connects; it shows what the network looks like in the year you are viewing. The year in view is solved first, then 2030 and 2035, then the rest, and the planner shows each as it lands.

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
                                                                   agent runs/steps · approvals · run notes
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
- **`main` is a branch row too.** Merging squashes a branch into it, last write wins, and it is the only way a main changes: projects, schedules, works and reinforcements are refused on any project's main (409), and a main cannot be discarded (400); its demand profile stays editable.
- **A branch knows where it started.** Opening one records its parent's state (`branches.fork_json`: projects, works, reinforcements, demand profile). Because a merge replaces the parent's state, a branch lacking changes its parent received since then is shown as *behind main* and cannot merge until the operator rebases it (`rebase.py`): the parent's current state plus the branch's own changes, every conflict (both sides changed the same thing) picked by the operator, never automatically; the branch is then out of date until it runs. For a branch older than fork points, the fork is rebuilt from the merge history (a main changes only by merges and a merged branch is frozen, so main then was the last branch merged into it, or the empty seed); main's demand profile is not logged, so a difference in it is a conflict. Where nothing can be rebuilt (an older branch opened from another branch), every difference between the two is a conflict, as in git without a common ancestor. An agent may propose a rebase without conflicts (`propose_rebase`); conflicts are only ever the operator's to pick.
- **Results are cached durably.** A run is a pure function of the model snapshot, the parameters, the branch's candidate set, its reinforcements and the engine's code, so every result is stored in the scenarios DB under that key: the same run never happens twice, not even after a restart, and two branches can never serve each other's queue. The per-year results are cached separately, under a key that adds the outages and the schedule, so changing a year or a maintenance window re-solves the years but not the queue. Inside a run, the engine keeps an exact trial cache: when a branch gains one project, only the trials whose state changed are solved again.
- **Runs are background jobs that publish as they go.** The planner starts a job and polls it; the overlay shows the engine's real stage (ranking, each phase's trials, the N-1 screen, each year). Once the queue is decided the job publishes partial results (the queue plus the years solved so far, the viewed year first), so the planner fills in before the run finishes. `main` is precomputed when the API starts.
- **The model speaks CIM.** `gridforge_optimizer.cim` serialises the network to CGMES 2.4.15 (equipment, topology, steady-state hypothesis and geography profiles) with deterministic identifiers, so two exports diff like any other versioned artefact. The pipeline writes one per edition (`nged_model_cgmes`); the API serves it at `GET /model/cgmes`. The export is verified by re-importing it with pandapower's CGMES importer: same elements, same ratings, same tap steps, same power-flow solution.
- **The analytics layer reduces a run before anyone reads it.** `gridforge_optimizer.analysis` turns a run's thousands of figures (an envelope per element per year, an N-1 row per breached element per outage per case) into what an engineer asks: the **binding set** (which elements bind, from which year, in which case, by how many MW of headroom, holding back which projects, breached by which outages), a **chain** per deferral (the reason's element, case and figure against the limit, when that element starts binding on its own, and what a connection-options study measured), and **clusters** of N-1 rows by cause (the weak link several outages overload, the buses several outages strand, the outages that collapse the voltage). `GET /branches/{id}/limits` serves it; the planner's Limits tab and the answerer's first read are this, not the ledger. `gridforge_optimizer.sensitivity` adds DC power transfer factors on the solved case (0.1 s for the whole network) so the hosting-capacity and connection-options studies probe with AC only the buses with room, ranked first-order and confirmed by the solve.
- **Agents are durable workflows inside the API process.** The note writer and the answerer (`apps/api/src/gridforge_api/agents/`), run by DBOS on its own small database (SQLite in dev, Postgres when the scenarios store is), so an answer interrupted by a restart resumes from its last completed step and the same run is never noted twice. The answerer's tools are the engine's limits, reads and studies, each recorded as a step with the cache key of what it ran, and the proposals the operator approves; digit figures in a note or an answer that no digest or step produced are flagged, by value (not plan years, counts up to 12 or numbers written as words). Agent studies wait for operator jobs and never run two power flows at once. What the agents spend is recorded per project and day from OpenRouter's billed cost and shown in the planner; there is no cap (you pay with your own key), only the operator's pause switch. Without `OPENROUTER_API_KEY` the runtime is never launched.
- **Postgres or DuckDB for the scenarios store.** Branches, added projects, schedules and the result cache live in a DuckDB file by default; set `GRIDFORGE_SCENARIOS_URL=postgresql://…` and they live in Postgres instead, through the same SQL (one small dialect layer). The warehouse stays DuckDB.

---

## HTTP API

`apps/api`, FastAPI on port 8000.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness, and whether the warehouse exists |
| `GET /model` | Buses (each with the voltage band it is judged against, `vmin_pu`/`vmax_pu`), lines (`in_service`: false at an open point), transformers, loads (each with its `region_id`) and the existing fleet, with coordinates; `regions`: the demand groups (LTDS Table 3 primaries, and each BSP over its primaries, by `level`) with their buses, firm capacity, demand today and P2/8 class |
| `GET /model/cgmes` | Today's network as a CIM/CGMES 2.4.15 exchange (EQ, TP, SSH, GL in one zip); re-imports with pandapower's CGMES importer to the same power flow |
| `GET /boundary` | GSP export limit, export today, and transmission projects (with registry ids where optional); a power flow, computed once per baseline and warmed at startup |
| `GET /forecasts` | NESO FES 2025 demand pathways, the plan's years (`plan_years`) and the policy horizons its two phases end at, plus the intake cap |
| `GET /snapshots` | The model's version history (`network@<snapshot_id>`, newest first, with the LTDS edition of each). Every response that read the warehouse carries `X-Warehouse-Snapshot`, and `X-Warehouse-Stale: 1` when it was served from the previous version because the pipeline was writing (503 with `Retry-After` when nothing had been read yet) |
| `GET /editions/changes` | What changed between NGED's previous LTDS edition and this one: flagged rows, model delta, physics delta |
| `GET /registry/changes` | What changed in the Embedded Capacity Register between the last two fetched editions |
| `GET /registry` | The optional projects |
| `POST /optimize` | Run `main` |
| `POST /branches` · `GET /branches` | Create and list branches |
| `POST /branches/{id}/registry` | Pull a registry project onto a branch |
| `POST /optimize/candidates` | Add a hand-entered project (optional `control`: how its connection offer runs it, `{mode: "pf", pf, absorbing}` or `{mode: "voltage", vm_pu, q_range_pf}`; left out, it is not stated and runs at unity power factor) |
| `GET /branches/{id}/candidates` · `PATCH /branches/{id}/candidates/{request_id}` | A branch's projects as stored (what its next run ranks), and a change to one: its `bus_id`, `rating_mw`, `import_mw`, `commissioning_year` or `control` (an agent's approved proposal or the operator's edit; re-triaged, the next run measures it). 404 when the project is not on the branch, 409 on `main` or a branch that isn't open |
| `POST /branches/{id}/optimize` | Run a branch: queue, per-phase results, per-year results (`years`, with outage studies and the demand side: `regions` and `alerts`), GSP exchange, N-1 findings, recommended and scheduled years. Body: `view_year` (solved first). The payload carries `run_key`, the identity of its physics (the plan-years cache key): the same for a re-run with the same inputs |
| `POST /branches/{id}/optimize/jobs` · `GET /jobs/{id}` | The same run as a background job, with stage and fraction while it runs; `?partial=true` returns the queue plus the years solved so far (`has_partial` says whether there are any; `partial_version` counts the partials published, and `&since=<version>` leaves out the one the caller already has); `POST /jobs/{id}/cancel` stops a job a newer edit supersedes (what it solved stays cached) |
| `GET /cache` | What the durable result cache holds, per kind and engine fingerprint |
| `GET /studies` · `POST /branches/{id}/studies/{kind}` | The study catalogue (`studies.STUDIES`: description, parameter schema with its `required` fields, cost in solves at the defaults, `null` for a study about one project or element) and a study run on a branch's plan as a background job; the result is a `StudyResult` (items with the engine's figures and stable fingerprints, what it did not study), cached by the branch's inputs and the parameters (kind `study:<kind>`). 422 for bad parameters or a plan-reading study on a branch that has not run |
| `POST /branches/{id}/schedule` | Set or clear a project's energisation year (`against_recommendation` is reported back) |
| `POST /branches/{id}/scenario` | Change a branch's demand profile (pathway and growth); takes effect on the next run |
| `GET` · `POST /branches/{id}/outages` · `DELETE /branches/{id}/outages/{outage_id}` | Planned works windows (line, transformer or existing generator; season, year, outage or derate; `work` maintenance / replacement / repowering, with `repower` uprate + `factor` (1 < factor ≤ 4) or add_parallel for repowering only). 409 on `main` or a branch that isn't open; 422 for an unknown element or season, or a work/repower/factor combination that doesn't fit |
| `GET` · `POST /branches/{id}/reinforcements` · `DELETE /branches/{id}/reinforcements/{reinforcement_id}` | Simulated reinforcements (an agent's approved proposal, or one added by hand), applied by every later run. 409 on `main` or a branch that isn't open |
| `GET /branches/{id}/diff` | Consequence diff against the parent branch: `projects`, `headline` (MW by 2030/2035), `phases`, `years` (per plan year: worst line/transformer, voltage, GSP export and N-1 deltas, lines and transformers newly over 100% or cleared, top movers) `works` (each of the branch's planned windows, its verdict on the parent's plan vs the branch's, the second faults during the window the branch adds or clears (`n1_new` / `n1_cleared`, compared as lists, never as counts), and the consequence in words) and `on_merge` (the planned works and reinforcements a merge adds to or removes from the parent, since merge replaces the parent's with the branch's). A read, never a solve of the branch's own plan: a branch that has not run for what it holds now answers 409 `{code: "not_solved", retry: false}` (run it first); the parent's years and the branch's windows on the parent's plan (only the years with a window, without the year's own N-1 screen but with the screen during the windows) are computed only while the engine is free, else 409 `not_solved` with `retry: true` (ask again when the run finishes); all cached by `ResultCache.key`. `?solve=1` waits and solves whatever is missing (scripts).): `fresh` / `stale_reasons`, `verdict` (`ok`, `blockers`, `warnings`, `context`, `years_compared`, `summary`), `requires_acknowledgement`, and the evidence it was judged on (cache keys, snapshot, engine). Never solves the branch's plan (a stale branch is judged stale); the parent's plan is computed only while the engine is free, else 409 `not_solved` with `retry: true` (`?solve=1` waits for it). A project's main is the plan of record: it merges nowhere, so its diff, merge check and merge answer 400; `into` must be a branch of the same project |
| `POST /branches/{id}/merge` · `/discard` | Adopt into its parent, its project's main for a branch off it (its scenario, projects, planned works and reinforcements replace main's), or drop. Merging is gated: a stale branch, or one that introduces or worsens a problem in any plan year, is refused with 409 `{code: "blocked", message, verdict}`; warnings are refused with `code: "warnings_unacknowledged"` until the body carries `acknowledge: true`. Every attempt is recorded in `merges`. Discard answers 409 unless the branch is open |
| `GET` · `POST /branches/{id}/rebase` | Rebase onto the parent as it is now. `GET` writes nothing: the parent's changes since the branch was opened (`parent_changes`), the branch's own (`own_changes`), the parent's the branch lacks (`behind`, what a merge would undo) and the `conflicts` (both sides changed the same project, one conflict per project with its clashing `fields`; removed a project the other changed; added works or reinforcements on the same element; or changed the demand profile), each with its `options`, and `fork` (`recorded`, `rebuilt` from the merge history, or `none`: every difference is a conflict). `POST {picks: {conflict id: "parent" \| "branch" \| "both"}}` writes the parent's state plus the branch's changes, moves the fork point and answers `{branch, taken}` (how many of the parent's changes it took in); 409 when a pick is missing or unknown (the parent moved since the preview). `GET /branches` gives each open branch's `behind` (things its parent changed that it lacks, null when not known) and `fork` |
| `GET /branches/{id}/findings` | The findings ledger: everything the branch's last run found (overloads, voltage breaches, the GSP margin, N-1 findings, demand alerts, works verdicts, deferred and rejected projects, schedules against the recommendation), one row per finding with a stable fingerprint, its status, and the evidence (the cached study's key, snapshot and engine). `?status=open\|acknowledged\|resolved`, `?year=` |
| `POST /findings/{id}/ack` | Acknowledge a finding (default), resolve it by hand, or reopen it: `{status, note}` |
| `GET` · `POST /projects` | The projects: the built-in NGED one and every import. `POST` is a multipart upload (`file`: .zip CGMES, .json pandapower, .mat MATPOWER; `name`; optional `gsp_export_limit_mw`, `gsp_name`, `min_demand_factor`, `summer_rating_ratio`, `intermediate_rating_ratio`; the required study basis: `forecasts` (JSON `{pathway: {year: growth on the year before}}`, 1.02 = +2 %, for every plan year after the first, multiplied up to each year; pathway `ht` Standard required, `fb` Low and `ee` High optional, Low ≤ Standard ≤ High), `forecast_source`, `n1_min_kv` (one of the file's levels) and `voltage_bands` (JSON `[{kv, vmin_pu, vmax_pu}]`, one per level)): 415 for another file type, 413 over 50 MB, 422 with the validation report when the engine cannot plan on it or the study basis is missing; otherwise the project with its report, capabilities and `main_id` |
| `GET /projects/formats` | The source kinds (`sources.SOURCES`): `{kind, label, extensions, offered}` each (`offered`: the import form offers it; MATPOWER is read but refused today, since it carries no generator technology), and the upload limit `max_bytes` |
| `POST /projects/inspect` · `GET /projects/{pid}/forecasts` | A file's voltage levels before it is imported (each with the lines and transformers an N-1 screen from it covers) the voltage-limit presets (`config.VOLTAGE_BAND_PRESETS`), the pathways a forecast stands in for (`{id, label, required}`, the default one required) and the factor cap (`factor_max`); nothing is stored. A project's demand pathways: the FES ones for NGED, the forecast entered at import for an import (each with its `curve` by year) |
| `GET` · `DELETE /projects/{pid}` · `GET /projects/{pid}/model` · `/model/cgmes` · `/boundary` · `/registry` · `/assumptions` · `/branches` · `POST /projects/{pid}/optimize` | One project: its row, its geolocated model (`crs` = `wgs84` or `synthetic`), its CIM export, its boundary card (404 when it models none), its registry (empty for an import), what it assumes, its branches, and a run of its main. `/model`, `/model/cgmes`, `/boundary`, `/registry` and `POST /optimize` are the NGED project's aliases. Deleting an import removes its branches, records, cached results and file; the built-in project answers 409 |
| `GET /projects/{pid}/agents` · `POST …/agents/pause` · `POST …/agents/resume` | The agents' status for the project: `starting` (the runtime is launching), `idle`, `running` or `paused` (by the operator), what the agents spent (today and in all, from OpenRouter's billed cost), the last events and runs; pause and resume |
| `POST /projects/{pid}/events` | An event for the agents: `{type, payload}` with `type` one of `events.TRIGGERS` (`run.finished`, `branch.merged`, `project.imported`, `edition.changed`, `operator.asked`). The API emits them itself (a `run.finished` after every run, main's included, carries the `run_key` and the parent's; a run whose physics is its parent's wakes nobody); only `run.finished` starts work, the note; the rest are recorded. Deduplicated by each trigger's identity |
| `GET` · `POST /projects/{pid}/threads` · `GET /projects/{pid}/threads/{tid}` | Operator conversations (optionally on a branch), with their messages and pending approvals |
| `POST /projects/{pid}/threads/{tid}/messages` · `GET …/threads/{tid}/stream?message_id=&after=` | Ask the model: the question is stored, a reply queued, the answer workflow started (409 while a reply is already streaming in the thread, or while the agents are paused). The stream is server-sent events: `tool_call` (tool, planning stage, `step_id`), `progress` (a running study's stage and fraction: each chunk as it lands, and the study's own stages), `tool_result`, `token`, then `final` (text, approvals, flags) or `error`; `after` or `Last-Event-ID` resumes from a position |
| `POST /projects/{pid}/threads/{tid}/cancel` | Stop the reply on its way: its message is marked `cancelled` at once (the thread takes the next question) and its workflow is cancelled at its next step; what it had computed stays cached. 409 when nothing is on its way |
| `GET /projects/{pid}/approvals` · `POST /projects/{pid}/approvals/{aid}` | Actions an answer proposed (a branch off main, a reinforcement, a works window, a project or a change to one, a run of the branch) and the operator's `{decision: approve \| deny, note}`. A decision is recorded at once; the answer continues (the approved tools run on the branch, the denied ones are refused to the model) once every proposal of that reply is decided, and until then the response's `waiting_for` lists the open ones with `workflow_id: null`. A second decision on the same proposal answers 409. A thread's view lists every proposal of the thread with its status |
| `GET /branches/{id}/limits` · `GET /branches/{id}/note` | What limits the branch's plan as the engine reduces it (`analysis.limits`: the binding set, the deferrals' chains, the N-1 clusters, the works; 409 `not_solved` until the branch has run for what it holds), and the engineer's note on its current run (`current`, with the digest it was written from and the figures flagged as not in it; `null` until written or once the run has moved on) |
| `GET /projects/{pid}/agents/runs` · `GET …/agents/runs/{rid}/steps` · `GET …/agents/steps/{step_id}` | The audit trail: every agent run (kind, agent, model, status, tokens, cost, solves), a run's recorded tool steps next to DBOS's own step list, and the evidence behind one step (the study re-read from the durable cache, `stale` when the engine has changed since) |

The agents (the note after every run, the answerer) call the model through OpenRouter. `OPENROUTER_API_KEY` is required: the API refuses to start without it, and there is no key-less mode. The agent routes answer 503 `starting` only while the runtime launches.

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
│  ├─ api/                         FastAPI: model, registry, branches, optimize, diff, agents
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
| Demand growth per primary substation: DFES 2025 winter-peak power projections per Electricity Supply Area, four scenarios (Holistic Transition = Standard, Electric Engagement = High, Hydrogen Evolution, Counterfactual = Low), every year 2025 to 2040; over Bicker Fen's 21 primaries (non-coincident) Holistic Transition is ×1.25 by 2030 and ×1.87 by 2035 on 2025, the Counterfactual ×1.11 and ×1.33 | NGED **Distribution Future Energy Scenarios 2025**, Connected Data Portal resource `7686c0a8-bde8-4a4b-8f26-50a3317882ee` | `data/nged/dfes.json`, `nged._growth_curves`, `network.per_load_growth` |
| Fault levels per busbar: the system impedance (pu on 100 MVA), NGED's three-phase and single-phase peak make and rms break currents, and the switchgear make and break ratings, 268 rows for the Bicker Fen group | NGED LTDS **Table 4 Fault Level**, resource `3bd0243c-71dd-4cdd-9ca9-57e6eb79d61f` | `data/nged/fault.json`, `nged._add_fault_data`, `faults.py` |
| Each primary's five-year maximum-demand forecast | NGED LTDS Table 3, "Forecast Year 1" to "Forecast Year 5" | `nged._growth_curves` (connections with no supply area) |
| GB peak demand growth: ×1.08 by 2030, ×1.35 by 2035 (Holistic Transition, underlying peak) | NESO **Future Energy Scenarios 2025**; the `custom` profile's default anchors | `config.GROWTH_2030`, `GROWTH_2035` |
| Substation positions (29 of 68 substations) | **OpenStreetMap**, © OpenStreetMap contributors, ODbL | `data/nged/coords.csv` |

### Published standards

| What | Value | Source | Where |
|---|---|---|---|
| Statutory voltage bands | ±10% at 132 kV, ±6% above 1 kV | ESQCR 2002, regulation 27 | `config.VOLTAGE_BANDS` |
| Demand classes and what may wait after a first circuit outage | Classes by group demand: A ≤ 1, B ≤ 12, C ≤ 60, D ≤ 300, E ≤ 1500 MW, F above. After a first circuit outage, C may lose max(12 MW, ⅓ of the group), D 20 MW, E and F nothing; A and B may wait for restoration | ENA EREC P2/8 (2019), Table 1, applied in simplified form | `config.P2_8_CLASSES` |
| Policy horizons | 2030 (Clean Power 2030), 2035 (strategic-need window) | DESNZ Clean Power 2030 Action Plan (Dec 2024); Ofgem connections reform (TMO4+, Apr 2025) | `config.HORIZONS` |
| The two planning conditions | Voltages to be achievable at interfaces to distribution networks: 1.05 pu at forecast Group Demand, 1.00 pu at forecast Minimum Demand ("the expected demand at the time of the annual minimum demand on the national electricity transmission system"); the Security Planned Transfer Conditions exclude "generation powered by intermittent sources (e.g. wind, wave, solar)" | NETS SQSS v2.13 (NESO, 2 Oct 2026), Table 6 (b) and the Security Planned Transfer Conditions | `network.CASE_SPECS`, `config.GENERATION_FACTORS["winter_peak"]` |
| Minimum demand is measured, not forecast | `demandMinimum`: "a normalised value calculated using historic measured values during normal operating conditions ... net demand corrected for any generation at the substation"; circuits and transformers carry `summerRating` and `winterRating`, a transformer's can differ by direction, and a substation carries `reversePowerFlowAvailableCapacity` | Ofgem LTDS Form of Statement (Apr 2024), Capacity Heatmaps Appendix 1 Information Model | `min_scale` (held at the LTDS factor, not grown), `net.line` ratio columns |
| Generation headroom: all generation at minimum demand | "reverse power thermal assessments which consider the network when all DG is operating when our customers are consuming the least amount at the time of minimum demand"; SSEN's Technical Limits method: PV at 1.0 in summer, "for other technologies we assumed full export across the day and season"; the ESO's net-flow factors (PV 0.84 at summer minimum with solar at its maximum, wind 0.5, batteries 1) are the softer view used to forecast curtailment, not headroom | Electricity North West Network Headroom Report (Aug 2021); SSEN curtailment methodology for Technical Limits; ENWL Technical Limits methodology | `config.GENERATION_FACTORS["summer_min"]` |
| Demand headroom: forecast peak against firm capacity, year by year | "The forecast peak demand for each year up to 2034/2035 ... is compared to the existing firm capacity of each EHV substation"; interventions "when thermal capacity exceeds existing firm capacity ratings"; limits located "including thermal, voltage and fault level" | Electricity North West Network Development Plan methodology (May 2026) | `demand.py`, `years.evaluate_year` |
| Contribution of distributed generation to security of supply | F factors by technology (EREP 130 Issue 3, Aug 2019); "typically significantly less than the sum of the generators' rated capacity values" (ENWL). The engine credits none: conservative | ENA EREP 130 via Ofgem's DCRP/MP/19/02 decision; ENWL NDP methodology | `demand.py` (no credit) |

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
| Summer-minimum demand | Each row's maximum × its LTDS minimum-demand factor, held flat over the plan years: minimum demand is a measured figure (the LTDS heatmap model), DNO export studies build the year from last year's observed flow (ENWL Technical Limits), and peak growth is winter-evening heat and transport, not a summer-midday figure | `min_scale` in `nged._add_loads`, `network._run_case` |
| Firm capacity in MW | LTDS "Firm Capacity of Substation" read as MVA (the table gives no unit) × the row's power factor | `nged._add_loads` |
| Existing fleet | LTDS Table 5 rows with status Connected or Energised, at the substation NGED names, at their connection voltage | `nged._add_existing_fleet` |
| Existing sites under 1 MW | The ECR's connected sites under 1 MW (80 with a capacity; 10.1 MW once the 6 with no published technology are left out, as is one at 0 MW), aggregated per primary and technology at its 11 kV busbar (most connect at 0.4 kV, below the model's lowest level, so LV voltage rise is not modelled); added, not netted from demand, because LTDS Table 3's minimum demand behaves as gross of generation: no negative minimum in 2,294 rows, and ~33-36 % even where a primary's generation is twice its peak (an inference from the data; NGED's definition was not found). Domestic rooftop PV is in no register and is not modelled | `nged._add_small_embedded` |
| The previous LTDS edition | Reconstructed from the New / Removed flags (Updated rows keep current values; the old ones aren't published) | `nged.EDITION_PREVIOUS` |
| Positions of the 39 substations OSM lacks | Each placed at the mean of its placed neighbours | `nged._bus_coords` |

### Planning assumptions (chosen, with the reason)

| What | Value | Why | Where |
|---|---|---|---|
| **Tap-changer target voltage** | **1.02 pu** | LTDS publishes no AVC targets, and GB DNOs set them above nominal so feeder ends stay in band at peak. 1.02 is the lowest value at which today's network meets the statutory band at winter peak (at 1.00 Horncastle 33 kV sits at 0.932 pu). Chosen, not sourced. | `config.OLTC_SETPOINT_PU` |
| Tap-changer deadband | ±0.01 pu | A typical AVC relay deadband | `config.OLTC_DEADBAND_PU` |
| Tap step | 1.25% per tap | LTDS gives each tap range but not the step; a typical GB value | `config.OLTC_TAP_STEP_PERCENT` |
| Generation at winter peak | PV and wind 0; batteries and hybrids charging at full import; gas, biomass and unclassified firm | The SQSS security condition excludes intermittent generation at peak; EREP 130's F factors would credit a little, the engine credits none. Batteries charging is the ESO's own base assumption for the winter-peak Technical Limit (ENWL switched it to discharging for its curtailment view) | `config.GENERATION_FACTORS` |
| Generation at summer minimum | Everything at full export | DNO generation-headroom practice: all DG operating at the time of minimum demand (ENWL), full export for every technology but PV, PV at 1.0 in summer (SSEN). The ESO's softer net-flow factors (PV 0.84, wind 0.5) are a curtailment forecast, not a headroom test | `config.GENERATION_FACTORS` |
| Demand and electrolyser projects at summer minimum | 50% of import capacity | Close to the LTDS minimum-demand factors (~0.5); not a measured profile | `config.DEMAND_PROJECT_MIN_FACTOR` |
| Power factor where LTDS leaves it blank | 0.95 | A typical lagging demand power factor | `nged._pf` |
| Line rating where LTDS leaves it blank | 1.0 / 0.7 / 0.6 / 0.5 / 0.4 kA at 132 / 66 / 33 / 20 / 11 kV | Conservative typical ratings by voltage | `nged._RATING_FALLBACK_KA` |
| Every element a builder fallback touched | Recorded on the network (`net["assumptions"]`: blank ratings, defaulted lengths, median seasonal ratios, assumed tap steps, fixed taps, default power factors) | Stated, never hidden; the `data_quality` study lists them with their element ids | `nged._assume`, `studies.data_quality` |
| GSP limit direction | "Export" = distribution to transmission | NGED's dataset doesn't document its sign convention | `nged.GSP_BOUNDARY` |
| Spring and autumn ratings | LTDS Intermediate Warm (the lower intermediate rating) | Conservative for the shoulder seasons | `config.SEASON_STUDY` |
| Derated element in a works window | 50% of rating | No published derate profile | `config.OUTAGE_DERATE_FACTOR` |
| N-1 screen scope | 132 kV backbone, in each study case (winter peak and summer minimum); outages islanding < 1 MW ignored; islanded demand reported on the winter-peak screen only | Export binds at summer minimum on a net-exporting GSP (today's network already fails N-1 there: losing one Bicker Fen to Boston circuit loads the other to 135% of its summer rating), demand at winter peak; an island is topology, the same in both. Bounded cost (about 3 s per case per year); spurs and tees aren't supply losses | `config.N1_CASES`, `N1_MIN_KV`, `N1_ISLAND_MIN_MW` |
| N-1 post-fault collapse | A post-fault state with any bus below 0.80 pu is one `collapse` finding for the outage ("no credible post-fault steady state", the lowest voltage and how many buses are below), not one breach per element | The solver converges to such states on the closed 33 kV mesh (one outage read as 59 voltage breaches at 0.31 pu plus loadings over 250%, all one event: current rises as voltage falls); a planning floor, chosen, not sourced | `config.N1_COLLAPSE_VM_PU`, `network.n1_screen` |
| Unpublished firm capacity | A demand group whose LTDS Table 3 firm capacity is blank or 0 raises no firm-capacity or headroom alert (the map says "no firm figure"); the gap is recorded on the model | A missing figure is not a 0 MW limit: Horncastle (T1) used to read as 12 MW above a 0 MW firm capacity | `demand._firm_alert`, `nged._assume` (`firm_capacity_unpublished`) |
| 132 kV bus sections | Run split, as the LTDS lists them: separate nodes with no coupler or section circuit between them (Boston 603/503, Skegness 103/203, Middlemarsh 103/203, Grantham North, Sleaford 103/203 with their tees, Grantham 303/403) | NGED publishes the connectivity, not the running arrangement, and a coupler is not invented. After a fault a circuit is therefore not picked up by its pair through the substation, which is what the N-1 screen reads; each such busbar is flagged `bus_sections_split` in the model's assumptions | `nged._assume_structure` |
| 33 kV running arrangement | A closed mesh: every LTDS 33 kV circuit in service, no normal-open points (11 independent loops on Bicker Fen) | None are published, and opening points would be a guess. A 132 kV outage therefore routes power through 33 kV paths (with one Bicker Fen to Boston circuit out at summer minimum, Skegness GT2 reads 244% of its rating and Horncastle to Spilsby 33 kV 109%), so post-fault 33 kV figures are what that mesh carries, likely above a DNO's running arrangement; each looped circuit is flagged `mv_mesh_closed` | `nged._assume_structure` |
| Firm-headroom warning | Below 10% of firm capacity | An early-warning margin, not from P2/8 | `config.HEADROOM_WARN_FRACTION` |
| Single-connection cap | 300 MW | Beyond this a generator connects to transmission; the ECR's largest Bicker Fen site is 248 MW | `config.MAX_CONNECTION_MW` |
| Connection options: higher-voltage busbars probed | 4: the busbars with the most first-order headroom (`sensitivity.rank_buses`, DC factors on the winter-peak point) when more are in reach, in the given order otherwise; each carries its distance in network steps | Bounds the study's cost; each is probed with the project's full MW in every case | `config.CONNECTION_OPTION_BUSES` |
| Smallest ECR registry project | 1 MW export | Sub-MW sites connect at LV, below the model's 11 kV floor; the connected ones are part of the existing fleet (above) | `nged.ECR_MIN_EXPORT_MW` |
| An ECR project's id | A hash of its location, energy source, voltage and acceptance date (not its name or capacity) | The ECR publishes no stable reference: a re-rated or renamed project keeps its id; a corrected location or date gives a new one | `nged._ecr_id` |
| An ECR site's identity between editions | Name, location, energy source and voltage | Keeps an accepted site that connects as the same site; a corrected name or location reads as withdrawn + added, and redacted sites without a location are not told apart (served as `caveats` by `GET /registry/changes`) | `editions.ECR_SITE_KEY` |
| DFES base year | 2025: each primary's projection is applied as a ratio to its 2025 value on the LTDS current maximum | The LTDS edition's current year; the DFES "year 0" sits within a few percent of it | `config.DFES_BASE_YEAR` |
| **Fault levels** | IEC 60909 initial symmetrical current, maximum case, every unit in service; inverter units (solar, wind, storage) as current sources at 1.1 × rated, other units as synchronous machines with x''d 0.20 pu and 0.9 power factor; the transmission infeed from the GSP busbar's published system impedance (read as pu on 100 MVA: 0.0346 gives 12.6 kA against the published 14.3 kA break, a percent reading would give 290 GVA). The figure judged against the published rating is NGED's own break current scaled by the modelled change from today's network, because the model's absolute currents sit above NGED's decremented ones (within 3% at the GSP, 1.0 to 1.2 × at 132 kV, up to 2 × at 11 kV). Informational: a warning in the merge gate, never a connection gate. Where NGED's published current already exceeds the published rating (Skegness 33 kV, Sleaford 33 kV, the GSP 132 kV board) it is reported as published and flagged | The one DNO check the engine lacked; ENA EREC G99 and G74 put an inverter's contribution at 1.1 to 1.2 × rated; machine data is not published, so the reactance is a typical value | `faults.py`, `config.FAULT_*`, `nged._add_fault_data` |
| Connections with no DFES supply area | Their LTDS five-year forecast (Forecast Year 1 = 2026), then held | Customer sites and the BSP aggregates have no supply area; the LTDS forecast is NGED's own; recorded as `forecast_ltds_only` | `config.LTDS_FORECAST_FIRST_YEAR`, `nged._growth_curves` |
| Curtailment search | ≤ 8 extra solves per case, 3 refining, steps under 1% relief put back | A bounded first-order estimate, not an optimal re-dispatch | `config.CURTAIL_*` |
| A project's control mode | As its connection offer sets it, stated by the operator (the ECR publishes none): a fixed power factor, its reactive power following the size of its active power in every case, export or import; or voltage control, a setpoint held within a reactive range (± the given power factor at its rating), dispatched by the case like any project. Not stated: unity power factor, said on the project card | GB DNOs set a power factor for most distribution connections and voltage control for large ones (G99 Type C/D); a voltage-controlled solar or wind project producing nothing is offline, so it holds no voltage at night | `types.Control`, `network.inject_project`, `_follow_power_factor` |
| Reinforcement levers | A parallel circuit (×2 rating, ½ impedance) or an uprate; reactive absorption at 0.98 / 0.95 / 0.90 pf (the reactive power following the output in every case) | Standard first options for thermal and voltage limits | `network.REINFORCERS`, `config.VOLTAGE_ABSORB_PF_STEPS` |
| **Merge gate policy** | A branch is refused when it **introduces or worsens** a problem relative to its parent in any plan year: new or worsened overloads, new voltage breaches, the GSP newly over its limit, new N-1 findings, new demand-side breaches, works windows that become infeasible, a year that stops converging, a stale or incomplete result, a parent that moved on. Worsened voltage, GSP export near its limit, new warnings, more curtailment, a works window the branch adds that needs curtailment or has second faults during it, a schedule against the recommendation, a changed demand profile and removed proposals warn. What the parent already carries is context. The parent is compared on the branch's demand profile (merging adopts it), so a difference is the branch's own; N-1 blockers come one per outage and case across the plan years it applies to, with the count and the worst breach. | "No merge while the grid would be broken in any plan year", read against the parent because main is not perfect either (otherwise nothing could ever merge). A policy, chosen; each kind's level is one line | `config.MERGE_GATE_LEVELS`, `gate.MERGE_CHECKS`, `PlanService._base_inputs` |
| Noise below which nothing moved | 0.05 (gate: GSP near its limit, alerts), 0.1 (diff: works windows, loadings) | A movement smaller than this is not a change | `config.GATE_NOISE`, `DIFF_NOISE` |
| GSP infeed voltage (built-in grid) | 1.02 pu | LTDS does not publish the supergrid side's voltage; held at the tap changers' target. Chosen, not sourced. | `config.GSP_INFEED_VM_PU` |
| Reactive range of a fixed-power-factor unit in the CIM export | ±0.33 × its rating | CIM needs a range on every machine; the engine does not use it (the unit holds its power factor) | `config.CIM_FIXED_PF_Q_SHARE` |
| Worsening margins | 1 loading point, 1 MW of GSP export, 0.005 pu | One rule wherever an element is already past its limit on a reference: below these it is not counted as worsened. The references: the phase's network before its own projects, with the earlier phases' accepted ones connected (a connection trial, the unblock suggestions and connection options, so a pre-existing breach defers nobody), today's network (hosting capacity), the intact network in the same case (an N-1 outage), the parent (the merge gate, intact or in the same N-1 finding: same outage, case and element). Voltage is measured as distance from 1.0 pu, stranded demand by `N1_ISLAND_MIN_MW`. Planning tolerances, chosen, not sourced | `config.WORSEN_PTS`, `WORSEN_GSP_MW`, `WORSEN_VM_PU`, `types.REASON_SPECS[...].worse`, `network.limit_baseline` |
| GSP near-limit warning | Export above 90% of the export limit | An early warning; the planner's gauge turns amber at the same point | `config.GSP_NEAR_LIMIT_FRACTION` |
| Hosting-capacity study | Bisection to 5 MW between 0 and the intake cap, on today's network, buses at 33 kV and above, at most 24 per study; the probe is a firm generator (export) or a demand connection (import) | Bounded cost; a firm probe is the conservative generator in both cases | `config.HOSTING_STEP_MW`, `HOSTING_MIN_KV`, `HOSTING_MAX_BUSES` |
| Contingency-ranking scope | Every circuit and transformer at 33 kV and above, in both study cases | The N-1 screen's mechanics, wider; bounded by the element count | `config.CONTINGENCY_MIN_KV` |
| Tap-margin warning | At a tap stop, or one step from it | No voltage control left there | `config.TAP_MARGIN_MIN_STEPS` |
| GSP margin warning | Export margin under 10% of the limit | The near-limit warning read as a margin, year by year | `config.GSP_MARGIN_WARN_FRACTION` |
| Agent models | Claude Sonnet 5.5 for the note and the answerer | Two roles only: the one that phrases the digest and the one that plans typed queries; the engine computes and the analytics reduce, so no role reads a table | `config.AGENT_MODELS` |
| Agent run limits | Per run: 12 tool calls, 600 solves, 400k tokens, 10 minutes (no daily cap: spend is recorded and shown, never a stop); per model response: 8k output tokens | Bounds, not tuning: a run that hits them says what it did not study; the output cap ends a model that loops (one once streamed 17 000 tokens of "(.)" for five minutes) | `config.AGENT_RUN_BUDGET` |
| Solver order | An agent study waits while an operator's job is queued or running, for as long as its own run's time allows (`AGENT_RUN_BUDGET.timeout_s` less a 60 s reserve to write the answer), saying so in its trace; past that its tool answers that the study is waiting, never an error. Every cache miss takes the one solver lock | Operators first; one power flow at a time in the process; the 60 s reserve is chosen | `config.AGENT_ANSWER_RESERVE_S`, `agents.tools.SolverGate`, `jobs.solver_lock` |
| Agent recovery version | The engine fingerprint, unless `GRIDFORGE_DBOS_APP_VERSION` is set | A code change that retires cached physics also retires in-flight agent runs | `config.AGENTS_APP_VERSION` |
| Imported grid: completeness | Refused, with the list, when it lacks an infeed, a line rating, a generator's technology, rating, voltage setpoint, reactive limits, minimum output or cost, a tap-changer type for a tap range, or reaches buses the infeed cannot | A grid is simulated as it runs or not at all: a filled-in value would give a false outlook (owner rule, 2026-10-05) | `sources.normalise_net` (`net["gaps"]`), `validate_net` |
| Imported grid: generators | Voltage-controlled units stay voltage-controlled (their setpoint, within their reactive limits); an inverter unit rated only by its nominal power is rated at it | Removing voltage control made a grid that solves (IEEE 39) never converge; an inverter's AC rating caps its export | `sources.normalise_net`, `network._runpp` (`enforce_q_lims`), `inverter_rating` |
| Imported grid: dispatch | Power stations (voltage-controlled, not solar, wind or storage) share each case's demand by merit order from the file's costs, every available unit synchronised; embedded generation, solar, wind and storage follow the case; the external grid balances | Real power stations are dispatched to balance demand; which units an operator keeps on for security is not modelled, and switching one off for cost alone stripped the voltage support IEEE 39 runs on | `dispatch.merit_order` (`merit_order_dispatch`) |
| Imported grid: the slack | The file's external grid, or the generator it marks as its slack | A power flow needs one; without it the import is refused | `sources.normalise_net` (`slack_from_generator`) |
| Imported grid: limits and cases | The intake cap applies as it stands; the summer-minimum case and the export limit exist only when the operator enters a minimum-demand factor, a summer rating ratio or a limit at import | Stated as assumptions rather than made configurable this round; the engine never invents a seasonal rating or a boundary | `sources.inspect_net`, `apply_import_meta`, `ImportMeta` |
| Imported grid: study basis | Entered at import, or the import is refused: peak demand's year-on-year growth for every plan year (Standard, optionally Low and High; multiplied up to each year; each factor above 0 and at most `IMPORT_FORECAST_FACTOR_MAX` = 2, a sanity bound), the lowest voltage the N-1 screen covers, the voltage limits at every level. Records `forecast_entered`, `n1_scope_entered`, `bands_entered` | A grid file carries none of them, and GB's FES growth, bands and 132 kV backbone say nothing true about another grid; the forecast is spread uniformly over the loads, since it says how much demand grows, not where | `sources._study_basis`, `ImportMeta`, `network.demand_multiplier`, `grow_for`, `bands_of`, `n1_floor` |
| Voltage-limit presets at import | GB ESQCR (±10 % at 132 kV and above, ±6 % from 1 kV, +10 / −6 % at LV); EN 50160 (±10 % up to 36 kV, nothing above) | Only fill the import form's boxes; what is imported is what the operator leaves in them | `config.VOLTAGE_BAND_PRESETS` |
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
| Contingency severity index | islanded MW × 1 + thermal excess MVA × 1 + worst voltage shortfall pu × 100; the components are reported with it | `config.CONTINGENCY_SEVERITY_WEIGHTS`, `studies.contingency_ranking` |

---

## Limitations

- **The GSP export limit is the only transmission constraint modelled.** The 400 kV network and wider transmission boundaries are not; the 400 kV projects are context only.
- **Generation dispatch per case is a planning assumption.** PV and wind at nil and batteries (and hybrids) charging at winter peak; everything at full export at summer minimum. Gas, gas engines, biomass and technologies the data doesn't classify are treated as firm in both.
- **Demand projects and electrolysers draw a fixed share.** Their full import capacity at winter peak and 50% of it at summer minimum; that 50% is an assumption, not a measured profile.
- **Planned works are reported, not enforced.** A works window is studied in its season's case(s) and its verdict is shown, but it never blocks a connection. The weeks are recorded but not placed in specific calendar weeks (the season stands in for them), so every window in the same season and year is studied as overlapping. The curtailment figure is a first-order estimate from a bounded search (nearest generators first, at most 8 extra solves per case), not an optimal re-dispatch; no other re-dispatch or switching is modelled. The N-1 screen during a window is informational. Unlike a connection, a window's verdict is judged against every limit, including those the year's network already breaks without it (a window on a network that already breaches is constrained). A repowering changes only the years after its window, and the queue run does not count it (add the upgrade as a reinforcement for that).
- **Every year is a fixed plan.** The per-year solves show the network in each year; they don't change who connects, which is still decided at the two phase horizons. Demand between them is interpolated linearly.
- **Tap-changer settings are assumed.** The LTDS gives each transformer's tap range but not its step or its target voltage; 1.25% per tap is used, and taps are regulated towards 1.02 pu with a ±0.01 pu deadband. The target was chosen as the lowest value at which today's network meets the statutory band at winter peak (at 1.00 pu Horncastle 33 kV sits at 0.932 pu); real targets vary by site, and line-drop compensation is not modelled.
- **N-1 is reported, not enforced.** The single-outage screen covers the 132 kV backbone in each study case; it does not yet apply a security-of-supply standard or take 33 kV elements out (their post-fault loading is checked, as every element's is). Each outage is judged as the post-fault steady state: the tap changers re-regulate (the relays act within a minute) and transformer loading is read against the LTDS emergency rating, so what remains is what the relays and the short-term rating cannot absorb; the instant after the fault, before the relays act, is not studied.
- **Bus sections run split and the 33 kV network meshed, as the LTDS lists them.** NGED publishes the connectivity, not the running arrangement: a substation's 132 kV bars are separate nodes with no coupler row, and no 33 kV normal-open point is listed. Neither is invented, so after a 132 kV fault power finds its way through the 33 kV mesh rather than through a coupler, and the post-fault 33 kV and grid-transformer loadings (and the second faults a works window reports) are what that reading gives. Both are flagged per element in the model's assumptions (`bus_sections_split`, `mv_mesh_closed`) and listed by the `data_quality` study.
- **The demand-side alerts are a simplified P2/8-style check.** Restoration times, switching, transfer capacity between groups and second circuit outages are not modelled, so a group P2/8 would pass by switching can still be flagged, and the classes are applied to each LTDS row as published (a two-transformer site fed from two BSPs appears as two groups). Everything is MW of demand: the open data has no customer counts.
- **Firm capacity units are read, not stated.** LTDS Table 3's "Firm Capacity of Substation" has no unit in the data; we read it as MVA and convert it to MW at the row's own power factor. A firm capacity of 0 (single-transformer sites and customers' own connections) is reported as is; such a group is only alerted on once it reaches class C. Firm capacity is compared with the group's own peak, not the GSP-coincident share the power flow carries. The "room for new demand" is first-order (≈): no power-flow probe is run for it.
- **Demand growth comes from a NESO FES pathway, spread per bus** with a seeded spread, distance from the GSP and hotspots. The LTDS's own 5-year substation forecasts are not used yet. An imported grid grows by the forecast entered with it, uniformly over its loads.
- **The GSP limit's direction is an assumption.** NGED's dataset doesn't document its sign convention; we read "export" as distribution → transmission.
- **Imported grids are simulated as they run, or refused.** A CGMES zip, a pandapower JSON or a MATPOWER `.mat` becomes a network the same engine plans on only when it is complete: whatever a real simulation needs and the file lacks (an infeed, a line rating, a generator's technology, rating, setpoint, reactive limits, minimum output or cost, a tap-changer type, the summer data) is listed and the import is refused until the operator states it; nothing is filled in. The study basis (the demand forecast, the N-1 floor, the voltage limits by level) is entered with it, and both study cases run on every grid. Without firm capacities there are no customer alerts; without an export limit, export is reported, never limited; without a supergrid transformer's rating, no "add a transformer" lever. Voltage-controlled generators stay voltage-controlled. A base case that does not converge is reported as such; one that already breaks a limit is reported in every plan year, and a project is deferred for it only if it makes it worse. Two sample files to try the path with are under `docs/samples/` (the IEEE 9-bus system as a pandapower JSON and as GridForge's own CGMES export).
- **Agents are advisory and bounded.** The note is written from the engine's digest and the answers from recorded steps; a digit figure in either that no digest or step produced is flagged, not blocked, and the prose around the figures is the model's. The analytics are first-order where they say so: a headroom in MW from a current-based loading percentage, a DC sensitivity ranking the AC solve confirms. Operators keep the solver first between an agent study's chunks.
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
