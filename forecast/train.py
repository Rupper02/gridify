"""Runs 0a, 0b, 1a, 1b, 2, 3, 4a-4c, 5a, 6a and the 4a checks (README section 7) on the development period, replayed day by day.

Issue time 09:30 on D-1: features use readings up to the half-hour ending 09:00 on D-1. UKPN labels a half-hour by its
start (the file runs 00:00 to 23:30 on whole days), so the last usable reading on D-1 is the one labelled 08:30.
LightGBM is refit every Monday at the issue time on every complete target day up to the day before.

Runs 2 and 3 are one model, trained with actual temperature (ERA5): run 2 predicts with ERA5 for D, run 3 with the
00 UTC ECMWF IFS run of D-1, so the gap between them is the weather forecast's alone.
"""
import inspect
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy import stats

import cache
from decomposition import decomposition_forecasts, fitted_normal
from gam import gam_forecasts, plot_combined, plot_curves
from fetch_weather import ERA5_FILE, RUNS_DIR as IFS_RUNS_DIR, era5_file, runs_dir
from tracking import child, log_refit, log_scores, start
from load import NEWMARKET_FILE, SITES, load_demand

# Bump by hand for any change the cache key cannot see (it already hashes replay, decomposition.py, offset functions,
# the input columns and the LightGBM version): it invalidates every cached forecast
CODE_VERSION = 1
DEV_START, DEV_END = "2024-03-14", "2024-12-31"
# Scoring periods (section 7): `--period test` is the final test, run once, only with the frozen models
PERIODS = {"dev": (DEV_START, DEV_END), "test": ("2025-01-01", "2025-12-31")}
HOLIDAYS_FILE = Path("data/raw/calendar/bank_holidays.json")
OUT_DIR = Path("data/runs")
# Slots 0..17 on D-1 start 00:00..08:30, so all of them have ended by 09:00
MORNING_SLOTS = list(range(18))
# UK heating base temperature (section 4)
HEATING_BASE_C = 15.5
# Fixed before the first run, not tuned
LGBM_PARAMS = dict(objective="regression", learning_rate=0.05, num_leaves=31, seed=0, deterministic=True, verbose=-1)
N_TREES = 500
# Days of autocorrelation the DM variance allows for: a week covers a cold spell
DM_LAGS = 7
FEATURES = ["slot", "dow", "doy_sin", "doy_cos", "bank_holiday", "christmas",
            "d2", "d1_morning", "d7", "d7_28_mean", "d364"]
WEATHER = ["temp", "temp_day_mean", "hdd"]
# Runs 4a-4c: one input added per step, each step on top of the last (section 7, step 4)
LADDER = {"4a": ["d1_same"], "4b": ["d3", "d4", "d5", "d6"], "4c": ["trend_years"]}
MODELS = {"f0a": "0a same as last week", "f0b": "0b mean of 4 weeks", "f1a": "1a decomposition", "f1b": "1b LightGBM",
          "f2": "2 + actual temp", "f3": "3 + forecast temp",
          **{f"f{run}_nw": f"{run} no weather" for run in LADDER},
          **{f"f{run}": f"{run} + forecast temp" for run in LADDER},
          "f5a_nw": "5a no weather", "f5a": "5a + forecast temp",
          "f6a_nw": "6a no weather", "f6a": "6a + forecast temp",
          "f4a_no364_nw": "4a-d364 no weather", "f4a_no364": "4a-d364 + fcst temp",
          "f4a_l1_nw": "4a L1 no weather", "f4a_l1": "4a L1 + fcst temp",
          "f4a_l1_no364_nw": "4a L1-d364 no weather", "f4a_l1_no364": "4a L1-d364 + fcst temp",
          "favg_nw": "avg 1a+4aL1 no weather", "favg": "avg 1a+4aL1 + fcst temp",
          "f7": "7 GAM + fcst temp",
          "f8a": "8a W + lag-day temp",
          "f8b_nw": "8b W-doy no weather", "f8b": "8b W-doy + fcst temp",
          "f9_nw": "9 avg 1a+W no weather", "f9": "9 avg GAM+W + fcst temp",
          "f11_nw": "11 Chronos-2 no weather", "f11": "11 Chronos-2 + fcst temp"}
