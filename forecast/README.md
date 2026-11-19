# forecast: how well can we forecast tomorrow's demand at a real substation from its history and the weather?

A standalone experiment, kept apart from Gridify (it imports nothing from it and nothing in Gridify imports it). It is
research code, not a product: we run experiments, measure the error, iterate, and see how good it can get. Whether and
how it ever feeds Gridify (as the demand profiles a plan year is solved on) is decided after the results, not before.

The question, the variables, the method and the validation are fixed **before** results are seen; the results log is
filled in only from runs.

## At a glance

- **Task.** Day-ahead, half-hourly demand at Newmarket Primary 11 kV (UK Power Networks), issued at 09:30 the day before,
  from the substation's own meter history, the calendar and the weather forecast as it was actually issued (ECMWF IFS).
- **Result on the held-out year (2025, run once, recomputed independently).** The best model, run 9 (an unweighted
  average of a per-half-hour GAM and a LightGBM model, both fed forecast temperature), scores **4.20% NMAE** (normalised
  mean absolute error) against **5.46%** for the best model without weather: **23% lower**, Diebold-Mariano p ≈ 3e-9,
  block-bootstrap 95% interval 16.7% to 28.4%. That clears the pre-registered "strong" line (20%). Peak-hour error is 43%
  lower. The forecast weather keeps 88% of the gain that the actual weather gives. Zero-shot Chronos-2 with temperature
  (4.40%) comes close; run 9 beats it narrowly (p = 0.04).
- **Carry-over.** Unchanged on Bungay 2025 (a calendar-driven town), the margin is only 6.35%: a miss against the 10%
  pass line, and an honest one. On Bungay and 15 other Eastern primaries drawn by rule (2024 development months, so not
  a test result), a recipe with extra weather inputs (13g) is 12.75% below each site's best no-weather model pooled,
  better at 15 of 16 sites (−5% at Kingsbury to 22% at Kenton; section 9). The experiment was then paused; Timestral and
  the blends ran at three of the 16 sites only, and no second final test has been run.
- **Method.** Section 7: replay day by day with a strict data cut-off (no look-ahead), development and test periods split
  in advance, a frozen specification and code hashes (section 12) before the single test run, every result checked by a
  second session before it was read.
- **Reading the notebook.** Sections 8 onwards are a dated record, kept as written. "The owner" is the human author; "the
  guide session" and "the reviewing session" are separate Claude Code sessions that wrote run specifications before
  runs and recomputed results independently afterwards.

## Code

One script per run or step; the docstring at the top of each names the README section that specified it.

| File | What it does |
|---|---|
| `load.py`, `sites.py` | Load a site's half-hourly demand (every published transformer required) |
| `fetch_weather.py`, `fetch_weather_extra.py`, `fetch_dev_sites.py`, `screen_sites.py` | Download weather (Open-Meteo: ERA5 actuals and every IFS run as issued) and demand; screen and draw the development / held-out sites |
| `train.py` | The day-by-day replay: baselines 0a/0b, LightGBM models, the working model W; `--period dev\|test`, `--frozen`, `--site` |
| `decomposition.py`, `gam.py`, `gam_extra.py` | Run 1a (three-layer decomposition, no weather) and the GAM (with weather) |
| `chronos_run.py`, `timestral_run.py`, `holidays_run.py` | Pretrained zero-shot models (Chronos-2, Timestral-123M), with and without known covariates |
| `ladder.py`, `blend.py`, `carryover.py` | Run 13 (the input ladder), run 15 (fixed blends), run 16 (carry-over to the development sites) |
| `report.py`, `explain.py` | The freeze-specification report (margins, Diebold-Mariano, bootstrap, by month) and SHAP contributions |
| `cache.py`, `tracking.py` | Forecast cache keyed on everything that determines a forecast; local MLflow tracking (telemetry off) |

**Running it.** `uv sync` in this folder, then `uv run python <script>.py` (each docstring gives its command line). The
data is not in the repository: `data/` is git-ignored (UK Power Networks' and NGED's data licences), so the fetch
scripts must be run first, with a UK Power Networks Open Data Portal API key as `UKPN_API_KEY` in `apps/pipeline/.env`
(section 6). Weather needs no key.

## 1. Question

How accurately can we forecast **tomorrow's demand, half-hour by half-hour,** at one real primary substation from its own
history, the calendar and the weather, and how much of that accuracy survives when we only have the weather **forecast**
(what is actually known the day before), rather than the weather that happened?

## 2. Background

- **Where we measure.** The national network hands power to a local network company at grid supply points (GSPs). Below
  them, primary substations ("primaries") each feed a town or a cluster of villages. A GSP's meter sees demand **minus**
  every solar and wind farm in the local network, so forecasting it is mostly forecasting generation. Large farms connect
  above the primaries, so a primary with little generation beneath it sees close to pure demand. That is the target.
- Weather is the largest driver of demand (heating on cold days, lighting on dark ones) and of the rooftop solar netted off
  it. How much it matters at the scale of one town is itself a result (see section 10, Haben et al.).
- Professional day-ahead forecasts exist for the whole of Great Britain: NESO's, made around 08:30 and published between
  09:00 and 09:15 the day before. Under the Grid Code NESO makes its own day-ahead forecast; network operators don't send
  one (OC1.1.3). A network operator's own need is day-ahead flexibility procurement (UK Power Networks; NGED since 31 March
  2026), which wants a forecast of each substation the morning before.

## 3. Decisions

| | Decision | Why |
|---|---|---|
| **Target** | Half-hourly demand at **Newmarket Primary 11 kV** (UK Power Networks, Eastern; Burwell GSP), transformers T1 + T2 summed | The longest metered series that overlaps the weather-forecast archive: UK Power Networks publishes measured half-hours from January 2023, so 2024–2025 can be tested on real meters with forecasts as issued. Of the 80 Eastern primaries that publish power for every transformer every month, it is among the largest (9.9 MW average, 16.4 MW winter peak), has no generator of 1 MW or more beneath it and never reverses, and is clearly weather-driven (winter demand 1.44 × summer, sharp rises in cold spells). A market town, so a result says something about towns in general; race meetings add special days known in advance |
| **Second place** | **Bungay Primary 11 kV** (Eastern; Bramford GSP) | 100% complete 2023–2025, no generation of 1 MW or more, no reversal, but calendar-driven (weekends about 2 MW lower, winter only 1.23 × summer): the contrast that tests whether weather's value depends on the kind of place |
| **Cross-place test** | **Sleaford 11 kV** (NGED, Lincolnshire), April 2019 – March 2021 | Metered, clean, almost no generation; another network company, another county, another period |
| **Horizon** | **Day-ahead**: the 48 half-hours of day D (46 or 50 on clock-change days), UK local time | The timescale of day-ahead flexibility procurement and of NESO's national forecast |
| **Issue time** | **09:30 UK local time on D−1** | After NESO publishes its day-ahead forecast (09:00–09:15), so it can be an input; before the morning deadlines a DNO forecast feeds: the Grid Code's daily 10:00 DNO submission (OC1.5.3) and DSO day-ahead flexibility requirements (10:00 at UK Power Networks) |
| **Data cut-off** | Meter readings up to the half-hour ending 09:00 on D−1; the latest weather forecast run available by 09:30; NESO's 09:00 forecast for D | A DNO control room reads its substations through SCADA in near real time (standard practice; latency unverified). The open data arrives later, which matters only for running this live from open data |
| **Point or range** | Point forecast first; quantiles (a range) once the point models are settled | Flexibility decisions need a range eventually, but a range on a bad point forecast means nothing |

