# gridforge_optimizer

The deterministic connection-queue engine behind GridForge. It's a standalone, tested Python package, used by the Dagster pipeline and the FastAPI service through a local editable path dependency.

It decides **which projects connect, in what order and in which phase**. Every decision is gated by pandapower AC power flow in two planning study cases plus the GSP export limit. It then solves **every year of the plan** as it would stand, with any planned maintenance, measures **what it would take** to unblock the projects it defers, and diffs two plans.

```python
from gridforge_optimizer import Candidate, OptimizeParams, evaluate_years, optimize, suggest_unblock

params = OptimizeParams(scenario="ht")
cands = [Candidate(request_id="A", bus_id=19, technology="battery", rating_mw=50,
                   readiness_score=0.3, strategic_fit=0.78, commissioning_year=2027)]
result = optimize(cands, params)
for q in result.queue:
    print(q.rank, q.request_id, q.status, q.recommended_year, q.reason and q.reason.message)
result.years = evaluate_years(result, cands, params, view_year=2028)
print(result.years["2028"].worst_line_loading_pct)
print(suggest_unblock(cands, params, result))
```

Nothing in `optimize()`, `evaluate_years()` or `suggest_unblock()` makes a network call, so the same inputs always give the same answer. That purity is what the caching leans on: `optimize(..., trial_cache=my_dict)` memoises every trial's outcome by (phase, the projects accepted before it, the project), so a re-run after one project is added solves only the trials whose state changed and still returns exactly the full answer; `progress=callback` reports the stage and fraction as the run advances; `net_factory=fn` supplies the base network (default: the bundled NGED build), so the same algorithm runs on any grid. `evaluate_years(..., cache=my_dict)` does the same for plan years: each year is keyed by `year_signature` (demand, the projects in service, reinforcements, that year's windows, earlier works that leave a change), so after an edit only the years whose signature changed are solved again.

---

## Modules

| Module | Responsibility |
|---|---|
| `nged.py` | Builds the real **NGED Bicker Fen** network from bundled open data (`data/nged/`), or from raw tables passed in (`tables=`), for the current or the reconstructed previous LTDS edition (`edition=`). Transformers carry their LTDS tap ranges; the existing fleet is sited at its named substations. `build_nged_net()` gives today's network; `nged_model()` the geolocated model for the map; `nged_candidates()` the optional-project registry (ECR + GSP-embedded TEC); `gsp_boundary()` the export limit plus transmission context. |
| `editions.py` | `edition_changeset(tables)`: what changed between NGED's previous LTDS edition and this one (rows, model, physics). `diff_ecr_editions(prev, cur)`: site-level changes between two fetches of the Embedded Capacity Register. Pure. |
| `cim.py` | `export_cgmes(net, model, snapshot_id)`: the network as CIM/CGMES 2.4.15 RDF/XML (EQ, TP, SSH, GL profiles), deterministic ids; `cgmes_zip_bytes` / `write_cgmes_zip`. Round-trips through pandapower's `from_cim` (tested). |
| `network.py` | pandapower helpers: `build_base_net`, demand growth (`apply_growth`, `per_bus_growth`, `grow_demand`, `interpolate_growth_for_year`), statutory `voltage_limits`, tap regulation inside `_solve`, per-case generation `dispatch_for_case`, `inject_sgen`/`drop_sgen`, **`feasibility`** (both study cases + GSP limit), `n1_screen` (with an optional seasonal `rating_ratio`), outage appliers (`OUTAGE_APPLIERS`), per-element results, `apply_reinforcement`. |
| `greedy.py` | `optimize`: intake, ranking, the per-phase greedy feasibility loop, recommended years. |
| `years.py` | `evaluate_years` / `evaluate_year`: every plan year (`PLAN_YEARS`, 2026..2035) solved as a fixed plan, with its works windows and earlier repowers; `year_order`, `energisation_years`. |
| `maintenance.py` | Planned works: `WORKS` (maintenance, replacement, repowering), `REPOWERERS`, `apply_works_after`, `study_windows` (combined windows, verdict, bounded curtailment search, N-1 during the window). |
| `demand.py` | The demand side: `regions_of(net)` (the demand groups tagged on `net.load`), `assess_demand(net, year, n1_violations)` (per group per year: demand, firm headroom, P2/8 class, N-1 stranding, voltage, ≈ demand room) and the alert registry `ALERT_CHECKS`. A simplified P2/8-style check. |
| `suggest.py` | `suggest_unblock`: "what would it take", measured by re-solving. |
| `diff.py` | `diff_results(base, head, works_on_base=)`: the consequence diff between two plans (queue, 2030/2035 phases, every plan year via `diff_years` / `diff_year`, planned works via `diff_works`). Pure. |
| `readiness.py` | `score_from_checklist`: the deterministic, auditable readiness rubric. |
| `scoring.py` | `grid_need_from_solved`: the "first *needed*" signal. |
| `types.py` | Pydantic models: `Candidate`, `OptimizeParams` → `QueueItem`, `PhaseResult`, `YearResult` (`.regions`: `RegionYear`, `.alerts`: `Alert`), `OptimizeResult` (`.years`), `Reason`, `Outage`, `OutageStudy` (+ `Curtailment`, `N1During`, `VERDICT_SEVERITY`), `Reinforcement`, `Suggestion`. |
| `config.py` | Every tunable: limits, growth pathways, weights, caps, LLM settings. |
| `llm.py` | The only module that calls out (OpenRouter): optional narration (`justify`, `narrate_diff`, `narrate_suggestion`) that phrases figures the engine already computed. Empty if no `OPENROUTER_API_KEY`. |

