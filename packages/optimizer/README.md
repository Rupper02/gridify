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
| `nged.py` | Builds the real **NGED Bicker Fen** network from bundled open data (`data/nged/`), or from raw tables passed in (`tables=`), for the current or the reconstructed previous LTDS edition (`edition=`). Transformers carry their LTDS tap ranges; the existing fleet is sited at its named substations. `build_nged_net()` gives today's network; `nged_model()` the geolocated model for the map; `nged_candidates()` the optional-project registry (ECR + GSP-embedded TEC); `gsp_boundary()` the export limit plus transmission context; `builder_assumptions()` what it had to assume and `PLANNING_ASSUMPTIONS` the register's planning assumptions as records. Behind `sources.NgedSource`, unchanged. |
| `editions.py` | `edition_changeset(tables)`: what changed between NGED's previous LTDS edition and this one (rows, model, physics). `diff_ecr_editions(prev, cur)`: site-level changes between two fetches of the Embedded Capacity Register. Pure. |
| `sources.py` | **Where a grid comes from.** The `GridSource` Protocol (`build_net`, `model`, `candidates`, `boundary`, `fingerprint`, `assumptions`, `capabilities`) and the `SOURCES` registry: `nged` (`NgedSource`, the builder below behind the seam), `cgmes` (a zip of CGMES profiles through pandapower's importer), `pandapower_json`, `matpower` (`.mat`). The grid-agnostic steps every import takes: `normalise_net` (keeps what the file states: its infeed, voltage-controlled units, fixed ratios; records every gap, never fills one), `apply_import_meta` (limits the operator enters), `inspect_net` (what the file did not carry, stated), `validate_net` (a `ValidationReport`). `source_from_file` picks the kind by extension; `default_source()` is NGED. See *Adapting a grid*. |
| `geometry.py` | Where buses sit: `interpolate_positions` (harmonic interpolation between the buses a source places), `synthetic_positions` (a deterministic Kamada-Kawai layout for a file with no coordinates; the model is then `crs: synthetic`). |
| `gridmodel.py` | `model_from_net`: the geolocated `GridModel` (buses, lines, transformers, loads, the existing fleet, demand groups when the net carries them) shaped the same way for every source; `fleet_of` reads a net's existing generators. |
| `cim.py` | `export_cgmes(net, model, snapshot_id, meta)`: any network (with a `substation` column on its buses) as CIM/CGMES 2.4.15 RDF/XML (EQ, TP, SSH, GL profiles), deterministic ids; `CgmesMeta` names the authority and regions (NGED's is `nged.NGED_CGMES_META`); generating units carry a `gridforge.tech=` tag so battery / hybrid round-trip; `cgmes_zip_bytes` / `write_cgmes_zip`. Round-trips through pandapower's `from_cim` (tested) and re-imports as a project through `sources.cgmes_source`. |
| `network.py` | pandapower helpers: `build_base_net`, demand growth (`grow_for`, `per_load_growth` on the network's published curves, `apply_growth`, `interpolate_growth_for_year` for `custom`), statutory `voltage_limits`, tap regulation inside `_solve`, per-case generation `dispatch_for_case`, `inject_project`/`drop_project` (a project as its `Control` runs it: an `sgen` whose reactive power follows its output per case, `_follow_power_factor`, or a voltage-controlled `gen`), `inject_sgen`, **`feasibility`** (both study cases + GSP limit), `n1_screen` (with an optional seasonal `rating_ratio`) over `n1_elements` + `outage_results` (the single-outage iterator the contingency ranking shares), outage appliers (`OUTAGE_APPLIERS`), per-element results, `apply_reinforcement`. |
| `greedy.py` | `optimize`: intake, ranking, the per-phase greedy feasibility loop, recommended years. |
| `years.py` | `evaluate_years` / `evaluate_year`: every plan year (`PLAN_YEARS`, 2026..2035) solved as a fixed plan, with its works windows and earlier repowers; `year_order`, `energisation_years`. |
| `maintenance.py` | Planned works: `WORKS` (maintenance, replacement, repowering), `REPOWERERS`, `apply_works_after`, `study_windows` (combined windows, verdict, bounded curtailment search, N-1 during the window). |
| `demand.py` | The demand side: `regions_of(net)` (the demand groups tagged on `net.load`), `assess_demand(net, year, n1_violations)` (per group per year: demand, firm headroom, P2/8 class, N-1 stranding, voltage, ≈ demand room) and the alert registry `ALERT_CHECKS`. A simplified P2/8-style check. |
| `windows.py` | `best_windows`: a work's window studied in every (year, season) against the plan that year, ranked (two passes: N-1 for a shortlist only). |
| `suggest.py` | `suggest_unblock`: "what would it take", measured by re-solving. `phase_net` and `discover_chain`: the plan's network in one phase and the parallel-circuit chain for one project, the public seams the connection-options study reuses. |
| `studies.py` | `STUDIES`, the registry of deterministic analyses an agent or the API runs on a plan: `hosting_capacity` (MW of new export or import per bus before the first limit, by bisection), `contingency_ranking` (every single outage at 33 kV and above in both cases, scored and ranked), `structural_weak_points` (bridges and busbars whose loss islands demand, no power flow), `tap_margin` (regulated transformers at a tap stop), `gsp_margin_by_year` (from the plan years), `data_quality` (what the builder assumed), `connection_options` (how one project could connect: what its busbar takes of it, the parallel-circuit chain, the higher-voltage busbars that take its full MW), `best_window` (the windows for a planned work, ranked). `run_study`, `chunk_study`, `merge_chunks`; every result says what it did not study. |
| `analysis.py` | What limits a plan, with no solve: `limits(result, years, model, ratings)` → the **binding set** (`ElementBinding`: the envelope per plan year with its case, the first near and breach years, the headroom in MW at the worst year, the projects deferred on it, the N-1 pairs that breach it), the deferrals' **chains**, the N-1 rows folded into **clusters** by cause, the works verdicts; `run_digest(...)` → the ≈2 kB `RunDigest` the note is written from. |
| `sensitivity.py` | DC power transfer factors on a solved case (`thermal_headroom`, `rank_buses`): first-order MW room per bus before a branch binds, 0.1 s for the whole network; the studies rank buses with it and confirm with AC. |
| `naming.py` | What elements are called: `element_names` / `name_model` (a bus's `place`, a line's `display_name` by the places it joins, parallel circuits numbered, a transformer's by its substation and ratio, parallel units numbered; `model_from_net` fills them), `name_text` ("lines 0 and 1" in any text named, the id kept in brackets) and `name_payload` (the same through a tool's payload; an N-1 `outage_name` by its type and id). The API names every agent tool output and narration summary with it. Pure. |
| `diff.py` | `diff_results(base, head, works_on_base=)`: the consequence diff between two plans (queue, 2030/2035 phases, every plan year via `diff_years` / `diff_year`, planned works via `diff_works`). Pure. |
| `findings.py` | `extract_findings(result, scheduled)`: every problem a plan carries as one flat list of `Finding`s with a stable, value-independent `fingerprint` (overloads, voltage breaches, the GSP margin, N-1 findings, demand alerts, works verdicts, deferred and rejected projects, schedules against the recommendation, non-convergent years); `EXTRACTORS` is the registry; `against_recommendation`. Pure. |
| `gate.py` | `merge_verdict(head, base, diff, fresh=…)`: may this branch become the plan of record? A pure policy over two results: blocks what the branch introduces or worsens in any plan year, warns on the rest, reports what the parent already carries as context. `MERGE_CHECKS` is the registry; every level lives in `config.MERGE_GATE_LEVELS`. Never solves. |
| `readiness.py` | `score_from_checklist`: the deterministic, auditable readiness rubric. |
| `scoring.py` | `grid_need_from_solved`: the "first *needed*" signal. |
| `types.py` | Pydantic models: `Candidate`, `OptimizeParams` → `QueueItem`, `PhaseResult`, `YearResult` (`.regions`: `RegionYear`, `.alerts`: `Alert`), `OptimizeResult` (`.years`), `Reason`, `Outage`, `OutageStudy` (+ `Curtailment`, `N1During`, `VERDICT_SEVERITY`), `Reinforcement`, `Suggestion`, `Finding`, `GateFinding`, `MergeVerdict` (`SEVERITY_ORDER`), `StudyItem`, `StudyResult`, `ModelAssumption`, `GridModel` (+ `ModelBus` … `ModelGenerator`, `crs`), `ImportMeta`, `ValidationReport`. `YearResult.converged` says whether the year's intact power flow converged. |
| `config.py` | Every tunable: limits, growth pathways, weights, caps, the OpenRouter base URL. |

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

The network is built **once per phase**. Each trial is an `sgen` inject, and a failed one is rolled back with `drop_project` and its tap positions restored (a rejected trial leaves no trace, so the greedy path never depends on solve history). Generation is injected as **PQ** (`create_sgen`, not a voltage-regulating `create_gen`), so voltage problems from export show up instead of being regulated away. Power flows are warm-started from the previous solution (`init="results"`), which roughly halves the Newton iterations. The ranking's grid-need solve is the same regulated winter-peak case at 2035 demand. The N-1 screen settles the taps for the case, then lets them re-regulate after each outage and restores them before the next. On the Bicker Fen network a full run of the 20-project registry takes about 14 s cold; lightsim2grid was measured and gave no gain at this size, so it is not a dependency.

### Feasibility (`network.feasibility`)

Each call solves **every study case** and returns the first limit breached:

| Case | Load scaling | Generation (`GENERATION_FACTORS`) | Line ratings |
|---|---|---|---|
| `winter_peak` | as grown by the demand pathway | solar 0 · wind 0 · battery and hybrid **−1** (charging at `import_mw`) · demand and electrolyser **−1** · other 1 | winter (`max_i_ka`) |
| `summer_min` | per-load `min_scale` (LTDS minimum-demand factor ÷ the load's coincidence, so each row's maximum × its minimum factor; **not grown**) | everything at 1 (full export) · demand and electrolyser **−0.5** | × per-line `summer_ratio` (LTDS summer ÷ winter) |

Technologies: `IMPORT_ONLY_TECHS` (`demand`, `electrolyser`) export nothing; they draw `import_mw` at winter peak and `DEMAND_PROJECT_MIN_FACTOR` (0.5, a planning assumption) of it at summer minimum. A `hybrid` (solar + battery) is dispatched like a battery. Anything without an entry in `GENERATION_FACTORS` (gas, gas engines, biomass, 'other') takes `GENERATION_FACTOR_DEFAULT`: firm in both cases.

Before each case is judged, `_solve` lets the on-load tap changers settle: every transformer with a tap range moves its tap (HV winding, GB convention: a lower tap raises the LV voltage) until its LV busbar is within `OLTC_DEADBAND_PU` of `OLTC_SETPOINT_PU` or at an end stop, in at most `OLTC_MAX_PASSES` power flows. Tap positions persist on the net, so a trial injection normally needs one solve.

Checks, in order:
1. Every bus inside its statutory band (`VOLTAGE_BANDS`: ±10% at 132 kV and above, ±6% below).
2. Line and transformer loading ≤ 100%.
3. **GSP export** at its worst case ≤ `net["gsp_export_limit_mw"]`.

Each failure is reported as a `Reason` (`voltage` / `line` / `trafo` / `gsp` / `non_convergent`) carrying the element, the value, the `limit` breached and the `case` it failed in.

`n1_screen(net, case)` takes every in-service line and transformer at or above `N1_MIN_KV` out in turn in one study case and reports every element it breaches (`case_breaches`: each bus outside its band, each line and transformer over its rating, each its own finding, so a breach behind a worse one is never hidden and the gate compares the same element under the same outage) and islanded demand (≥ `N1_ISLAND_MIN_MW`), each finding carrying its `case` and a message that names the outage ("line 1 out: line 0 overloaded at 138.2% …"), each as the post-fault steady state; a state the solver settles into with any bus below `N1_COLLAPSE_VM_PU` (0.80 pu) is no credible steady state and is reported as one `collapse` finding for the outage (the lowest voltage, how many buses are below) instead of one breach per element the collapsed voltages drag over their limits: the tap changers re-regulate and transformer loading is read against the emergency rating (`net.trafo.emergency_ratio`, LTDS Table 2a; `outage_results` scales `trafo_pct` so 100% is that rating). `n1_screen_cases(net)` runs it in every case of `config.N1_CASES` the network supports (winter peak, then summer minimum) and returns one list: every case's thermal, voltage and convergence findings, islanded demand from the first case only (an island is topology, the same in every case; the demand case is where `demand.py` reads it). `optimize` runs that on each phase's final state and puts the findings on `PhaseResult.n1_violations` (`n1_cases` names the cases); it is not a connection gate.

After the call, `net.res_*` hold the **worst-case envelope** across cases: highest loading, and the voltage furthest from 1.0. So the heat-map helpers (`line_loadings`, `bus_voltages`, `overloaded_line_ids`, …) report the binding case.

A network without `min_scale`, `summer_ratio` or `gsp_export_limit_mw` is studied at winter peak against an unlimited slack. That keeps the engine grid-agnostic.

### Every year of the plan (`years.py`)

```
evaluate_years(result, candidates, params, scheduled=, outages=, reinforcements=,
               view_year=, years=PLAN_YEARS, net_factory=, progress=, on_year=)
```

After `optimize` has decided the queue, each year in `PLAN_YEARS` (`PLAN_START_YEAR`..`PLAN_END_YEAR`, 2026..2035) is solved as a **fixed plan** by `evaluate_year`:
- demand grown by `network.grow_for(net, params, year)`: per load on the curves the network carries (`net.load["growth_curves"]`: the built-in grid's DFES projection per primary for the pathway, or its LTDS five-year forecast where no supply area matches), uniformly on an imported grid's entered forecast (`OptimizeParams.curve`) or the `custom` anchors (`interpolate_growth_for_year`); the load-weighted multiplier is stamped on the net (`YearResult.growth`);
- the branch's reinforcements applied, then what every works window of an EARLIER year leaves behind (`maintenance.apply_works_after`: a repowered element);
- every accepted project whose energisation year has arrived injected (`energisation_years`: the operator's `scheduled` year, else the recommendation);
- both study cases, then that year's works windows (`maintenance.study_windows`, with the N-1 screen passed in when the year runs it), then the N-1 screen in each case of `config.N1_CASES` (`n1_screen_cases`).

It returns `{str(year): YearResult}`: a `PhaseResult` plus `year`, `growth`, `energised`, `trafo_loading`, `outage_studies`, and the demand side, `regions` and `alerts` (`demand.assess_demand`, below). Every loading and voltage figure is the worst of the study cases; `envelope_case` says which case set each element's (case → line, transformer and bus ids) and `gsp_case` the export's, so the planner can say "93% at summer minimum" rather than "worst case". It never changes who connects. `year_order(view_year)` solves the year in view first, then 2030 and 2035, then the rest; `on_year` is called as each lands so a caller can publish partial results, and `progress` reports the fraction within this step.

### The demand side (`demand.py`)

Customers are what the network is for, so every plan year also judges each **demand group**. `nged._add_loads` tags every load with the LTDS Table 3 row it came from (`net.load` columns `region_id`, `region`, `bsp`, `primary`, `firm_mva`, `firm_mw`, `peak_mw`) and, under a BSP, with that BSP's group (`bsp_region_id`, `bsp_region`, `bsp_firm_mva`, `bsp_firm_mw`, `bsp_sites`, `bsp_coincidence`); `demand.py` reads only those columns, level by level (`demand.LEVELS`), so any net that carries them has regions and one that does not simply reports none. Regions come at two levels:
- **primary**: one live Table 3 row for a primary substation (or a customer's own connection), at its loads' buses, exactly as NGED publishes its demand and firm capacity.
- **bsp**: a bulk supply point over every primary it feeds, at its own 33 kV busbars, with the firm capacity of its 132/33 kV transformers. Table 3 lists those transformers as rows of their own ("Sleaford (GT1)", "(GT2)", equal halves of the group demand), but they are the same customers seen one level up (`nged._bsp_aggregates`): they add **no load**. The BSP's demand is its primaries' own peaks × `bsp_coincidence` (its published maximum ÷ the sum of theirs), so today it equals NGED's own figure and grows with them. Its N-1 stranding, voltage and transformer spare are read at its busbars.

A load counts once per level, so no customer is counted twice in the power flow.

`assess_demand(net, year, n1_violations)` runs at the end of `evaluate_year`, on the solved intact envelope, and returns `(list[RegionYear], list[Alert])`. Per region:
- `demand_mw`: the group's own peak this year (`peak_mw`, the row's LTDS maximum demand with no diversity, times the year's growth) plus what plan projects on its buses draw at winter peak (demand connections, charging batteries; the existing fleet is excluded, its import is already in LTDS demand). `modelled_mw` is the same on the power flow's basis (each load's share of the GSP's coincident peak, `net.load.coincidence`).
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

When the year runs the N-1 screen, the window gets `n1_during`: the 132 kV backbone screened with the window in place, in its cases and season's ratings (`n1_screen(..., rating_ratio=)`). `violations` lists the second faults that add to what the window does alone (a breach on another element, or ≥ 1 MW stranded beyond the window's own), worst first (no convergence, then demand stranded, then the highest overload, then voltage), each the screen's own finding with its `case`; `findings` is how many second faults (outage and case) they come from, `worst` the first in words, `second_fault_at_risk_mw` the demand the worst island strands. `diff_works` compares the two sides' lists by `findings.n1_key` (`WorkDelta.n1_new` / `n1_cleared`): with the same verdict and burden, a window the branch adds a second-fault problem to reads `worse`, one it clears a problem from `better`. Informational, like the year's own screen. Measured on Bicker Fen: ~50 ms per window without N-1 (~75 ms when curtailment is searched), plus ~0.6 s per case for the N-1 during it, so the whole backbone is screened rather than a neighbourhood.

`study_windows` leaves the net as found (elements, generator ratings, tap positions): a year's own results never depend on whether a window was studied in it. `message` is a plain-English summary naming elements by id.

`config.SEASON_STUDY` picks the case(s) and line ratings per season:

| Season | Cases | Line ratings |
|---|---|---|
| Winter | `winter_peak` | winter |
| Spring, Autumn | `winter_peak` and `summer_min` | `intermediate_ratio` (LTDS Intermediate Warm ÷ winter, built in `nged.py`) |
| Summer | `summer_min` | `summer_ratio` |

Besides the verdict, an `OutageStudy` carries the cases studied, `ok` (no breach before curtailment), the first breach per case, worst loadings, GSP export and `after`. Like N-1, works windows are reported per year and are **never a connection gate**.

### The best window for a work (`windows.py`)

```
best_windows(result, candidates, params, (element_kind, element_id), years=PLAN_YEARS, seasons=SEASONS,
             work=, kind=, repower=, factor=, weeks=, scheduled=, reinforcements=, outages=,
             n1=True, n1_shortlist=BEST_WINDOW_N1_SHORTLIST, net_factory=, progress=) -> list[WindowOption]
```

Probes the element's window in every (year, season) of the range, each year through `years.evaluate_year` (the year's net built once, with its demand, energised projects, reinforcements, earlier works and the branch's other windows; a probe sharing a season with them is studied together with them). Probes of different years never see each other. Ranking, deterministic: verdict (feasible < curtailment < demand_at_risk < not_feasible), curtailed MW, demand at risk, N-1 findings during the window, worst line then transformer loading, earliest year, season order.

Two passes bound the cost: every window without the N-1 screen, then the screen for a shortlist of `BEST_WINDOW_N1_SHORTLIST` (6: the best window of each season, then the next best). The rest report `n1_findings = None` and rank after a screened window they tie with, so a window with fewer second-fault findings can exist among them (a stated limit). Measured on the NGED network, 10 years × 4 seasons: 5.5 to 6.5 min screening every window, 2 to 3.5 min with the shortlist (a busy dev machine; the curtailment search dominates windows that breach a limit).

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
- **`works`** — one `WorkDelta` per head window (`diff_works(on_main, on_branch)`): its verdict and curtailed / at-risk MW on head's plan against the same window (by outage id and year) studied on base's plan, `change` (`worse` / `better` / `unchanged` / `unstudied`; a heavier burden under the same verdict counts as worse, ordered by `VERDICT_SEVERITY`) and a plain-English `consequence` ("Feasible on main, but needs 40.0 MW of curtailment on this branch."). `on_base` says whether base schedules the window itself (the outage ids in base's own years; unknown, so true, when base has no years): `change` compares the window across the two plans, which is what the branch's projects do to it, so a window only the branch schedules says so first ("New on this branch: needs 14.2 MW of curtailment. Main does not schedule it; ..."), and the headline counts them (`n_works_new`). The base-plan study is the caller's: the API solves head's windows on base's energised plan (base's projects, schedule and reinforcements; `evaluate_year(..., n1=False)` for each year with a window) and passes them as `works_on_base`. Without it, head's windows are compared with base's own windows of the same id.

### Merge guardrails and the findings ledger (`gate.py`, `findings.py`)

`merge_verdict(head, base, diff=None, *, fresh, stale_reasons, scheduled, removed_works, removed_reinforcements, base_label, parent_moved, fork_unknown) -> MergeVerdict`, pure. The rule: **no merge while the grid would be broken in any plan year**, read against the parent, because the parent is not perfect either. Every check in `MERGE_CHECKS` compares the branch with its parent in the same plan year and emits `GateFinding`s whose level comes from `config.MERGE_GATE_LEVELS`, the only place a level is decided:

| Check | Blocks | Warns | Context |
|---|---|---|---|
| `_stale`, `_no_result`, `_unstudied_years` | a result not solved for the branch's current inputs; a missing side; a plan year missing on either side | | |
| `_non_convergent` | a year that converges on the parent but not on the branch | | both sides fail to converge |
| `_behind_base` | each change the parent received after the branch was opened that the branch lacks (`parent_moved`, one `ParentMove` each, read by the API from the branch's fork point, recorded or rebuilt from the merge history), whether or not the result is fresh: merging would undo it, so the branch is rebased first; without a fork point, only a project on the parent but not on the branch can be seen (from the diff) | | |
| `_fork_unknown` | | a branch with no known fork point (`fork_unknown`: opened from another branch before fork points were recorded): what its parent received since cannot be told from its own changes, so it is rebased with every difference picked | |
| `_thermal` | a line or transformer newly over its rating; one already over it loading more than `GATE_WORSEN_PTS` more | | already over it on the parent, unchanged |
| `_voltage` | a bus newly outside its statutory band | one already outside it drifting more than `GATE_VM_WORSEN_PU` further | already outside it, unchanged |
| `_gsp` | export newly above the limit; already above it and more than `GATE_GSP_WORSEN_MW` higher | export above `GSP_NEAR_LIMIT_FRACTION` of the limit and higher than the parent's | already above or near it, not added to |
| `_n1` | a new N-1 finding (islanded demand, a post-fault collapse, or a limit breached after a single outage), keyed by `findings.n1_key`, never capped: one item per outage and case across the plan years it appears in, with the count of elements, the years and the worst breach | the same finding (outage, case, element) worse beyond the planning tolerance of its kind (`_N1_WORSE`: `GATE_WORSEN_PTS` loading points; `GATE_VM_WORSEN_PU` further from 1.0 pu, or a deeper collapse; `N1_ISLAND_MIN_MW` more stranded), grouped the same way, both figures shown for the worst | findings already on the parent (a smaller move included), summarised per year |
| `_alerts` | a new `breach` alert, or a warning that became a breach | a new `warn` alert; one further past its threshold | unchanged alerts |
| `_works` | a window whose verdict becomes `demand_at_risk` or `not_feasible` on the branch | more curtailment under the same verdict; a window infeasible on both plans; a window the branch adds (`on_base` false) that needs curtailment, puts demand at risk or has second faults during it (`work_new`) | |
| `_schedule`, `_profile`, `_proposals` | | a project scheduled against the recommendation; a changed demand profile; works or reinforcements the merge removes from the parent | |
| `_deferred` | | | projects the branch still defers on the grid |

Connections stay ungated (N-1 and planned works are reported, never a connection gate); merges are gated, because a supply-security regression is what "the grid would be broken" means. The API decides freshness (its caches know whether the branch was solved for its current inputs) and whether warnings need acknowledging.

`extract_findings(result, scheduled) -> list[Finding]` is the ledger's input: every problem a result carries, breaches first, each with a `fingerprint` of kind + element + year + case (never the value), so a re-run upserts the same finding instead of duplicating it. `EXTRACTORS`: overloads and voltage breaches per year (the worst-case envelope), the GSP over or near its limit, every N-1 finding, every demand alert, every works window that is not simply feasible, deferred (with the binding reason) and rejected projects, schedules against the recommendation, non-convergent years. A gate finding carries the ledger fingerprint it refers to (`finding_fingerprint`).

### Studies (`studies.py`)

`run_study(kind, StudyContext(net_factory, params, candidates, result, progress, schedule, outages), params) -> StudyResult` (the branch's schedule and planned windows are there for the studies that study the plan year by year). Each study is bounded, pure given its network, reports `StudyItem`s with the engine's figures and a stable `fingerprint` (kind + element + case + year, never the value), and lists what it did **not** study. `chunk_study` splits a study into independent parts (one per background step) and `merge_chunks` puts them back. The agents see `STUDIES` as tools; the API caches each study by its params.

| Study | Method | Cost |
|---|---|---|
| `hosting_capacity` | Per bus (`bus_ids`, else every bus at or above `HOSTING_MIN_KV`, the `HOSTING_MAX_BUSES` with the most first-order room first, `sensitivity.rank_buses`) and study case: a firm generator (export) or a demand connection (import) injected at the bus, the case solved with the taps regulated, bisection between 0 and the intake cap to `HOSTING_STEP_MW`; the net is left exactly as found after every probe. `value` = the MW before the first `LIMIT_CHECKS` or GSP breach, `extra.binding` = that reason. Today's network as the branch reinforces it; demand growth and the plan's projects are not applied. | about 7 solves per bus and case; chunked 4 buses per part |
| `contingency_ranking` | `n1_elements(net, CONTINGENCY_MIN_KV)` out one at a time through `outage_results` (the post-fault steady state: taps re-regulated from the case's settled positions, transformer loading as % of the emergency rating), in each case: islanded demand (MW), thermal excess (sum of overload above 100% × rating, MVA), worst voltage shortfall (pu), non-convergence. Ranked by that tuple; `value` = the weighted index (`CONTINGENCY_SEVERITY_WEIGHTS`, a ranking heuristic, never a gate). Contingencies that break nothing are not reported. | one solve per element and case; chunked per case |
| `structural_weak_points` | The network as a simple graph: bridges with a single circuit (no parallel) and articulation busbars whose removal leaves components without the slack; demand and rated generation on them. | none |
| `tap_margin` | Taps settled per case; every OLTC within `TAP_MARGIN_MIN_STEPS` of a stop (breach at the stop, warning one step away), with its LV busbar voltage. | one solve per case |
| `gsp_margin_by_year` | From the branch's plan years: limit minus export, warning under `GSP_MARGIN_WARN_FRACTION` of the limit, breach below zero. Needs the plan. | none |
| `data_quality` | The builder's recorded assumptions (`net["assumptions"]`, `nged._assume`: blank ratings filled, defaulted lengths, median seasonal ratios, assumed tap steps, fixed taps, default power factors) with their element ids, plus transformers with no usable tap changer. | none |
| `connection_options` | For one project (`request_id`), on the plan's hardest phase (`suggest.phase_net`: demand grown, the projects accepted by then energised except this one, the branch's reinforcements applied) in each study case: **size**, the MW its own busbar takes of it (the project's own technology, so the case dispatch applies, and a case where it dispatches at nil, PV at winter peak, is skipped and listed as not studied; bisection to `step_mw`; `fits` when it takes all of it; else the message says a firm connection of that size, or a flexible one firm to it), **reinforce**, the parallel-circuit chain (`suggest.discover_chain`) with its reinforcements and where it stops, and **move**, its full MW probed at the higher-voltage busbars nearest by network steps (`max_buses`, or `bus_ids`), bisected where it does not fit. `extra.option` names the kind; `extra.binding` the reason. Needs the plan. Not studied: the other years, the works and cost of a new point of connection, transmission works, curtailment hours, fault levels. | the chain (up to `MAX_REINFORCE_STEPS` + 1) plus about 7 solves per case for the size and per busbar and case for the moves; chunked: the site, then one part per busbar |
| `best_window` | `windows.best_windows` for one element (`element_kind`, `element_id`, `work`, `kind`, `repower`, `factor`, `weeks`) over `years` and `seasons`, against the plan as it stands each year with the branch's schedule and other windows: one item per window with the verdict (info feasible, warn curtailment, breach demand at risk or not feasible), the curtailed MW as `value`, the demand at risk and the second-fault count in `extra`. With `n1` the shortlist is screened and the study runs whole; without it, chunked per year (ranks are then per year). Needs the plan. | about 3 solves per window, plus the N-1 shortlist |

---

### What limits the plan (`analysis.py`)

A run is thousands of figures; an engineer asks three things of them. `limits` answers them as data, deterministically:

- **The binding set.** For every line, transformer and bus: its envelope figure per plan year with the study case that set it (`PhaseResult.envelope_case`), the first year it comes within `GSP_NEAR_LIMIT_FRACTION` of its loading limit (a bus: within the tap deadband of its band), the first year it breaches, the worst year and the headroom left there in MW (first-order: `(limit − loading) × rating`, the rating √3·kV·I·parallel for a line with the summer ratio in the summer case, `sn·parallel` for a transformer), the projects whose deferral names it and the distinct (outage, case) pairs whose post-fault state breaches it. Elements comfortably within their limits with nothing deferred on them and no outage breaching them are left out: the view is what limits the plan, worst first.
- **A chain per deferral.** The queue's `Reason` (its element, case and figure against the limit, from the 2035-phase trial), when that element starts binding on its own, and, when a `connection_options` study has run for the project, the firm size at its own busbar, whether parallel circuits reach full MW and the best higher-voltage busbar. Nothing is solved here: a chain says `studied: false` until the study exists.
- **Clusters.** The N-1 rows folded by cause: the element several outages overload or push out of band (a weak link), the set of buses several outages strand (an island), the outages whose post-fault state has no credible steady state (a collapse). Twelve outages that strand the same 1.1 MW are one row.

- **The grid's character.** `character(binding, headline)` counts the binding elements by the case of their worst year, with the GSP when its export comes within `GSP_NEAR_LIMIT_FRACTION` of its limit, and names the grid export-bound (the summer-minimum count dominates: every generator at full output, demand at its measured minimum, so new generation moves the figures and demand growth does not), demand-bound (winter peak dominates) or mixed; `Limits.character.text` is the line the Limits tab and the note lead with. The headline also carries the two headroom figures a DNO publishes per substation: generation headroom at the GSP (limit less the plan's peak export) and demand headroom at the tightest demand group (firm capacity less that year's peak, worst year).

`run_digest` folds the limits, the headline figures, the character, the works and what changed against the parent (the consequence diff and the gate's blocker kinds) into about 2 kB: what the note writer reads, and all it reads.

### Sensitivities (`sensitivity.py`)

`thermal_headroom(net, buses, direction)` builds the DC PTDF matrix of the case the net was last solved for (pandapower's `makePTDF` on the reduced ppc; taps and in-service state honoured, the slack at the external grid) and gives, per bus, the MW of new export (or demand) before the most constrained branch reaches its rating, flow-direction aware; a branch already over its rating gives 0; an islanded bus gets no entry. On the NGED network it takes about 0.1 s for 114 buses and injecting the predicted room at a bus takes the worst AC loading to 92–98 %. It knows no voltage and no reactive power, so it only **ranks**: `hosting_capacity` and `connection_options` probe with AC the buses it puts first (`studies._ranked`), and every figure a study reports is the AC solve's.

### Adapting a grid (`sources.py`)

Every engine function takes `net_factory=` and reads the network through a handful of columns, so any grid the seam can produce is planned on the same way. What the engine reads from a pandapower net:

| Table / key | Column | Who fills it | Without it |
|---|---|---|---|
| `net.load` | `scaling` | pandapower (growth multiplies it) | required (pandapower default 1) |
| `net.load` | `min_scale` | NGED from the LTDS minimum-demand factor; an import from the file or `ImportMeta.min_demand_factor` | an import is refused: both study cases run on every grid |
| `net.load` | `peak_mw`, `region_id`, `region`, `bsp`, `primary`, `firm_mva`, `firm_mw`, `bsp_*` | NGED from LTDS Table 3 | no demand groups: no firm-capacity alerts, `regions` empty |
| `net.load` | `type` | the file (`wye`, `MV Load`, …) | growth spread without a residential / industrial shape |
| `net.line` | `max_i_ka`, `parallel` | the file | an import is refused: the report lists every unrated line |
| `net.line` | `summer_ratio`, `intermediate_ratio` | NGED from LTDS seasonal ratings; an import from the file or `ImportMeta` | no `summer_ratio`: an import is refused; no `intermediate_ratio`: spring and autumn windows use the winter ratings |
| `net.trafo` | `tap_side`, `tap_min/max/neutral/pos`, `tap_step_percent`, `tap_changer_type` | the file, as it states it: a fixed ratio (a position, no range) is kept; a range with a tap-changer type is an on-load changer the engine regulates | no tap data: the nominal ratio; a range without a type is refused (on-load or fixed, the file has to say) |
| `net.sgen` | `p_rated_mw`, `import_mw`, `fleet_id`, `type` | NGED's builder; `normalise_net` from `max_p_mw` (an inverter unit's `sn_mva`, `inverter_rating`), `EX-<idx>`, the file's type or our `gridforge.tech=` tag | an import is refused: no technology, no rating, a battery without its charging capacity |
| `net.gen` | voltage-controlled units: `vm_pu`, `min_q_mvar`, `max_q_mvar`, `max_p_mw`, `type`; a power station also `min_p_mw` and its `poly_cost` | the file (kept voltage-controlled: they hold their setpoint within their reactive limits, `enforce_q_lims`); `EX-G<idx>` | an import is refused, with the list of what each unit lacks |
| `net.ext_grid` | the slack; with power stations, its `poly_cost` and `max_p_mw` | the file, or the generator the file marks as its slack (`slack_from_generator`) | an import is refused: no infeed; or no price and limit for the merit order |
| `net["gsp_export_limit_mw"]`, `gsp_name`, `gsp_sgt_mw` | the export limit | NGED's `GSP_BOUNDARY`; an import from `ImportMeta.gsp_export_limit_mw` and `gsp_sgt_mw` | export to the slack is reported, never limited; without `gsp_sgt_mw` the "add a supergrid transformer" lever is not offered |
| `net.bus` | `substation`, `geo` | NGED's name parsing / OSM join; an import from `zone` (CGMES substation) and the GL profile or `bus.geo` | buses stand for themselves; a file with no positions gets a synthetic layout |
| `net["assumptions"]` | one record per assumption the study makes | the builder's `_assume`, `normalise_net`, `apply_import_meta`, `inspect_net` | the data-quality study and the import report list them |
| `net["gaps"]` | what a file lacks for a real simulation | `normalise_net` | `validate_net` makes each an error: the import is refused with the list (buses the infeed cannot reach included) |

An imported grid is simulated as it runs, or not at all: nothing its own description needs is assumed. Its power stations are dispatched by merit order in every study case (`dispatch.py`: equal marginal cost from the file's costs, within their limits, every available unit synchronised; embedded generation, solar, wind and storage follow the case as on NGED; the external grid balances). `validate_net` runs the structural checks (buses, a slack, voltages, dangling lines, islands) and the gaps, then one `feasibility()` pass on a complete grid: a base case that already breaks a limit is a warning that every project would be deferred for it; a base case with no solution is reported as such, telling apart a file whose own operating point does not solve from one that solves but not as studied; a collapse at the plan's last year (on the Standard forecast) names a generation shortfall when it is one. The study basis is stated at import or the import is refused (`_study_basis`): the forecast by pathway and year (`net["forecasts"]`, served as `GridSource.forecasts()`), the N-1 floor (`net["n1_min_kv"]`, read by `n1_floor`) and the limits at every level (`net["voltage_bands"]`, read by `bands_of`); NGED keeps the FES pathways, `VOLTAGE_BANDS` and `N1_MIN_KV`. `inspect_file` reads a file's levels for the import form. `MAX_CONNECTION_MW` applies to every grid. A source's `fingerprint()` is the content identity results are cached under (for an import: the bytes, the kind, `IMPORTER_VERSION` and the entered limits).

## Demand growth (`network.grow_for`)

The built-in grid grows **per primary substation** on NGED's DFES 2025 winter-peak power projections (`data/nged/dfes.json`, one Electricity Supply Area per primary, four scenarios, every year to 2040): each load's multiplier for a year is its supply area's projection divided by its 2025 value (`config.DFES_BASE_YEAR`, the LTDS edition's current year), so a plan year is NGED's own figure for that substation (`nged._growth_curves`, `network.per_load_growth`). `FORECASTS` maps the planner's profiles to the DFES scenarios (`dfes`: Standard = Holistic Transition, High = Electric Engagement, Hydrogen = Hydrogen Evolution, Low = Counterfactual); `nged.dfes_pathways` gives the network-wide, load-weighted multiplier per year the picker shows. Connections with no supply area (customer sites, the BSP aggregates) follow their LTDS five-year forecast and then hold (`forecast_ltds_only`). An imported grid grows uniformly on the forecast entered at import; `custom` on the GROWTH_2030 / GROWTH_2035 anchors, interpolated. Only demand grows: no generation is pre-loaded.

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
OLTC_SETPOINT_PU / OLTC_DEADBAND_PU = 1.02 / 0.01 ; OLTC_TAP_STEP_PERCENT = 1.25 (assumed)
GENERATION_FACTORS                  = winter: solar 0, wind 0, battery/hybrid -1, demand/electrolyser -1 ;
                                      summer: all 1, demand/electrolyser -DEMAND_PROJECT_MIN_FACTOR
GENERATION_FACTOR_DEFAULT           = firm (1) in both cases: gas, gas engines, biomass, other
IMPORT_ONLY_TECHS / DEMAND_PROJECT_MIN_FACTOR = ("demand", "electrolyser") / 0.5 (assumed)
PLAN_START_YEAR / PLAN_END_YEAR     = 2026 / 2035
SEASON_STUDY                        = season -> study case(s) + line rating column (see above)
OUTAGE_DERATE_FACTOR                = 0.5
CURTAIL_MAX_SOLVES / CURTAIL_REFINE_STEPS / CURTAIL_MIN_RELIEF = 8 / 3 / 0.01   # window curtailment search (first-order)
BEST_WINDOW_N1_SHORTLIST            = 6        # best-window search: windows screened N-1 during the window
N1_MIN_KV / N1_ISLAND_MIN_MW        = 132 / 1.0
P2_8_CLASSES                        = group MW: A <=1, B <=12, C <=60, D <=300, E <=1500, F above (ENA EREC P2/8 Table 1)
HEADROOM_WARN_FRACTION              = 0.10     # firm-headroom warning margin (assumed)
LINE_LOADING_MAX_PCT / TRAFO_...    = 100 / 100
MAX_CONNECTION_MW                   = 300      # intake plausibility (ECR has 248 MW accepted at 132 kV)
W_READINESS / W_NEED / W_STRATEGIC  = 0.5 / 0.35 / 0.15
GROWTH_2030 / GROWTH_2035           = 1.08 / 1.35   # FES 2025 Holistic Transition
MAX_SUGGESTIONS / MAX_REINFORCE_STEPS = 5 / 4
MERGE_GATE_LEVELS                   = kind -> blocker | warning | info   # the merge-gate policy (see above)
GATE_WORSEN_PTS / GATE_GSP_WORSEN_MW / GATE_VM_WORSEN_PU = 1.0 / 1.0 / 0.005   # worsening margins (assumed)
GSP_NEAR_LIMIT_FRACTION             = 0.9      # GSP export warning band
HOSTING_STEP_MW / HOSTING_MIN_KV / HOSTING_MAX_BUSES = 5 / 33 / 24   # hosting-capacity study bounds
CONNECTION_OPTION_BUSES             = 4        # connection options: higher-voltage busbars probed, nearest first
CONTINGENCY_MIN_KV / CONTINGENCY_SEVERITY_WEIGHTS = 33 / {islanded_mw 1, thermal_excess_mva 1, voltage_shortfall_pu 100}  # ranking heuristic
TAP_MARGIN_MIN_STEPS / GSP_MARGIN_WARN_FRACTION = 1 / 0.10
```

NGED-specific values live in `nged.py`: `GSP_PEAK_DEMAND_MW = 149.235` (NESO FES 2024 regional breakdown; today's winter-peak demand sums to it), `GSP_BOUNDARY` (2 × 263.5 MW SGT export limit, with the source resource id), `TRANSMISSION_PROJECTS` and `ECR_MIN_EXPORT_MW = 1`.

---

## Tests

```bash
cd packages/optimizer && uv run pytest -q     # 153 tests on 4 workers (pytest-xdist); ~2 min
```

The N-1 screen is stubbed in every test except the one that tests it (`conftest.py`, marker `n1`): it costs ~2 s per phase inside `optimize()` and would otherwise dominate the suite.

Tests are **grid-agnostic**. `tests/_grid.py` derives every fixture from the network `build_base_net()` returns:
- a stiff bus, the weakest buses, and a saturating queue sized from the local circuits' thermal rating (not from any policy cap);
- no hard-coded bus ids.

What they cover:
- the CGMES export: well-formed, fully linked, deterministic, and re-imported by pandapower to the same network and power flow (`test_cim.py`);
- the sources: NGED through the seam is the same network and model; the NGED CGMES export re-imports as a grid with the same elements, a converging base case, the technology tag intact and its missing data stated; operator-entered limits enable the summer case and the boundary and change the fingerprint; a pandapower JSON with no coordinates gets a deterministic synthetic layout and a slack; an unrated line is a gap that refuses the import; a network nobody can feed fails validation; a MATPOWER `.mat` imports (`test_sources.py`);
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
- the best-window search: every (year, season) once, ranked, the same study the year reports, combined with same-season windows, probes independent across years, the N-1 shortlist, bad requests (`test_windows.py`);
- reinforcement, suggestions and the diff;
- the merge gate: each check against the policy table, pre-existing problems as context, worsening margins, blockers never cut off by the diff's display caps, determinism, and a live pair on the grid (`test_gate.py`);
- the findings ledger's input: every kind extracted, stable value-independent fingerprints, a clean result has none, real years name elements by index (`test_findings.py`);
- the studies: every registry entry runs twice to the same result, hosting capacity is bounded and names its binding limit and leaves the net as found, the contingency ranking contains every N-1 finding and leaves `n1_screen` unchanged, the structural study makes no power flow and names real bridges, a transformer parked at a stop is flagged, the GSP margin reads the plan, the data-quality study lists the builder's assumptions, connection options size the project at its busbar, chain circuits and probe higher-voltage busbars nearest first (chunked per busbar and merged item for item, a project not on the branch refused), the best-window study wraps the search and chunks per year without N-1 (`test_studies.py`; one full-scope test marked `slow`); `phase_net` leaves a project out and `discover_chain` is public (`test_suggest.py`);
- the readiness rubric.

`test_nged.py` adds the NGED data rules: removed equipment is excluded, every live MW of demand is modelled, and nothing from the registry is pre-loaded.