Sources: Grid Code OC1 (Issue 6 Rev 21, https://neso.energy/document/33946/download); NESO day-ahead forecast schedule
(https://neso.energy/data-portal/1-day-ahead-demand-forecast/day_ahead_national_demand_forecast); NGED day-ahead
flexibility (https://dso.nationalgrid.co.uk/news-and-events/latest-news/national-grid-dso-moves-to-day-ahead-flexibility-procurement);
UKPN day-ahead process (https://files.dso.ukpowernetworks.co.uk/app/uploads/2024/04/Day-Ahead-Webinar-Slides-27.03.24.pdf).

## 4. Variables

**Dependent (what we measure):** the error of the forecast against the metered demand (section 7).

**Independent (what we vary, one at a time):**

| Factor | Levels |
|---|---|
| Model | See the lineup below |
| Weather input | None (history and calendar only); **actual** weather (ERA5: the upper bound, a perfect forecast); **forecast** weather from the **00 UTC ECMWF IFS run of D−1** (the realistic case: the run an operator has at 09:30) |
| Weather variables | Temperature first; then cloud cover, solar irradiance, wind speed, humidity, one at a time; which ones matter is a result |
| Other inputs | Added one at a time after the first runs: school holidays, race meetings, NESO's national day-ahead forecast for D (and lockdowns, for Sleaford only) |

**Inputs of the first runs.** Every input must be known by 09:30 on D−1; the column says why it is.

| Group | Input | Why it is in | Known at 09:30 on D−1 because |
|---|---|---|---|
| Calendar | Half-hour of the day (0–47, UK local time) | The daily shape, including the night-storage-heater bump after midnight | The clock |
| Calendar | Day of week | Weekdays against weekends | The calendar |
| Calendar | Time of year, as a smooth yearly cycle (sine and cosine of the day of the year) | The season, without a jump at New Year | The calendar |
| Calendar | Bank holiday (gov.uk list) | Holidays behave like Sundays or stranger | Published years ahead |
| Calendar | Christmas–New Year period (24 Dec – 2 Jan) | The strangest days of the year | The calendar |
| History | Same half-hour on D−2 | The most recent complete day | D−1 is incomplete at 09:30 |
| History | Mean of D−1 from 00:00 to 09:00, only when all 18 half-hours are metered (otherwise missing) | The latest level (a cold spell already underway) | Metered by 09:00 |
| History | Same half-hour on D−7 | The weekly shape | A week old |
| History | Mean of the same half-hour on D−7, D−14, D−21, D−28 | A steadier weekly shape | Weeks old |
| History | Same half-hour on D−364 | Last year's echo, weekday-aligned (364 = 52 weeks) | A year old |
| Weather (runs 2 and 3) | Temperature at each half-hour of D (hourly values interpolated) | The main driver: about 0.25 MW per °C below 15 °C at Sleaford | Run 2: hindsight (ERA5). Run 3: the 00 UTC run of D−1, delivered 05:45–06:12 UTC |
| Weather (runs 2 and 3) | Daily mean temperature of D | Heating follows the whole day's cold, and the daily mean is forecast better (0.56 °C error against 0.7–1.0 °C hourly) | As above |
| Weather (runs 2 and 3) | Heating degrees: max(0, 15.5 °C − daily mean) | Heating starts below about 15.5 °C and is flat above it (the UK heating base temperature; the Sleaford scatter flattens around 15 °C) | As above |

The Previous Runs API's "forecast 24 hours before" value is **not** used: for the evening of D it comes from a run made in
the evening of D−1, after the issue time, which would leak information.

**Model lineup:**

| Role | Model |
|---|---|
| Simple methods (the floor) | Same half-hour on the same weekday last week; the average of the same half-hour and weekday over the past weeks |
| Strong model without weather | The three-layer decomposition of Iftikhar et al. (long-run trend and yearly cycle, weekly and quarterly pattern, residual), one model per half-hour |
| Our models with weather | A **GAM** (additive smooth effects, each one plottable); **LightGBM** (gradient-boosted trees), also as one model per half-hour |
| Reference | **Chronos-2**, a pretrained foundation model, used without training: does a specialist trained on this town beat a generalist that has never seen it? |

A neural network trained from scratch is left out until the trees show a ceiling: the literature (section 10) rarely sees one
win on a few years of one series.

**Controlled (held fixed while a factor varies):** the target, the issue time, the replay periods, the metrics.

## 5. Hypotheses

- **H1.** Adding weather reduces the error against the strong model without weather, most at the peaks.
- **H2.** Using the weather forecast instead of actual weather keeps most of that gain.
- **H3.** Our trained models with weather beat both the simple methods and the strong model without weather.
- **H4.** Our trained models match or beat Chronos-2.

Null for each: no difference, by the Diebold–Mariano test (section 7).

## 6. Data

Raw files live in `forecast/data/raw/` (git-ignored). API keys are in `apps/pipeline/.env` (`UKPN_API_KEY`, and the NGED
token under `NESO_API_KEY`), never printed.

**Demand, UK Power Networks Open Data Portal (CC BY 4.0, credit UK Power Networks):**

| Dataset | Span | Nature | Use |
|---|---|---|---|
| Primary Transformer Power Flow Historic Half Hourly – Eastern Power Networks (`ukpn-primary-transformer-power-flow-historic-half-hourly-epn`) | **1 Jan 2023 – 31 Dec 2025, and Aug–Sep 2026** (checked; the catalogue says "from 2021"; January–July 2026 is not published) | Measured, "not derived", from the historian: report-by-exception readings time-weighted to half-hours. Per transformer: MW and amps; timestamps in UTC; some transformers redacted or amps only | **The target series** |
| Primary Transformer Power Flow Historic Monthly | Jan 2023 – Sep 2026 | Which transformers are published each month, with monthly statistics | Picks fully published primaries |
| Embedded Capacity Register (1 MW and above) | n/a | Generators and where they connect | Picks primaries with no large generation |
| Grid and Primary Sites | n/a | Site coordinates, winter and summer maximum demand | The weather point |

Checked on download (2023–2025): **Newmarket** has 92% of half-hours with both transformers (867 gaps, mostly short, the
longest about 26 hours, in summer 2024), averages 9.9 MW (minimum 4.4, maximum 18.7), never negative, 5% of values repeat
the previous one. **Bungay** is 100% complete, averages 7.6 MW (3.2 to 12.4), never negative.

**Demand, NGED Connected Data Portal (registered users, WPD Shared Data Licence: not to be committed):**

| Dataset | Span | Nature | Use |
|---|---|---|---|
| Primary Transformer Flows, East Midlands | **31 Mar 2019 – 1 Apr 2021** (checked; COVID from March 2020) | Metered import, generation, demand per transformer; UTC, labelled by the half-hour's end; import negative towards customers | Sleaford, the cross-place test |
| Substation loading, Bicker Fen group | 2024 | Derived by NGED (PSS/E + sensitivity factors), cleansed, imputed. Sleaford is bus 46830 (`SLEA5_MAIN1`) | Context only: derived |
| Sleaford BSP Transformer Flows | 31 Mar 2022 – 1 Apr 2023 | Metered, one level up, with solar farms of up to 76 MW | Context only |
| Live Primary Data, East Midlands | the last ~7 days, 5-minute | Metered; Sleaford's file looks like one of its two transformers | Not used yet |

Sleaford (checked): 2.6% missing in 18 whole-day gaps, at most 0.1 MW of generation, 8.0 MW on average, the April–May 2020
lockdown about 12% below 2019.

**Weather (Open-Meteo):**

- **Actual:** the historical archive (ERA5 reanalysis, the best reconstruction of past weather), hourly, at the primary's
  location.
- **Forecast as issued (used):** the Single Runs API, one model run at a time: the **00 UTC ECMWF IFS HRES run of D−1**
  (`https://single-runs-api.open-meteo.com/v1/forecast?...&run=<D−1>T00:00&models=ecmwf_ifs`), archived from
  **14 March 2024** (checked at Newmarket: 13 March refused, 14 March onwards 72 hourly values). Day D in UK local time is
  forecast hours 23–48. ECMWF delivers hours 0–90 of the 00 UTC run between 05:45 and 06:12 UTC
  (https://www.ecmwf.int/en/forecasts/datasets/set-i), before the 09:30 issue time.
- **Forecast, other archives (checked, not used for the scored runs):** the Previous Runs API (the value forecast 24, 48…
  hours before valid time) and the Historical Forecast API (the first hours of each run stitched together, close to
  actual weather).
  - **At Newmarket** the day-ahead temperature starts in **February 2024** (January 2024 absent, 10% of February missing),
    complete from March 2024. It is off by 0.70 °C an hour against ERA5 in 2024 and 0.98 °C in 2025 (0.56 °C on the daily
    mean): the default model changes over the archive, so forecast skill is not constant.
  - **At Sleaford, 2024–2025:** cloud cover off by 22 points, humidity 4.6, wind 2.7 km/h. Solar radiation looked *better*
    two days ahead than one, which can't be skill: ERA5 is a poor reference for sunshine, so solar needs a measured one
    (a weather station or satellite).
  - **For the Sleaford years (2019–2021)** only JMA GSM has day-ahead values: temperature and cloud cover, no solar; its
    temperature is off by 1.0 °C an hour (0.58 °C on the daily mean).

**Other:**

- Calendar: UK bank holidays from gov.uk (`https://www.gov.uk/bank-holidays.json`); Suffolk school holidays; the Newmarket
  racing fixtures (published in advance) if they turn out to matter.
- NESO historic day-ahead national demand forecasts, 2018 to now, about 8 cardinal points a day (peaks, troughs, fixed
  times) with the issue timestamp: NESO API, resource `9847e7bb-986e-49be-8138-717b25933fbb`.

## 7. Method and validation (fixed before the first run)

1. Assemble the data: demand, weather actuals and forecasts, calendar, NESO. Align time zones (UK clocks change twice a
   year) and the half-hour convention (starting or ending). Record every gap and imputation; a missing half-hour is
   never filled and never scored.
2. **Replay day by day (rolling origin).** For each day D in a period: train on everything up to the issue time on D−1,
   forecast D, step one day forward. Models may be refit less often than daily (weekly) to save time; the data cut-off is
   always the issue time.
3. **Three periods (Newmarket):**
   - **Warm-up, January 2023 – February 2024:** training data only, never scored. It gives every model a full year of
     history ("same day last year") before the first scored day, and the forecast archive only starts in February 2024.
   - **Development, 14 March – December 2024:** for choosing features, settings and model variants, with actual and
     forecast weather. It starts on the first day of the ECMWF single-run archive.
   - **Final test, January – December 2025:** a full year, every season, run **once** per model as fixed at the end of
     development. Nothing is chosen by looking at it. August–September 2026 is scored the same way as a later check.
4. **Run plan.** The simple methods first, then one input group at a time. H1 compares the **same** model with and without
   weather, so the gain is weather's alone and not the model's. Every run goes in the results log, including the worse
   ones.

   | Run | Model | Inputs | Answers |
   |---|---|---|---|
   | 0a | Same as last week | Same half-hour on D−7 | The floor |
   | 0b | Recent-weeks mean | Mean of the same half-hour on D−7 … D−28 | A steadier floor |
   | 1a | Three-layer decomposition | Demand history and calendar | The best model without weather from the literature |
   | 1b | LightGBM | Calendar + history (section 4) | Our model without weather |
   | 2 | LightGBM | 1b + actual temperature | H1, best case |
   | 3 | LightGBM | 1b + forecast temperature | H2: the realistic case |
   | 4+ | LightGBM | 3 + one more input each: cloud cover, school holidays, race meetings, NESO's forecast… | What else helps |

   The GAM and Chronos-2 follow the same ladder once LightGBM's has run.

5. **Training examples and refits.** One row per half-hour of D, with that half-hour's inputs; **one model** learns all 48
   half-hours (it sees the most data; 48 separate half-hour models are a later one-factor step). Refit **weekly**, every
   Monday at the issue time, on everything up to then; the week's forecasts use that fit. Features never look past
   09:00 on D−1, whatever the refit day.
6. **Scored half-hours.** A half-hour of D is scored if it is metered and every model in the comparison forecasts it;
   for the weather runs, only on days whose forecast run of D−1 exists. Every model is scored on the same half-hours.
   The daily peak error uses only days with every half-hour metered (48, or 46 or 50 on clock-change days). (Changed on
   2026-11-11 from whole days only, which left 54 of 293 development days; see the lab notebook.)
7. Iterate in the development period only: look where the error is largest (peaks, cold spells, sunny afternoons, holidays),
   change one thing, run again.
8. The models fixed on Newmarket are then run unchanged on Bungay (2025) and Sleaford (replay over April 2020 – March
   2021 after a year of warm-up), to see whether the method, not just one fit, carries over.

**Metrics:**

- **MAE** in MW over every half-hour, and **NMAE**: MAE divided by the mean demand of the period. Not MAPE: demand at a
  primary with rooftop solar can approach zero, and percentage errors explode there.
- **Peak error:** the error on each day's highest half-hour; and the high-demand NMAE of Chattopadhyay et al. (section 10),
  so our numbers sit next to theirs.
- Pinball loss once quantiles are added.

**Success criterion:** with **forecast** weather, the best of our models has a whole-day NMAE on the final test below the
best model without weather (the strong model or a simple method, whichever is better) by:

- **at least 10%: pass**;
- **at least 20%: strong**;

and the Diebold–Mariano test rejects "no difference" at the 5% level. The peak error is reported against the same two
levels as a second check. A result that misses is reported as such, with the number.

Every result is reported with its training window, test period and data snapshot.

## 8. Lab notebook

What was done, in order, before and between runs. Decisions go in sections 3–7; this records how we got there.

- **2026-10-17. Brief and target.** Day-ahead chosen over year-ahead: a weather forecast exists for tomorrow, so H2 can be
  tested. A primary chosen over a GSP: a GSP's net flow is mostly generation.
- **2026-10-17. NGED data.** Primary Transformer Flows (East Midlands) need a registered account; downloaded Sleaford and
  Ingoldmells. Span 31 Mar 2019 – 1 Apr 2021, not continuing; the 2024 substation loading is derived; the live feed keeps
  7 days. Sleaford plotted (`data/plots/1_two_years.png` to `4_one_week.png`): about 0.25 MW per °C below 15 °C, flat
  above; a night-storage bump after midnight in winter; the evening peak steady within a week whatever the temperature;
  winter lockdowns did not lower demand.
- **2026-10-17. Weather forecast check.** Day-ahead temperature off by 0.75 °C an hour at Sleaford (2024–2025), 0.46 °C on
  the daily mean; cloud cover by 22 points. ERA5 unsuitable as the reference for solar.
- **2026-10-17. Other network companies.** UK Power Networks (Eastern) publishes measured primary half-hours from January
  2023 to the previous month (January–July 2026 missing); SP Energy Networks a rolling 12 months; Northern Powergrid, SSEN
  and Electricity North West nothing comparable at primary level. Target moved to Newmarket (`data/plots/5_ukpn_towns.png`).
- **2026-10-17. Forecast leak found and fixed.** The Previous Runs "24 hours before" value comes, for the evening of D, from
  a run made after the issue time. Replaced by the 00 UTC ECMWF run of D−1 from the Single Runs API (from 14 March 2024);
  the development period now starts that day.
- **2026-10-21. Newmarket loaded (`load.py`).** T1 + T2 summed per UTC half-hour, missing unless both transformers
  reported (counting a missing one as zero gave a fake 2.68 MW minimum). 2023–2025: 52,608 half-hours, 48,411 complete
  (92.0%), in 867 gaps, the longest 53 half-hours (29–30 June 2024). Relabelled in UK local time from a gap-free UTC
  grid: the three spring clock-change days have 46 half-hours, the three autumn ones 50. Mean corrected to 9.9 MW in
  sections 3 and 6: the 9.8 on download came from the whole file, Aug–Sep 2026 included (about 8.0 MW). Open: whether
  UK Power Networks labels a half-hour by its start or its end (one row of leakage at the cut-off if read wrongly). (Superseded: see the audit entry of 2026-11-11; no leakage under either convention.)
- **2026-11-11. First runs (0a, 0b, 1b) on the development period (`train.py`).** Half-hours taken as labelled by their
  start (the file runs 00:00 to 23:30 on whole days), so the last reading used on D−1 is the one labelled 08:30. LightGBM
  settings fixed before the run, not tuned (500 trees, learning rate 0.05, 31 leaves, squared-error objective). Only 54 of
  293 days scored: 166 days miss at least one half-hour (median 5 missing, 52 days miss only 1–2), spread over every month
  (13–23 a month from April), and 73 more lack a complete D−7 for run 0a. The scoring rule (section 7, step 6) leaves the
  development period too thin to choose between variants; how to handle it is the next decision.
- **2026-11-11. Scoring changed to half-hours (section 7, step 6).** Every half-hour that is metered and forecast by every
  model is scored, the same half-hours for each model; nothing is filled. The daily peak error stays on complete days.
  Decided before any 2025 result exists. Rerun: 11,482 half-hours on 292 of 293 days; 1b stays well ahead of both floors.
- **2026-11-11. Weather downloaded (`fetch_weather.py`).** Weather point: Newmarket Primary, 52.2422 N 0.3954 E (UKPN Grid
  and Primary Sites). ERA5 hourly temperature Dec 2022 – Dec 2025, and all 657 00 UTC ECMWF IFS runs from 14 March 2024
  to 30 December 2025 (none missing; 168 hourly values each). Hourly values are interpolated linearly to half-hour starts.
  14 March 2024 is unscored in the weather batch: its run (13 March) is not archived.
- **2026-11-11. Runs 2 and 3 share one model.** It is trained with ERA5 temperature on every row since January 2023; run 2
  predicts D with ERA5, run 3 with the 00 UTC run of D−1. So the gap between them is the forecast error's alone (H2), and
  run 3 can start in March 2024 although the forecast archive gives it no training history. Caveat: live, ERA5 arrives
  about five days late, so the last days before each refit would be missing from training (section 11).
- **2026-11-11. Run 1a (`decomposition.py`), specified before running.** Per slot: one least-squares fit of a linear
  trend, two yearly sine/cosine pairs, day of week, bank holiday and Christmas period (layers 1 and 2 together), then an
  AR(7) on the slot's daily residuals (layer 3), one day ahead for slots before 09:00 and two after. Gaps are skipped when
  fitting; in the forecast an unmetered lag counts as zero residual. Weekly refit like the others. Least squares in numpy,
  not statsmodels: its autoregression cannot skip gaps. Result: 1a beats LightGBM without weather (5.56% against 6.24%
  NMAE) with LightGBM's untuned settings; the bar for the success criterion is 1a.
- **2026-11-11. Runs 4a–4c: the history inputs 1a has and LightGBM lacked**, added one at a time, each run without weather
  (against 1a) and with forecast weather (against run 3). Same slot on D−1 before 09:00 helped a little (4a); D−3…D−6
  added nothing (4b); a trend term hurt badly (4c), because a tree cannot extrapolate past the dates it was trained on.
  The gap to 1a stays (6.09% against 5.56% without weather), so missing lags were not the reason. Likely reason, not yet
  tested: 1a forecasts the deviation from each slot's expected pattern; LightGBM predicts the raw level from raw lags.
  Seven comparisons on one development period: the 4a gain (p = 0.044) is weak evidence.
- **2026-11-11. Run 5a: LightGBM on the deviation from a past-only normal**, specified before running: normal = mean of the
  same slot on D−7…D−28 (run 0b), inputs as 4a, the model learns demand minus normal. Worse than 4a, with and without
  weather (6.54% and 5.26% NMAE). That normal lags the season by about two and a half weeks and carries four days' noise,
  so the deviation from it is harder to learn than the level. 1a's normal is a smooth fitted curve; that is the variant
  still untested.
- **2026-11-11. Methodology review (a second session acting as reviewer; the owner approved its flags and the order).**
  Six flags: the DM test treated days as independent; d364 is in only 15% of the earliest training rows (data starts
  January 2023); with one year of history the day-of-year inputs can act as a date stamp; training objective (squared
  error) and metric (MAE) disagree; LightGBM's settings are untuned, so "1a beats LightGBM" means against these
  settings, not that trees under-use the history; runs 2–4 train on ERA5 and predict from forecasts (train/serve skew,
  0.74 °C mean absolute difference at Newmarket), so a run trained on the IFS runs as issued is still owed. No leakage
  found in the features, the replay or `decomposition.py`.
- **2026-11-11. DM test corrected, before anything touches 2025.** Daily loss differences are autocorrelated (cold spells
  last days) and slots from 09:00 are two days ahead, so the variance is now Newey–West (Bartlett weights, 7 daily lags)
  with the Harvey–Leybourne–Newbold correction for h = 2, p from t with n − 1 degrees of freedom. Re-reported: 1a vs 0a
  7.62 (p ≈ 4e-13); 1b vs 1a −3.98 (p ≈ 9e-5); 2 vs 1b 4.69 (p ≈ 4e-6); 3 vs 1b 4.66 (p ≈ 5e-6); **3 vs 1a 1.92
  (p = 0.056, was 0.003)**; 3 vs 2 −1.37 (p = 0.17); 4a vs 3 1.92 (p = 0.056); 4a vs 1a 2.17 (p = 0.031); 4b vs 3 0.82;
  4c vs 3 −2.07 (p = 0.04); 5a vs 4a −3.20 (p = 0.002). The large effects survive; run 3's lead over 1a is no longer
  significant at 5% on the development period.
- **2026-11-11. Run 6a, flag checks.** The deviation from 1a's fitted layers (refit each Monday) did not help (6a vs 4a
  p = 0.32). The deviation idea is not shown to help in the two forms tried, both of which changed only the target:
  the history inputs stayed raw levels, so the trees still had to rebuild the normal and subtract it from each lag
  themselves (1a's third layer regresses deviations on deviations; on 1a's own residual, 500 trees with raw-level lags
  lost to a 7-coefficient AR: 6a 6.32% against 1a 5.56% without weather); and the normal is an in-sample fit for
  training rows but an extrapolation for forecast rows. Dropping d364 helped slightly, not significantly. The
  absolute-error objective helped significantly with and without weather (4a L1: 4.67% NMAE, 16% below 1a,
  p = 0.0006), the first change without new inputs that clearly works. Under the corrected test, run 3's lead over 1a
  (p = 0.056) did not clear the 5% bar on development data; 4a L1's does. Next: SHAP on 4a L1, then the GAM.
- **2026-11-11. Owner decisions, rules written before the results.** (1) A fixed 50/50 average of 1a and 4a L1, nothing
  fitted, with and without weather, scored on the batch's half-hours, DM against 1a, 4a L1 and each other. (2) Working
  model rule: 4a L1 without d364 replaces 4a L1 if it is not significantly worse under the corrected DM test (two-sided
  p ≥ 0.05, or better) and its NMAE is within noise; the simpler model is kept when an input is not shown to help. SHAP
  then moves to the working model. (3) A forecast cache, with a no-cache full replay that must reproduce it before
  anything is frozen for 2025 and after any change to shared code. Run 6b (lags as deviations too) is held until after
  SHAP and the GAM.
- **2026-11-11. Tooling: MLflow tracking, a forecast cache, one hang.** Runs are logged to a local MLflow store
  (`tracking.py`, `data/mlflow.db`; telemetry to MLflow's developers switched off). Forecasts are cached (`cache.py`),
  keyed on the model spec, fingerprints of every input column read, the source of `replay` and `decomposition.py`, the
  LightGBM version and a manual `CODE_VERSION`; `train.py --no-cache` refits everything. The first tracked replay froze
  inside LightGBM (`Booster.update`) at run 5a's 18th refit (training up to 15 July 2024), all cores busy, no progress
  for over seven minutes; killed. That refit and its neighbours trained in 1.4–2.4 s in isolation, with and without the
  per-tree logging. Nothing else heavy was running (six other Python processes, under 7 CPU-seconds between them). Cause
  not proven; likely LightGBM's threads spinning on Windows. The machine (Intel Core Ultra 7 265U) is hybrid: 2
  hyperthreaded performance cores and 10 efficiency cores, 14 logical processors, so LightGBM's default of 14 threads
  makes every tree wait for the slowest core. If it recurs, or for speed: time one refit at `num_threads` 4, 6, 8, 10
  and the default (three repeats, nothing else running), pick the fastest stable one, decide it once (it changes every
  cache key), and check that two or three models' forecasts are unchanged. The GPU and NPU are not used: the NPU cannot
  train, and LightGBM's GPU mode is slower on this little data and changes the numbers.
- **2026-11-11. Reproducibility checks passed.** The tracked replay (which also filled the cache) against the untracked
  one: all 21 forecast columns identical on the 11,434 scored half-hours (largest difference 0.0). The rerun from the
  cache against the tracked replay: identical again, and every printed metric and DM value the same; 12 s instead of
  about 27 min.
- **2026-11-11. SHAP on 4a L1 with forecast temperature (`explain.py`).** Exact per-forecast contributions from LightGBM
  (`pred_contrib`), each weekly model explaining the week it forecast from IFS inputs (`data/plots/6_shap_first_last_refit.png`,
  `7_shap_by_refit.png`, `data/runs/shap_4a_l1.csv`). Mean absolute contribution: same slot on D−2 0.4–0.9 MW and the
  4-week mean about 0.5 MW lead, then the half-hour of the day. Temperature contributes most when the weather departs from
  the recent past: the May warm-up (about 0.3 MW) and the mid-November 2024 cold snap (0.6 MW), near 0.1 MW in steady
  spells, where the lags already carry it. d364 stays small: 0.02 MW at the first refit (in 15% of training rows) and 0.08
  MW at the last. The day-of-year inputs grow through the year (doy_sin 0.2–0.28 MW in September–October, doy_cos 0.23 MW
  at Christmas): consistent with a date stamp learned from 2023 (flag 3), but not distinguishable here from seasonality;
  an ablation would settle it.
- **2026-11-11. Working model and the average.** 4a L1 without d364 is within noise of 4a L1 (p = 0.85 without weather,
  0.55 with), so under the rule recorded before the result it becomes the working model: 4.64% NMAE with forecast
  temperature. The fixed 50/50 average of 1a and 4a L1 is the best model without weather (5.49%, not significantly better
  than 1a, p = 0.27, but clearly better than 4a L1, p ≈ 3e-6): the two models' errors partly cancel, so 1a carries
  information the trees miss. With forecast temperature the average loses to 4a L1 on peaks (0.565 against 0.477 MW),
  since half of it ignores the weather. Against the best model without weather (the average), the working model is 15%
  lower in NMAE (DM 3.45, p = 0.0006): pass level, not strong, on development data. That 1a still adds information is the
  gap the held run 6b would test.
- **2026-11-11. Next steps and their rules, written before running (owner-approved order).**
  - **Run 7: the GAM (Generalised Additive Model), specified here and not tuned on the result.** 1a's structure with
    weather added, one model per slot like 1a (each slot's daily shape and its own temperature response; one pooled
    model would need slot × temperature interactions to do the same). Per slot, least squares on 1a's layers 1 and 2
    (trend, two yearly sine/cosine pairs, day of week, bank holiday, Christmas) plus two smooth temperature terms: a
    cubic regression spline of the daily mean temperature of D (heating below about 15 °C, any cooling above) and one of
    the slot's own temperature, each with knots at the 20/40/60/80% quantiles of its training values (seven basis
    functions each once the constant is absorbed). Temperatures outside the training range are clamped to its ends, as a
    spline cannot extrapolate. Then 1a's AR(7) on the slot's daily residuals, one day ahead before 09:00, two after.
    Unpenalised regression splines, so no smoothing parameter to choose. Library: numpy least squares with scipy
    `BSpline.design_matrix` (scipy 1.17.1); no GAM package. Training uses ERA5; the forecast uses the IFS 00 UTC run of
    D−1 for D and ERA5-based residuals for the AR lags (past days). Gaps: days without the slot's reading or temperature
    are skipped in fitting, never filled; an unmetered AR lag counts as zero residual, as in 1a. Weekly Monday refit,
    same cut-off, same scored half-hours, cached. Without weather the GAM is 1a by construction, so 1a stands as its
    no-weather version. Compared under the corrected DM test with 1a, the no-weather average and the working model.
  - **Run 8a: lag-day temperature on the working model, weather version only.** Adds dtemp_d2 (daily mean temperature
    of D minus that of D−2) and dtemp_d7_28 (D minus the mean of the daily means on D−7, D−14, D−21, D−28), differences
    because trees cannot subtract columns. Trained on ERA5; predicted with D from the IFS run of D−1 and the past days
    from ERA5. Rule: adopted only if NMAE is lower and the corrected DM test against the working model is significant at
    5%.
  - **Run 8b: the working model without doy_sin and doy_cos, with and without weather (flag 3).** Rule: dropped if not
    significantly worse (as for d364). If the no-weather version gets clearly worse and the weather version does not,
    the date-stamp reading is confirmed (day of year standing in for weather).
  - If 8a and 8b both change the working model, their combination runs once before it is called the working model.
  - **Run 9:** a fixed 50/50 average of the GAM and the working model, with forecast temperature and without weather;
    DM against each member and the current best; peak error reported.
  - **Run 10 (flag 6):** the working model trained on the IFS runs as issued (from 14 March 2024) instead of ERA5,
    reported over the development period and separately for its last three months.
  - Then a stop: the candidate to freeze goes to the owner. 6b stays held. The d1_morning change alters an input of every
    model, so it is not a one-factor run; it stays queued.
- **2026-11-11. GAM code check.** With its two temperature terms switched off, `gam.py` reproduces 1a exactly (14,064
  forecasts, largest difference 0), so its fitting, AR and refit logic match `decomposition.py`.
- **2026-11-11. Runs 7–9.** The GAM (4.71% NMAE, 0 rank-deficient fits out of 2,064) ties W (4.64%, p = 0.91) and has
  the lowest peak error of any single model (0.434 MW). By quarter of the development period it is weaker than W in the
  first weeks (March: 4.85% against 4.21%) and in Q4 (4.99% against 4.62%), better in Q2 (4.39% against 4.91%). Its
  fitted temperature curves (`data/plots/8_gam_temperature_curves.png`) are not the temperature effect: at 12:00 the
  daily-mean term rises about 6 MW towards 25 °C while the slot-temperature term falls about 5 MW over the same range,
  and the 18:00 daily-mean term is U-shaped. The two terms cancel (the collinearity caveat); only their combination is
  meaningful, and the forecasts are unaffected. Run 8a (lag-day temperature) was not adopted (p = 0.11, NMAE higher).
  Run 8b: dropping day of year leaves the no-weather model unchanged (p = 0.66) but hurts the weather model (p = 0.036),
  so day of year is kept; flag 3's date-stamp reading is not supported on this evidence. Day of year carries something
  temperature does not, most likely daylight. W stays the working model, so no combination run. Run 9, the fixed 50/50
  average of the GAM and W, is the best so far: 4.41% NMAE, peak MAE 0.409 MW, better than both members (p ≈ 4e-5 and
  0.0002), and 19.78% below the best model without weather (DM 4.83, p ≈ 2e-6): pass, 0.2 points short of strong, on
  development data.
- **2026-11-11. Independent audit by the reviewing session (read-only).** Leak test: replacing every reading from 09:00
  on D−1 with 1e6 for 24 development days (clock-change days included) changed no history input of day D; corrupting
  from 08:30 moves d1_same and d1_morning, so the test can fail. 1a and the metrics recompute exactly; its own DM
  matches. The IFS files are forecasts as issued (each starts at its own 00 UTC; error against ERA5 grows with lead
  day: 0.61, 0.75, 0.89, 1.07 °C...). Findings: (1) most of the ERA5–IFS gap is two datasets disagreeing, not forecast
  error: at lead day 0 they already differ by 0.61 °C, at lead day 1 by 0.75 °C, so "run 3 keeps 92% of run 2's gain"
  understates what a forecast keeps; H2 needs that caveat, run 10 may match run 2, and a cleaner "actual" weather would
  be the IFS analysis. (2) d1_morning is partial on a third of development days (all 18 slots on 195 of 293, 10–17 on
  78, 2–8 on 16, none on 4); fixing it is a re-baseline of every model, for the owner to decide before the freeze. (3)
  The GAM curves cancel (above). (4) The label question cannot cause leakage with the current code: under either
  convention the row labelled 08:30 ends by 09:00; only a half-hour alignment against temperature and the day boundary
  is at stake (the open item of 2026-10-21 overstated it). (5) `explain.py` refits with its own copy of the training
  logic; it should take the model from a shared function when next touched, so SHAP cannot drift from the scored model.
  Not verified by the audit: the literature and portal claims in sections 2, 6 and 10, ECMWF's delivery times, and the
  cause of the LightGBM hang.
- **2026-11-11. Owner decision: fix the audit findings, then one re-baseline, rules written before the result.**
  d1_morning becomes the mean of D−1's 18 morning half-hours only when all 18 are metered, otherwise missing (LightGBM
  takes a missing input; nothing is filled): a mean over whichever slots survive changes with which slots those are, a
  different quantity on a third of days. d1_same is per slot and unaffected. This corrects an input, so the new numbers
  replace the old as the baseline whatever they are; if the working model gets significantly worse (corrected DM, 5%),
  the owner decides on a composition-corrected mean instead. `explain.py` now trains through the same function as the
  replay and explains the working model. The GAM gets a combined-effect plot. The re-baseline refits every LightGBM
  model and the GAM (their code or an input changed). Run 10 follows on the new input. The full refit started earlier for run 10 was stopped before finishing, so there is no pre-fix run 10.
- **2026-11-11. Re-baseline and run 10.** Every model refit (the LightGBM keys changed with `replay`, the GAM's with
  `gam.py`, 1a's when `replay`'s hash left the shared key); the models that do not read d1_morning (0a, 0b, 1a, the GAM)
  came out identical, a no-cache check for them. W moved from 4.64% to 4.69% with forecast temperature, not
  significantly (p = 0.43), so the new numbers are the baseline and W stays. The best model without weather is now the
  0.5 × 1a + 0.5 × W average (5.553%), and run 9 sits 20.33% below it (DM 4.74, p ≈ 3e-6): just past the strong line on
  development data, with a margin of a third of a point that the re-baseline alone moved by half a point, so read it as
  "at the line", not clear of it. The GAM's combined temperature effect (`data/plots/9_gam_combined_temperature_effect.png`)
  is heating physics: demand falls about 0.2 MW per °C up to 12–17 °C and is flat above, with a slight rise near 25 °C,
  the same at the first and last refit. Run 10, W trained on the IFS runs as issued, is much worse (6.06% overall,
  6.41% in October–December, against W's 4.65% and 4.64% on the same half-hours). It removes the ERA5–IFS mismatch, but
  it also loses all of 2023: it trains on at most nine months, against fourteen to twenty-three for W, with no summer
  or autumn behind it until the end of the period. The two effects are confounded, so this does not show that IFS
  training is worse, only that a forecast-trained model with this little history is. A run trained on ERA5 before 14
  March 2024 and IFS after would separate them; not run. No model trained on ERA5 and predicting from ERA5 exists with
  W's inputs (run 2 has 1b's), so run 10 cannot be set against "run 2 for W".
- **2026-11-11. Re-audit of the re-baseline (reviewing session, read-only): every check passes.** Same scored index,
  no missing values; 0a, 0b, 1a and the GAM unchanged, every LightGBM column changed; all 30 NMAEs, the run 9 blend
  identities and the DM values reproduced independently; the leak test passes with the new d1_morning (present on 195 of
  293 development days, all-18-or-missing on every day). Two measurements from that audit:
  - **How firm the 20.33% is.** A moving-block bootstrap over days (7-day blocks, 4,000 resamples) of run 9's margin
    over the best no-weather model gives a median of 20.0% and a 95% interval of 13.9% to 25.8%; half the resamples
    reach 20%. On development data, strong against pass is a coin flip; pass (10%) is clear.
  - **Where the margin comes from.** By month: March 10%, April 43%, May 17%, June 11%, July 2%, August 5%, September
    10%, October 22%, November 27%, December 19%. Weather adds almost nothing in high summer and most in the shoulder
    and heating months.
- **2026-11-11. Run 11: Chronos-2 (H4), specified before running.** Zero-shot, no training or fine-tuning on Newmarket.
  Package `chronos-forecasting` 2.3.2 (PyPI, 8 September 2026; PyTorch 2.15.0 CPU), model `amazon/chronos-2` (120M
  parameters, Apache-2.0), Hugging Face revision recorded in the cache key and here when downloaded; API
  `Chronos2Pipeline.predict_quantiles` with `cross_learning=False`, CPU. The model outputs quantiles directly (no
  sampling); the point forecast is the 0.5 quantile. For each development day D, on the UTC half-hour grid: the context
  is every half-hour before 09:00 local on D−1 (so it ends with the reading labelled 08:30), at most the model's
  context length of 8,192 half-hours (about 170 days; always shorter than the history available, so the maximum is
  used); the forecast runs from 09:00 on D−1 to the end of D, and only D's half-hours (mapped back to local time, 46 or
  50 on clock-change days) are scored. Missing readings stay missing: Chronos-2 builds its context mask from NaN
  (`model.py`, "the context_mask will be automatically constructed based on the NaN values"; it left-pads with NaN), so
  gaps are passed as NaN, nothing filled. Two versions: 11_nw, demand history only; 11, plus the half-hour temperature
  as a known-future covariate (`past_covariates` from ERA5 over the context, `future_covariates` from the IFS 00 UTC run
  of D−1 over the forecast window, the split the other weather runs use; supported per the model card). Scored in the
  batch if it forecasts every scored half-hour, otherwise separately as run 10 was. Run time recorded (the cost of a
  daily live run). H4 reading rule, before the result: compare run 9 with the better of 11_nw and 11 by NMAE; H4 holds
  if run 9's NMAE is not higher; the corrected DM says whether the difference is distinguishable.
  Caveat, recorded before the result: our models are told about bank holidays and the Christmas period; Chronos-2 as
  specified sees only demand (and temperature). That is the fair zero-shot reading of H4 (a generalist that has never
  seen this town against a specialist), but a holiday-heavy week is not like for like. A version with the two calendar
  flags as known-future covariates would be the one-factor follow-up, for the owner to decide.
- **2026-11-11. Run 11 checks and result.** Checks on 31 March (spring clock change), 10 July and 27 October (autumn),
  both versions: every reading from the cut-off onwards set to 1e6 left the forecasts for D identical (no leak through
  the new context code); repeated runs identical; contexts with 342, 696 and 1,145 missing half-hours gave finite
  forecasts with no NaN; 46, 48 and 50 half-hours returned as the clock changes require; the library emitted no
  warnings. Model revision `29ec3766d36d6f73f0696f85560a422f50e8498c`. Run time on this CPU (Core Ultra 7 265U, PyTorch
  2.15.0 CPU): 1,538 s for 293 days, 5.2 s per forecast day for both versions (6–7 s per day when run one day at a time;
  the first call also downloaded the model, 88 s). It forecast every scored half-hour, so it is scored in the batch,
  which is unchanged (every other column identical). Result: 11_nw 5.81% NMAE, 11 with temperature 4.85% (peak 0.616
  MW). H4, by the rule recorded before the run: run 9 (4.42%) against the better Chronos version (11, 4.85%): run 9's
  NMAE is lower and the DM test distinguishes them (−3.10, p = 0.002), so H4 holds on development data. Zero-shot
  Chronos-2 with temperature is within noise of W (p = 0.30) and the GAM (p = 0.27) on NMAE, a strong showing for a
  model that never saw Newmarket, but clearly worse on daily peaks; without weather it does not beat 1a (p = 0.12).
- **2026-11-11. Freeze mechanics proven.** The scoring period is now a parameter (`--period dev|test`) and `--frozen` runs
  only the models named in section 12. `train.py --period dev --frozen --no-cache` recomputed every frozen model from
  scratch and reproduced the development forecasts exactly (largest difference 0.0 in all eleven columns, same 11,434
  half-hours). Chronos-2 took 455 s this time (1.6 s per day, both versions) against 1,538 s in run 11; the first figure
  was probably slowed by other load on the machine, so a daily live run costs a few seconds either way. W fed ERA5 (the
  H2 counterpart proposed for 2025) scores 4.65% on development data against W's 4.69% (DM −0.70, p = 0.49). The freeze
  specification is section 12.
- **2026-11-11. Freeze specification confirmed by the owner** (asked directly in this session as well as through the
  reviewing session), with W fed ERA5 in the 2025 list; section 12 is final. The single 2025 run follows.
- **2026-11-11. An interrupted start of the 2025 run (no result produced).** The owner started `train.py --period test`
  by hand at about 18:06 and stopped it at about 18:20, after the code hashes were last checked equal to section 12
  (about 18:00) and before any scoring: no `test_runs_frozen.csv`, and MLflow holds only training-loss metrics, no
  error against 2025 actuals. It left four 2025 forecasts in the cache, made by the frozen code and reused by the run
  that follows: 1a `3f308f4a41938eb0d3669649` (18:06:55), the GAM `6903db4280e2fdf23b232c4d` (18:07:10), Chronos-2
  `4d7b76f2c2088ef1237474e2` (18:18:44) and W without weather `d1279ae5eee83355d3162567` (18:20:37). Its MLflow entries
  are marked KILLED. Its two `_test` plots were not opened; the completed run redraws them.
- **2026-11-11. The 2025 final test, run once.** Started from this session as a background job after the owner's
  direct go; code hashes at launch equal section 12; it reused the four 2025 forecasts above and fitted W (and W fed
  ERA5) for 2025. Both commands exited normally. Run 9 is 23.02% below the best no-weather model (run 9 without
  weather), DM p ≈ 3e-9, bootstrap 16.7%–28.4%: strong under the criterion; peak-error margin 43.31%, strong. H1, H3 and
  H4 hold; under H2, actual weather is distinguishably better than the forecast (p = 0.0001) and the forecast keeps 88%
  of the gain. January–February, never seen in development, gives a 33.0% margin. Numbers in section 9; sent to the
  reviewing session for independent recomputation before the owner reads them as final. No further runs on 2025.
- **2026-11-11. The 2025 result confirmed independently** by the reviewing session: the output file (sha256
  e8cbc72876e4aa32; 14,818 rows, 365 days, no missing values or duplicate instants; its demand column equals the raw
  series) gives the same NMAE for all eleven models, the same margin (23.02%), monthly table, January–February margin
  (33.05% on 59 days), peak figures (43.31% on 33 complete days) and DM values; a bootstrap with another seed gives a
  median of 22.8% and a 95% interval of 17.0% to 28.2% (84% of resamples at or above 20%). A leak test on 20 days of
  2025 (1 January, both clock changes and the day after each) changed no history input of day D, and 1a rebuilt from
  data cut at 09:00 on D−1 matches the saved forecasts to 1.8e-15. Code hashes still equal section 12. What bounds the
  result: the peak-error check rests on 33 complete days of 365; H4 holds narrowly (p = 0.038), with zero-shot
  Chronos-2 ahead of the GAM and close to W; and H2's 88% includes the ERA5–IFS dataset difference, not only forecast
  error. Next steps (section 7, step 8: Bungay and Sleaford unchanged; the August–September 2026 check; quantiles) are
  the owner's to choose.
- **2026-11-11. The Bungay 2025 carry-over run, run once (section 13).** The owner's go was relayed by the reviewing
  session. Before launch, the model and scoring files (`gam.py`, `decomposition.py`, `chronos_run.py`, `cache.py`,
  `report.py`) equalled section 12; `train.py` (c272eb9ae88b9463) and `load.py` (1fd92f349a58f307) differ from section
  12 only by the reviewed `--site` edits of section 13; the Newmarket 2025 file was unchanged (e8cbc72876e4aa32), and
  no Bungay output or cache entry existed. Background job 21:39–21:50; both commands exited normally, no interruption.
  Raw result in section 13; under the criterion it is a miss (margin 6.35%). Sent to the reviewing session for
  independent recomputation; no reading of it is written until that check is back. No further runs on Bungay 2025.
- **2026-11-11. The Bungay result confirmed independently** by the reviewing session: the output file (sha256
  873a0aeb73db06b0; 17,518 rows, 365 days, no missing values or duplicate instants; its demand column equals the raw
  series) gives the same NMAE for all eleven models, comparator, margin (6.35%), DM values, monthly table,
  January–February margin (16.03%) and peak figures (8.54% on 364 days); a bootstrap with another seed gives a median of
  6.4% and a 95% interval of 2.1% to 11.2%. A leak test on 20 days changed no history input of day D, and 1a rebuilt from
  data cut at 09:00 on D−1 matches the saved forecasts to 3.6e-15. The two unscored half-hours (6 April 2025, 01:00 and
  01:30) have no same local time a week earlier after the spring clock change, as designed. The miss stands. Its
  reading (section 13) is left for the owner to word.
- **2026-11-11. 2025 spent; next test intended; run 12 (Timestral) specified before running** (section 14). Owner's go
  relayed by the reviewing session. UKPN availability checked (January–April 2026 now on the portal, August–September
  2026 no longer returned; 93 Eastern primaries at least 99% complete in 2023–2025 before screening).
- **2026-11-12. Overnight queue (section 14.1), B and C done, run 13 prepared.** Newmarket's extra weather complete
  (ERA5 27,048 hours, no gaps; 293 of 293 IFS runs, 168 values, none missing beyond each run's first hour of
  radiation and precipitation). Site screen built and its two bugs fixed openly (14.1); split drawn under the guide's
  rule: 15 development sites, 14 held out; demand for the 15 downloaded to 31 December 2024 (`sites.py` for
  one-transformer sites; it reproduces `load_demand` on Newmarket exactly). Radiation alignment check (ERA5, 19 July
  2024, the July day with the highest mean radiation, by UTC hour after alignment): zero from 20:00 to 03:00, then 26,
  132, 275, 421, 559, 681, 704, 785, **792** (12:00–13:00), 751, 685, 545, 414, 250, 146, 37 W/m²; 16 zero half-hours;
  the peak hour is symmetric about solar noon at Newmarket (about 12:04 UTC). The IFS run of 18 July gives the same
  shape (peak 759 at 10:00–11:00, afternoon cloud forecast). The IFS extras miss only 14 March 2024 (no run the day
  before; not a scored day).
- **2026-11-12. Run 12 (Timestral) run once and confirmed; run 13 started; item G added.** `timestral_run.py`
  (ff45b89f99de18f8) with Timestral-123M (the size the timing rule picked: 209M was estimated at 4.08 h), background job
  22:57–01:01, 7,392 s predicting (25.2 s a day, both versions), exit 0; output `data/runs/dev_run12_timestral.csv`
  (sha256 ace31c4cd9b66807, 11,434 half-hours, no missing forecast). Recomputed independently by the reviewing session:
  every NMAE, MAE, peak figure and DM statistic matches, the demand column equals the frozen file and the raw series,
  and `dev_runs_frozen.csv` (d1594bff8c35981f) and both 2025 result files are unchanged. Result in section 9. The
  development-site weather fetch stopped once on an empty reply from Open-Meteo after dropped connections (an error
  the frozen `fetch_weather.get_json` does not retry); it was restarted unchanged, skipping finished files. Run 13
  started after run 12. Item G (run 15, two fixed blends with Timestral) specified in 14.1 before it runs.
- **2026-11-12. Runs 13 and 15 run once and confirmed; run 14 started; item H specified.** Run 13 (`ladder.py`
  9e03304ce3ceff02, `gam_extra.py` e14c372c282f77f8) 01:02–01:13, exit 0, output sha256 cfef8ae8c212ff4f; both
  baselines reproduced the frozen columns (largest difference 1.8e-15) before any rung was scored. Run 15 (`blend.py`
  b4fad884c81238af) 01:13, output sha256 5d27b7eede3a8def. Both recomputed independently by the reviewing session: every
  figure matches, and the blends in the file equal its own to 1.8e-15. Results in section 9. Run 14 started about 01:13.
  The reviewing session's decision (overnight delegation, for the owner to confirm): the working candidate is now
  {GAM + radiation day mean, W + the five inputs, Timestral-123M with forecast temperature}, with 13g and 15a as its
  two combinations; item H (run 16, its carry-over to the development sites, 2024 only) specified in 14.1 before
  anything of it runs; item F moves after H.
- **2026-11-12. Run 14 run once and confirmed; run 16 started.** `holidays_run.py` (e42f85909cef598d) with
  `chronos timestral`, 01:13–04:36, exit 0; Chronos-2 1,454 s, Timestral-123M 10,734 s (36.6 s a day against 12.6 s
  in run 12: three covariate rows tripled the time). Output sha256 6837ed9fc27e20f4. Recomputed independently by the
  reviewing session: every figure matches. Result in section 9. The candidate is unchanged. Run 16's Newmarket check
  started straight after.
- **2026-11-12. Run 16: check passed under the amended tolerance (14.1 H); the run was interrupted by a shutdown and
  restarted.** The check ran 04:37–04:56 (console `data/runs/run16_check_console.txt`). The cheap models for Bungay
  and the first six development sites started at 04:57 (`carryover.py` 57e1f5a16ea47d5b). The computer shut down at
  about 06:00. By then three cheap-model files had been saved in full: Bungay 05:16 (1,117 s), Hardwick Rd 05:34
  (1,095 s) and Thompsons Ln 05:52 (1,088 s). Guyhirn was interrupted with no file written and is rerun from scratch.
  The 08:30 report did not go out. At 11:28 the reviewing session checked that the 2025 result files,
  `dev_runs_frozen.csv`, the outputs of runs 12–15, the frozen code and `carryover.py` all have the hashes they had
  before the shutdown. An interim report on the three saved sites (console `data/runs/run16_report0_console.txt`,
  11:23) matches the reviewing session's recomputation; the results go in section 9 once run 16 is complete. The
  chain was restarted at 11:24 in the same order, the consoles appended after a restart marker: the cheap models for
  Guyhirn, Gaywood Bridge, Chelmsford East Local and Kenton, then Timestral for Bungay, then report 1.
- **2026-11-12. Run 16: report 1 confirmed; the remaining sites started; the computer was in standby for about three
  hours.** Report 1 (7 sites with the cheap models, Bungay with Timestral; console
  `data/runs/run16_report1_console.txt`, 13:18) was recomputed independently by the reviewing session, and every figure
  matches; the results go in section 9 with report 2. The 13f masking drops no half-hour at Bungay. The cheap models for
  the nine remaining sites started at 13:19 (console `data/runs/run16_cheap2_console.txt`). The Windows System log shows
  the laptop in Modern Standby from 13:23 to 16:27 (Kernel-Power events 506/507). The job was suspended, not hung, and
  needed no restart. Orton's file is stamped 13:40 (logged as 1,260 s), inside the logged standby window, so Windows
  probably kept the process running for part of it at reduced speed. The times logged in this stretch include the
  standby and are not model cost. The overnight delegation ended with the owner's return; from here the reviewing
  session makes no new decisions on the owner's behalf, and only the already queued items continue.
- **2026-11-12. Run 16 paused by the owner's change of direction (relayed by the reviewing session at about 19:45:
  the experiment is paused and the work now serves Gridify).** The cheap models are complete at all 16 sites. The
  remaining nine sites' cheap models finished at 18:02 (exit 0), and report 2 was confirmed independently and is in
  section 9. Timestral-123M exists for three sites: Bungay (3,900 s), Hardwick Rd (3,732 s) and Thompsons Ln (3,823 s,
  saved 20:08; sha256 b62c726faa4e1e5b, 8e943d7bbd866898, 497b06f23ab3708a). The last report, written after Thompsons
  Ln, is `data/runs/run16_report_after_thompsons_ln_primary_11kv.txt`. Stopping the chain at 20:09 did not kill its
  child processes at first. The loop started Timestral for Guyhirn and then Gaywood Bridge, and both were killed by
  hand within seconds; no file was saved for either. A report file was written in between,
  `run16_report_after_guyhirn_primary_11kv.txt`, and is identical to the Thompsons Ln report apart from its header; it
  is kept, not deleted. The console notes the stop. The other 13 sites have no Timestral run, by the owner's choice,
  not for any result, and can be resumed later site by site with `uv run python carryover.py timestral KEY`. The 14
  held-out sites and all 2025 and 2026 data remain untouched, and no final test has been run.
## 9. Results log

One row per run: date, hypothesis, target, period, inputs, model, metrics, baseline metrics, criterion met or not, notes.
Metrics are on the same scored days for every row of a batch.

| Date | Run | Hypothesis | Target | Period (scored) | Inputs | Model | MAE | NMAE | Peak MAE | Against the baselines | Criterion | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-11 | 0a | floor | Newmarket | dev, 14 Mar – 31 Dec 2024 (54 days, 2,594 half-hours, mean 9.69 MW) | D−7 | same half-hour last week | 0.743 MW | 7.67% | 0.924 MW | n/a | n/a | |
| 2026-11-11 | 0b | floor | Newmarket | as above | mean of D−7…D−28 | recent-weeks mean | 0.853 MW | 8.81% | 1.083 MW | n/a | n/a | |
| 2026-11-11 | 1b | H3 (no weather) | Newmarket | as above | calendar + history (section 4) | LightGBM, weekly refit from Jan 2023 | 0.602 MW | 6.21% | 0.701 MW | NMAE 19% below 0a; DM vs 0a 2.82 (p = 0.007), vs 0b 4.01 (p = 0.0002) | n/a: the criterion is for forecast weather on the final test | Old whole-day rule, superseded by the next batch |
| 2026-11-11 | 0a | floor | Newmarket | dev, 14 Mar – 31 Dec 2024, half-hour scoring (11,482 half-hours on 292 days, mean 9.51 MW; peak error on 54 complete days) | D−7 | same half-hour last week | 0.772 MW | 8.12% | 0.924 MW | n/a | n/a | |
| 2026-11-11 | 0b | floor | Newmarket | as above | mean of D−7…D−28 | recent-weeks mean | 0.826 MW | 8.69% | 1.083 MW | n/a | n/a | |
| 2026-11-11 | 1b | H3 (no weather) | Newmarket | as above | calendar + history (section 4) | LightGBM, weekly refit from Jan 2023 | 0.595 MW | 6.25% | 0.701 MW | NMAE 23% below 0a (the better floor); DM vs 0a 7.53, vs 0b 7.65 (both p < 1e-12) | n/a: the criterion is for forecast weather on the final test | Superseded by the weather batch (same model, one day fewer) |
| 2026-11-11 | 0a | floor | Newmarket | dev, 15 Mar – 31 Dec 2024, half-hour scoring (11,434 half-hours on 291 days, mean 9.51 MW; peak error on 53 complete days) | D−7 | same half-hour last week | 0.769 MW | 8.08% | 0.907 MW | n/a | n/a | Weather batch |
| 2026-11-11 | 0b | floor | Newmarket | as above | mean of D−7…D−28 | recent-weeks mean | 0.825 MW | 8.67% | 1.077 MW | n/a | n/a | |
| 2026-11-11 | 1b | H3 (no weather) | Newmarket | as above | calendar + history | LightGBM | 0.593 MW | 6.24% | 0.699 MW | NMAE 23% below 0a; DM 7.45 (p ≈ 1e-12) | n/a | |
| 2026-11-11 | 2 | H1, best case | Newmarket | as above | 1b + ERA5 temperature (half-hour, daily mean, heating degrees) | LightGBM | 0.459 MW | 4.83% | 0.451 MW | NMAE 23% below 1b; DM vs 1b 7.55 (p ≈ 6e-13) | n/a (actual weather) | |
| 2026-11-11 | 3 | H1, H2 | Newmarket | as above | 1b + IFS 00 UTC D−1 forecast temperature | LightGBM (run 2's model) | 0.470 MW | 4.94% | 0.458 MW | NMAE 21% below 1b (DM 7.28, p ≈ 3e-12); 92% of run 2's gain kept (most of the ERA5–IFS gap is a dataset difference, not forecast error: notebook, audit); vs run 2 DM −1.72 (p = 0.086) | Development only; see run 1a below, which is the better model without weather | Peak MAE 34% below 1b |
| 2026-11-11 | 1a | H3 (no weather) | Newmarket | as above | demand history and calendar | Three-layer decomposition (`decomposition.py`), one model per slot | 0.529 MW | 5.56% | 0.743 MW | NMAE 31% below 0a (DM 10.16, p ≈ 6e-21); beats 1b (DM 4.97, p ≈ 1e-6) | n/a | The best model without weather. Run 3 is 11% below it on NMAE (DM 3.04, p = 0.003): "pass", not "strong", if it held on 2025. Peak MAE: run 3 38% below 1a |
| 2026-11-11 | 4a, no weather | H3 | Newmarket | as above | 1b + same slot on D−1 (slots before 09:00 only) | LightGBM | 0.580 MW | 6.09% | 0.685 MW | still worse than 1a (DM −4.26, p ≈ 3e-5) | n/a | |
| 2026-11-11 | 4a | H1, H2 | Newmarket | as above | run 3 + same slot on D−1 | LightGBM (ERA5-trained, forecast at prediction) | 0.463 MW | 4.87% | 0.476 MW | vs 3: DM 2.02 (p = 0.044); vs 1a: 12% lower NMAE (DM 3.47, p = 0.0006) | Development only | The only step that helped, and only just |
| 2026-11-11 | 4b, no weather | H3 | Newmarket | as above | 4a + same slot on D−3…D−6 | LightGBM | 0.581 MW | 6.12% | 0.690 MW | worse than 1a (DM −4.44) | n/a | |
| 2026-11-11 | 4b | H1, H2 | Newmarket | as above | 4a + same slot on D−3…D−6 | LightGBM | 0.466 MW | 4.90% | 0.468 MW | vs 3: DM 0.98 (p = 0.33) | Development only | No gain over 4a |
| 2026-11-11 | 4c, no weather | H3 | Newmarket | as above | 4b + trend (years since Jan 2023) | LightGBM | 0.654 MW | 6.87% | 0.797 MW | worse than 1b | n/a | |
| 2026-11-11 | 4c | H1, H2 | Newmarket | as above | 4b + trend | LightGBM | 0.506 MW | 5.32% | 0.505 MW | vs 3: DM −3.19 (p = 0.002), worse | Development only | Trees cannot extrapolate a trend: every forecast day lies past the training range |
| 2026-11-11 | 5a, no weather | H3 | Newmarket | as above | 4a's inputs; target = demand − mean of same slot D−7…D−28 | LightGBM on the deviation | 0.622 MW | 6.54% | 0.725 MW | worse than 4a (DM −3.66, p = 0.0003) and 1a | n/a | |
| 2026-11-11 | 5a | H1, H2 | Newmarket | as above | 4a + forecast temperature; same target | LightGBM on the deviation | 0.500 MW | 5.26% | 0.521 MW | worse than 4a (DM −3.97, p ≈ 9e-5) | Development only | The 4-week mean is a noisy, lagging "normal" |

Rows below use the corrected DM test (Newey–West variance, 7 daily lags, Harvey–Leybourne–Newbold correction for h = 2;
lab notebook, 2026-11-11). DM values in the rows above used the naive variance and overstate significance; the
re-reported values are in that notebook entry.

| Date | Run | Hypothesis | Target | Period (scored) | Inputs | Model | MAE | NMAE | Peak MAE | Against the baselines | Criterion | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-11 | 6a, no weather | H3 | Newmarket | dev, 15 Mar – 31 Dec 2024 (11,434 half-hours on 291 days; peak error on 53 complete days) | 4a's inputs; target = demand − 1a's layers 1+2 fitted on the days before each Monday | LightGBM on the deviation | 0.601 MW | 6.32% | 0.662 MW | vs 4a: DM −1.38 (p = 0.17); vs 1a: −4.07 (p ≈ 6e-5) | n/a | No gain over 4a |
| 2026-11-11 | 6a | H1, H2 | Newmarket | as above | 4a + forecast temperature; same target | LightGBM on the deviation | 0.479 MW | 5.03% | 0.484 MW | vs 4a: DM −0.99 (p = 0.32) | Development only | The deviation idea, fair version: no gain |
| 2026-11-11 | 4a without d364, no weather | H3 | Newmarket | as above | 4a minus same slot D−364 | LightGBM | 0.567 MW | 5.96% | 0.656 MW | vs 4a: DM 1.66 (p = 0.098) | n/a | Slightly better without it, not significant |
| 2026-11-11 | 4a without d364 | H1, H2 | Newmarket | as above | 4a + forecast temp, minus D−364 | LightGBM | 0.455 MW | 4.78% | 0.469 MW | vs 4a: DM 1.52 (p = 0.13) | Development only | As above |
| 2026-11-11 | 4a L1, no weather | H3 | Newmarket | as above | 4a | LightGBM, absolute-error objective (`regression_l1`) | 0.557 MW | 5.85% | 0.714 MW | vs 4a: DM 2.94 (p = 0.004); vs 1a: −2.11 (p = 0.036) | n/a | Objective matched to the MAE metric |
| 2026-11-11 | 4a L1 | H1, H2 | Newmarket | as above | 4a + forecast temp | LightGBM, absolute-error objective | 0.444 MW | 4.67% | 0.477 MW | vs 4a: DM 2.59 (p = 0.010); vs 1a: 16% lower NMAE, DM 3.48 (p = 0.0006) | Development only: between pass and strong | Best so far |
| 2026-11-11 | 4a L1 without d364, no weather | H3 | Newmarket | as above | 4a minus D−364 | LightGBM, absolute-error objective | 0.560 MW | 5.89% | 0.677 MW | vs 4a L1: DM −0.18 (p = 0.85) | n/a | |
| 2026-11-11 | **4a L1 without d364** | H1, H2 | Newmarket | as above | 4a + forecast temp, minus D−364 | LightGBM, absolute-error objective | 0.442 MW | 4.64% | 0.480 MW | vs 4a L1: DM 0.60 (p = 0.55); vs 1a: DM 3.52 (p = 0.0005); vs the average without weather: 15% lower NMAE, DM 3.45 (p = 0.0006) | Development only: pass, not strong, against the best model without weather | **Working model** under the recorded rule |
| 2026-11-11 | Average 1a + 4a L1, no weather | H3 | Newmarket | as above | 1a and 4a L1 forecasts | 0.5 × 1a + 0.5 × 4a L1 (no weather), nothing fitted | 0.522 MW | 5.49% | 0.699 MW | vs 1a: DM 1.09 (p = 0.27); vs 4a L1: DM 4.73 (p ≈ 3e-6) | n/a | Best model without weather by NMAE, though not significantly better than 1a |
| 2026-11-11 | Average 1a + 4a L1 | H1, H2 | Newmarket | as above | 1a and 4a L1 (forecast temp) | 0.5 × 1a + 0.5 × 4a L1, nothing fitted | 0.456 MW | 4.79% | 0.565 MW | vs 1a: DM 5.19 (p ≈ 4e-7); vs 4a L1: DM −0.61 (p = 0.54) | Development only | Half the forecast has no weather: the peak error is 18% worse than 4a L1's |
| 2026-11-11 | 7 GAM | H1, H2, H3 | Newmarket | as above | 1a's layers 1+2 + splines of D's daily mean and the slot's temperature, AR(7) on residuals; ERA5-trained, IFS at prediction | GAM, one model per slot (`gam.py`, numpy + scipy 1.17.1) | 0.447 MW | 4.71% | 0.434 MW | vs 1a: DM 3.95 (p ≈ 1e-4); vs the no-weather average: 3.62 (p = 0.0003); vs W: −0.12 (p = 0.91) | Development only: 14% below the best no-weather model | Without weather it is 1a by construction; lowest peak error of any single model |
| 2026-11-11 | 8a | H1, H2 | Newmarket | as above | W + dtemp_d2, dtemp_d7_28 (D from IFS, past days from ERA5) | LightGBM L1 | 0.450 MW | 4.74% | 0.492 MW | vs W: DM −1.58 (p = 0.11) | Development only | Not adopted (rule: lower NMAE and p < 0.05) |
| 2026-11-11 | 8b, no weather | H3 | Newmarket | as above | W without doy_sin, doy_cos | LightGBM L1 | 0.566 MW | 5.95% | 0.751 MW | vs W no weather: DM −0.44 (p = 0.66) | n/a | |
| 2026-11-11 | 8b | H1, H2 | Newmarket | as above | W + forecast temp, without doy_sin, doy_cos | LightGBM L1 | 0.465 MW | 4.89% | 0.551 MW | vs W: DM −2.11 (p = 0.036), worse | Development only | Day of year kept |
| 2026-11-11 | 9, no weather | H3 | Newmarket | as above | 1a and W (no weather) | 0.5 × 1a + 0.5 × W, nothing fitted (the GAM without weather is 1a) | 0.526 MW | 5.53% | 0.681 MW | vs 1a: DM 0.86 (p = 0.39); vs the 1a + 4a L1 average: −0.79 (p = 0.43) | n/a | |
| 2026-11-11 | **9** | H1, H2 | Newmarket | as above | GAM and W (forecast temp) | 0.5 × GAM + 0.5 × W, nothing fitted | 0.419 MW | **4.41%** | **0.409 MW** | vs GAM: DM 4.15 (p ≈ 4e-5); vs W: 3.81 (p = 0.0002); vs the best no-weather model (1a + 4a L1 average, 5.49%): 19.78% lower NMAE, DM 4.83 (p ≈ 2e-6) | Development only: pass, 0.2 points short of strong | Best so far, and best on peaks |

**Re-baseline (2026-11-11).** Every row above used the partial-mean d1_morning. From here d1_morning is the mean of
D−1's 18 morning half-hours only when all 18 are metered, otherwise missing. Same 11,434 scored half-hours; NMAE before →
after, peak MAE after, corrected DM:

| Run | NMAE before | NMAE after | Peak MAE after | Notes |
|---|---|---|---|---|
| 0a / 0b / 1a | 8.08 / 8.67 / 5.56% | unchanged | 0.907 / 1.077 / 0.743 MW | Do not read d1_morning |
| 1b | 6.24% | 6.35% | 0.685 MW | |
| 2 / 3 | 4.83 / 4.94% | 4.93 / 5.00% | 0.421 / 0.469 MW | 3 vs 2: DM −0.70 (p = 0.48) |
| 4a / 4b / 4c, no weather | 6.10 / 6.12 / 6.87% | 6.20 / 6.19 / 6.90% | | |
| 4a / 4b / 4c + forecast temp | 4.87 / 4.90 / 5.32% | 4.88 / 4.95 / 5.33% | 0.485 / 0.474 / 0.477 MW | |
| 5a no weather / + forecast temp | 6.54 / 5.26% | 6.53 / 5.30% | | |
| 6a no weather / + forecast temp | 6.32 / 5.04% | 6.14 / 4.99% | | |
| 4a − d364 no weather / + forecast temp | 5.96 / 4.78% | 6.10 / 4.83% | | |
| 4a L1 no weather / + forecast temp | 5.86 / 4.68% | 6.10 / 4.68% | 0.464 MW | |
| **W** (4a L1 − d364) no weather / + forecast temp | 5.89 / 4.64% | 5.96 / **4.69%** | 0.475 MW | New vs old W: DM −0.78 (p = 0.43) with weather, −1.24 (p = 0.21) without: not significantly worse, so no stop. W vs 4a L1: 2.43 (p = 0.016) without weather, −0.48 (p = 0.63) with |
| Average 1a + 4a L1 no weather / + forecast temp | 5.49 / 4.79% | 5.60 / 4.79% | 0.566 MW | |
| 7 GAM | 4.71% | 4.71% | 0.434 MW | Does not read d1_morning; refit (gam.py changed), identical forecasts. vs W: DM 0.11 (p = 0.91) |
| 8a | 4.74% | 4.77% | 0.481 MW | vs W: −1.26 (p = 0.21): still not adopted |
| 8b no weather / + forecast temp | 5.95 / 4.89% | 6.18 / 4.91% | 0.571 MW | vs W: −1.33 (p = 0.18) / −1.92 (p = 0.056): day of year kept (worse on NMAE and peaks; no longer significant at 5% with weather) |
| 9 no weather (0.5 × 1a + 0.5 × W) | 5.53% | **5.55%** | 0.668 MW | Now the best model without weather (1a 5.56%; vs the 1a + 4a L1 average DM 2.07, p = 0.039; vs 1a 0.43, p = 0.67) |
| **9** (0.5 × GAM + 0.5 × W) | 4.41% | **4.42%** | **0.415 MW** | vs GAM 4.09 (p ≈ 6e-5); vs W 4.16 (p ≈ 4e-5). **20.33% below the best model without weather** (run 9 no weather, 5.553%), DM 4.74 (p ≈ 3e-6); 20.45% below 1a |

| Date | Run | Hypothesis | Target | Period (scored) | Inputs | Model | MAE | NMAE | Peak MAE | Against the baselines | Criterion | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-11 | 10 (flag 6) | H2, deployable version | Newmarket | dev, its own half-hours: 12,447 on 288 days (no forecast in the first week, no training data yet) | W's inputs | LightGBM L1 trained only on rows with an IFS run as issued (target days from 15 March 2024), predicted from IFS | 0.570 MW | 6.06% | 0.831 MW | Same half-hours: W 4.65%, run 9 4.36%; DM vs W −4.33 (p ≈ 2e-5), vs run 9 −5.36 (p ≈ 2e-7) | Development only | Much worse |
| 2026-11-11 | 10, Oct–Dec 2024 | as above | Newmarket | 4,218 half-hours on 92 days | as above | as above | 0.698 MW | 6.41% | 0.844 MW | Same half-hours: W 4.64%, run 9 4.51%; DM vs W −2.32 (p = 0.023), vs run 9 −2.62 (p = 0.010) | Development only | Still much worse with seven months of forecast history |
| 2026-11-11 | 11, no weather | H4 | Newmarket | dev, the batch's 11,434 half-hours | demand history only (last 8,192 half-hours before 09:00 on D−1) | Chronos-2 zero-shot (`amazon/chronos-2` @ 29ec3766, chronos-forecasting 2.3.2), median | 0.553 MW | 5.81% | 0.793 MW | vs 1a: DM −1.55 (p = 0.12); vs run 9 no weather: −1.65 (p = 0.099) | n/a | Between the simple floors and 1a |
| 2026-11-11 | 11 | H4 | Newmarket | as above | + half-hour temperature as known-future covariate (ERA5 past, IFS run of D−1 future) | as above | 0.461 MW | 4.85% | 0.616 MW | vs run 9: DM −3.10 (p = 0.002); vs W −1.04 (p = 0.30); vs GAM −1.11 (p = 0.27); vs 1a 2.40 (p = 0.017); vs 11 no weather 4.12 (p ≈ 5e-5) | Development only | Zero-shot, it ties our single weather models on NMAE but not on peaks (0.616 against 0.434–0.475 MW) |

**Final test, 2025 (run once on 2026-11-11 under section 12).** `train.py --period test`, then `report.py`;
output `data/runs/test_runs_frozen.csv` (sha256 e8cbc72876e4aa32), console in `data/runs/test_train_console.txt` and
`test_report_console.txt`. Scored: 14,818 half-hours on 365 days, 1 January – 31 December 2025, mean 10.07 MW; peak
error on the 33 complete days.

| Model | MAE | NMAE | Peak MAE |
|---|---|---|---|
| 0a same half-hour last week | 0.842 MW | 8.362% | 0.892 MW |
| 0b mean of 4 weeks | 0.797 MW | 7.913% | 1.209 MW |
| 1a decomposition | 0.558 MW | 5.540% | 0.766 MW |
| W, no weather | 0.580 MW | 5.765% | 0.768 MW |
| Run 9, no weather (0.5 × 1a + 0.5 × W) | 0.549 MW | 5.457% | 0.754 MW |
| W + forecast temperature | 0.437 MW | 4.342% | 0.408 MW |
| 7 GAM + forecast temperature | 0.449 MW | 4.462% | 0.477 MW |
| **Run 9 (0.5 × GAM + 0.5 × W), the frozen candidate** | **0.423 MW** | **4.200%** | **0.428 MW** |
| 11 Chronos-2, no weather | 0.542 MW | 5.379% | 0.752 MW |
| 11 Chronos-2 + forecast temperature | 0.443 MW | 4.396% | 0.562 MW |
| W fed ERA5 (actual temperature) | 0.418 MW | 4.149% | 0.368 MW |

- **Success criterion.** Comparator: run 9 without weather, the lowest no-weather NMAE (5.457%). Run 9's margin:
  **23.02%**, DM 6.06 (p ≈ 3e-9): **strong**. Block bootstrap (7-day blocks, 4,000 resamples, seed 0): median 22.7%,
  95% interval 16.7% to 28.4%; 82% of resamples at or above 20%, all at or above 10%. Peak-error margin: 43.31%,
  strong on the second check, but resting on only the 33 complete days of 365 (most 2025 days miss at least one
  half-hour). Run 9 also beats each of its members on the test year: the GAM (DM 4.74, p ≈ 3e-6) and W (3.25,
  p = 0.0012).
- **Margin by month:** January 34.0%, February 32.0%, March 26.5%, April 8.9%, May 23.5%, June 12.3%, July 13.1%,
  August 5.0%, September 6.4%, October 9.0%, November 41.5%, December 25.9%. **January–February: 33.0%** (59 days).
- **H1 (weather helps, same model):** W against W without weather DM 5.92 (p ≈ 7e-9); run 9 against run 9 without
  weather 6.06 (p ≈ 3e-9); Chronos-2 with against without temperature 5.02 (p ≈ 8e-7). Holds.
- **H2 (forecast weather keeps most of the gain):** W fed ERA5 4.149% against W fed the forecast 4.342%; DM for W
  against W fed ERA5 −3.91 (p = 0.0001), so actual weather is distinguishably better. The forecast keeps 88% of the
  gain over W without weather ((5.765 − 4.342) / (5.765 − 4.149)); section 11 notes that part of the ERA5–IFS
  difference is a dataset difference rather than forecast error.
- **H3 (our models beat the simple and decomposition baselines):** run 9 against 0a 7.19, 0b 5.89, 1a 6.74; W against
  0a 7.14, 0b 5.73, 1a 6.19 (all p < 1e-7). Holds.
- **H4 (our models match or beat Chronos-2):** run 9 (4.200%) against the better Chronos-2 version (with temperature,
  4.396%): run 9's NMAE is lower, DM 2.08 (p = 0.038). Holds, narrowly: zero-shot Chronos-2 with temperature beat the
  GAM (4.462%) and came within 0.05 points of W (4.342%) on the test year, a finding in its own right.

**Carry-over test, Bungay 2025 (run once on 2026-11-11 under section 13; confirmed independently).** Run 9 4.805%
against the comparator 1a at 5.131%: margin 6.35%, DM 2.66 (p = 0.0081), a **miss** (bootstrap 2.0% to 11.1%; peak-error
margin 8.54%, also a miss). Full table, months and hypotheses in section 13.

**Run 12, Timestral-123M zero-shot (development period, Newmarket, 11,434 half-hours; run once on 2026-11-11/12 under
section 14; confirmed independently).** Not a test result: the development period has been used to choose models.

| Model | MAE | NMAE | Peak MAE (53 complete days) |
|---|---|---|---|
| 12 Timestral, no weather | 0.505 MW | 5.313% | 0.704 MW |
| **12 Timestral + forecast temperature** | **0.417 MW** | **4.381%** | 0.510 MW |
| 11 Chronos-2, no weather | 0.553 MW | 5.812% | 0.793 MW |
| 11 Chronos-2 + forecast temperature | 0.461 MW | 4.851% | 0.616 MW |
| 9 (0.5 × GAM + 0.5 × W) | 0.421 MW | 4.425% | **0.415 MW** |
| W + forecast temperature | 0.446 MW | 4.693% | 0.475 MW |
| 7 GAM + forecast temperature | 0.447 MW | 4.705% | 0.434 MW |

- Corrected DM (positive: the second model better): Timestral with against without temperature 4.69 (p = 4e-6);
  Timestral without weather against Chronos-2 without weather 4.47 (p = 1e-5); Timestral with temperature against
  Chronos-2 with temperature 6.44 (p = 5e-10), against run 9 0.19 (p = 0.85), against W 2.19 (p = 0.029), against the
  GAM 1.86 (p = 0.064). Without weather Timestral is worse than run 9 (−4.71), W (−3.23), the GAM (−3.41) and Chronos-2
  with temperature (−2.44, p = 0.015).
- **Reading.** Timestral beats Chronos-2 with and without temperature. With forecast temperature it is level with run
  9 on NMAE (no detectable difference) but clearly worse at the daily peak (0.510 against 0.415 MW). Temperature removes
  17.5% of its error (5.313% to 4.381%).
- By month (reviewing session's recomputation): Timestral with temperature beats Chronos-2 with temperature in every
  month; against run 9 it is better in March–May and November, about level in June, worse in July–September and
  December (December 5.04% against 4.63%, July 6.38% against 5.75%). First and second half of the period: 4.37% and
  4.39%, so no sign that its longer context is what helps late in the year. Mean bias: −0.014 MW with temperature,
  −0.020 MW without.
- **Limit.** "Zero-shot" is as far as anyone can tell: the pretraining data of Timestral and Chronos-2 has not been
  checked against this substation, and its 2024 readings are on an open portal, so it cannot be ruled out that either
  model saw them. Unverified either way.

**Run 13, the input ladder (development period, Newmarket, the same 11,434 half-hours; run once on 2026-11-12 under
14.1 D; confirmed independently).** Each rung adds one weather input to the model without it (W: the half-hour value
and D's mean; GAM: one spline of D's mean), trained on ERA5 and forecast from the IFS run of D−1. Keep rule: lower NMAE
and corrected DM p < 0.05. In brackets, information only: the same trained W fed ERA5 for D (W fed ERA5: 4.651%).

| Rung | W (4.693%) | DM, p | Kept | GAM (4.705%) | DM, p | Kept |
|---|---|---|---|---|---|---|
| 13a solar radiation | 4.371% (ERA5 4.361%) | 5.39, 2e-7 | yes | 4.533% | 2.26, 0.025 | yes |
| 13b cloud cover | 4.556% (4.499%) | 2.55, 0.011 | yes | 4.620% | 1.55, 0.12 | no |
| 13c wind speed | 4.557% (4.534%) | 3.12, 0.002 | yes | 4.645% | 0.79, 0.43 | no |
| 13d relative humidity | 4.581% (4.459%) | 2.59, 0.010 | yes | 4.750% | −0.88, 0.38 | no |
| 13e precipitation | 4.479% (4.451%) | 5.41, 1e-7 | yes | 4.651% | 1.02, 0.31 | no |

- 13f: W with all five inputs 4.388% (DM 4.43 against W); the GAM with radiation 4.533%. The fixed rule kept all five
  for W although radiation alone scored slightly better (4.371%); that stays as decided and is one reason the result
  needs checking elsewhere.
- **13g = 0.5 × GAM_13f + 0.5 × W_13f: 4.178% against run 9's 4.425%**, DM 3.88 (p = 0.00013); peak MAE 0.409 against
  0.415 MW. Margin over run 9 by month: March +5.7%, April +9.2%, May +8.2%, June +2.6%, July +7.9%, August −1.2%,
  September +5.9%, October +6.6%, November +6.7%, December +2.0%; by time band: 00–06 +0.1%, 06–10 +2.6%, 10–16
  +10.9%, 16–20 +7.3%, 20–24 +3.4% (the midday band gains most, as radiation would).
- Fed actual weather, W with radiation scores 4.361% against 4.371% from the forecast: the radiation forecast costs
  almost nothing, unlike humidity (4.459% against 4.581%).
- The GAM with a precipitation spline had 2,064 rank-deficient fits (the daily precipitation mean is zero on many
  days); it was not kept. Ten keep tests at 5% give about one chance in two of a false keep (recorded before the run).

**Run 15, two fixed blends with Timestral (same half-hours; run once on 2026-11-12 under 14.1 G; confirmed
independently).** Run 13 kept inputs for both models, so the blends use GAM_13f, W_13f and 13g.

| Model | MAE | NMAE | Peak MAE (53 days) |
|---|---|---|---|
| **15a = (GAM_13f + W_13f + Timestral) / 3** | **0.385 MW** | **4.053%** | 0.419 MW |
| 15b = 0.5 × 13g + 0.5 × Timestral | 0.387 MW | 4.065% | 0.439 MW |
| 13g | 0.397 MW | 4.178% | **0.409 MW** |
| 12 Timestral + forecast temperature | 0.417 MW | 4.381% | 0.510 MW |
| 9 (frozen) | 0.421 MW | 4.425% | 0.415 MW |

- Corrected DM: 15a against Timestral 3.43 (p = 0.0007), against run 9 5.18 (p = 4e-7), against 13g 2.24 (p = 0.026);
  15b against Timestral 4.43 (p = 1e-5), against run 9 4.04 (p = 7e-5), against 13g 1.29 (p = 0.20).
- 15a against run 9 is better in every month (3.0% to 16.3%) and every time band (4.9% to 13.1%); against 13g it is
  worse in July (−3.2%) and September (−1.1%) and gains most from 00:00 to 06:00 (+7.6%). 13g keeps the best peak error.
- Not established: 15b was not blind (the 4.212% information line, recorded before the run), and the 13f inputs were
  themselves chosen on this period. Everything here was chosen on Newmarket 2024; run 16 checks it elsewhere.

**Run 14, holiday flags for the pretrained models (same half-hours; run once on 2026-11-12 under 14.1 E; confirmed
independently).** Bank-holiday and Christmas-period rows added as known covariates to each model with temperature.

| Model | NMAE (with flags / without) | Peak MAE | DM, p | Kept | 7 bank-holiday days |
|---|---|---|---|---|---|
| Chronos-2 | 4.820% / 4.851% | 0.569 / 0.616 MW | 0.48, 0.63 | no | 7.96% / 8.36% |
| Timestral-123M | 4.324% / 4.381% | 0.486 / 0.510 MW | 1.14, 0.26 | no | 7.07% / 8.05% |

- On the 8 scored days of the Christmas period (24–31 December) the flags cut the error from 7.95% to 5.92% for
  Chronos-2 and from 7.32% to 5.89% for Timestral; on all other days the change is 4.764% to 4.742% and 4.290% to
  4.255% (reviewing session's recomputation). The whole effect sits in a handful of days, so the test cannot separate
  it from chance: **not shown on this period; too few holiday days to judge**, not "holiday flags do not help".
- Cost: the flags tripled Timestral's time (36.6 s a day against 12.6 s). The candidate stays Timestral with
  temperature only.

**Run 16, carry-over to Bungay and the 15 development sites, cheap models (2024 development months only, 13 March –
30 December; run once on 2026-11-12 under 14.1 H; report 2, console `data/runs/run16_report2_console.txt`; confirmed
independently).** Each site is scored on its own half-hours, those metered and forecast by every cheap model; the
comparator is the site's best model without weather. Timestral and the blends 15a and 15b ran at three sites before
the pause (below).

| Site | Mean MW | Comparator | NMAE | Run 9 | 13g | Chronos-2 | Margin of 13g | 13g vs run 9, DM (p) |
|---|---|---|---|---|---|---|---|---|
| Bungay | 7.38 | 1a | 5.08% | 4.88% | 4.31% | 5.90% | 15.0% | +7.39 (1.5e-12) |
| Hardwick Rd | 8.31 | 9 no weather | 5.85% | 5.56% | 5.07% | 5.56% | 13.3% | +5.30 (2.3e-7) |
| Thompsons Ln | 7.77 | 9 no weather | 3.49% | 2.70% | 2.75% | 3.38% | 21.0% | −1.43 (0.15) |
| Guyhirn | 1.36 | 1a | 11.39% | 10.48% | 9.72% | 10.61% | 14.7% | +4.66 (4.8e-6) |
| Gaywood Bridge | 7.73 | 1a | 6.46% | 6.31% | 5.90% | 6.23% | 8.6% | +4.21 (3.3e-5) |
| Chelmsford East Local | 5.12 | 9 no weather | 5.46% | 5.04% | 4.87% | 5.18% | 10.8% | +2.55 (0.011) |
| Kenton | 2.31 | 1a | 4.49% | 3.76% | 3.48% | 3.95% | 22.4% | +5.03 (8.5e-7) |
| Orton | 9.77 | 9 no weather | 5.24% | 4.92% | 4.59% | 5.73% | 12.4% | +5.18 (4.2e-7) |
| Hendon Way | 11.24 | 9 no weather | 4.08% | 3.60% | 3.64% | 3.58% | 10.9% | −0.70 (0.48) |
| Hadleigh | 4.98 | 1a | 6.49% | 5.86% | 5.32% | 6.60% | 18.0% | +6.34 (8.9e-10) |
| Kingsbury | 5.63 | 9 no weather | 4.80% | 5.01% | 5.06% | 3.82% | −5.3% | −0.40 (0.69) |
| Hitcham | 5.22 | 9 no weather | 4.77% | 4.44% | 4.12% | 4.56% | 13.6% | +5.35 (1.7e-7) |
| Walsoken | 6.42 | 1a | 5.98% | 5.95% | 5.54% | 5.58% | 7.3% | +5.87 (1.2e-8) |
| George Hill | 8.02 | 9 no weather | 5.58% | 5.21% | 4.83% | 6.22% | 13.5% | +4.79 (2.7e-6) |
| Basildon Local | 8.27 | 9 no weather | 3.89% | 3.41% | 3.14% | 3.76% | 19.4% | +5.68 (3.3e-8) |
| Takeley | 3.23 | 9 no weather | 6.50% | 5.64% | 5.20% | 6.32% | 20.0% | +6.14 (2.7e-9) |
| **Pooled** (sum-based / plain mean) | | | 5.193% / 5.596% | 4.818% / 5.172% | **4.531% / 4.846%** | 5.109% / 5.436% | 12.75% | |

- **13g against run 9: better at 13 of 16 sites, significantly at all 13, significantly worse at none.** Pooled margin
  over each site's comparator: run 9 7.22%, 13g 12.75%. With 13g, 13 of 16 sites gain 10% or more; with run 9, 5 do.
  Pooled, 13g beats run 9 in every month, from 3.5% (March) to 11.1% (May).
- The two halves of 13g behave differently. W with the five inputs beats W at all 16 sites (DM 1.79 to 6.76). The GAM
  with radiation beats the GAM at 13 sites and is significantly worse at exactly the three where 13g does not improve:
  Thompsons Ln (DM −2.65), Hendon Way (−2.64) and Kingsbury (−3.23). This is an observation only: what those three
  sites have in common is not established, and nothing is changed on the strength of it.
- **Kingsbury** is the one site where neither weather recipe beats the no-weather comparator, and where Chronos-2
  (3.82%) is far ahead of everything else (run 9 5.01%). Cause unknown; recorded, not investigated.
- Half-hours below 10% of the site's median: none at 13 sites; 1 at Guyhirn, 1 at Orton, 5 at Takeley. The 13f
  masking drops no half-hour at Bungay.
- **Limits:** same region and the same months of 2024; the sites were screened to exclude generation and reverse
  flow; 13g's inputs were chosen at Newmarket on these same months. This tests carry-over across places, not across
  time. The 14 held-out sites and all 2025 and 2026 data are untouched.

**Run 16 paused (2026-11-12, by the owner's change of direction; last report
`data/runs/run16_report_after_thompsons_ln_primary_11kv.txt`, confirmed independently).** Timestral-123M and the blends
exist for three sites only; the other 13 are not run.

| Site | 13g | Timestral | 15a | 15b | Margin of 15a | 15a vs 13g, DM (p) | Timestral vs Chronos-2, DM |
|---|---|---|---|---|---|---|---|
| Bungay | 4.31% | 5.06% | 4.24% | 4.33% | 16.39% | +0.91 (0.37) | +5.85 |
| Hardwick Rd | 5.07% | 5.23% | 4.78% | 4.76% | 18.34% | +3.68 (0.00028) | +2.92 |
| Thompsons Ln | 2.75% | 2.90% | 2.55% | 2.55% | 26.80% | +3.97 (9e-5) | +4.19 |
| **Pooled** (sum-based) | 4.057% | 4.400% | **3.865%** | 3.887% | 19.73% | | |

- **15a better than 13g at 3 of 3 sites, significantly at 2.** Three sites do not settle the blend question.
- 15a beats run 9 significantly at all three (DM 6.10, 8.46, 2.60). Timestral beats Chronos-2 significantly at all
  three but not run 9 at any (DM −0.69, 1.42, −1.52). Pooled margin over each site's comparator on these three sites:
  run 9 8.82%, 13g 15.75%, 15a 19.73%.
- The limits above apply: same region and months, inputs chosen at Newmarket, final test unspent.

## 10. Related work

Read from the abstracts unless marked; the two closest are read in full before the first run.

- Iftikhar et al., *Day-Ahead Electricity Demand Forecasting Using a Novel Decomposition Combination Method*, Energies 16(18)
  6675, 2023 (read in full). Nordic market, hourly, 2014–2019, rolling day-ahead on 2019. Decomposition into long-run,
  seasonal and residual layers cut MAPE to 1.9% from 2.9–4.4% for the same models without it. No weather. The winner is
  picked from 192 combinations on the test year, which flatters it: we choose on the development period.
- Chattopadhyay et al., *Peak-Aware Short-Term Load Forecasting Across Distribution Grid Aggregation Levels*, arXiv
  2609.18588, 2026. UK and Swiss open data at area, substation and feeder level; Chronos-2 had the lowest high-demand error
  at every level (HD-MAPE 4.5%, 9.5%, 16.1%), 20–51% below LightGBM and XGBoost. **Read in full.**
- Haben, Giasemidis, Ziel and Arora, *Short Term Load Forecasts of Low Voltage Demand and the Effects of Weather*, IJF 2019,
  arXiv 1804.02955. 100 UK feeders, actual vs forecast temperature: at that scale weather was not the dominant driver.
  **Read in full.**
- Roy, Pyltsov and Hu, *Hourly-Binned Regression Models Beat Transformers in Load Forecasting*, arXiv 2505.11390, 2025.
  Day-ahead with temperature and irradiance: XGBoost lowest error; deep models, TimeGPT included, not consistently better on
  limited data.
- Simeone, *Time Series Foundation Models for Energy Load Forecasting on Consumer Hardware*, arXiv 2602.10848, 2026.
  Chronos-2 well calibrated on ERCOT, on a laptop without a GPU.
- arXiv 2510.00742, 2025: zero-shot foundation models degrade when the target data differs from their pretraining data.
- Zimmermann and Ziel, *Spatial Weather, Socio-Economic and Political Risks in Probabilistic Load Forecasting*, arXiv
  2408.00507, 2024. Interpretable GAMs separating calendar, weather and autoregressive effects.
- Haben et al., *Review of Low Voltage Load Forecasting*, arXiv 2106.00006, 2021: few papers work at primary level; a list
  of open datasets.
- Later, if an ensemble weather archive exists: EGU26-9383 (2026 abstract), ensemble weather quantiles instead of a single
  forecast improved calibration and peak detection.

## 11. Threats to validity

- Rooftop solar beneath the primary is netted off what the meter sees; neither UK Power Networks nor NGED separates it at
  primary level, so "demand" is net of small solar.
- The historian logs a value only when it changes enough; half-hours are time-weighted from those points, so short spikes
  may be smoothed and flat stretches may hide a stuck reading.
- One year of final test: one unusual winter weighs a lot.
- Forecast skill in the archive changes between 2024 and 2025 (0.70 vs 0.98 °C at Newmarket); a model tuned on 2024's
  forecasts meets worse forecasts in 2025.
- Actual weather in a backtest overstates what a real forecast achieves (hence the forecast-weather level).
- ERA5 and the IFS forecast differ by 0.61 °C even at lead day 0, where the forecast has had almost no time to go wrong,
  and by 0.75 °C at lead day 1 (measured over all 657 runs). So most of the gap between runs trained on ERA5 and fed IFS
  is two datasets disagreeing about the same weather, not forecast error: the share of run 2's gain that run 3 keeps
  understates what a forecast keeps. Training on IFS as issued (run 10) removes that mismatch.
- Reading the meter up to 09:00 on D−1 assumes an operator's SCADA; from open data alone the cut-off is much earlier.
- Runs 2 and 3 train on ERA5 up to each refit; live, ERA5 lags about five days, so the backtest's training is slightly
  fresher than an operator's would be.
- Run 8a's lag-day temperatures use ERA5 for D−2; live, ERA5 for D−2 is not yet available (about five days late), so a
  live system would use the latest analysis or a short-range forecast for those days.
- Connections and new homes beneath the primary change over the years; the long-run layer and the rolling refit absorb
  slow change, not steps.
- Newmarket's gaps cluster in summer 2024 (development period); unscored days there make development summers thinner.
- The development period (14 March – 31 December 2024) has no January or February. The 2025 test contains two
  deep-winter months the models were never chosen on, where weather's margin was largest in the months seen (October to
  December): the 2025 margin can land well away from the development figure in either direction.
- The Bungay carry-over test (section 13) is the same year and region as the Newmarket test, about 75 km away, under
  the same weather: it tests another place, not another period, and the two results are not independent.

## 12. Freeze specification (final test, 2025)

Written on 2026-11-11, after run 11 and before anything touches 2025. **Status: confirmed by the owner on 2026-11-11,
before any 2025 number existed.** The 2025 run happens once.

**The frozen candidate: run 9**, the fixed average 0.5 × GAM (run 7) + 0.5 × W, nothing fitted. W is LightGBM with the
absolute-error objective (`regression_l1`, learning rate 0.05, 31 leaves, 500 trees, seed 0, deterministic) on the
calendar inputs (slot, day of week, day-of-year sine and cosine, bank holiday, Christmas period), the history inputs
(same slot on D−2 and D−7, mean of D−7…D−28, d1_morning under the all-18-or-missing rule, same slot on D−1 before
09:00; not D−364) and the three temperature inputs (half-hour, daily mean, heating degrees below 15.5 °C). The GAM is
`gam.py` as run (1a's calendar layers, two cubic regression splines with knots at the 20/40/60/80% training quantiles,
AR(7) on residuals, one model per slot). Both are trained on ERA5 and predict from the IFS 00 UTC run of D−1; both are
refit every Monday at 09:30 on everything before that Monday, on an expanding window that continues through 2025.
Nothing in it changes after this point.

**The models that get their single 2025 run:** 0a, 0b, 1a, W without weather, run 9 without weather (0.5 × 1a + 0.5 × W
without weather), W, the GAM, run 9, Chronos-2 without weather (11_nw) and with temperature (11), and W fed ERA5 at
prediction (the same trained models as W, a second prediction table, no extra training; confirmed by the owner, the
only way to answer H2 on 2025). The development rungs (1b to 6a, the 4a variants, the 1a + 4a L1 average,
8a, 8b, run 10) are not run on 2025.

**The comparator, fixed now:** the lowest 2025 NMAE among the no-weather models in that list (0a, 0b, 1a, W without
weather, run 9 without weather). Run 9 is judged against that one exactly as section 7 says: at least 10% lower NMAE is
a pass, at least 20% strong, with the corrected DM test significant at 5%; the peak error is checked against the same
two levels.

**Reported whatever the outcome:** every model's NMAE, MAE and peak MAE; run 9's margin over the comparator with a
moving-block bootstrap interval over days (7-day blocks, 4,000 resamples, as in the 2026-11-11 audit); the margin by
month; January and February separately (the models were never chosen on deep winter); H1 (W against W without weather,
run 9 against run 9 without weather, 11 against 11_nw), H2 (W against W fed ERA5), H3 (run 9 and W
against 0a, 0b and 1a) and H4 (run 9 against the better Chronos-2 version), each answered with the corrected DM test.
The bootstrap and by-month calculations are to be written as a script and shown on the development file before the
test run, so that nothing about the analysis is chosen after 2025 is seen.

**Mechanics.** The test is `uv run python train.py --period test`, which forces the frozen model list; the scored set
follows section 7, step 6 (metered and forecast by every model in the 2025 list). The path was proven on 2026-11-11:
`train.py --period dev --frozen --no-cache` recomputed every frozen model from scratch and reproduced the development
forecasts exactly (11,434 half-hours, largest difference 0.0 in all eleven columns); after the revision pin and
the separated test outputs, `train.py --period dev --frozen` reproduced them again (0.0; W, 1a and the GAM from cache,
Chronos-2 refit under the pinned revision). Code (first 16 hex digits of
sha256): `train.py` 5bf6731dea9cf9d8, `gam.py` 2186c6db2b37a804, `decomposition.py` 3ef3391475461362, `chronos_run.py`
d7a94984a0788331, `load.py` f4d9884d7688b3df, `cache.py` c5af3ff208e401da, `report.py` f0dc1dd70c440cdc. Development cache keys of the frozen
models: W without weather cd3215534b39828b3bbcb105, W (and W fed ERA5) 1f5302574fec379eccfc6082, GAM
04b54ff36e488adbc6cb60b9, 1a 541a23ae6ec0e59191f6f8b6, Chronos-2 07155bb00b3bcab092d3d6d0 (the test period gets its
own keys, since the period is part of every key). Libraries: lightgbm 4.7.0, numpy 2.4.6, pandas 3.0.6, scipy 1.17.1,
chronos-forecasting 2.3.2 with `amazon/chronos-2` at revision 29ec3766d36d6f73f0696f85560a422f50e8498c, torch 2.15.0
(CPU). Data: demand through 2025 in the pinned UKPN file; ERA5 to 31 December 2025; IFS runs to 30 December 2025 (the
run for 31 December). Known edge: ERA5 ends at 23:00 UTC on 31 December 2025, so the half-hour starting 23:30 that
day has no interpolated actual temperature; it affects only W fed ERA5, on that one half-hour (LightGBM takes the
missing input). The Chronos-2 load is pinned to that revision (`REVISION` in `chronos_run.py`). The test run writes its
own files (`data/runs/test_runs_frozen.csv`, plots suffixed `_test`) and logs to its own MLflow experiment
(`newmarket-test`), so the development record is untouched. The analysis is `report.py`, which takes the output file
as its only input: on the development file it gives the 20.33% margin, a bootstrap interval of 14.0% to 26.0% (seed 0;
the audit's other seed gave 13.9% to 25.8%), the audit's monthly table, and the H1–H4 tests above; the same command
runs on the test file unchanged.

**After the owner confirms:** run 2025 once and write the results; no reruns, except for a bug that is demonstrated and
fixed in the open, with both results kept.

## 13. Carry-over test: Bungay (specification, written before running)

Written on 2026-11-11, before any Bungay forecast exists. The owner chose the site with more data: Bungay Primary
11 kV (UK Power Networks, Eastern; Bramford GSP), 2023–2025 at 100% completeness (section 6), the same file format and
the same IFS single-run archive, so the frozen models can run unchanged. Sleaford is not started: two years with gaps,
the lockdown, and no IFS runs for its period.

- **Unchanged.** The frozen models, the 2025 list, the comparator rule, the scoring rule and `report.py` of section 12
  are used exactly as frozen. Nothing is chosen, tuned or dropped on Bungay. Its data before 2025 is warm-up and
  training only; no development run is made or looked at there (the code refuses a Bungay period other than the test).
- **Target:** Bungay Primary 11 kV, T1 + T2, read by `load.py` from `data/raw/ukpn/bungay_primary_half_hourly.csv`.
  Test period 2025, run once, the same rule on reruns as section 12 (only for a bug demonstrated and fixed in the open,
  both results kept).
- **Weather:** the same two sources at Bungay's own location: BUNGAY PRIMARY 33/11kV, 52.453032 N 1.437208 E (UKPN Grid
  and Primary Sites, EPN-S0000000H5004). ERA5 hourly from December 2022, and every 00 UTC IFS run from 14 March 2024 to
  30 December 2025; missing runs listed, never filled. The site is a parameter of `fetch_weather.py` and `train.py`.
- **What it answers, recorded before the result:** whether the method carries over to a second town. It is the same
  year and the same region as the Newmarket test, about 75 km away, so it tests another place, not another period, and
  the two results share the weather: they are not independent. Section 3 already expects Bungay to be calendar-driven
  with a weaker winter (1.23 × summer, against Newmarket's 1.44), so a smaller weather margin there would be the
  expected direction, not a failure of the method. The criterion is read exactly as for Newmarket (pass 10%, strong
  20%, corrected DM at 5%, peak error as the second check).
- **Preparation (2026-11-11), no Bungay forecast made.** The site is a parameter (`--site`, sites in `load.SITES`);
  Newmarket's cache keys, file names and outputs are unchanged, and `train.py --period dev --frozen` on Newmarket still
  reproduces the development forecasts exactly (0.0 in all eleven columns, every model from its unchanged cache key);
  the Newmarket 2025 file is untouched (sha256 e8cbc72876e4aa32). A Bungay period other than the test is refused by the
  code. Weather fetched at Bungay's coordinates: ERA5 hourly, 1 December 2022 – 23:00 UTC on 31 December 2025, no
  missing values (the same 31 December 23:30 edge as at Newmarket), and all 657 IFS 00 UTC runs from 14 March 2024 to
  30 December 2025, none missing, 168 hourly values each. Input checks against section 6 (demand only): 2023–2025 is
  100% complete (52,608 of 52,608 half-hours, no gaps), mean 7.60 MW, minimum 3.15, maximum 12.43, never negative;
  each year 7.63, 7.63 and 7.55 MW; the clock-change days have 46 and 50 half-hours; 1.4% of values repeat the
  previous one. Everything matches section 6. The Bungay 2025 run waits for the owner's go:
  `uv run python train.py --site bungay --period test`, then `uv run python report.py data/runs/bungay_test_runs_frozen.csv`.
- **Recorded before the result (inputs, measured by the reviewing session).** At Bungay the IFS runs differ from ERA5 by
  1.04 °C on lead day 0 and 1.10 °C on lead day 1 (then 1.19, 1.29, 1.45, 1.62, 1.79 °C), against 0.61 and 0.75 °C at
  Newmarket: the two temperature sources disagree much more there before any forecast error, most likely because the
  site is near the coast and the two models' grid cells see different mixes of land and sea. So the frozen models,
  trained on ERA5 and fed IFS, carry a larger train/predict mismatch at Bungay; a larger gap between W and W fed ERA5
  (a lower share of the gain kept under H2) is expected and would be read mainly as dataset disagreement, not worse
  forecasting; and with the weaker seasonality, a smaller weather margin at Bungay is the expected direction on two
  counts. The reviewing session also confirmed the preparation independently: Newmarket's test file and development
  reproduction unchanged, no Bungay output or cache entry yet, Bungay's ERA5 not a copy of Newmarket's (mean
  difference 1.09 °C), all 657 IFS files starting at their own 00 UTC with 168 values.

- **Raw result (2026-11-11, run once; awaiting the reviewing session's independent recomputation).**
  `train.py --site bungay --period test`, then `report.py`; output `data/runs/bungay_test_runs_frozen.csv` (sha256
  873a0aeb73db06b0), consoles `data/runs/bungay_test_train_console.txt` and `bungay_test_report_console.txt`. Scored:
  17,518 half-hours on 365 days, mean 7.55 MW; peak error on 364 complete days; GAM 2,544 fits, 0 rank-deficient.

| Model | MAE | NMAE | Peak MAE |
|---|---|---|---|
| 0a same half-hour last week | 0.627 MW | 8.312% | 0.574 MW |
| 0b mean of 4 weeks | 0.591 MW | 7.827% | 0.588 MW |
| 1a decomposition | 0.387 MW | 5.131% | 0.389 MW |
| W, no weather | 0.425 MW | 5.627% | 0.430 MW |
| Run 9, no weather (0.5 × 1a + 0.5 × W) | 0.388 MW | 5.138% | 0.392 MW |
| W + forecast temperature | 0.404 MW | 5.356% | 0.388 MW |
| 7 GAM + forecast temperature | 0.372 MW | 4.935% | 0.368 MW |
| **Run 9 (0.5 × GAM + 0.5 × W), the frozen candidate** | **0.363 MW** | **4.805%** | **0.356 MW** |
| 11 Chronos-2, no weather | 0.422 MW | 5.587% | 0.439 MW |
| 11 Chronos-2 + forecast temperature | 0.407 MW | 5.394% | 0.421 MW |
| W fed ERA5 (actual temperature) | 0.391 MW | 5.180% | 0.379 MW |

  - **Success criterion.** Comparator: 1a decomposition (5.131%). Run 9's margin **6.35%**, DM 2.66 (p = 0.0081):
    **miss** (below 10%). Bootstrap (7-day blocks, 4,000, seed 0): median 6.4%, 95% interval 2.0% to 11.1%; 6% of
    resamples at or above 10%, none at or above 20%. Peak-error margin 8.54%: miss.
  - **Margin by month:** January 17.4%, February 14.4%, March 14.0%, April 8.8%, May 16.3%, June 3.3%, July −0.6%,
    August −2.6%, September −4.9%, October −15.8%, November 21.8%, December −2.2%. January–February 16.0% (59 days).
  - **H1:** W against W without weather DM 2.25 (p = 0.025); run 9 against run 9 without weather 3.03 (p = 0.0026);
    Chronos-2 with against without temperature 1.45 (p = 0.15).
  - **H2:** W against W fed ERA5 DM −2.96 (p = 0.0033).
  - **H3:** run 9 against 0a 6.90, 0b 6.54, 1a 2.66 (p = 0.0081); W against 0a 5.90, 0b 5.58, 1a −1.59 (p = 0.11).
  - **H4:** run 9 against Chronos-2 with temperature (5.394%): DM 2.42 (p = 0.016).

  - **Confirmed by the reviewing session (2026-11-11); observations, not owner decisions.** Every figure above
    recomputed independently and equal. The direction recorded before the run was right (a smaller margin than
    Newmarket's, a larger gap between W and W fed ERA5), but the size is a miss under the criterion. W alone does not
    beat 1a at Bungay (5.356% against 5.131%, DM −1.59); the GAM carries the weather gain, and run 9 does not
    significantly beat the GAM (DM 1.80, p = 0.073). H1 holds for W and run 9 but not for Chronos-2 (p = 0.15). H2:
    the forecast keeps 60.6% of the gain over W without weather ((5.627 − 5.356) / (5.627 − 5.180)), against 88% at
    Newmarket. September is poor for every model (8–9% NMAE, all forecasting 0.27 to 0.43 MW too high) except Chronos-2
    (about 7%); in October W forecasts 0.19 MW too low even when fed ERA5, so the October loss is not weather-forecast
    error. **Unverified hypothesis:** a change in the demand level around September 2025; recorded only, not to be
    investigated with any rerun or new model on 2025.

## 14. After 2025: the spent test year, the next final test, and run 12 (written before running)

Written on 2026-11-11, after the Bungay result and before any Timestral forecast exists. Owner's go relayed by the
reviewing session.

- **2025 is spent, at Newmarket and at Bungay.** Both final tests have been read. No model, input, setting or choice
  made from here on may be judged on 2025 at either site; 2025 may still be training data and context for forecasts
  of later periods, as any past data is. The 2025 results of sections 9, 12 and 13 stand as they are.
- **The next final test (intended; the owner confirms it once availability is known).** 2026 data at Newmarket and
  Bungay, plus primary substations never looked at during development, under a new freeze specification written
  before it runs, in the manner of section 12. Availability checked on 2026-11-11 (aggregate queries on the UKPN
  portal, nothing downloaded):
  - The half-hourly dataset now runs from 1 January 2023 to 30 April 2026 (about 50.0 million rows). January–March
    2026 is published for both sites; April 2026 for Bungay (both transformers, every half-hour) but not Newmarket.
    May 2026 onward is not on the portal. August–September 2026, which section 6 records as published and which our
    local files already hold, is no longer returned by the portal.
  - Bungay: January–April 2026 complete in both transformers' row counts (1,488, 1,344, 1,488, 1,440 per month).
    Newmarket: January–March 2026 at about 98% of half-hours per transformer.
  - Comparable sites, 2023–2025: 908 transformers at 488 Eastern primaries. Primaries where every transformer has a
    MW value for at least 99% of the 52,608 half-hours: 93; at least 95%: 136; at least 90%: 166. (Grouped by the
    transformer id's site name; large embedded generation, redactions and amps-only sites not yet screened, as section
    6 screens them.)
- **Run 12: Timestral, zero-shot, beside Chronos-2 (development only, 14 March – 31 December 2024, Newmarket).**
  Mistral AI's time-series foundation model (released 15 October 2026). Code: `github.com/mistralai/timestral`
  (Apache-2.0), installed pinned to commit a534bdbd244d64f3d9d743f46c7bf6fc330ed4ff (package `timestral` 1.0.0).
  Weights: Hugging Face `mistralai/Timestral-*`, Modified MIT licence (the same text for all four sizes, checked:
  keep Mistral's attribution notice with any copy; no rights if the user's company or employer has monthly revenue
  above $20 million; covers derivatives). The repository is inference only: it has no training or fine-tuning code.
  Code lives in its own module, `timestral_run.py`; no frozen file is edited.
  - **Same as run 11, so the comparison with Chronos-2 is like for like.** For each development day D on the UTC
    half-hour grid: context = every half-hour before 09:00 local on D−1, at most the model's context length; forecast
    from 09:00 on D−1 to the end of D; only D's half-hours are kept and scored. Missing readings are passed as NaN,
    nothing filled: Timestral builds its observation mask from NaN (`forecaster.py`; masked steps are ignored by the
    model). Two versions: 12_nw, demand alone; 12, plus the half-hour temperature as a known-future covariate
    (`known_covariates`, ERA5 over the context and the IFS 00 UTC run of D−1 over the forecast window, one row); a
    day whose IFS run is missing gets no 12 forecast, as for run 11. Point forecast = the 0.5 quantile (`median`).
  - **Differences from run 11, recorded before the result.** Timestral's context length is 32,768 half-hours (about
    683 days) against Chronos-2's 8,192 (about 170): under the same rule it sees all history from 1 January 2023
    until mid-November 2024, then the latest 32,768. Library defaults are kept, nothing tuned: symmetric averaging
    (the forecast of the negated series reflected and averaged in) and clipping at zero for a non-negative context.
    One day per call (the context length differs every day; no padding).
  - **How the library treats missing readings and its defaults (facts from its source, checked by the reviewing
    session).** We pass NaN and fill nothing, but inside the library the target row is forward-filled
    (`ffill_with_mask`) and a mask marks those positions as not observed: the model's input holds the carried-forward
    value under a "not observed" flag. That is the library's mechanism, not a fill of ours, but under the rule "never
    fill missing data" it is stated plainly here. Symmetric averaging runs a second pass on the negated context, with
    the temperature row negated too, and averages the reflected result with the first; clipping at zero applies because
    the context is never negative. Config of 209M: patch 32 half-hours, decode block 32 patches (1,024 half-hours); the
    horizon of 76–80 half-hours is 3 patches, decoded in one block, so no forecast median is fed back as context.
  - **Guard.** If either version lacks a forecast on any of the 11,434 scored half-hours, the script stops before
    scoring, so every model scores on the same set.
  - **Revision and size, fixed before the run.** `Timestral-209M` at revision 9874d252ab0aae16f7f7c999f98f98d6ad7d8365
    if a timing on five development days, both versions, puts the full run under three hours on this laptop;
    otherwise `Timestral-123M` at revision 5a147287addda85f6acd8da3fb8858fe9af7e8f7. Chosen on time only; the timing
    forecasts are not scored or looked at. Pinned like Chronos-2's REVISION.
  - **Scoring.** The same 11,434 half-hours as the development table (`data/runs/dev_runs_frozen.csv`): NMAE, MAE,
    peak MAE on the complete days, and the corrected DM test against Chronos-2 (both versions), run 9, W and the GAM;
    12 against 12_nw for the weather effect. Output `data/runs/dev_run12_timestral.csv`, console kept. One run, no
    tuning, no new inputs (holiday flags, solar radiation and the rest come later, one at a time, on the owner's word).
    This is development: the result can inform what goes into the next freeze, which is then judged on the next test,
    not on this table.

### 14.1 Overnight plan, 11–12 November 2026 (decided by the guide session overnight, for the owner to confirm)

The owner, away until 12 November, told both sessions to keep working without waiting on them. The reviewing
("guide") session set the queue below; each item's rule is written here before it runs. Limits kept: nothing scored on
2025 at either site or on any 2026 data; no final test; held-out sites never downloaded or looked at; no commits;
missing data never filled; no input sees past 09:00 on D−1; frozen files and the three frozen result files unchanged
(new code in new modules, new data in new files); one heavy job at a time.

Why (the guide's read-only breakdown of run 9 on the development period): 68% of a typical day's error is level (the
whole day too high or too low); 10:00–16:00 carries 29% of the absolute error; winter midday is under-forecast by
0.36 MW; the summer weather margin is 0–10% in every time band; the daily error is unrelated to the size of the
temperature-forecast error (correlation 0.01); the worst days are whole-day misses of 1.1–1.5 MW in November–December
at ordinary temperatures; Chronos-2 scores 8.4% on bank holidays against 5.7% for run 9. So temperature is not what is
missing; other weather and day-level information may be.

- **B. More weather at Newmarket** (`fetch_weather_extra.py`, new files `newmarket_era5_extra_hourly.csv` and
  `newmarket_ifs_00z_extra_runs/`): shortwave (solar) radiation, cloud cover, wind speed at 10 m, relative humidity,
  dew point, precipitation; ERA5 1 December 2022 – 31 December 2025 for actuals, every 00 UTC IFS run 14 March –
  31 December 2024 for forecasts (the development period only). Units (Open-Meteo): radiation W/m², mean of the
  preceding hour; precipitation mm, sum of the preceding hour; cloud cover and humidity %, dew point °C, wind m/s,
  instantaneous at the hour. Each run's first hour has no radiation or precipitation (nothing precedes it); that hour is
  D−1 00:00 UTC, never in a forecast window. Free-tier limits: under 600 calls a minute, 5,000 an hour, 10,000 a day;
  the fetch makes one call a second.
- **C. Sites.** Screen, then split with a fixed seed, before any site's demand is downloaded. Candidates: the 93 Eastern
  primaries where every published transformer has a MW value on at least 99% of 2023–2025's half-hours (corrected
  to 77 below). A site is kept
  only if (1) no transformer of it is marked redacted in any month of 2023–2025 (monthly dataset); (2) the number of
  transformers published equals the site's `powertransformercount` (Grid and Primary Sites), so nothing is missing from
  the sum; (3) no connected generator of 1 MW or more in the Embedded Capacity Register has it as its primary
  (Bungay's rule); (4) no transformer's monthly minimum MW is negative in 2023–2024 (no reverse flow); (5) its
  coordinates are found unambiguously. Newmarket and Bungay are left out of the draw (they are development sites
  already). The survivors, sorted by name, are shuffled with `numpy.random.default_rng(20261112).permutation`; the first
  24 are development sites, the rest held out (names listed, nothing downloaded). Only data up to 31 December 2024 is
  used for now. The ECR query reads only non-personal columns (primary, status, capacity), as the repo's rule asks.
  From section 14 on, Bungay's data up to 31 December 2024 may also be used for development (section 13's rule
  applied to the finished carry-over test).
- **D. Run 13, the input ladder** (Newmarket, development period, the same scored half-hours as `dev_runs_frozen.csv`,
  the same weekly refit and training rule: trained on ERA5, forecast from the IFS run of D−1). One addition at a time
  on top of W and of the GAM, each compared with the same model without it: 13a solar radiation (half-hour value and the
  day's mean); 13b cloud cover (half-hour value and day mean); 13c wind speed; 13d humidity; 13e precipitation. Keep
  rule, fixed now: an input is kept for a model if it lowers that model's development NMAE **and** the corrected DM test
  against the same model without it gives p < 0.05. Kept inputs are then combined once (13f) and run 9 is recomputed
  as the average of the new GAM and new W (13g). No other combinations, no tuning. In the GAM each input is one smooth
  term; rank-deficient fits reported. By-month and by-time-band tables for the kept ones. Detailed specification
  written before it runs.
- **E. Run 14, holiday information for the pretrained models.** Chronos-2, and Timestral-123M if run 12 has it within
  0.3 percentage points of Chronos-2's NMAE, each with temperature plus two known-future flags (bank holiday; Christmas
  period, as defined in `calendar_features`), against the same model without the flags. Same keep rule.
- **F. Only if A–E finish before the owner returns: a pooled W** (one LightGBM on all development sites, demand
  divided by each site's training-window mean, site id as a category), scored at Newmarket on the development period
  against the single-site W. Specification first.
- Not tonight: fine-tuning, prices, anything at the held-out sites.
- **C, first result (2026-11-12, blocked, no split made).** Grouping transformers by the portal's `ltds_name` (907 of
  908 mapped) gives 436 Eastern primaries, 77 of them at least 99% complete; the earlier "93 of 488" came from a cruder
  grouping by the transformer id's text and is withdrawn. Two screen bugs, caught because Bungay failed: rule (4) as
  written ("any negative monthly minimum") rejected Bungay over −0.03 MW in March 2023, metering noise while one
  transformer sat near zero; **the rule was changed to a monthly minimum below −0.5 MW, after seeing counts (not site
  names)**. Coordinate matching now requires the site's own voltage (33/11 kV, not 33 kV). Result (`screen_sites.py`,
  `data/raw/ukpn/sites_screen.csv`): of 77, connected ECR generation 29, reverse flow 46, transformer count mismatch 2,
  not located 6, redacted 0; kept 19 including Bungay, so 18 in the draw: too few for 24 development sites plus a
  held-out set. Kept at 95% completeness: 30; at 90%: 33. Options sent to the guide session; nothing drawn or
  downloaded.
- **C, the split rule (decided by the guide session overnight, for the owner to confirm; written before the draw).**
  Option (b): completeness 95% for every published transformer, every other screen rule as it now stands (rule (4) at
  −0.5 MW, the changed rule recorded above); 29 sites in the draw. Sort their site ids (`sitefunctionallocation`)
  ascending, shuffle with `numpy.random.default_rng(20261112).permutation`; the first 15 are development sites, the
  last 14 held out. Both lists saved (`data/raw/ukpn/sites_dev.csv`, `sites_heldout.csv`); from then on the held-out 14
  are not downloaded or queried beyond the aggregate screen already done. Newmarket and Bungay are development sites
  outside the draw. Reasons: 95% is enough because nothing is filled and every model tolerates gaps (Newmarket itself
  is 94%); the generation and reverse-flow rules stay, since the question is about demand-dominated sites and a
  normalised error is not comparable where net flow crosses zero, so **no result here speaks for the 46 reverse-flow
  sites or those with generation** (a separate later study); 14 held-out sites give a usable test; the 24 was picked
  before the count was known and is dropped, not rescued by loosening rules.
- **D, run 13 detailed specification (written 2026-11-12 before it runs; `ladder.py`, a new module, nothing frozen
  edited).** Newmarket, development period, scored on exactly the 11,434 half-hours of `dev_runs_frozen.csv`.
  - **Baselines recomputed and checked first:** W (4a L1 without d364, L1 objective, inputs + temperature, trained on
    ERA5, forecast from the IFS run of D−1, refit each Monday) and the GAM are rebuilt by the same functions
    (`train.replay`, and a copy of `gam.gam_forecasts` that accepts extra terms); both must reproduce the frozen
    columns (largest difference below 1e-9) before any addition is scored. If not, stop and report.
  - **Inputs per variable v**, ERA5 for training, the IFS 00 UTC run of D−1 for the forecast, exactly as temperature:
    the half-hour value of v and D's mean of it (`v`, `v_day_mean`). Instantaneous variables (cloud cover, wind speed,
    relative humidity) are interpolated to the half-hour's label instant like temperature. Radiation and
    precipitation are preceding-hour means or sums: a half-hour starting at t takes the value of the hour ending at the
    next full hour after t's hour starts (t floored to the hour, plus one hour), no interpolation. Humidity is relative
    humidity (dew point fetched but not used: one choice, made now). Label convention: a demand half-hour is stamped with its start
    (the slot 08:30 covers 08:30–09:00), so the half-hour starting at t lies in the hour whose value is stamped at
    t floored to the hour plus one hour (decided by the guide session; checked on a clear summer day, notebook).
  - **W + v:** W's inputs plus `v` and `v_day_mean`. **GAM + v:** the GAM plus one cubic regression spline of
    `v_day_mean` (same knot rule as the temperature terms; the day mean, not the half-hour value, because the half-hour
    value of radiation is zero at night and a spline of a constant cannot be fitted). Rank-deficient fits counted.
  - Rungs: 13a solar radiation, 13b cloud cover, 13c wind speed at 10 m, 13d relative humidity, 13e precipitation;
    each against the same model without it. **Keep rule** (from 14.1): lower development NMAE and corrected DM p < 0.05.
    13f: W with all inputs kept for W, the GAM with all kept for the GAM (if none is kept for a model, it stays as
    is). 13g: 0.5 × new GAM + 0.5 × new W, compared with run 9 (DM). By-month and by-time-band tables (00–06, 06–10,
    10–16, 16–20, 20–24 local) for the kept rungs and 13g. Output `data/runs/dev_run13_ladder.csv`, console kept.
  - **Information only, not part of the keep rule** (added at the guide's review): every W rung's trained models also
    predict from the ERA5 table, and that NMAE is printed beside the forecast one and saved, to separate "this input
    does not matter" from "it matters but its forecast is too poor".
  - **Recorded before the result:** ten keep tests at the 5% level give about one chance in two of a false keep
    somewhere; the judgment that counts is 13g against run 9, and nothing from run 13 is treated as established until it
    is tested on data not used to choose it.
- **C, development sites kept as drawn (decided by the guide session overnight, for the owner to confirm).** Observed
  on download (1 January 2023 – 31 December 2024, `sites.load_site_demand`, every published transformer required;
  three sites have one transformer): completeness 97.2–100%, no negative values, clock-change days 46 and 50
  half-hours. Guyhirn is small (mean 1.43 MW, minimum 0.00, 5.5% repeated values); Kenton is small (2.41 MW, 8.2%
  repeats); Orton's minimum is 0.44 MW against a mean of 10.1 (possibly a transfer); Takeley's minimum is 0.08 MW. All
  four stay: the screen is the rule, fixed before the draw. Written before any pooled result: every pooled result is
  reported per site as well as overall, and near-zero readings stay as they are (never filled or clipped), with the
  count of half-hours below 10% of the site's median reported per site.
- **E, run 14 detailed specification (written 2026-11-12 before it runs; `holidays_run.py`, a new module).**
  Newmarket, development period, the same scored half-hours. Chronos-2 at its pinned revision, and Timestral-123M at
  its pinned revision only if run 12's better version is within 0.3 percentage points of Chronos-2's better version
  (NMAE). Each model exactly as in runs 11 and 12 with temperature (the same context, window, median and defaults),
  plus two known-future covariate rows over the context and the forecast window: bank holiday (England and Wales,
  the same `bank_holidays.json`) and the Christmas period (24 December – 2 January, as `train.calendar_features`
  defines it), each 0/1 by the local date of the half-hour. Chronos-2 takes them as `past_covariates` and
  `future_covariates`; Timestral as `known_covariates` rows (all-0/1 rows are treated as indicators, its README).
  Compared with the same model with temperature only (f11, f12); keep rule as in D. The development period holds
  bank holidays on 29 March, 1 April, 6 May, 27 May, 26 August, 25 and 26 December 2024: few days, so the DM test
  has little to work with, recorded before the result. Output `data/runs/dev_run14_holidays.csv`, console kept.
  Also recorded before the result: Chronos-2's context is 8,192 half-hours (about 170 days), so each forecast sees
  only the bank holidays of the last five or six months. For 29 March and 1 April 2024 that means Christmas Day, Boxing
  Day and New Year's Day 2023–24, and no spring holiday; for 26 August, the three spring ones. Timestral's longer
  context sees every holiday since January 2023. A null result for Chronos-2 would therefore say little about holiday
  information in general. The bank-holiday line is the NMAE of those days (normalised by their own mean demand), with
  the number of days.
- **G, run 15, two fixed blends with Timestral (decided by the guide session overnight, 12 November 2026, for the owner
  to confirm; written before it runs; `blend.py`, a new module).** Newmarket, development period, the same 11,434
  half-hours. No model is fitted: only saved columns are combined. Run after run 13 reports.
  - **15a** = (GAM + W + Timestral with forecast temperature) / 3, equal weights. GAM and W are run 13's 13f versions
    if run 13 keeps any input for that model, otherwise the frozen f7 and `f4a_l1_no364`.
  - **15b** = 0.5 × run 9 + 0.5 × Timestral with forecast temperature, where run 9 is 13g if run 13 keeps anything,
    otherwise the frozen f9.
  - No weights are fitted or searched; these two are the only blends. Each is compared with run 9 (and with 13g if run
    13 keeps anything) and with f12: NMAE, MAE, peak MAE (53 complete days), corrected DM, by month and by time band
    (00–06, 06–10, 10–16, 16–20, 20–24 local). Output `data/runs/dev_run15_blends.csv`, console kept.
  - **Recorded before the result:** the reviewing session has already seen, as an information line in its own audit,
    that 0.5 × f12 + 0.5 × f9 scores 4.212% on this period, so 15b is not a blind test; neither blend counts as
    established until it is checked on data not used to choose it.
- **H, run 16, carry-over of the candidate to the development sites, 2024 only (decided by the guide session
  overnight, 12 November 2026, for the owner to confirm; written before anything of it runs; `carryover.py`, a new
  module; nothing frozen edited). Replaces F in the order; F moves after it.**
  - **Sites:** Bungay first, then the 15 development sites in draw order, each once its IFS runs (all seven
    variables) are complete. Bungay gets the five extra variables fetched for ERA5 (to 31 December 2024) and for the
    2024 runs only. **No 2025 data is used at any site:** demand is cut at 00:00 UTC on 1 January 2025 straight after
    loading; ERA5 is read up to and including that instant (the end of 31 December 2024: the last half-hour's
    interpolation and its preceding-hour mean need it); only the runs of 13 March – 30 December 2024 are read.
    Held-out sites are not touched.
    Bungay's extra ERA5 ends at 23:00 UTC on 31 December 2024 (the archive stops at the end of the end date), so its
    extra inputs for 31 December 23:30 are missing in the ERA5 table only; that row is a target day, never in training
    (the last refit, Monday 30 December, trains on earlier dates), so no forecast changes (reviewed by the guide session).
  - **Per site, exactly Newmarket's recipe, nothing chosen per site:** 0a, 0b, 1a, W without weather, 9 without
    weather; W, the GAM, run 9; W_13f (all five inputs), GAM_13f (radiation day mean), 13g; Chronos-2 with forecast
    temperature; Timestral-123M with forecast temperature; 15a; 15b. Same refit rule, issue time, alignment rules
    (14.1 D), pinned revisions and library defaults; demand through `sites.load_site_demand` with every published
    transformer required; the England and Wales bank-holiday file for every site. Weather models only on days whose
    run of D−1 exists (as `train.py`); the 13f models also need D's mean of each of the five inputs.
  - **Check first:** the same generic code run on Newmarket must reproduce the saved development columns (frozen file,
    run 13) to within 1e-9, give exactly the frozen file's scored half-hours, and reproduce Timestral on three days
    of run 12 (within 1e-4 MW); otherwise nothing is run on any site.
    **Amended after seeing the check (decided by the guide session, 12 November 2026, 04:56):** the check (console
    `data/runs/run16_check_console.txt`, `carryover.py` dab2ce0001a64d67) reproduced eleven columns to 1.8e-15 –
    3.6e-15 and the scored set exactly (11,434 half-hours), and Timestral to 4.73e-07, but Chronos-2 (f11, f11_nw)
    differed by 4.77e-07 MW, exactly 2⁻²¹: one rounding step of a 32-bit float at 8–16 MW (Chronos-2 returns 32-bit
    values; the saved file holds them as shortest float32 text, none of whose values is exactly representable after the
    round trip). The gate failed as written and nothing ran. The tolerance for those two columns was loosened to 1e-5 MW
    after seeing the check, for that reason; the other eleven stay at 1e-9. The check was not rerun; its printed result
    passes under the amended rule. (The Timestral line covers two days: the first pick, 14 March, has no run of D−1.)
  - **Order changed for time, before any site result exists (guide session, 04:56):** the cheap models took 1,154 s at
    Newmarket, so all 16 sites need about five hours. New order: cheap models for Bungay and the first six development
    sites (Hardwick Rd, Thompsons Ln, Guyhirn, Gaywood Bridge, Chelmsford East Local, Kenton); Timestral for Bungay; a
    report on what exists (about 08:30); then the other nine sites' cheap models and a second report; then Timestral
    site by site in draw order, the report re-run after each. Every site is still run and reported; none is dropped.
  - **Order (one heavy job at a time):** every model except Timestral, 15a and 15b for all sites whose weather is
    complete, saved per site (`data/runs/carryover/<site>_cheap.csv`); then Timestral (about an hour a site) in the same
    order for as many sites as fit before about 08:30, adding 15a and 15b where it exists.
  - **Scored half-hours per site:** metered and forecast by every model in the list for that site (a site without
    Timestral is scored on the cheap models' intersection, and said so).
  - **Reported per site and pooled** (pooled = sum of absolute errors over sum of demand, and the plain mean of site
    NMAEs): every model's NMAE; comparator = the site's best no-weather model (as `report.py`); margins of run 9, 13g
    and 15a over it; corrected DM per site for 13g against run 9, 15a against 13g, 15a against run 9, Timestral against
    Chronos-2, Timestral against run 9, with the count of sites where each is positive and where it is significant;
    pooled NMAE by month; per site, the half-hours below 10% of the site's median.
  - **Recorded before any result:** these sites were screened and drawn by rule, not chosen by result. This checks a
    recipe chosen at one site on 16 other places in the same region and months, so it tests carry-over across places,
    not across time. The guide expects smaller gains than at Newmarket (as Bungay 2025 showed: 6.35% against 23%),
    and expects the radiation gain to vary with how much small-scale solar each site has. Every site is reported,
    including the four odd ones; none is dropped.