---

## The algorithm

```
optimize(candidates, params, reinforcements):
  valid    = auto_accept, bus exists in the network, 0 < rating ≤ MAX_CONNECTION_MW
             (import-only techs: 0 < import_mw ≤ MAX_CONNECTION_MW, rating may be 0)
  rejected = the rest  → queue as "Rejected" with a plain-English reason

  need_net = grow(build_base_net(), 2035)          # one solve: the "first needed" signal per bus
  rank_score = W_READINESS·readiness + W_NEED·need + W_STRATEGIC·strategic_fit
  ranked = valid by rank_score desc (tie-break: readiness desc, rating asc, id)

  accepted = []
  for phase in (2030, 2035):
      net = grow(build_base_net(), phase)          # demand only — nothing is pre-loaded
      inject every already-accepted project
      for c in ranked not yet accepted:
          trial-inject c; ok, reason = feasibility(net)
          ok → accepted (Phase1 / Phase2)    else → roll back, keep reason, retry next phase

  each accepted project gets recommended_year = clamp(requested year, phase window)
```

`reinforcements` (optional) are applied to every network the run builds, so a lever tried on a branch is measured against the whole queue. There is one mode: the old single-year run (`OptimizeParams.study_year`) is gone; the years are a separate, fixed-plan step.

The network is built **once per phase**. Each trial is an `sgen` inject, and a failed one is rolled back with `drop_sgen` and its tap positions restored (a rejected trial leaves no trace, so the greedy path never depends on solve history). Generation is injected as **PQ** (`create_sgen`, not a voltage-regulating `create_gen`), so voltage problems from export show up instead of being regulated away. Power flows are warm-started from the previous solution (`init="results"`), which roughly halves the Newton iterations; the N-1 screen keeps the intact tap settings. On the Bicker Fen network a full run of the 20-project registry takes about 14 s cold; lightsim2grid was measured and gave no gain at this size, so it is not a dependency.

### Feasibility (`network.feasibility`)

Each call solves **every study case** and returns the first limit breached:

| Case | Load scaling | Generation (`GENERATION_FACTORS`) | Line ratings |
|---|---|---|---|
| `winter_peak` | as grown by the demand pathway | solar 0 · wind 0 · battery and hybrid **−1** (charging at `import_mw`) · demand and electrolyser **−1** · other 1 | winter (`max_i_ka`) |
| `summer_min` | per-load `min_scale` (LTDS minimum-demand factor ÷ diversity; **not grown**) | everything at 1 (full export) · demand and electrolyser **−0.5** | × per-line `summer_ratio` (LTDS summer ÷ winter) |

