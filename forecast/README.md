# forecast: does learning from observed flows tell a planner something the planning snapshots don't?

A side project inside the Gridify repo, kept apart from the backbone (`packages/optimizer`, `apps/*`) until it earns its
place. Written as an experiment: the question, the hypothesis, the method and the success criteria are fixed **before**
any result is seen, and the results section is filled in only from runs.

**Status: not started.** Sections marked *to decide* are decided in the first session, with their reasons, before any
model is trained.

## 1. Question

Gridify judges a plan on two assumed snapshots per year (winter peak, summer minimum), built from published growth factors
and planning dispatch rules. Can a model learned from **observed** half-hourly flows predict how a network behaves (when
and how often its elements approach their limits) better than those planning assumptions and the simple profiles DNOs use,
well enough to change a planning decision?

A result only matters if it would change a decision: where and when to reinforce, whether a connection can go ahead on a
flexible offer, what is really driving the peaks.

## 2. Background

- **Planning practice.** DNOs judge headroom on two conditions (forecast peak demand against capacity; all generation at
  minimum demand); curtailment studies for flexible connections build the year from last year's observed half-hourly flow
  plus contracted generation (ENWL Technical Limits), or from generic per-technology profiles (NGED). Sources:
  `docs/reports/study-basis-2026-10-07.md`.
- **What we already measured.** On Bicker Fen, the planning cases sit above what was observed in 2024: GSP export 301 MW
  (planning) against 278 MW (observed maximum); the Bicker Fen to Boston circuit towards the GSP 106 MW against 85 MW. The
  winter planning import is a third above the observed peak import, because the security condition credits no wind.
- **What is hard.** Net flow hides gross demand and embedded generation (rooftop solar is in no register); the derived
  series are NGED's own model outputs, not raw metering; open history is short.

## 3. Hypotheses (*to decide*: choose one primary, state it falsifiably)

Candidates:

- **H1 (year-ahead behaviour).** A model trained on one year of observed flows, given weather and the change in connected
  fleet, predicts the next year's distribution of net flow at a supply point (in particular the hours above a threshold)
  more accurately than (a) last year's profile and (b) the planning snapshots.
- **H2 (curtailment).** For a new connection at a busbar, curtailment hours computed from learned profiles through power
  flow differ materially from those computed with NGED's generic profiles, and the learned ones are closer to what the
  observed flows imply.
- **H3 (disaggregation).** Net flow at a supply point can be separated into gross demand and embedded generation well
  enough to reproduce the solar and demand split NGED's live feed reports.
- **H4 (transfer).** A model trained on other GSP groups predicts Bicker Fen without its own history nearly as well as one
  trained on it (the model learns grids, not one grid).

The null hypothesis for whichever is chosen: the learned model does no better than the baselines on the pre-registered
metric.

## 4. Data (checked on NGED's Connected Data Portal, 2026-10-16)

| Dataset | Span | Resolution | Nature | CKAN |
|---|---|---|---|---|
| Substation loading, every node of the Bicker Fen group | 2024 only | half-hourly | Derived by NGED (PSS/E + sensitivity factors), cleansed, outages imputed; MW and MVAr per bus; demand +, generation − | `substation-loading`, resource `c95d6700-9728-42b3-ac99-f8762b17954c` |
| Branch loading, 164 circuits | 2024 only | half-hourly | Derived from the substation loading | `branch-loading`, resource `d82aeab2-25f2-4157-98ac-ae0412a8b97d` |
| Bus index (bus numbers to LTDS names) | n/a | n/a | | `curtailment_buses`, resource `6ba4ccd6-a9f8-405e-a3cf-45c79de9f16e` |
| Supergrid transformer flows, Bicker Fen GSP | 31 Mar 2022 to 31 Mar 2023 | half-hourly | Metered per transformer: import, generation, demand, voltage. Download URL redacted; read through `datastore_search` | `super-grid-transformer-flows-east-midlands`, resource `9ab7426c-e0a9-49bd-9e9e-611ff902b5a6` |
| Live GSP data, Bicker Fen | rolling last ~6 hours | 5-minute | Net demand, generation, import, solar, wind, STOR | `live-gsp-data-east-midlands`, resource `6808c948-f326-43a4-9095-85a1f31fd123` |
| Generic generator profiles, Bicker Fen | 2024 | half-hourly | NGED's per-unit profiles (wind, PV, BESS, other): an assumption, not an observation | `generic-generator-profiles`, resource `29fcc7f5-cea6-4b8f-8b50-57b61e2b8939` |
| LTDS, ECR, DFES | editions | | Already bundled in Gridify (`gridify_optimizer.nged`) | |

