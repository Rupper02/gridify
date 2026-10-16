# forecast: how well can we estimate demand on a real network from historicals and weather?

A standalone experiment, kept apart from Gridify. No product, no code structure yet: we run experiments, measure the error,
iterate, and see how good it can get. Whether and how it ever feeds Gridify is decided after the results, not before.

The question, the variables, the method and the validation are fixed **before** results are seen; the results log is
filled in only from runs.

## 1. Question

How accurately can we estimate demand levels at a real supply point from its own history, the calendar and the weather,
and how much of that accuracy survives when we only have the weather **forecast** (what is actually known in advance),
rather than the weather that happened?

## 2. Background

- We want to estimate demand levels from historical data. Planning today uses fixed assumptions (a grown peak, a measured
  minimum, generic per-technology profiles) or last year's observed half-hourly flow. Those are the baselines to beat.
- Weather is the largest driver of demand (heating on cold days, lighting and solar on bright ones) and of embedded
  generation (solar, wind), which is netted off the demand a substation sees.
- What we already know on Bicker Fen: the planning cases sit above the observed 2024 flows (GSP export 301 MW planning vs
  278 MW observed; winter planning import a third above the observed peak).

## 3. Variables

**Dependent (what we measure):** the error of the estimate against observed demand: overall, at the peaks, at the
minimums, and in hours above a threshold. Exact metrics in section 7.

**Independent (what we vary, one at a time where possible):**

| Factor | Levels |
|---|---|
| Model | Baselines (last year's profile, a seasonal average, NGED's generic profiles); then several model families (e.g. linear regression, gradient-boosted trees, a neural network), compared on the same data and splits |
| Weather input | None (calendar only); historical **actual** weather (an upper bound: perfect knowledge); historical **forecast** weather for the zone as it was issued at the time (the realistic case) |
| Weather variables | Temperature, solar irradiance, wind speed, cloud cover, humidity; which ones matter is itself a result |
| Other inputs | Calendar (hour, weekday, season, bank holidays), lags of demand where the horizon allows, the connected generation fleet over time |

**Controlled (held fixed while a factor varies):** the target series and place, the train / test split, the horizon, the
metric.

**To decide before the first run:** the target (net flow at the GSP; at a primary; gross demand if we can separate it) and
the horizon (day ahead, where weather forecasts exist, or year ahead, where only the climate's distribution does).

## 4. Hypotheses

- **H1.** Adding weather reduces the error against a calendar-only estimate, most at the peaks.
- **H2.** Using the weather forecast instead of actual weather keeps most of that gain (the realistic case is close to the
  upper bound).
- **H3.** Some model families beat the baselines and each other consistently across splits; which one, and by how much, is
  a result, not an assumption.

Null for each: no difference beyond the variation across splits.

## 5. Data

**Demand and flows (NGED Connected Data Portal, checked 2026-10-16):**

| Dataset | Span | Resolution | Nature | CKAN |
|---|---|---|---|---|
| Substation loading, every node of the Bicker Fen group | 2024 only | half-hourly | Derived by NGED (PSS/E + sensitivity factors), cleansed, outages imputed; MW and MVAr per bus; demand +, generation − | `substation-loading`, resource `c95d6700-9728-42b3-ac99-f8762b17954c` |
| Branch loading, 164 circuits | 2024 only | half-hourly | Derived from the substation loading | `branch-loading`, resource `d82aeab2-25f2-4157-98ac-ae0412a8b97d` |
| Bus index (bus numbers to LTDS names) | n/a | n/a | | `curtailment_buses`, resource `6ba4ccd6-a9f8-405e-a3cf-45c79de9f16e` |
| Supergrid transformer flows, Bicker Fen GSP | 31 Mar 2022 to 31 Mar 2023 | half-hourly | Metered per transformer: import, generation, demand, voltage (read through `datastore_search`; the download URL is redacted) | `super-grid-transformer-flows-east-midlands`, resource `9ab7426c-e0a9-49bd-9e9e-611ff902b5a6` |
| Live GSP data, Bicker Fen | rolling last ~6 hours | 5-minute | Net demand, generation, import, solar, wind, STOR | `live-gsp-data-east-midlands`, resource `6808c948-f326-43a4-9095-85a1f31fd123` |
| Generic generator profiles, Bicker Fen | 2024 | half-hourly | NGED's per-unit profiles (wind, PV, BESS, other): an assumption, used as a baseline | `generic-generator-profiles`, resource `29fcc7f5-cea6-4b8f-8b50-57b61e2b8939` |

The same datasets exist for other GSP groups (45 curtailment, 15 East Midlands live and SGT). Guidance:
https://dso.nationalgrid.co.uk/downloads/15104/nged-curtailment-analysis-data-usage-guidance.pdf.

**Weather (to find and verify):** historical actuals for the Bicker Fen area (e.g. ERA5 reanalysis, Open-Meteo's archive,
Met Office stations) and **historical forecasts as issued** for the same period (e.g. an archive of numerical weather
prediction runs), so the realistic case uses only what was known at the time.

**History is short.** Node-level demand covers 2024 only; the GSP has 2022/23 (metered transformers) and 2024 (derived),
which are different quantities until reconciled. Archiving the live feed from now on builds a genuine out-of-sample set.
Looking for longer series (other NGED datasets, NESO GSP-level demand) is part of the first step.

## 6. Method

1. Fix the target, place and horizon (section 3) and the success criterion (section 7).
2. Assemble the data: demand series, weather actuals and forecasts, calendar; align time zones and half-hour conventions;
   record every gap and imputation.
3. Run the baselines and record their errors.
4. Add one factor at a time (weather actual, weather forecast, each model family, each weather variable) and record the
   error of every run against the same splits.
5. Iterate: look at where the error is largest (peaks, cold spells, sunny minimums), change one thing, run again. Every
   run goes in the results log, including the ones that do worse.

## 7. Validation (fixed before the first run)

- **Splits.** Never random half-hours (neighbours leak). Within a year: blocked by month (leave-one-month-out). Across
  years where the data allows (the GSP: 2022/23 to 2024). Across places (train on other GSP groups, test on Bicker Fen) to
  see whether the model learns demand in general or one place.
- **Metrics.** Mean absolute error and its percentage; error on the daily and annual peak and minimum; error in the number
  of hours above a threshold; quantile (pinball) loss if the estimate carries uncertainty.
- **Success criterion.** *To decide numerically before results*, e.g. "with forecast weather, beats the best baseline's
  peak error by at least 20%".
- Every result is reported with its training window, test period and data snapshot; a result that misses the criterion is
  reported as such.

## 8. Results log

*Empty until runs exist.* One row per run: date, hypothesis, target, split, inputs, model, metrics, baseline metrics,
criterion met or not, notes.

## 9. Threats to validity

- NGED's node series are derived and imputed: a model may learn NGED's model rather than the grid.
- Net flow mixes demand and embedded generation; "demand" is gross demand only if we can separate them.
- One year of node history: a cold snap or an outage can dominate.
- Actual weather in a backtest overstates what a real forecast achieves (hence the forecast-weather level).
- The connected fleet changes over the period; the ECR's dates are targets, not confirmed energisation dates.