Technologies: `IMPORT_ONLY_TECHS` (`demand`, `electrolyser`) export nothing; they draw `import_mw` at winter peak and `DEMAND_PROJECT_MIN_FACTOR` (0.5, a planning assumption) of it at summer minimum. A `hybrid` (solar + battery) is dispatched like a battery. Anything without an entry in `GENERATION_FACTORS` (gas, gas engines, biomass, 'other') takes `GENERATION_FACTOR_DEFAULT`: firm in both cases.

Before each case is judged, `_solve` lets the on-load tap changers settle: every transformer with a tap range moves its tap (HV winding, GB convention: a lower tap raises the LV voltage) until its LV busbar is within `OLTC_DEADBAND_PU` of `OLTC_SETPOINT_PU` or at an end stop, in at most `OLTC_MAX_PASSES` power flows. Tap positions persist on the net, so a trial injection normally needs one solve.

Checks, in order:
1. Every bus inside its statutory band (`VOLTAGE_BANDS`: ±10% at 132 kV and above, ±6% below).
2. Line and transformer loading ≤ 100%.
3. **GSP export** at its worst case ≤ `net["gsp_export_limit_mw"]`.

Each failure is reported as a `Reason` (`voltage` / `line` / `trafo` / `gsp` / `non_convergent`) carrying the element, the value, the `limit` breached and the `case` it failed in.

`n1_screen(net)` takes every in-service line and transformer at or above `N1_MIN_KV` out in turn at winter peak and reports overloads, band breaches and islanded demand (≥ `N1_ISLAND_MIN_MW`). `optimize` runs it on each phase's final state and puts the findings on `PhaseResult.n1_violations`; it is not a connection gate.

After the call, `net.res_*` hold the **worst-case envelope** across cases: highest loading, and the voltage furthest from 1.0. So the heat-map helpers (`line_loadings`, `bus_voltages`, `overloaded_line_ids`, …) report the binding case.

A network without `min_scale`, `summer_ratio` or `gsp_export_limit_mw` is studied at winter peak against an unlimited slack. That keeps the engine grid-agnostic.

### Every year of the plan (`years.py`)

```
evaluate_years(result, candidates, params, scheduled=, outages=, reinforcements=,
               view_year=, years=PLAN_YEARS, net_factory=, progress=, on_year=)
```