# Scored on their own half-hours, not in the batch intersection (run 10 has no forecasts before its training data exists)
SEPARATE = {"f10": "10 W trained on IFS as issued"}
# The working model W is 4a L1 without d364 (lab notebook, 2026-11-11)
WORKING_NW, WORKING = "f4a_l1_no364_nw", "f4a_l1_no364"
# The models that get the single final-test run (freeze specification, README); the rest are development rungs.
# W with actual temperature (H2) is a by-product of W's own trained models, proposed for the owner to confirm.
MODELS["fW_actual"] = "W + actual temp (H2)"
FROZEN = ["f0a", "f0b", "f1a", WORKING_NW, "f9_nw", WORKING, "f7", "f9", "f11_nw", "f11", "fW_actual"]
# Run 5a: 4a's inputs, but the model learns the deviation from this past-only "normal" (run 0b's forecast)
NORMAL = "d7_28_mean"


def half_hours(demand: pd.Series) -> pd.DataFrame:
    """One row per half-hour: local date, wall-clock slot 0-47 and the metered MW"""
    idx = demand.index
    return pd.DataFrame({
        "date": pd.DatetimeIndex(idx.date),
        "slot": idx.hour * 2 + idx.minute // 30,
        "mw": demand.to_numpy(),
    }, index=idx)


def day_slot_matrix(rows: pd.DataFrame) -> pd.DataFrame:
    """Demand as one row per day and one column per slot; the two autumn 01:xx readings share a slot and are averaged"""
    days = rows.pivot_table(index="date", columns="slot", values="mw", aggfunc="mean")
    return days.reindex(pd.date_range(days.index.min(), days.index.max(), freq="D"), columns=range(48))


def slot_matrix(rows: pd.DataFrame, values: pd.Series) -> pd.DataFrame:
    """Any half-hourly series as one row per day and one column per slot, like day_slot_matrix"""
    return day_slot_matrix(rows.assign(mw=values))


def lag_temperature(rows: pd.DataFrame, day_of_d: pd.Series, past: pd.Series) -> pd.DataFrame:
    """D's daily mean temperature minus that of D-2, and minus the mean of D-7, D-14, D-21, D-28 (run 8a)"""
    past = past.reindex(pd.date_range(past.index.min(), past.index.max(), freq="D"))
    weeks = pd.concat([past.shift(k) for k in (7, 14, 21, 28)], axis=1).mean(axis=1)
    d = rows["date"]
    return pd.DataFrame({"dtemp_d2": d.map(day_of_d).to_numpy() - d.map(past.shift(2)).to_numpy(),
                         "dtemp_d7_28": d.map(day_of_d).to_numpy() - d.map(weeks).to_numpy()}, index=rows.index)


def history_features(rows: pd.DataFrame) -> pd.DataFrame:
    """Section 4's history inputs for each (date, slot), each looked up on an earlier day only"""
    days = day_slot_matrix(rows)
    # shift(k) on a daily index moves every row k days later: row D then holds day D-k
    lag = {k: days.shift(k) for k in (1, 2, 3, 4, 5, 6, 7, 14, 21, 28, 364)}
    weeks = [lag[k] for k in (7, 14, 21, 28)]
    morning = lag[1][MORNING_SLOTS]
    morning_mean = morning.mean(axis=1).where(morning.notna().sum(axis=1) == len(MORNING_SLOTS))
    feats = {
        # Same slot on D-1: metered by 09:00 only for slots before 09:00
        "d1_same": lag[1][MORNING_SLOTS].reindex(columns=range(48)),
        "d2": lag[2],
        **{f"d{k}": lag[k] for k in (3, 4, 5, 6)},
        "d7": lag[7],
        # Mean of whichever of D-7..D-28 were metered
        "d7_28_mean": sum(w.fillna(0) for w in weeks) / sum(w.notna().astype(int) for w in weeks).replace(0, np.nan),
        "d364": lag[364],
        # Same value for every slot of D: the mean of D-1 up to 09:00, only when all 18 slots are metered (a mean over
        # whichever slots survive would change with which slots those are)
        "d1_morning": pd.DataFrame({s: morning_mean for s in range(48)}),
    }
    stacked = {name: f.stack(future_stack=True) for name, f in feats.items()}
    return pd.concat(stacked, axis=1).rename_axis(["date", "slot"])


