# forecast: learning how the grid actually behaves

A side project inside the Gridify repo, kept apart from the backbone (`packages/optimizer`, `apps/*`) until it earns its
place. **Status: not started. This file is the kickoff brief: the first session decides the open questions below and
rewrites this file as the project's README.**

## Why

Gridify solves every plan year in two planning snapshots (winter peak, summer minimum) built from assumptions: DFES growth
factors, PV and wind at nil in winter, everything at full export in summer, demand connections at 50% of their import. A
planning engineer already has that picture. What nobody gives them is **how the grid really behaves**: when each element
binds, for how many hours, in which season, and how that changes as connections land.

The idea: a model that learns the patterns of demand and generation on a real network from observed data (open data first,
live sensors later) and produces the profiles Gridify's physics runs on. The prediction should change three decisions:
**what to connect, when, and where the grid is fragile.** The headline it could produce: "you can connect 15 MW here on a
flexible connection and be curtailed ~120 hours a year, mostly summer middays", instead of "full" from one assumed peak.

The owner's goal: a fun project that impresses.

## Ground rules (from the Gridify `AGENTS.md`, still true here)

- The ML model produces **inputs** (demand and generation profiles, with uncertainty). Feasibility stays deterministic AC
  power flow in Gridify. The model never judges a limit.
- Honesty over fake precision: every forecast carries its uncertainty and its training window; state what is not modelled.
- Real data, real units, sources cited (resource ids next to the code that fetches them).
- Lean: the smallest thing that shows the idea working on Bicker Fen.

## Data we already know exists (NGED Connected Data Portal, CKAN API)

| What | Resource | Notes |
|---|---|---|
| Bicker Fen **substation loading**, derived half-hourly net flow per substation node, 2024 | `c95d6700-9728-42b3-ac99-f8762b17954c` | "calculated using the substation loading and sensitivity factors ... PSS/E": derived, not raw metering |
| Bicker Fen **branch loading**, half-hourly per circuit, 2024 | `d82aeab2-25f2-4157-98ac-ae0412a8b97d` | Already checked against the engine: GSP export max 278 MW observed vs 301 MW planning case |
| Bicker Fen **bus index** (maps the series to nodes) | `6ba4ccd6-a9f8-405e-a3cf-45c79de9f16e` | |
| DFES 2025 power projections per supply area | `7686c0a8-bde8-4a4b-8f26-50a3317882ee` | Already bundled (`packages/optimizer/src/gridify_optimizer/data/nged/dfes.json`) |
| LTDS (network, max/min demand per primary), ECR (connected and accepted sites) | see `nged.py` | Already bundled; the builder is `gridify_optimizer.nged` |

Candidates to look for: weather history (temperature, irradiance, wind) for Lincolnshire (e.g. Open-Meteo, ERA5, Met
Office), longer flow history than 2024, NESO national demand and embedded solar/wind estimates, smart-meter aggregates.
CKAN `/download/` URLs sometimes return 403 while the `datastore_search` API works.

## Decisions for the first session

Decide each, with the reason, and write it here:

1. **Dataset.** Which series, which years, which substations. Start: the 2024 half-hourly substation and branch loading
   for Bicker Fen + weather for the same period. Check coverage, gaps and how the series are derived before trusting them.
2. **Inputs (features).** Calendar (hour, weekday, season, holidays), weather, the connected fleet per substation (from the
   ECR), lagged values. Open question: can we separate gross demand from embedded generation in a net flow (the
   disaggregation problem behind-the-meter PV creates)? That is the hard, valuable part.
3. **Model.** Start with an honest baseline (seasonal profile or last-year-same-period, which is what DNOs use), then a
   gradient-boosted model per substation, then something richer only if it beats both. Probabilistic output (quantiles)
   from the start.
4. **Structure.** A Python package under `forecast/` (uv, like the other packages), with fetch → features → train →
   evaluate → export as separate steps; whether it becomes Dagster assets in `apps/pipeline` later is a later decision.
5. **Output.** What Gridify would consume: per substation (primary/BSP node) and plan year, a set of representative
   half-hourly profiles or a full year of half-hours, demand and generation separately, with quantiles. Agree the shape
   before training anything.
6. **Results.** How we know it works: backtest on held-out months against the baselines (MAE / pinball loss on the peak and
   minimum periods that matter for planning, not just average error), and one end-to-end demo: Bicker Fen through Gridify
   with learned profiles vs the planning snapshots, showing hours over limit per element and a curtailment estimate for a
   new connection.

## How it would plug into Gridify (later)

Today a year is `years.evaluate_year`: `plan_net` grows demand (`network.grow_for`) and dispatches by case factors
(`config.GENERATION_FACTORS`). The forecast would add a time-series mode: the same network solved over a profile's
half-hours, loads and generation set from the forecast, reporting hours over each limit. That is a change to the engine
and needs its own decision; the forecast project only has to produce the profiles in the agreed shape.