After `optimize` has decided the queue, each year in `PLAN_YEARS` (`PLAN_START_YEAR`..`PLAN_END_YEAR`, 2026..2035) is solved as a **fixed plan** by `evaluate_year`:
- demand grown by `network.interpolate_growth_for_year(year, growth_2030, growth_2035)`: 1.0 in 2026, linear to the 2030 multiplier, then linear to the 2035 one, with the per-bus shape of the horizon the year falls in;
- the branch's reinforcements applied, then what every works window of an EARLIER year leaves behind (`maintenance.apply_works_after`: a repowered element);
- every accepted project whose energisation year has arrived injected (`energisation_years`: the operator's `scheduled` year, else the recommendation);
- both study cases, then that year's works windows (`maintenance.study_windows`, with the N-1 screen passed in when the year runs it), then the N-1 screen.

It returns `{str(year): YearResult}`: a `PhaseResult` plus `year`, `growth`, `energised`, `trafo_loading`, `outage_studies`, and the demand side, `regions` and `alerts` (`demand.assess_demand`, below). It never changes who connects. `year_order(view_year)` solves the year in view first, then 2030 and 2035, then the rest; `on_year` is called as each lands so a caller can publish partial results, and `progress` reports the fraction within this step.

### The demand side (`demand.py`)

Customers are what the network is for, so every plan year also judges each **demand group**. `nged._add_loads` tags every load with the LTDS Table 3 row it came from (`net.load` columns `region_id`, `region`, `bsp`, `primary`, `firm_mva`, `firm_mw`, `peak_mw`); `demand.py` reads only those columns, so any net that carries them has regions and one that does not simply reports none. A region is one live Table 3 row: a primary substation, or a BSP's own 33 kV group (one row per grid transformer), exactly as NGED publishes demand and firm capacity.

`assess_demand(net, year, n1_violations)` runs at the end of `evaluate_year`, on the solved intact envelope, and returns `(list[RegionYear], list[Alert])`. Per region:
- `demand_mw`: the group's own peak this year (`peak_mw`, the row's LTDS maximum demand with no diversity, times the year's growth) plus what plan projects on its buses draw at winter peak (demand connections, charging batteries; the existing fleet is excluded, its import is already in LTDS demand). `modelled_mw` is the same on the power flow's after-diversity basis.
- `firm_mw` (LTDS "Firm Capacity of Substation", read as MVA and converted at the row's power factor; 0 when NGED publishes 0), `headroom_mw = firm_mw - demand_mw`, and `p2_class` from `config.P2_8_CLASSES` by `demand_mw`.
- `n1_at_risk_mw` / `n1_outage`: the most of the group's demand one 132 kV backbone outage cuts off, from the N-1 screen's islanded violations (each now carries `islanded_bus_ids`).
- `voltage_violation_bus_ids`, `worst_vm_pu`, `worst_vm_limit_pu`: the group's load buses against their statutory band in the intact envelope.
- `demand_room_mw` (≈, first-order): the smaller of the firm headroom (when firm capacity is published) and the spare winter-peak capacity of the in-service transformers feeding the group's buses (one extra winter-peak solve per year via `network.solve_case`, taps left as found). No power-flow probe adds load; say ≈ when showing it.

`ALERT_CHECKS` is the alert registry, one function per check, each `(RegionYear, year) -> Alert | None`:

| Check | Kind | Level |
|---|---|---|
| `_firm_alert` | `firm_capacity`: demand above firm capacity (skipped for class A/B groups with no firm capacity published) | `breach` when the shortfall exceeds what P2/8 lets wait after a first circuit outage (`p2_loss_allowed`: class C max(12 MW, 1/3 of the group), D 20 MW, E/F none), else `warn` |
| `_n1_alert` | `n1_stranded`: an N-1 outage cuts off at least `N1_ISLAND_MIN_MW` in a class C+ group | `breach` above `p2_loss_allowed`, else `warn` |
| `_voltage_alert` | `voltage`: load buses outside the statutory band with the network intact | `breach` |
| `_headroom_alert` | `headroom`: firm headroom positive but under `HEADROOM_WARN_FRACTION` (10%, assumed) of firm capacity | `warn` |

A new alert is one function plus one entry. Each `Alert` carries `kind`, `level`, `region_id`, `year`, `value`, `limit` and a plain-English `message` restating those figures. **This is a simplified P2/8-style check**: restoration times, switching, transfer capacity and second circuit outages are not modelled, and everything is MW (no customer counts in the open data). Cost on Bicker Fen: about +0.07 s per year on a ~0.7 s `evaluate_year`, mostly the extra winter-peak solve; the N-1 screen itself is unchanged.

### Planned works (`maintenance.py`)

An `Outage` is a works window: `element_kind` (`line`, `trafo`, or `gen` for an existing generator, matched on `sgen.fleet_id`, the model id `EX-30xx`), `season`, `year`, `weeks`, `kind` (`outage` = out of service, `derate` = rating or output × `OUTAGE_DERATE_FACTOR`, 0.5) and `work`. `OUTAGE_APPLIERS` (`network.py`) maps each element kind to a function that applies it and returns an undo, so a new kind of target is one entry.

`maintenance.WORKS` is the registry of work types (a new one is one `WorkSpec` entry: how the window is applied, what it leaves behind, how that reads):

| `work` | During the window | After it |
|---|---|---|
| `maintenance` (default) | out, or derated (`kind`) | as it was |
| `replacement` | fully out | like-for-like: as it was (recorded only) |
| `repowering` | fully out | from the **following** year, `repower`: `uprate` (rating × `factor`, 1 < factor ≤ 4; impedance in ohms unchanged, via `REINFORCERS` / `_scale_rating`) or `add_parallel` (a parallel circuit; a second identical unit for a generator). A generator's uprate scales its export rating and import. |

Repowering changes the years after the window (`evaluate_year` applies it via `REPOWERERS`), which is intended: it is a planned asset change on a branch. **The queue run (`greedy.optimize`) does not see it**: who connects is decided on the network as it is plus the branch's reinforcements. That is a stated simplification: the queue has no year axis inside a phase, so a dated asset change cannot be placed in it honestly; to let the queue count an upgrade, add it as a reinforcement.

Windows with the same season and year are **studied together** (all applied at once; `weeks` is not placed in calendar weeks, so this is the conservative reading); each `OutageStudy` lists the others in `with_ids`. Each group gets a `verdict`:

| `verdict` | When |
|---|---|
| `feasible` | no limit breached in any of the season's cases |
| `curtailment` | a thermal, GSP or overvoltage limit is breached, no demand is stranded, and constraining generation clears it: `curtailment` = `[{id, name, mw, case}]`, `curtailed_mw` = the most in one case |
| `demand_at_risk` | demand stranded on an island (`_islanded_mw` ≥ `N1_ISLAND_MIN_MW`), or demand at load buses left outside the voltage band that curtailment does not clear: `demand_at_risk_mw` |
| `not_feasible` | a limit stays breached after the curtailment search, or no convergence |

The curtailment search is a **first-order planning estimate, not an optimal dispatch**: generators exporting in the binding case (the existing fleet and accepted projects in service that year) are constrained one at a time, electrically nearest the binding element first (hops; the biggest exporter first for the GSP), re-solving each time; a step that eases the breach by less than `CURTAIL_MIN_RELIEF` of its excess is put back; the last generator is bisected. At most `CURTAIL_MAX_SOLVES` (8) extra solves per case. Reported MW are rounded up. An undervoltage is not something less generation fixes, so it is never curtailed.

When the year runs the N-1 screen, the window gets `n1_during`: the 132 kV backbone screened with the window in place, in its cases and season's ratings (`n1_screen(..., rating_ratio=)`). `findings` counts second faults that add to what the window does alone (a breach on another element, or ≥ 1 MW stranded beyond the window's own); `second_fault_at_risk_mw` is the demand the worst one strands. Informational, like the year's own screen. Measured on Bicker Fen: ~50 ms per window without N-1 (~75 ms when curtailment is searched), plus ~0.6 s per case for the N-1 during it, so the whole backbone is screened rather than a neighbourhood.

`study_windows` leaves the net as found (elements, generator ratings, tap positions): a year's own results never depend on whether a window was studied in it. `message` is a plain-English summary naming elements by id.

`config.SEASON_STUDY` picks the case(s) and line ratings per season:

| Season | Cases | Line ratings |
|---|---|---|
| Winter | `winter_peak` | winter |
| Spring, Autumn | `winter_peak` and `summer_min` | `intermediate_ratio` (LTDS Intermediate Warm ÷ winter, built in `nged.py`) |
| Summer | `summer_min` | `summer_ratio` |

Besides the verdict, an `OutageStudy` carries the cases studied, `ok` (no breach before curtailment), the first breach per case, worst loadings, GSP export and `after`. Like N-1, works windows are reported per year and are **never a connection gate**.

### What would it take (`suggest.py`)

`suggest_unblock(candidates, params, base, max_suggestions, *, request_id=None, net_factory=build_base_net)`. For the highest-ranked deferred projects (`MAX_SUGGESTIONS`), or only `request_id` when given, each lever is applied and the trials re-run on `net_factory`'s network (the API passes one with the branch's simulated reinforcements) to measure `freed_mw_2030/2035`:

- **`line` / `trafo` binding** — chain `add_parallel` reinforcements (halves impedance, doubles rating) up to `MAX_REINFORCE_STEPS`. If a voltage limit takes over, hand off to the voltage lever. If the GSP limit takes over, say so.
- **`voltage` binding** — re-inject the project absorbing reactive power at 0.98/0.95/0.90 pf, else reinforce one upstream circuit.
- **`gsp` binding** — `Reinforcement(kind="gsp")`, i.e. one more supergrid transformer (+`gsp_sgt_mw`). Its caveat flags it as transmission works.

Freed MW is first-order: the knock-on of a freed project blocking a later one isn't modelled, so the UI shows it as "≈". The caveats say these are feasible levers, not least-cost designs.

### The consequence diff (`diff.py`)

`diff_results(base, head, *, works_on_base=None) -> ConsequenceDiff`, pure (no I/O, no pandapower). It reshapes what the two results already hold:

- **`projects`** — each project's move (`accelerated`, `slipped`, `moved_up`/`moved_down`, `added`, `dropped`), with head's reason.
- **`headline`** — MW connected by 2030 and 2035 (the phases), connected/deferred counts, movers, and `n_works_worse` / `n_works_better`.
- **`phases`** — the 2030/2035 phase deltas (worst line/transformer, voltage band, lines newly over 100% or cleared, top 10 line movers).
- **`years`** — `{year: YearDelta}` for every plan year solved on both results (`OptimizeResult.years`; `diff_years` / `diff_year`): worst line and transformer loading base/head/delta, min/max voltage delta, peak GSP export base/head/delta (with the limit), N-1 finding counts and the findings new on head or cleared (`n1_new` / `n1_cleared`, by lost element + breached element), lines AND transformers newly over 100% or cleared, the top 10 line and transformer movers (`LoadingDelta`: `element_id`, `base_pct`, `head_pct`, `delta`, `crossed`, plus any crossing beyond the top 10), and the projects in service on only one side.
- **`works`** — one `WorkDelta` per head window (`diff_works(on_main, on_branch)`): its verdict and curtailed / at-risk MW on head's plan against the same window (by outage id and year) studied on base's plan, `change` (`worse` / `better` / `unchanged` / `unstudied`; a heavier burden under the same verdict counts as worse, ordered by `VERDICT_SEVERITY`) and a plain-English `consequence` ("Feasible on main, but needs 40.0 MW of curtailment on this branch."). The base-plan study is the caller's: the API solves head's windows on base's energised plan (base's projects, schedule and reinforcements; `evaluate_year(..., n1=False)` for each year with a window) and passes them as `works_on_base`. Without it, head's windows are compared with base's own windows of the same id.