def calendar_features(rows: pd.DataFrame, holidays: set) -> pd.DataFrame:
    date = rows["date"]
    doy = 2 * np.pi * date.dt.dayofyear / 365.25
    christmas = ((date.dt.month == 12) & (date.dt.day >= 24)) | ((date.dt.month == 1) & (date.dt.day <= 2))
    return pd.DataFrame({
        "dow": date.dt.dayofweek,
        "doy_sin": np.sin(doy),
        "doy_cos": np.cos(doy),
        "bank_holiday": date.isin(holidays).astype(int),
        "christmas": christmas.astype(int),
        "trend_years": (date - pd.Timestamp("2023-01-01")).dt.days / 365.25,
    }, index=rows.index)


def load_holidays(path: Path) -> set:
    events = json.loads(path.read_text(encoding="utf-8"))["england-and-wales"]["events"]
    return set(pd.to_datetime([e["date"] for e in events]))


def to_half_hours(hourly: pd.Series, at: pd.DatetimeIndex) -> pd.Series:
    """Hourly values linearly interpolated to the given instants"""
    joined = hourly.reindex(hourly.index.union(at)).interpolate(method="time", limit_area="inside")
    return joined.reindex(at)


def read_hourly(path: Path) -> pd.Series:
    frame = pd.read_csv(path, parse_dates=["time_utc"])
    return frame.set_index("time_utc")["temperature_c"]


def era5_temps(rows: pd.DataFrame, path: Path = ERA5_FILE) -> pd.Series:
    return to_half_hours(read_hourly(path), rows.index.tz_convert("UTC")).set_axis(rows.index)


def ifs_temps(rows: pd.DataFrame, folder: Path = IFS_RUNS_DIR) -> pd.Series:
    """For each day D, the temperature the 00 UTC run of D-1 forecast; NaN where that run is missing"""
    parts = []
    for path in sorted(folder.glob("*.csv")):
        target = pd.Timestamp(path.stem) + pd.Timedelta(days=1)
        on_day = rows.index[rows["date"] == target]
        if len(on_day):
            parts.append(to_half_hours(read_hourly(path), on_day.tz_convert("UTC")).set_axis(on_day))
    return pd.concat(parts).reindex(rows.index)


def weather_features(rows: pd.DataFrame, temp: pd.Series) -> pd.DataFrame:
    """Temperature at each half-hour of D, the daily mean of D and heating degrees (section 4)"""
    day_mean = temp.groupby(rows["date"]).transform("mean")
    return pd.DataFrame({"temp": temp, "temp_day_mean": day_mean,
                         "hdd": (HEATING_BASE_C - day_mean).clip(lower=0)}, index=rows.index)


def refit_mondays(table: pd.DataFrame, start: str = DEV_START, end: str = DEV_END) -> pd.Series:
    """For each row of the period, the Monday whose refit forecasts it (the Monday of its issue day, D-1)"""
    dev = table[(table["date"] >= start) & (table["date"] <= end)]
    issue = dev["date"] - pd.Timedelta(days=1)
    return issue - pd.to_timedelta(issue.dt.dayofweek, unit="D")


def train_one(table: pd.DataFrame, features: list, monday: pd.Timestamp, base: pd.Series, params: dict | None,
              record: bool = False) -> tuple:
    """The model of one weekly refit: every metered row before `monday`, learning demand minus `base`.

    Returns (booster, training-loss curve) or (None, None) when there is nothing to learn from yet.
    """
    # Every target day up to the Sunday before is fully metered by 09:00 on Monday
    train = (table["date"] < monday) & table["mw"].notna() & base.notna()
    if not train.any():
        return None, None
    data = lgb.Dataset(table.loc[train, features], table.loc[train, "mw"] - base[train])
    curve = {}
    watch = dict(valid_sets=[data], valid_names=["train"], callbacks=[lgb.record_evaluation(curve)]) if record else {}
    model = lgb.train(params or LGBM_PARAMS, data, num_boost_round=N_TREES, **watch)
    return model, (next(iter(curve["train"].values())) if record else None)


