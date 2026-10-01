# gridforge_optimizer

The deterministic connection-queue engine behind GridForge — a standalone, tested Python package shared by the Dagster pipeline and the FastAPI service via a local editable path dependency. It decides **which generation/storage projects connect, in what order, and in which phase**, gated by a pandapower AC power flow. The only non-deterministic work (LLM extraction, the Jev strategic decision, the closing narrative) is isolated in `llm.py`; everything that ranks and connects projects is plain, testable code.

```python
from gridforge_optimizer import Candidate, OptimizeParams, optimize

result = optimize(
    [Candidate(request_id="A", bus_id=120, technology="solar", rating_mw=4.5,
               readiness_score=0.9, strategic_fit=0.8)],
    OptimizeParams(scenario="ht"),
)
for q in result.queue:
    print(q.rank, q.request_id, q.status, q.reason and q.reason.message)
```

`optimize()` makes **no network calls** — candidates arrive already scored (by the pipeline), so a run is fast and fully reproducible.

---

## Modules

| Module | Responsibility |
|---|---|
| `config.py` | Every tunable: feasibility limits, growth defaults + DFES pathways, ranking + rubric weights, model names, prompts. One place to change behaviour. |
| `types.py` | Pydantic models: `Candidate`, `OptimizeParams` (in); `QueueItem`, `PhaseResult`, `OptimizeResult`, `Reason` (out). |
| `network.py` | pandapower helpers: `build_base_net`, `apply_growth` / `per_bus_growth`, `inject_sgen` / `drop_sgen`, `feasibility`, `line_loadings`. |
| `scoring.py` | `grid_need_from_solved` — the "first *needed*" signal from a solved network. |
| `readiness.py` | `score_from_checklist` — the deterministic, auditable readiness rubric. |
| `greedy.py` | `optimize` — ranking + the per-phase greedy feasibility loop. |
| `llm.py` | OpenRouter wrappers: fact extraction (Sonnet), strategic fit (Jev decisions model), narration (Sonnet). The *only* module that calls out. |

---

## The algorithm

```
optimize(candidates, params):
  valid    = candidates that passed intake triage (auto_accept, real bus, 0 < rating ≤ cap)
  rejected = the rest                              →  appended to the queue as "Rejected"

  # "first needed": one power flow under the 2035 scenario reads the grid signal at each bus
  need_net = grow(build_base_net(), 2035, scenario)
  need[c]  = grid_need_from_solved(need_net, c.bus)

  rank_score(c) = w_readiness·readiness + w_need·need[c] + w_strategic·strategic_fit
  ranked = valid sorted by rank_score desc, tie-break (readiness desc, rating asc, id)

  accepted = []
  for phase in (2030, 2035):                      # "first connected", phased
      net = grow(build_base_net(), phase, scenario)
      for a in accepted: inject_sgen(net, a)      # everyone already connected stays on
      for c in ranked not yet accepted:
          idx = inject_sgen(net, c)               # trial this project
          ok, reason = feasibility(net)           # runpp → voltage band + thermal limits
          if ok: accepted += c
          else:  drop_sgen(net, idx); c.last_reason = reason   # still eligible next phase

  queue = ranked (each tagged Phase1 / Phase2 / Deferred + its binding reason) + rejected
```

**Why the network is rebuilt once per phase, not per trial:** building `mv_oberrhein` is the expensive step. The loop builds it once, keeps accepted generators in place, and injects/`drop_sgen`s only the *trial* project — turning ~N rebuilds into one, which (with numba-compiled `runpp`) keeps a full run well under two seconds warm.

### Feasibility gate (`network.feasibility`)

A trial is accepted only if, after `pp.runpp`:

- every bus voltage is within **[`VOLTAGE_MIN_PU`, `VOLTAGE_MAX_PU`]** = [0.9, 1.1] pu, **and**
- every line loading ≤ **`LINE_LOADING_MAX_PCT`** (100%), **and**
- every transformer loading ≤ **`TRAFO_LOADING_MAX_PCT`** (100%).

Otherwise it returns a `Reason` naming the binding element (`voltage` at a bus / `line` / `trafo` / `non_convergent`). Generation is injected with **`create_sgen` (PQ)**, deliberately *not* `create_gen` (PV): a PV node would regulate voltage and hide exactly the violations the reform is about.

A project deferred in 2030 stays eligible in 2035 — higher demand can absorb a generator's reverse flow that had no thermal headroom a phase earlier.

---

## Scoring — the right tool for each sub-question

### Readiness — deterministic rubric (`readiness.py`)