---

## Demand growth (`network.per_bus_growth`)

A NESO FES 2025 pathway (`FORECASTS`: `ht` default, `ee`, `he`, `fb`) sets the network-wide multiplier for 2030 and 2035. Growth is then spread per load so the **total equals the pathway exactly**, while individual buses differ:

```
w = β_type · (1 + α·(2·hash01(scenario, horizon, bus) − 1)) · (1 + γ·(hops/hops_max − 0.5)) · hotspot
factor = 1 + (m − 1)·w / w̄            # w̄ = load-weighted mean of w
```

It's deterministic in `(scenario, horizon, network)`. `β_type` separates residential from industrial loads only when the network labels load types. NGED's LTDS doesn't, so on this network the spread comes from the seeded heterogeneity, the distance from the GSP and the hotspots.

---

## Readiness rubric (`readiness.py`)

| Milestone | Weight | Levels → credit |
|---|---|---|
| land rights | 0.30 | secured 1.0 · in_progress 0.5 · none 0 |
| planning consent | 0.30 | granted 1.0 · submitted 0.5 · pre_application 0.1 · none 0 |
| connection agreement | 0.20 | signed 1.0 · offered 0.5 · none 0 |
| financing | 0.10 | committed 1.0 · in_progress 0.5 · none 0 |
| commissioning timeline | 0.10 | ≤2 yrs 1.0 · ≤5 yrs 0.6 · else/unknown 0.3 |

How the registry's facts map onto it:
- ECR *accepted to connect* → connection agreement **signed**.
- TEC *awaiting consents* → planning **submitted**.
- Facts the source doesn't publish → no credit, and the rationale says so.

---

## Config (selected)