def replay(table: pd.DataFrame, features: list, predict_with: dict, offset=None, params: dict | None = None,
           track: tuple | None = None, start: str = DEV_START, end: str = DEV_END) -> dict:
    """Forecasts for every development day, refit each Monday on target days before that Monday.

    The model is trained on `table`; each entry of `predict_with` supplies the feature values it predicts from.
    With `offset` (a column name, or a function of the refit Monday returning a value per row), the model learns demand
    minus the offset and adds it back; rows without an offset get no forecast. `track` is (MLflow client, run ids).
    """
    refit = refit_mondays(table, start, end)
    dev = table.loc[refit.index]
    forecasts = {name: [] for name in predict_with}
    mondays = refit.unique()
    for step, (monday, target_rows) in enumerate(dev.groupby(refit)):
        if offset is None:
            base = pd.Series(0.0, index=table.index)
        elif callable(offset):
            base = offset(monday)
        else:
            base = table[offset]
        model, loss = train_one(table, features, monday, base, params, record=bool(track))
        if model is None:
            # Nothing to learn from yet (run 10 before the forecast archive starts): no forecast this week
            continue
        if track:
            importance = dict(zip(features, model.feature_importance("gain")))
            client, run_ids = track
            for run_id in run_ids:
                log_refit(client, run_id, step, monday, loss, importance, last=step == len(mondays) - 1)
        rows = target_rows.index[base[target_rows.index].notna()]
        for name, source in predict_with.items():
            forecasts[name].append(pd.Series(model.predict(source.loc[rows, features]) + base[rows], index=rows))
    return {name: pd.concat(parts).reindex(predict_with[name].index) for name, parts in forecasts.items()}


def complete_days(dev: pd.DataFrame) -> pd.Index:
    """Days with every half-hour metered: the only days a daily peak is known"""
    by_day = dev.groupby("date")["mw"]
    complete = by_day.count() == by_day.size()
    return complete.index[complete]


def metrics(scored: pd.DataFrame, peak_days: pd.DataFrame, col: str) -> dict:
    err = (scored[col] - scored["mw"]).abs()
    peaks = peak_days.loc[peak_days.groupby("date")["mw"].idxmax()]
    return {
        "MAE": err.mean(),
        "NMAE": err.mean() / scored["mw"].mean(),
        "peak_MAE": (peaks[col] - peaks["mw"]).abs().mean(),
    }


def diebold_mariano(dev: pd.DataFrame, a: str, b: str) -> tuple[float, float]:
    """DM test on daily MAE: a positive statistic means b beats a.

    Daily loss differences are autocorrelated (cold spells last days) and slots from 09:00 are two days ahead, so the
    variance is Newey-West (Bartlett weights, DM_LAGS days) with the Harvey-Leybourne-Newbold correction for h=2.
    """
    errors = dev.assign(ea=(dev[a] - dev["mw"]).abs(), eb=(dev[b] - dev["mw"]).abs())
    daily = errors.groupby("date")[["ea", "eb"]].mean()
    d = (daily["ea"] - daily["eb"]).to_numpy()
    n, dev_d = len(d), d - d.mean()
    variance = dev_d @ dev_d / n
    for lag in range(1, DM_LAGS + 1):
        variance += 2 * (1 - lag / (DM_LAGS + 1)) * (dev_d[lag:] @ dev_d[:-lag]) / n
    dm = d.mean() / np.sqrt(variance / n)
    h = 2
    dm *= np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    return dm, 2 * stats.t.sf(abs(dm), df=n - 1)


