# GridForge

**A grid planning backbone: a real UK distribution network, AC power flow through the plan years, and branches to try changes on.**

GridForge models one real Grid Supply Point, **Bicker Fen 132 kV, Lincolnshire**, operated by National Grid Electricity Distribution (NGED), built entirely from open data. `main` is the network **as it exists today**. You open a branch, connect generation, storage or demand at a busbar and choose the year it energises, and the engine solves every plan year (2026 to 2035) with AC power flow in the two planning cases a DNO studies. Every year reports each line's and transformer's loading, every busbar's voltage, the GSP's export, and every limit breached, with its element, figure and case. You compare the branch with its parent year by year and merge it, or throw it away.

The physics is deterministic and reproducible (pandapower). There is no AI in the product today: this repository is the backbone the next layer (learned demand and generation profiles, analysis) will be built on.

---

## Contents

- [What you can do](#what-you-can-do)
- [The network and the data](#the-network-and-the-data)
- [How a year is solved](#how-a-year-is-solved)
- [Architecture](#architecture)
- [HTTP API](#http-api)
- [Quickstart](#quickstart)
- [Refreshing the data](#refreshing-the-data)
- [Tests](#tests)
- [Sources and assumptions](#sources-and-assumptions)
- [Limitations](#limitations)

---

## What you can do

| | |
|---|---|
| **`main` = today** | The as-is network: the connected fleet, today's demand and the GSP. Nothing is pre-loaded for future years. `main` is read-only: it changes only by merging a branch into it. |
| **Branch** | Open a branch from `main` (or from another branch). Its connections and demand profile come along. |
| **Connect** | Click a busbar and place a connection there: technology, export (and import for storage or demand), the year it energises. Or pull a project from the registry (the not-yet-built sites NGED publishes), at its requested year. Change a connection's year or remove it at any time. |
| **Simulate** | Every edit re-runs the branch: each plan year is solved with demand grown to it (NGED's DFES projection per primary, on the Low, Standard or High pathway) and the connections in service by then. Years an edit does not touch come from the cache. |
| **Read the result** | The map colours loading or voltage for the year in view; the readings give the worst line and transformer, the voltage range and the GSP export against its limit; *Limits* lists every breach in the year and every element that breaches across the plan, with the first year it does; a selected element shows its figure in every year. |
| **Compare** | The branch against its parent, year by year, on the same demand profile: new and cleared breaches, the biggest loading movers, the GSP export change. The map shows the change in loading. |
| **Merge or discard** | Merging makes the branch's connections and profile its parent's. |

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
- Demand is each substation's LTDS maximum, scaled to what is on at the GSP's winter peak by two published figures: each BSP's own maximum (its primaries don't all peak together) and NESO's peak for Bicker Fen GSP, 149.2 MW. No assumed diversity factor. A BSP's own Table 3 rows ("Sleaford (GT1)", "(GT2)") are the group demand its 132/33 kV transformers carry, the same customers as the primaries listed under it, so they add no load. The summer minimum is each row's maximum × its LTDS minimum-demand factor.
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

The demand side matches the observation; the export side is the planning extreme (every generator at full output at the measured minimum), 8% above the observed GSP maximum and 25% above the observed circuit maximum; the winter import is the SQSS security condition (no wind credited), a third of which is what the GSP actually imported at the 2024 peak with 180 MW of wind on the group. Sources and method: `docs/reports/study-basis-2026-10-07.md`.

---

## How a year is solved

A plan year is today's network with demand grown to that year and every connection whose year has arrived. It is solved in two study cases:

- **Winter peak**: grown demand, winter thermal ratings, solar and wind at nil, batteries charging at their import capacity, demand connections drawing their full import.
- **Summer minimum**: the LTDS minimum demand (measured, not grown), summer ratings, every generator at full export, demand connections drawing half their import.

These are the two planning conditions the SQSS sets at the interface with a distribution network, and the two headroom studies every DNO's Network Development Plan publishes (peak against capacity; all generation at minimum demand); the register below cites them. The on-load tap changers are regulated in each case before anything is judged.

The limits, in both cases:
- every busbar inside its **statutory voltage band**: ±10% at 132 kV, ±6% at 33 kV and 11 kV (GB ESQCR);
- every line and transformer at or below 100% of its rating for the season;
- **the GSP exporting no more than its supergrid transformers allow**: 2 × 263.5 MW = 527 MW.

A year reports every breach in every case, the worst figure of the two cases for each element (and which case set it), the GSP's export and import, and whether the power flow converged. Nothing is a gate: the plan is reported as it stands, every year.

**Technologies.**
- **Solar, wind**: nil at winter peak, full export at summer minimum.
- **Battery, hybrid (solar + battery)**: charging at its import capacity at winter peak, full export at summer minimum.
- **Demand, electrolyser** (import-only): export nothing; their import at winter peak, half of it at summer minimum (an assumption).
- **Gas, gas engines, biomass and anything unclassified**: firm, full output in both cases.

A connection runs at unity power factor unless its control mode says otherwise (a fixed power factor, or voltage control within a reactive range).

Engine details: [`packages/optimizer/README.md`](packages/optimizer/README.md).

---

## Architecture

```
apps/pipeline   Dagster: the pinned LTDS / ECR / OSM / DFES snapshot -> the DuckDB warehouse (read-only for the API)
packages/optimizer   gridforge_optimizer: the network build (nged.py), the physics (network.py), the plan years (years.py), the comparison (diff.py)
apps/api        FastAPI on :8000: the grid, branches and their connections, runs as background jobs, the result cache, the comparison
apps/web        Vite + React + TypeScript planner on :3000: the map, the readings, the timeline, the side panel
```

- The engine is the single source of truth for the physics; the API and the planner never duplicate it.
- The API keeps everything a user does in its own scenarios store (DuckDB by default, Postgres with `GRIDFORGE_SCENARIOS_URL`), never in the warehouse.
- Every result is cached under the grid's snapshot, the demand profile, the connections and the engine's code fingerprint, in process and durably; plan years are cached one by one, so an edit re-solves only the years it changes.
- One power flow runs at a time in the API process (one job worker and one solver lock).

---

## HTTP API

| Method | Path | What |
|---|---|---|
| GET | `/health` | Liveness, and whether the warehouse exists |
| GET | `/model` | The geolocated grid for the map, with its name and snapshot |
| GET | `/boundary` | The GSP's export limit and today's export |
| GET | `/forecasts` | The demand pathways, the plan years and the intake limits |
| GET | `/assumptions` | What the model assumes (builder fallbacks and planning assumptions) |
| GET | `/registry` | The not-yet-built projects NGED publishes |
| GET, POST | `/branches` | List the branches; open one from another (`{name, from_branch}`) |
| GET | `/branches/{id}` | One branch |
| GET, POST | `/branches/{id}/connections` | A branch's connections; place one (by hand, or `from_registry`) |
| PATCH, DELETE | `/branches/{id}/connections/{rid}` | Change one (bus, size, control, year) or remove it |
| POST | `/branches/{id}/profile` | The demand pathway (`fb`, `ht`, `ee`, or `custom` with both anchors) |
| POST | `/branches/{id}/run` | Run as a background job (every plan year, `view_year` first); joins a run of the same inputs |
| POST | `/branches/{id}/simulate` | Run and wait (scripts, tests) |
| GET | `/branches/{id}/result` | The result for what the branch holds now, never solving (409 `not_solved` until run) |
| GET | `/branches/{id}/diff` | The branch against its parent, year by year |
| POST | `/branches/{id}/merge`, `/discard` | Merge into the parent, or discard |
| GET | `/jobs/{id}` | A job's status, progress, partial result (`partial=true`) and result; `POST /jobs/{id}/cancel` stops it |

`main` refuses connection edits, merges and discards (409): it changes only by merging into it. Its demand profile stays editable.

---

## Quickstart

**Prerequisites:** Node 22 + pnpm 10, Python 3.11+ with [uv](https://docs.astral.sh/uv/). No API key is needed.

```bash
pnpm install                                   # JS deps (monorepo root)

# build the warehouse from the bundled data (runs the Dagster asset graph + checks)
cd apps/pipeline
uv run dagster asset materialize -m grid_simulator.definitions --select 'ltds_tables*'
cd ../..

# run the app: two terminals, from the repo root
pnpm --filter @gridforge/api dev               # API on http://localhost:8000
pnpm --filter web dev                          # planner on http://localhost:3000
```

Open **http://localhost:3000**. You land on `main`, today's network, already solved. Click a busbar and add a connection: `main` is read-only, so the first change opens a branch for it, and the branch re-runs by itself. Pick a year on the timeline, read *Limits*, and open *Compare* to see what the branch changes against `main`.

- **Shell quoting:** quote `'ltds_tables*'`, or the shell may expand it. It selects the root asset and everything downstream.
- **Dagster UI:** `uv run dg dev` shows lineage and check results. It also uses port 3000, so don't run it alongside the web app.
- **Postgres (optional):** `GRIDFORGE_SCENARIOS_URL=postgresql://user@host:5432/dbname` before starting the API moves the scenarios store to Postgres.
- **A store from before the backbone:** on first start each branch's old projects become its connections (in their scheduled year, else their requested one), and the old optimizer, works, ledger and agent tables are dropped.

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

## Tests

```bash
pnpm test                                     # everything, via Turborepo
cd packages/optimizer && uv run pytest -q     # engine (4 workers): the physics, the cases, the plan years, the NGED data rules, the editions, the CIM export
cd apps/api && uv run --with pytest pytest tests -q   # API (a temp scenarios DB; +1 against Postgres if GRIDFORGE_TEST_PG_URL is set)
```

The engine tests are **grid-agnostic**: fixtures are derived from whatever network `build_base_net()` returns, never from hard-coded bus ids. `test_nged.py` holds the NGED data rules (removed equipment is excluded, every live MW of demand is modelled, no registry project is pre-loaded). The planner has no unit tests; it is checked in a real browser.

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
| Each primary's five-year maximum-demand forecast | NGED LTDS Table 3, "Forecast Year 1" to "Forecast Year 5" | `nged._growth_curves` (connections with no supply area) |
| GB peak demand growth: ×1.08 by 2030, ×1.35 by 2035 (Holistic Transition, underlying peak) | NESO **Future Energy Scenarios 2025**; the `custom` profile's default anchors | `config.GROWTH_2030`, `GROWTH_2035` |
| Substation positions (29 of 68 substations) | **OpenStreetMap**, © OpenStreetMap contributors, ODbL | `data/nged/coords.csv` |

### Published standards

| What | Value | Source | Where |
|---|---|---|---|
| Statutory voltage bands | ±10% at 132 kV, ±6% above 1 kV | ESQCR 2002, regulation 27 | `config.VOLTAGE_BANDS` |
| Policy horizons | 2030 (Clean Power 2030), 2035 (strategic-need window) | DESNZ Clean Power 2030 Action Plan (Dec 2024); Ofgem connections reform (TMO4+, Apr 2025) | `config.HORIZONS` |
| The two planning conditions | Voltages to be achievable at interfaces to distribution networks: 1.05 pu at forecast Group Demand, 1.00 pu at forecast Minimum Demand ("the expected demand at the time of the annual minimum demand on the national electricity transmission system"); the Security Planned Transfer Conditions exclude "generation powered by intermittent sources (e.g. wind, wave, solar)" | NETS SQSS v2.13 (NESO, 2 Oct 2026), Table 6 (b) and the Security Planned Transfer Conditions | `network.CASE_SPECS`, `config.GENERATION_FACTORS["winter_peak"]` |
| Minimum demand is measured, not forecast | `demandMinimum`: "a normalised value calculated using historic measured values during normal operating conditions ... net demand corrected for any generation at the substation"; circuits and transformers carry `summerRating` and `winterRating`, a transformer's can differ by direction, and a substation carries `reversePowerFlowAvailableCapacity` | Ofgem LTDS Form of Statement (Apr 2024), Capacity Heatmaps Appendix 1 Information Model | `min_scale` (held at the LTDS factor, not grown), `net.line` ratio columns |
| Generation headroom: all generation at minimum demand | "reverse power thermal assessments which consider the network when all DG is operating when our customers are consuming the least amount at the time of minimum demand"; SSEN's Technical Limits method: PV at 1.0 in summer, "for other technologies we assumed full export across the day and season"; the ESO's net-flow factors (PV 0.84 at summer minimum with solar at its maximum, wind 0.5, batteries 1) are the softer view used to forecast curtailment, not headroom | Electricity North West Network Headroom Report (Aug 2021); SSEN curtailment methodology for Technical Limits; ENWL Technical Limits methodology | `config.GENERATION_FACTORS["summer_min"]` |

### Derived from published data

| What | Method | Where |
|---|---|---|
| Line impedance in ohms | LTDS %Z on a 100 MVA base × the circuit's own voltage² / 100 | `nged._add_lines` |
| Line charging | LTDS B1 (positive-sequence susceptance, % on 100 MVA): B = B1 / kV², C = B / 2πf over the circuit, as nF/km for pandapower (medians 12 nF/km at 132 kV, 42 at 33 kV); 9 circuits with no B1 carry none (`charging_blank`) | `nged._add_lines` |
| Transformer impedance | LTDS X1, R1 on 100 MVA rescaled to the unit's rating; vk clamped to 0.1 to 25% to keep the solver stable on bad rows | `nged._add_transformers` |
| Seasonal line ratings | LTDS Winter and Summer ratings, summer as a ratio of winter | `net.line` ratio columns |
| Coincidence at each BSP | The BSP's published maximum ÷ the sum of its primaries' maxima (0.78 Grantham, 0.89 Sleaford, 1.02 Skegness) | `nged._bsp_membership` (`bsp_coincidence`) |
| Coincidence at the GSP | NESO's GSP peak ÷ the BSP-coincident total (0.959), so today's winter-peak demand is exactly 149.235 MW | `nged._coincidence` |
| Summer-minimum demand | Each row's maximum × its LTDS minimum-demand factor, held flat over the plan years: minimum demand is a measured figure (the LTDS heatmap model), DNO export studies build the year from last year's observed flow (ENWL Technical Limits), and peak growth is winter-evening heat and transport, not a summer-midday figure | `min_scale` in `nged._add_loads`, `network._run_case` |
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
| GSP limit direction | "Export" = distribution to transmission | NGED's dataset doesn't document its sign convention | `nged.GSP_BOUNDARY` |
| 132 kV bus sections | Run split, as the LTDS lists them: separate nodes with no coupler or section circuit between them (Boston 603/503, Skegness 103/203, Middlemarsh 103/203, Grantham North, Sleaford 103/203 with their tees, Grantham 303/403) | NGED publishes the connectivity, not the running arrangement, and a coupler is not invented; each such busbar is flagged `bus_sections_split` in the model's assumptions | `nged._assume_structure` |
| 33 kV running arrangement | A closed mesh: every LTDS 33 kV circuit in service, no normal-open points (11 independent loops on Bicker Fen) | None are published, and opening points would be a guess. A 132 kV outage therefore routes power through 33 kV paths (with one Bicker Fen to Boston circuit out at summer minimum, Skegness GT2 reads 244% of its rating and Horncastle to Spilsby 33 kV 109%), so post-fault 33 kV figures are what that mesh carries, likely above a DNO's running arrangement; each looped circuit is flagged `mv_mesh_closed` | `nged._assume_structure` |
| Single-connection cap | 300 MW | Beyond this a generator connects to transmission; the ECR's largest Bicker Fen site is 248 MW | `config.MAX_CONNECTION_MW` |
| Smallest ECR registry project | 1 MW export | Sub-MW sites connect at LV, below the model's 11 kV floor; the connected ones are part of the existing fleet (above) | `nged.ECR_MIN_EXPORT_MW` |
| An ECR project's id | A hash of its location, energy source, voltage and acceptance date (not its name or capacity) | The ECR publishes no stable reference: a re-rated or renamed project keeps its id; a corrected location or date gives a new one | `nged._ecr_id` |
| An ECR site's identity between editions | Name, location, energy source and voltage | Keeps an accepted site that connects as the same site; a corrected name or location reads as withdrawn + added, and redacted sites without a location are not told apart (served as `caveats` by `GET /registry/changes`) | `editions.ECR_SITE_KEY` |
| DFES base year | 2025: each primary's projection is applied as a ratio to its 2025 value on the LTDS current maximum | The LTDS edition's current year; the DFES "year 0" sits within a few percent of it | `config.DFES_BASE_YEAR` |
| Connections with no DFES supply area | Their LTDS five-year forecast (Forecast Year 1 = 2026), then held | Customer sites and the BSP aggregates have no supply area; the LTDS forecast is NGED's own; recorded as `forecast_ltds_only` | `config.LTDS_FORECAST_FIRST_YEAR`, `nged._growth_curves` |
| A project's control mode | As its connection offer sets it, stated by the operator (the ECR publishes none): a fixed power factor, its reactive power following the size of its active power in every case, export or import; or voltage control, a setpoint held within a reactive range (± the given power factor at its rating), dispatched by the case like any project. Not stated: unity power factor, said on the project card | GB DNOs set a power factor for most distribution connections and voltage control for large ones (G99 Type C/D); a voltage-controlled solar or wind project producing nothing is offline, so it holds no voltage at night | `types.Control`, `network.inject_connection`, `_follow_power_factor` |
| GSP infeed voltage (built-in grid) | 1.02 pu | LTDS does not publish the supergrid side's voltage; held at the tap changers' target. Chosen, not sourced. | `config.GSP_INFEED_VM_PU` |
| Reactive range of a fixed-power-factor unit in the CIM export | ±0.33 × its rating | CIM needs a range on every machine; the engine does not use it (the unit holds its power factor) | `config.CIM_FIXED_PF_Q_SHARE` |
| Every element a builder fallback touched | Recorded on the network (`net["assumptions"]`: blank ratings, defaulted lengths, median seasonal ratios, assumed tap steps, fixed taps, default power factors) | Stated, never hidden; the planner lists them under *What the model assumes* (`GET /assumptions`) | `nged._assume` |
| Noise below which a loading did not move | 0.1 loading points | A movement smaller than this is not a change in the comparison | `config.DIFF_NOISE` |

### Registry data (what the registry rows carry)

The registry is a list of not-yet-built projects to pull onto a branch; the engine never ranks or picks them. These fields come with each row and are shown as published.

| What | Value | Where |
|---|---|---|
| Requested energisation year for LTDS Table 5 projects | 2027 to 2035 from readiness, technology, size and a deterministic jitter; not a developer's date | `nged.commission_year` |
| ECR projects | The published target date is the requested year | `nged.ecr_candidates` |
| Readiness of a registry row | A rubric over published facts (connection status, a signed agreement); kept on the rows for the pipeline, not used by the planner | `readiness.py`, `config.READINESS_WEIGHTS` |

---

## Limitations

- **The GSP export limit is the only transmission constraint modelled.** The 400 kV network and wider transmission boundaries are not.
- **Two snapshot cases per year, not a time series.** Each year is its winter peak and its summer minimum; how many hours an element is over its limit, or how often, is not modelled.
- **Generation dispatch per case is a planning assumption.** PV and wind at nil and batteries charging at winter peak; everything at full export at summer minimum; demand projects at 50% of their import at summer minimum.
- **Tap-changer settings are assumed.** The LTDS gives each transformer's tap range but not its step or its target voltage; 1.25% per tap is used, regulated towards 1.02 pu with a ±0.01 pu deadband. Line-drop compensation is not modelled.
- **Intact network only.** No N-1 or planned outages: every year is studied with everything in service. Bus sections run split and the 33 kV network meshed, as the LTDS lists them (NGED publishes the connectivity, not the running arrangement), flagged per element in the model's assumptions.
- **The GSP limit's direction is an assumption.** NGED's dataset doesn't document its sign convention; we read "export" as distribution to transmission.
- **One grid.** The network is NGED Bicker Fen, behind the `GridSource` seam; importing another grid is not built.
- **The previous LTDS edition is reconstructed, not fetched.** NGED's New/Removed flags give it exactly, but Updated rows carry their current values in both editions.

---

## How this was built

GridForge was built in about a week by one person working with Claude Code as a pair, and the commit history says so: every commit carries a `Co-Authored-By: Claude` trailer. It would be odd to hide that from a company that lists "AI-assisted software development" as a skill it hires for, so here is how the division of labour actually worked.

**What the human did.** Chose the problem and the data (one real GSP, open data only, NGED because it is the launch customer's network), set the rules the agent works under (`AGENTS.md`: `main` is only what exists today, the LLM never touches physics, honesty over fake precision), made every product decision (the pull-request framing, the registry of optional projects, "parameters are set by the flows, not the operator", recommend-then-override for energisation years), and reviewed the result in the browser after each slice. The pivots (restoration → data pipeline → connection-queue optimiser → PR workflow on a real network) were human calls, as was the decision to throw away a working manual-editing frontend.

**What the agent did.** Wrote most of the code, the tests and the docs, in slices that the human directed and inspected. Then, asked to review the project as the hiring team would, it produced a critique of its own work and worked through the fixes one at a time.

**What that review caught, because this is the part that matters.** A fresh clone 500'd on first load (two concurrent table creations on an empty database). The frontend was a Next.js shell redirecting to a 1,600-line template-dialect file that compiled JSX in the browser; it was rebuilt as a plain Vite + React + TypeScript app. The Dagster lineage was decorative (assets ignored their inputs) and the snapshot table was overwritten on every run. Voltage limits were 0.9–1.1 pu everywhere instead of the statutory ±6 % below 132 kV, which only became a sensible rule once the tap changers were modelled. The existing fleet was placed round-robin rather than at its real substations. PV ran at full output at the winter evening peak. The Python `.gitignore` template was silently keeping the planner's `src/lib` folder out of git. Tests took ten minutes because every one paid for an N-1 screen it was not testing.

**What the agent got wrong along the way, and how it was caught.** pandapower 3 ignores transformer taps unless a changer type is declared, so the first tap-regulation loop moved taps that did nothing; a probe of the busbar voltages exposed it. The LTDS tap ranges (−12..+4) are HV-winding taps where a lower tap raises the LV voltage; the first implementation tapped the wrong winding and hit the stop. The first React port dropped the coalesced re-run after rapid adds because it read React state that had not flushed yet; a headless browser run that added four projects and found one caught it. In every case the fix came from measuring (a power-flow probe, a request log, a screenshot), not from re-reading the code, and each is now a test.

**Commit discipline.** The early commits are large because the project was built in large slices. From the review onward each change is its own commit with a message that states what was measured. That is the practice going forward.

**Honesty about scope.** This is a planning toy on one GSP built from open data, not a product. The limitations above are real; the numbers are only as good as the LTDS tables and the assumptions written next to them.
