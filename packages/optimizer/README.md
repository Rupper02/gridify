# gridforge_optimizer

The deterministic connection-queue engine behind GridForge. It's a standalone, tested Python package, used by the Dagster pipeline and the FastAPI service through a local editable path dependency.

It decides **which projects connect, in what order and in which phase**. Every decision is gated by pandapower AC power flow in two planning study cases plus the GSP export limit. It also measures **what it would take** to unblock the projects it defers, and diffs two plans.

```python
from gridforge_optimizer import Candidate, OptimizeParams, optimize, suggest_unblock

cands = [Candidate(request_id="A", bus_id=19, technology="battery", rating_mw=50,
                   readiness_score=0.3, strategic_fit=0.78, commissioning_year=2027)]
result = optimize(cands, OptimizeParams(scenario="ht"))
for q in result.queue:
    print(q.rank, q.request_id, q.status, q.recommended_year, q.reason and q.reason.message)
print(suggest_unblock(cands, OptimizeParams(scenario="ht"), result))
```

Nothing in `optimize()` or `suggest_unblock()` makes a network call, so the same inputs always give the same answer.

---

## Modules

| Module | Responsibility |
|---|---|
| `nged.py` | Builds the real **NGED Bicker Fen** network from bundled open data (`data/nged/`). `build_nged_net()` gives today's network; `nged_model()` gives the geolocated model for the map. `nged_candidates()` gives the optional-project registry (ECR + GSP-embedded TEC); `gsp_boundary()` gives the export limit plus transmission context. |
| `network.py` | pandapower helpers: `build_base_net`, demand growth (`apply_growth`, `per_bus_growth`), `inject_sgen`/`drop_sgen`, **`feasibility`** (both study cases + GSP limit), per-element results, `apply_reinforcement`. |
| `greedy.py` | `optimize`: intake, ranking, the per-phase greedy feasibility loop, recommended years. |
| `suggest.py` | `suggest_unblock`: "what would it take", measured by re-solving. |
| `diff.py` | `diff_results(base, head)`: the consequence diff between two plans. |
| `readiness.py` | `score_from_checklist`: the deterministic, auditable readiness rubric. |
| `scoring.py` | `grid_need_from_solved`: the "first *needed*" signal. |
| `types.py` | Pydantic models: `Candidate`, `OptimizeParams` → `QueueItem`, `PhaseResult`, `OptimizeResult`, `Reason`, `Reinforcement`, `Suggestion`. |
| `config.py` | Every tunable: limits, growth pathways, weights, caps, LLM settings. |
| `llm.py` | The only module that calls out (OpenRouter): optional narration (`justify`, `narrate_diff`, `narrate_suggestion`) that phrases figures the engine already computed. Empty if no `OPENROUTER_API_KEY`. |

---

## The algorithm

```
optimize(candidates, params):
  valid    = auto_accept, bus exists in the network, 0 < rating ≤ MAX_CONNECTION_MW
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

The network is built **once per phase**. Each trial is an `sgen` inject, and a failed one is rolled back with `drop_sgen`. Generation is injected as **PQ** (`create_sgen`, not a voltage-regulating `create_gen`), so voltage problems from export show up instead of being regulated away.

### Feasibility (`network.feasibility`)

Each call solves **every study case** and returns the first limit breached:

| Case | Load scaling | Line ratings |
|---|---|---|
| `winter_peak` | as grown by the demand pathway | winter (`max_i_ka`) |
| `summer_min` | per-load `min_scale` (LTDS minimum-demand factor ÷ diversity; **not grown**) | × per-line `summer_ratio` (LTDS summer ÷ winter) |

Checks, in order:
1. Bus voltage within [`VOLTAGE_MIN_PU`, `VOLTAGE_MAX_PU`] = [0.9, 1.1].
2. Line and transformer loading ≤ 100%.
3. **GSP export** at its worst case ≤ `net["gsp_export_limit_mw"]`.

Each failure is reported as a `Reason` (`voltage` / `line` / `trafo` / `gsp` / `non_convergent`) carrying the element, the value and the `case` it failed in.

After the call, `net.res_*` hold the **worst-case envelope** across cases: highest loading, and the voltage furthest from 1.0. So the heat-map helpers (`line_loadings`, `bus_voltages`, `overloaded_line_ids`, …) report the binding case.

A network without `min_scale`, `summer_ratio` or `gsp_export_limit_mw` is studied at winter peak against an unlimited slack. That keeps the engine grid-agnostic.

### What would it take (`suggest.py`)

For the highest-ranked deferred projects (`MAX_SUGGESTIONS`), each lever is applied and the trials re-run to measure `freed_mw_2030/2035`:

- **`line` / `trafo` binding** — chain `add_parallel` reinforcements (halves impedance, doubles rating) up to `MAX_REINFORCE_STEPS`. If a voltage limit takes over, hand off to the voltage lever. If the GSP limit takes over, say so.
- **`voltage` binding** — re-inject the project absorbing reactive power at 0.98/0.95/0.90 pf, else reinforce one upstream circuit.
- **`gsp` binding** — `Reinforcement(kind="gsp")`, i.e. one more supergrid transformer (+`gsp_sgt_mw`). Its caveat flags it as transmission works.

Freed MW is first-order: the knock-on of a freed project blocking a later one isn't modelled, so the UI shows it as "≈". The caveats say these are feasible levers, not least-cost designs.

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
VOLTAGE_MIN_PU / VOLTAGE_MAX_PU     = 0.9 / 1.1
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
cd packages/optimizer && uv run pytest -q     # 30 tests
```

Tests are **grid-agnostic**. `tests/_grid.py` derives every fixture from the network `build_base_net()` returns:
- a stiff bus, the weakest buses, and a saturating queue sized from the local circuits' thermal rating (not from any policy cap);
- no hard-coded bus ids.

What they cover:
- feasibility and the worst-case envelope;
- the summer-minimum case raising export;
- the GSP limit binding, and an SGT relieving it;
- greedy outcomes and determinism;
- recommended years;
- reinforcement, suggestions and the diff;
- the readiness rubric.

`test_nged.py` adds the NGED data rules: removed equipment is excluded, every live MW of demand is modelled, and nothing from the registry is pre-loaded.