if __name__ == "__main__":
    period = sys.argv[sys.argv.index("--period") + 1] if "--period" in sys.argv else "dev"
    START, END = PERIODS[period]
    # The final test runs only the frozen models; on the development period `--frozen` proves that path reproduces
    frozen = "--frozen" in sys.argv or period == "test"
    site = sys.argv[sys.argv.index("--site") + 1] if "--site" in sys.argv else "newmarket"
    if site != "newmarket" and period != "test":
        # Carry-over sites run only the frozen test (README section 13): nothing is developed or looked at there
        raise SystemExit(f"{site}: only --period test is allowed")
    demand = load_demand(SITES[site]["file"])
    rows = half_hours(demand)
    table = rows.join(history_features(rows), on=["date", "slot"])
    holidays = load_holidays(HOLIDAYS_FILE)
    table = table.join(calendar_features(rows, holidays))
    use_cache = "--no-cache" not in sys.argv
    # The table fingerprints catch changes in what the feature code produces; the source hashes catch changes in how
    # forecasts are made from the same table; the LightGBM version catches a library upgrade
    shared = {"code_version": CODE_VERSION, "dev": [START, END], "lightgbm": lgb.__version__,
              "demand": cache.fingerprint(rows, ["date", "slot", "mw"]), "holidays": cache.file_fingerprint(HOLIDAYS_FILE),
              "decomposition_src": cache.file_fingerprint(Path("decomposition.py"))}
    if site != "newmarket":
        # Newmarket's keys stay as they were; any other site is named in its keys as well as fingerprinted
        shared["site"] = site
    spec_1a = {**shared, "model": "1a decomposition"}
    key_1a = cache.key(spec_1a)
    f1a = cache.load(key_1a) if use_cache else None
    if f1a is None:
        f1a = decomposition_forecasts(day_slot_matrix(rows), holidays, START, END)
        cache.save(key_1a, f1a, spec_1a)
    table = table.join(f1a.rename("f1a"), on=["date", "slot"])
    era5, ifs = era5_temps(rows, era5_file(site)), ifs_temps(rows, runs_dir(site))
    actual = table.join(weather_features(rows, era5))
    forecast = table.join(weather_features(rows, ifs))
    # Run 8a: D's daily mean temperature against D-2 and against D-7..D-28; the past days always from ERA5
    era5_day, ifs_day = era5.groupby(rows["date"]).mean(), ifs.groupby(rows["date"]).mean()
    actual_8a = actual.join(lag_temperature(rows, era5_day, era5_day))
    forecast_8a = forecast.join(lag_temperature(rows, ifs_day, era5_day))

    # Run 7: the GAM, trained on ERA5, forecast from the IFS run of D-1 (gam.py)
    spec_7 = {**shared, "model": "7 GAM", "gam_src": cache.file_fingerprint(Path("gam.py")),
              "era5": cache.fingerprint(era5), "ifs": cache.fingerprint(ifs)}
    key_7 = cache.key(spec_7)
    gam_out = cache.load(key_7) if use_cache else None
    if gam_out is None:
        gam_out = gam_forecasts(day_slot_matrix(rows), holidays, slot_matrix(rows, era5), era5_day,
                                slot_matrix(rows, ifs), ifs_day, START, END)
        cache.save(key_7, gam_out, spec_7)
    f7, gam_ranks, gam_curves = gam_out

    # Run 11: Chronos-2, zero-shot (chronos_run.py)
    import chronos
    import torch
    from chronos_run import MODEL_ID, REVISION, chronos_forecasts

    def ifs_run(run_day, instants):
        path = runs_dir(site) / f"{run_day:%Y-%m-%d}.csv"
        return to_half_hours(read_hourly(path), instants).to_numpy() if path.exists() else None

    spec_11 = {**shared, "model": "11 Chronos-2", "chronos": chronos.__version__, "torch": torch.__version__,
               "model_id": MODEL_ID, "revision": REVISION, "src": cache.file_fingerprint(Path("chronos_run.py")),
               "era5": cache.fingerprint(era5), "ifs": cache.fingerprint(ifs)}
    key_11 = cache.key(spec_11)
    chronos_out = cache.load(key_11) if use_cache else None
    if chronos_out is None:
        chronos_out = chronos_forecasts(demand, era5, ifs_run, START, END)
        cache.save(key_11, chronos_out, spec_11)
    print(f"Chronos-2 ({spec_11['revision'][:12]}): {chronos_out['days']} days, context {chronos_out['context_length']}, "
          f"{chronos_out['seconds']:.0f} s predicting ({chronos_out['seconds'] / chronos_out['days']:.1f} s per day, both versions)")
    table = table.join(f7.rename("f7"), on=["date", "slot"])
    deficient = (gam_ranks["rank"] < gam_ranks["columns"]).sum()
    print(f"GAM: {len(gam_ranks)} fits, {deficient} rank-deficient")
    # The development plots keep their names; other periods get their own files
    suffix = ("" if period == "dev" else f"_{period}") + ("" if site == "newmarket" else f"_{site}")
    plot_curves(gam_curves, Path(f"data/plots/8_gam_temperature_curves{suffix}.png"))
    plot_combined(gam_curves, Path(f"data/plots/9_gam_combined_temperature_effect{suffix}.png"))

    models = "frozen models" if frozen else "every run in README section 9"
    cache_state = "on" if use_cache else "off"
    client, parent = start(f"{site}, {period} replay ({START} to {END}), {models}; weather runs train on ERA5 and predict from "
                           f"the IFS 00 UTC run of D-1. Cache {cache_state}.",
                           experiment="newmarket-development" if period == "dev" else f"{site}-{period}")
    run_ids = {}
    ifs_rows = forecast[forecast["temp"].notna()]
    labels = {id(ifs_rows): "forecast temp", id(actual): "actual temp", id(forecast): "forecast temp", id(actual_8a): "actual temp + lag-day temp",
              id(forecast_8a): "forecast temp + lag-day temp"}

    def fit(outputs: dict, train_on: pd.DataFrame, features: list, trained_on: str, **kw) -> None:
        """Replay one model (or reuse its cached forecasts), log it to MLflow, store its forecasts in `table`"""
        offset = kw.get("offset")
        source = {col: labels.get(id(src), "no weather") for col, src in outputs.items()}
        params = {"features": ",".join(features), "trained_on": trained_on, "n_trees": N_TREES,
                  "offset": getattr(offset, "__name__", offset), **(kw.get("params") or LGBM_PARAMS)}
        read = features + ([offset] if isinstance(offset, str) else [])
        spec = {**shared, **params, "predicts_from": source, "replay_src": cache.text_fingerprint("".join(inspect.getsource(f) for f in (replay, train_one, refit_mondays))),
                "offset_src": cache.text_fingerprint(inspect.getsource(offset)) if callable(offset) else None,
                "train_inputs": cache.fingerprint(train_on, read + ["date", "slot", "mw"]),
                "predict_inputs": {col: cache.fingerprint(src, read) for col, src in outputs.items()}}
        spec_key = cache.key(spec)
        cached = cache.load(spec_key) if use_cache else None
        ids = {col: child(client, parent, {**MODELS, **SEPARATE}[col], {**params, "predicts_from": source[col],
                                                         "cached": cached is not None, "cache_key": spec_key})
               for col in outputs}
        forecasts = cached or replay(train_on, features, outputs, track=(client, list(ids.values())), start=START,
                                     end=END, **kw)
        if cached is None:
            cache.save(spec_key, forecasts, spec)
        for col, pred in forecasts.items():
            table[col] = pred
        run_ids.update(ids)

    features_4a = FEATURES + LADDER["4a"]
    without_364 = [f for f in features_4a if f != "d364"]
    l1 = {**LGBM_PARAMS, "objective": "regression_l1"}
    # The working model W (4a L1 without d364): trained on ERA5, predicting from IFS and, for H2, from ERA5
    fit({"f4a_l1_no364_nw": table}, table, without_364, "no weather", params=l1)
    fit({"f4a_l1_no364": forecast, "fW_actual": actual}, actual, without_364 + WEATHER, "ERA5", params=l1)
    if not frozen:
        fit({"f1b": table}, table, FEATURES, "no weather")
        fit({"f2": actual, "f3": forecast}, actual, FEATURES + WEATHER, "ERA5")
        features = list(FEATURES)
        for run, added in LADDER.items():
            features += added
            fit({f"f{run}_nw": table}, table, features, "no weather")
            fit({f"f{run}": forecast}, actual, features + WEATHER, "ERA5")
        fit({"f5a_nw": table}, table, features_4a, "no weather", offset=NORMAL)
        fit({"f5a": forecast}, actual, features_4a + WEATHER, "ERA5", offset=NORMAL)
        # Run 6a: the deviation from 1a's layers 1 and 2, refit on the days before each Monday
        days = day_slot_matrix(rows)
        keys = pd.MultiIndex.from_frame(table[["date", "slot"]])
        def normal_at(monday):
            return pd.Series(fitted_normal(days, holidays, monday).reindex(keys).to_numpy(), index=table.index)
        fit({"f6a_nw": table}, table, features_4a, "no weather", offset=normal_at)
        fit({"f6a": forecast}, actual, features_4a + WEATHER, "ERA5", offset=normal_at)
        # One-factor checks on 4a: without d364 (thin in early training), and an absolute-error objective (the metric)
        fit({"f4a_no364_nw": table}, table, without_364, "no weather")
        fit({"f4a_no364": forecast}, actual, without_364 + WEATHER, "ERA5")
        fit({"f4a_l1_nw": table}, table, features_4a, "no weather", params=l1)
        fit({"f4a_l1": forecast}, actual, features_4a + WEATHER, "ERA5", params=l1)
        # Fixed 50/50 average of 1a and 4a L1, nothing fitted
        table["favg_nw"] = 0.5 * table["f1a"] + 0.5 * table["f4a_l1_nw"]
        table["favg"] = 0.5 * table["f1a"] + 0.5 * table["f4a_l1"]
        # Run 8a: W + lag-day temperature (weather only); run 8b: W without the day-of-year inputs
        lag_temp = ["dtemp_d2", "dtemp_d7_28"]
        fit({"f8a": forecast_8a}, actual_8a, without_364 + WEATHER + lag_temp, "ERA5", params=l1)
        without_doy = [f for f in without_364 if f not in ("doy_sin", "doy_cos")]
        fit({"f8b_nw": table}, table, without_doy, "no weather", params=l1)
        fit({"f8b": forecast}, actual, without_doy + WEATHER, "ERA5", params=l1)
    # Run 9: fixed 50/50 averages of the GAM and W (the GAM without weather is 1a), nothing fitted
    table["f9_nw"] = 0.5 * table["f1a"] + 0.5 * table[WORKING_NW]
    table["f9"] = 0.5 * table["f7"] + 0.5 * table[WORKING]
    table["f11_nw"] = chronos_out["f11_nw"].reindex(table.index)
    table["f11"] = chronos_out["f11"].reindex(table.index)
    if not frozen:
        # Run 10 (flag 6): W trained on the IFS runs as issued, only rows that have one (from 15 March 2024)
        fit({"f10": forecast}, ifs_rows, without_364 + WEATHER, "IFS as issued", params=l1)
    table["f0a"] = table["d7"]
    table["f0b"] = table["d7_28_mean"]
    # Section 7, step 6: weather runs are scored only on days whose forecast run of D-1 exists
    weather_cols = ["f3", *(f"f{run}" for run in LADDER), "f5a", "f6a", "f4a_no364", "f4a_l1", "f4a_l1_no364", "favg",
                    "f7", "f8a", "f8b", "f9", "f11"]
    active = {col: MODELS[col] for col in (FROZEN if frozen else MODELS)}
    table.loc[forecast["temp_day_mean"].isna(), [c for c in weather_cols + ["fW_actual"] if c in active]] = np.nan

    dev = table[(table["date"] >= START) & (table["date"] <= END)]
    # Section 7, step 6: metered and forecast by every model
    scored = dev.dropna(subset=["mw", *active])
    # Peak error (at the half-hour of the actual daily peak): complete days on which every model forecasts every half-hour
    complete = dev[dev["date"].isin(complete_days(dev))]
    forecast_all = complete[list(active)].notna().all(axis=1).groupby(complete["date"]).all()
    peak_days = complete[complete["date"].isin(forecast_all.index[forecast_all])]
    client.log_metric(parent, "gam_rank_deficient_fits", deficient)
    print(f"{period}{' (frozen models)' if frozen else ''}: {len(dev)} half-hours on {dev['date'].nunique()} days; scored {len(scored)} half-hours on "
          f"{scored['date'].nunique()} days (mean {scored['mw'].mean():.2f} MW); peak error on {peak_days['date'].nunique()} complete days")
    issue = scored["date"] - pd.Timedelta(days=1)
    week = issue - pd.to_timedelta(issue.dt.dayofweek, unit="D")
    for col, name in active.items():
        m = metrics(scored, peak_days, col)
        print(f"{name:22s} MAE {m['MAE']:.3f} MW  NMAE {m['NMAE']:.2%}  peak MAE {m['peak_MAE']:.3f} MW")
        run_id = run_ids.get(col) or child(client, parent, name, {"model": name})
        log_scores(client, run_id, m, (scored[col] - scored["mw"]).abs().groupby(week).mean())
    pairs = [("f0a", "f1a"), ("f0a", "f1b"), ("f1a", "f1b"), ("f1b", "f2"), ("f1b", "f3"), ("f1a", "f3"), ("f2", "f3")]
    pairs += [(a, f"f{run}{suffix}") for run in LADDER for a, suffix in (("f1a", "_nw"), ("f1a", ""), ("f3", ""))]
    pairs += [("f1a", "f5a_nw"), ("f4a_nw", "f5a_nw"), ("f1a", "f5a"), ("f4a", "f5a")]
    for run in ("6a", "4a_no364", "4a_l1"):
        pairs += [("f1a", f"f{run}_nw"), ("f4a_nw", f"f{run}_nw"), ("f1a", f"f{run}"), ("f4a", f"f{run}")]
    pairs += [("f4a_l1_nw", "f4a_l1_no364_nw"), ("f4a_l1", "f4a_l1_no364"), ("f1a", "f4a_l1_no364")]
    pairs += [("f1a", "favg_nw"), ("f4a_l1_nw", "favg_nw"), ("f1a", "favg"), ("f4a_l1", "favg"), ("favg_nw", "f4a_l1_no364")]
    pairs += [("f1a", "f7"), ("favg_nw", "f7"), (WORKING, "f7"),
              (WORKING, "f8a"), (WORKING_NW, "f8b_nw"), (WORKING, "f8b"),
              ("f7", "f9"), (WORKING, "f9"), ("favg_nw", "f9"), ("f1a", "f9_nw"), (WORKING_NW, "f9_nw"), ("favg_nw", "f9_nw")]
    pairs += [(a, b) for b in ("f11_nw", "f11") for a in ("f9", WORKING, "f7", "f1a", "f9_nw")] + [("f11_nw", "f11")]
    pairs += [(WORKING_NW, WORKING), ("f9_nw", "f9"), ("fW_actual", WORKING)]
    pairs += [(a, "f9") for a in ("f0a", "f0b", "f1a", WORKING_NW, "f11")]
    for a, b in dict.fromkeys(pair for pair in pairs if pair[0] in active and pair[1] in active):
        dm, p = diebold_mariano(scored, a, b)
        print(f"DM {MODELS[b]} vs {MODELS[a]}: {dm:.2f} (p = {p:.2g})")
        client.log_metric(parent, f"DM/{b[1:]}_vs_{a[1:]}", dm)
        client.log_metric(parent, f"DM_p/{b[1:]}_vs_{a[1:]}", p)

    # Run 10 on its own half-hours, against W (ERA5-trained) on the same ones; whole period and its last three months
    for label, since in (("whole period", DEV_START), ("Oct-Dec 2024", "2024-10-01")) if not frozen else ():
        own = dev[dev["date"] >= since].dropna(subset=["mw", "f10", WORKING, "f9"])
        # Peak error on days where every half-hour is metered and forecast by all three
        per_day = own.groupby("date").size()
        own_peak = own[own["date"].isin(per_day.index[per_day == dev.groupby("date").size().reindex(per_day.index)])]
        own_issue = own["date"] - pd.Timedelta(days=1)
        own_week = own_issue - pd.to_timedelta(own_issue.dt.dayofweek, unit="D")
        print(f"run 10, {label}: {len(own)} half-hours on {own['date'].nunique()} days")
        for col, name in (("f10", SEPARATE["f10"]), (WORKING, MODELS[WORKING]), ("f9", MODELS["f9"])):
            m = metrics(own, own_peak, col)
            print(f"  {name:30s} MAE {m['MAE']:.3f} MW  NMAE {m['NMAE']:.2%}  peak MAE {m['peak_MAE']:.3f} MW")
            if col == "f10" and label == "whole period":
                log_scores(client, run_ids["f10"], m, (own[col] - own["mw"]).abs().groupby(own_week).mean())
        for a in (WORKING, "f9"):
            dm, p = diebold_mariano(own, a, "f10")
            print(f"  DM run 10 vs {MODELS[a]}: {dm:.2f} (p = {p:.2g})")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prefix = "" if site == "newmarket" else f"{site}_"
    out_file = OUT_DIR / f"{prefix}{period}_runs{'_frozen' if frozen else ''}.csv"
    scored[["mw", *active]].to_csv(out_file)
    if not frozen:
        dev[["mw", "f10"]].dropna().to_csv(OUT_DIR / "dev_run10.csv")
    client.log_artifact(parent, str(out_file))
    client.set_terminated(parent)