Readiness is a factual Gate-2 checklist, so an LLM only *extracts* the facts (`llm.extract_readiness_checklist`, bounded enums) and this rubric scores them:

| Milestone | Weight | Levels → credit |
|---|---|---|
| land rights | 0.30 | secured 1.0 · in_progress 0.5 · none 0 |
| planning consent | 0.30 | granted 1.0 · submitted 0.5 · pre_application 0.1 · none 0 |
| connection agreement | 0.20 | signed 1.0 · offered 0.5 · none 0 |
| financing | 0.10 | committed 1.0 · in_progress 0.5 · none 0 |
| commissioning timeline | 0.10 | ≤2 yrs 1.0 · ≤5 yrs 0.6 · else/unknown 0.3 |

`score_from_checklist` returns the score, a human-readable rationale (secured / in-progress / outstanding), **and a per-milestone `readiness_breakdown`** (level, credit, weight, points) — so every point is auditable. Weights and credit thresholds live in `config.py` (`READINESS_WEIGHTS`, `READINESS_COMMISSIONING_*`).

### Grid need — the "first needed" signal (`scoring.py`)

`grid_need_from_solved(net, bus)` blends, each normalized to 0..1: local demand served at the bus (saturating at `GRID_NEED_DEMAND_FULL_MW`) and voltage depression (how far below 1.0 pu, over the allowed band). Weak, demand-heavy buses score higher — local generation helps most there.

### Strategic fit — a decisions model (`llm.score_strategic_fit`)

The one genuinely judgmental question ("is this the right addition?") goes to **Jev**, a typed decisions model, via OpenRouter's `/api/alpha/decisions`. It's asked to choose `{high, medium, low}` given the project plus its measured grid signal (the state), and returns a choice, a probability distribution, and a **calibrated confidence**. The `strategic_fit` score is the expected value over the distribution (`STRATEGIC_FIT_VALUE`); the confidence is persisted as the act-vs-defer knob. If the endpoint is unreachable, `llm.py` falls back to a structured chat call (confidence `None`).

---

## Per-bus demand growth (`network.per_bus_growth`)

A DFES pathway sets the feeder-wide multiplier `m`; growth is then distributed **per bus** so the feeder total is preserved exactly while individual buses diverge realistically. Each load gets a weight

```
w = β_type · (1 + α·(2·hash01(scenario,bus) − 1)) · (1 + γ·(d/d_max − 0.5)) · hotspot
factor = 1 + (m − 1)·(w / w̄)          # w̄ = load-weighted mean → Σ pᵢ·(factorᵢ−1) = (m−1)·Σ pᵢ
```

where `β_type` is `GROWTH_BETA_RESIDENTIAL` for `"MV/LV Station"` loads (LV networks — fast, EV + heat-pump led) vs `GROWTH_BETA_INDUSTRIAL` for directly-connected MV industrial (slow); `α` (`GROWTH_HETEROGENEITY`) is a seeded per-bus spread; `γ` (`GROWTH_EDGE_TILT`) tilts growth toward the feeder edge (hop-distance from the HV/MV transformer); and ~20% of buses (`GROWTH_HOTSPOT_QUANTILE`) become adoption hotspots (`GROWTH_HOTSPOT_MULT`). Everything is a pure function of `(scenario, horizon, network structure)`, so it's deterministic. `apply_growth` accepts either a scalar (uniform) or this per-load series.

---

## Config reference (selected)

```python
VOLTAGE_MIN_PU / VOLTAGE_MAX_PU         = 0.9 / 1.1       # feasibility voltage band
LINE_LOADING_MAX_PCT / TRAFO_...        = 100 / 100       # thermal limits
MAX_CONNECTION_MW                       = 20              # intake plausibility cap (20 kV feeder)
W_READINESS / W_NEED / W_STRATEGIC      = 0.5 / 0.35 / 0.15
GROWTH_2030 / GROWTH_2035               = 1.10 / 1.30     # Holistic Transition defaults
FORECASTS                               = ht · ee · he · fb   # NESO FES 2025 pathways
SCORING_MODEL / JUSTIFY_MODEL           = anthropic/claude-sonnet-5.5
JEV_MODEL / DECISIONS_URL               = typesafe/jev-1.13  @  /api/alpha/decisions
```

---

## Tests

```bash
cd packages/optimizer && uv run pytest -q
```

9 tests: base network feasibility, the growth/injection primitives, the greedy accept/defer/reject outcomes and ranking determinism, the per-bus growth average-preservation property, `line_loadings` coverage, and the readiness rubric's bounds and monotonicity.