```python
VOLTAGE_BANDS                       = ((132, 0.90, 1.10), (1, 0.94, 1.06))   # statutory, by level
OLTC_SETPOINT_PU / OLTC_DEADBAND_PU = 1.0 / 0.01 ; OLTC_TAP_STEP_PERCENT = 1.25 (assumed)
GENERATION_FACTORS                  = winter: solar 0, wind 0, battery/hybrid -1, demand/electrolyser -1 ;
                                      summer: all 1, demand/electrolyser -DEMAND_PROJECT_MIN_FACTOR
GENERATION_FACTOR_DEFAULT           = firm (1) in both cases: gas, gas engines, biomass, other
IMPORT_ONLY_TECHS / DEMAND_PROJECT_MIN_FACTOR = ("demand", "electrolyser") / 0.5 (assumed)
PLAN_START_YEAR / PLAN_END_YEAR     = 2026 / 2035
SEASON_STUDY                        = season -> study case(s) + line rating column (see above)
OUTAGE_DERATE_FACTOR                = 0.5
CURTAIL_MAX_SOLVES / CURTAIL_REFINE_STEPS / CURTAIL_MIN_RELIEF = 8 / 3 / 0.01   # window curtailment search (first-order)
N1_MIN_KV / N1_ISLAND_MIN_MW        = 132 / 1.0
P2_8_CLASSES                        = group MW: A <=1, B <=12, C <=60, D <=300, E <=1500, F above (ENA EREC P2/8 Table 1)
HEADROOM_WARN_FRACTION              = 0.10     # firm-headroom warning margin (assumed)
LINE_LOADING_MAX_PCT / TRAFO_...    = 100 / 100
MAX_CONNECTION_MW                   = 300      # intake plausibility (ECR has 248 MW accepted at 132 kV)
W_READINESS / W_NEED / W_STRATEGIC  = 0.5 / 0.35 / 0.15
GROWTH_2030 / GROWTH_2035           = 1.08 / 1.35   # FES 2025 Holistic Transition
MAX_SUGGESTIONS / MAX_REINFORCE_STEPS = 5 / 4
```

NGED-specific values live in `nged.py`: `DEMAND_DIVERSITY = 0.55`, `GSP_BOUNDARY` (2 × 263.5 MW SGT export limit, with the source resource id), `TRANSMISSION_PROJECTS` and `ECR_MIN_EXPORT_MW = 1`.

---

## Tests

```bash
cd packages/optimizer && uv run pytest -q     # 79 tests on 4 workers (pytest-xdist); ~2 min
```

The N-1 screen is stubbed in every test except the one that tests it (`conftest.py`, marker `n1`): it costs ~2 s per phase inside `optimize()` and would otherwise dominate the suite.

Tests are **grid-agnostic**. `tests/_grid.py` derives every fixture from the network `build_base_net()` returns:
- a stiff bus, the weakest buses, and a saturating queue sized from the local circuits' thermal rating (not from any policy cap);
- no hard-coded bus ids.

What they cover:
- the CGMES export: well-formed, fully linked, deterministic, and re-imported by pandapower to the same network and power flow (`test_cim.py`);
- the trial cache is exact and saves solves; progress is reported in order (`test_cache.py`);
- statutory voltage bands by level, tap-changer regulation, per-case dispatch, fleet siting and the N-1 screen (`test_physics.py`);
- feasibility and the worst-case envelope;
- the summer-minimum case raising export;
- the GSP limit binding, and an SGT relieving it;
- greedy outcomes and determinism;
- recommended years;
- the plan year by year: growth interpolation, year order, energisation from the schedule, demand connections, and planned outages per season, kind and year (`test_yearly.py`);
- works windows: repowering changes only the years after the window, replacement and maintenance leave them as they were, combined windows, each verdict (feasible, curtailment that really holds the limits, demand at risk) and the N-1 during a window (`test_maintenance.py`);
- the demand side: regions cover every load once, demand grows with the years, headroom = firm - demand, P2/8 class bands, a starved firm capacity raising the alert, project demand counted in its group, N-1 stranding attributed to the islanded group, and the alert registry (`test_demand.py`; NGED rows in `test_nged.py`);
- reinforcement, suggestions and the diff;
- the readiness rubric.

`test_nged.py` adds the NGED data rules: removed equipment is excluded, every live MW of demand is modelled, and nothing from the registry is pre-loaded.
