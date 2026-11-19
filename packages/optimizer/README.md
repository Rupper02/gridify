# gridify_optimizer

The deterministic grid engine behind Gridify: it builds NGED's Bicker Fen 132 kV GSP from open data, grows its demand to each plan year, connects the branch's connections in their years, and solves every year with AC power flow (pandapower) in the two planning cases. No network calls, no LLM: the same inputs always give the same result.

```python
from gridify_optimizer import Connection, PlanParams, simulate, diff_plans

base = simulate([], PlanParams())                      # main: today's network, every plan year
pv = Connection(request_id="PV-1", bus_id=17, technology="solar", rating_mw=150, year=2029)
head = simulate([pv], PlanParams())
d = diff_plans(base, head)                             # what the connection changes, year by year
```

## Modules

| Module | What it owns |
|---|---|
| `nged.py` | The network build from the bundled LTDS / ECR / OSM / DFES snapshot (`build_nged_net`), the model for the map (`nged_model`), the registry of not-yet-built projects (`nged_candidates`), the GSP boundary, the builder's recorded assumptions |
| `network.py` | The physics: demand growth (`grow_for`), voltage bands, connecting a connection (`inject_connection`), dispatch per case, tap regulation, the study cases (`CASE_SPECS`), the limit checks (`LIMIT_CHECKS`), `feasibility`, and one moment given as values (`solve_snapshot`) |
| `dispatch.py` | The per-case factors and the merit order for voltage-controlled power stations (`merit_order`) |
| `years.py` | The plan year by year: `evaluate_year`, `simulate`, `year_signature` (the per-year cache key) |
| `diff.py` | Two plans compared year by year: `diff_year`, `diff_plans` |
| `sources.py` | The `GridSource` seam and `NgedSource`; `default_source()` is what `build_base_net()` builds; `measured_year(folder, net, reactive)` maps a grid's measured half-hours onto a net |
| `nged_flows.py` | NGED's half-hourly flows (curtailment-analysis data) mapped onto the built network: injections per cluster by Kirchhoff's law, the metered primary series, the reactive-power screen (`REACTIVE_MODES`) |
| `runs.py` | The year view's reads of run files, general to any grid: `RunFiles(folder, catalogue, net_factory)` with `summarise` (per element peak and hours over rating, busbars out of band, primary substations above firm capacity), each element's agreement with the source's model (`compare_with_source`: the measured year's rules on the catalogue's `reference` run, each label with its `label_year`; kept until the reference file changes) and each run's input reliability (`unreliable_buses`, from the screen flags the run's own file carries for its source flows), `month_hour_grid`, and `compare` (a branch's year, `branch-…`, against its "before"). What runs a grid has is its `RunCatalogue`, from `GridSource.run_catalogue()` |
| `nged_points.py` | NGED's supply points, one `SupplyPoint` record each: where its data is filed (LTDS group, Table 5 and ECR spellings, the loading files and bus mapping), the published figures it is built to (NESO's GSP peak, the supergrid transformers' limits) and its named exceptions (`removed_in_error`, `generation_sites`, `ecr_additions`, `held_at_zero`, `year_shapes`), with its run catalogue. `BICKER_FEN` holds today's values and is the default everywhere (`nged.*(..., point=)`, `NgedSource(point=)`). A supply point with no published peak cannot be built (`require_peak` raises); one with no bundled snapshot must pass its tables |
| `nged_runs.py` | NGED Bicker Fen's `RunCatalogue`: the run files and how each is made, the grown years a branch's year can be run on (`bases`), the measured flows' folder, a run whose file carries no screen flags and the run whose flags stand for it (`screen_from`), the reference run for agreement (2025 screened), each run's limits in plain words |
| `timeseries.py` | The measured year: `run_year(folder, out, reactive=)` solves every half-hour in time order with `solve_snapshot` and saves one `.npz`. `scale=` grows each metered primary (a grown year); `connections=` with `plan_year=` adds a branch's connections in service by that year (`years.in_service`), each on its technology's 2024 per-unit shape (`YEAR_DISPATCH`, the shapes from `GridSource.measured_year`; README register: "Year shape"). `growth_scale(folder, year, pathway)` gives a grown year's multipliers (the engine's per-load growth over each metered cluster) |
| `types.py` | The pydantic contract: `Connection`, `Control`, `PlanParams`, `YearResult`, `PlanResult`, `Reason`, `GridModel` |
| `config.py` | Every tunable, each listed in the *Sources and assumptions* register (`docs/sources-and-assumptions.md`) |
| `gridmodel.py`, `geometry.py`, `naming.py` | The geolocated model for the map, bus positions, and what elements are called |
| `editions.py`, `cim.py`, `readiness.py` | For the pipeline: LTDS / ECR edition change-sets, the CIM/CGMES export, the registry's readiness rubric |

## Feasibility (`network.feasibility`)

`feasibility(net) -> (ok, breaches, metrics)` solves **every study case** the network supports and returns every limit breached in each, then the GSP boundary.