The curtailment datasets exist for 45 GSP groups; the live and SGT datasets for the 15 East Midlands GSPs. Guidance:
https://dso.nationalgrid.co.uk/downloads/15104/nged-curtailment-analysis-data-usage-guidance.pdf. Still to look for:
weather history (Open-Meteo, ERA5, Met Office), NESO GSP-level demand and embedded-generation estimates, older NGED
editions. **Start archiving the live feed now**: in a year it is a genuine out-of-sample test set nobody else keeps.

What the data allows: node-level history is one year, so year-ahead tests are possible **only at the GSP** (2022/23
metered transformer flows to 2024 derived node flows, once the two are reconciled), and within 2024 only blocked by month.

## 5. Methodology (*to decide*, per the chosen hypothesis)

1. **Target and unit.** The quantity, the place (supply point, circuit), the horizon (next day, next year) and the
   resolution.
2. **Data preparation.** Fetch, align time zones and half-hour conventions, map bus numbers to LTDS names, reconcile
   metered against derived series, document every gap and imputation NGED flags.
3. **Inputs.** Only what is knowable at forecast time: calendar, weather (actual for backtests, stated as such), the
   connected fleet from the ECR at that date, lags where the horizon allows.
4. **Baselines (fixed before any model).** (a) Last year's profile at the same calendar position; (b) NGED's generic
   profiles scaled to the connected fleet; (c) the Gridify planning snapshots, where the target is a peak or a minimum.
5. **Model.** The simplest model that could beat the baselines first; anything richer only if it does. Probabilistic
   output (quantiles) from the start.
6. **Code.** A small Python package under `forecast/` (uv), steps run separately and reproducibly (fetch, prepare, train,
   evaluate), with a fixed random seed and data snapshots pinned by hash.

## 6. Validation (pre-registered before training)

- **Splits.** Year-ahead at the GSP (train 2022/23, test 2024); blocked by month within 2024 (never random half-hours,
  neighbours leak); across places (train on other GSP groups, test on Bicker Fen) for H4.
- **Metrics.** Chosen for the decision, not only on average: pinball loss on the quantiles; error on the annual peak and
  minimum; error in **hours above a threshold** (e.g. 80% and 100% of a rating); for H2, the difference in curtailment
  hours.
- **Success criterion.** *To decide, numerically, before results*: for example, "beats the best baseline on hours above
  80% of rating by at least 20% in the year-ahead test".
- **Checks.** Every result reported with its training window and test period; a result that fails the criterion is
  reported as such.

## 7. Results

*Empty until runs exist.* Each entry: date, hypothesis, data snapshot (hashes), split, metric, baselines, model, result,
and whether the success criterion was met.

## 8. Threats to validity

- The node series are NGED's model outputs (derived and imputed), so a model may learn NGED's model rather than the grid.
- One year of node history: seasonality and one-off events (a cold snap, an outage) cannot be separated well.
- Metered SGT flows and derived node flows are different quantities until reconciled.
- The connected fleet changes between years; the ECR's dates are targets, not confirmed energisation dates.
- Weather in a backtest is the actual weather; a real forecast would have only its distribution.

## 9. Ground rules

The model produces estimates with uncertainty; network feasibility stays deterministic power flow (Gridify). Every figure
states its training window. Real data, real units, sources cited. Lean: the smallest experiment that can falsify the
hypothesis.