| Case | Load scaling | Generation (`GENERATION_FACTORS`) | Line ratings |
|---|---|---|---|
| `winter_peak` | as grown by the demand pathway | solar 0 · wind 0 · battery and hybrid **−1** (charging at `import_mw`) · demand and electrolyser **−1** · other 1 | winter (`max_i_ka`) |
| `summer_min` | per-load `min_scale` (each row's maximum × its LTDS minimum-demand factor; **not grown**) | everything at 1 (full export) · demand and electrolyser **−0.5** | × per-line `summer_ratio` (LTDS summer ÷ winter) |

Before each case is judged, `_solve` lets the on-load tap changers settle: every transformer with a tap range moves its tap (HV winding, GB convention: a lower tap raises the LV voltage) until its LV busbar is within `OLTC_DEADBAND_PU` of `OLTC_SETPOINT_PU` or at an end stop, in at most `OLTC_MAX_PASSES` power flows.

Checks (`LIMIT_CHECKS`, each returning every breach worst first; a new kind of limit is one function and one entry):
1. every bus inside its statutory band (`VOLTAGE_BANDS`: ±10% at 132 kV and above, ±6% below);
2. line and transformer loading ≤ 100%;
3. in each case, the **GSP import** ≤ that case's season's import limit (`net["gsp_import_limit_mw"][CaseSpec.season]`, both SGTs; no check when the grid gives none);
4. then the **GSP export** at its worst case ≤ `net["gsp_export_limit_mw"]`.

Each breach is a `Reason` (`voltage` / `line` / `trafo` / `gsp_import` / `gsp`) carrying the element, the value, the `limit` and the `case`. A case that does not converge stops the study with one `non_convergent` reason and no metrics. So does a case that converges with an in-service busbar below `config.COLLAPSE_VM_FLOOR_PU` (0.5 pu): it gets one `voltage_collapse` reason naming the lowest busbar and its voltage, because it is the low-voltage solution of the equations, not an operating point. In a measured or grown year such a half-hour is not solved, and is counted in the run file's `collapsed`, apart from non-convergence.

`solve_snapshot(net, load_p, load_q, sgen_p, sgen_q, rating_ratio=None)` solves one moment given as values rather than as a study case (each load's and generator's P and Q by the net's own ids, optionally each line's rating as a multiple of winter), with the same power flow and tap settling; both it and the cases go through `_solve_with`, which puts the net's inputs back. It returns the case results plus each branch's MW, for the measured year (step 1).

**The measured year** (`timeseries.py`): `python -m gridify_optimizer.timeseries <flows folder> <out.npz> [published|screened|unity] [first last]`. The flows folder is the pipeline's `nged_flows` asset. `published` takes NGED's reactive power as published, `screened` substitutes it where the screen flags it implausible (README register), and `unity` sets it to 0 (a diagnostic). A year takes about 16 minutes on one core; never split it, since tap positions carry from one half-hour to the next. The report: `docs/reports/measured-year-2024/report.md`.

After the call, `net.res_*` hold the **worst-case envelope** across cases (highest loading; the voltage furthest from 1.0 pu), and `metrics["envelope_case"]` says which case set each element's figure. A network without `min_scale` and `summer_ratio` is studied at winter peak only; without `gsp_export_limit_mw` against an unlimited slack.

## The plan years (`years.py`)

```
simulate(connections, params, view_year=, years=PLAN_YEARS, net_factory=, progress=, on_year=, cache=) -> PlanResult
```

Each year in `PLAN_YEARS` (2026..2035) is solved by `evaluate_year`: a fresh net from `net_factory`, demand grown by `network.grow_for(net, params, year)`, every connection whose `year` has arrived connected (`inject_connection`: an `sgen` at unity or a fixed power factor, or a voltage-controlled `gen`), then `feasibility`. A `YearResult` carries the year's growth, who is energised, whether it converged, every loading and voltage (worst of the cases, with `envelope_case`), the GSP's export, import and limit, and `violations`: every breach in every case.

`year_order(view_year)` solves the year in view first; `on_year` is called as each lands so a caller can publish partial results. `cache` (a mapping the caller keys by snapshot and engine) holds years by `year_signature` (the profile and the connections in service that year), so an edit re-solves only the years it changes.

## The comparison (`diff.py`)

`diff_plans(base, head)` compares every year both runs solved: the worst line and transformer, the voltage range, the GSP export, the breaches head adds and clears (by type, element and case), lines and transformers that newly overload or clear, the biggest loading movers (`_TOP` per kind, plus every crossing of 100%), and who is in service on one side only. Pure: no pandapower.

## Demand growth (`network.grow_for`)

The built-in grid grows **per primary substation** on NGED's DFES 2025 winter-peak power projections (`data/nged/dfes.json`, one Electricity Supply Area per primary, four scenarios, every year to 2040): each load's multiplier for a year is its supply area's projection divided by its 2025 value (`config.DFES_BASE_YEAR`), so a plan year is NGED's own figure for that substation (`nged._growth_curves`, `network.per_load_growth`). `FORECASTS` maps the planner's profiles to the DFES scenarios (Standard = Holistic Transition, High = Electric Engagement, Low = Counterfactual). Connections with no supply area (customer sites, the BSP aggregates) follow their LTDS five-year forecast and then hold (`forecast_ltds_only`). `custom` grows uniformly on the GROWTH_2030 / GROWTH_2035 anchors, interpolated. Only demand grows: no generation is pre-loaded.

## Tests

```bash
uv run pytest -q   # 4 workers (pytest-xdist)
```

Grid-agnostic: fixtures come from `build_base_net()` through `tests/_grid.py` (`stiff_bus`, `weak_buses`), never hardcoded bus ids; NGED's data rules live in `tests/test_nged.py`.
