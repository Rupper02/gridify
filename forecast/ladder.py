"""Run 13, the input ladder (README section 14.1, item D; the specification is written there before running).

Newmarket, development period, scored on the half-hours of data/runs/dev_runs_frozen.csv. W and the GAM are rebuilt
and checked against the frozen columns; then one weather input at a time is added to each, trained on ERA5 and
forecast from the IFS 00 UTC run of D-1. Keep rule: lower NMAE and corrected DM p < 0.05. Kept inputs are combined
once (13f) and run 9 recomputed as 0.5 x new GAM + 0.5 x new W (13g).

    uv run python ladder.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

from fetch_weather_extra import era5_extra_file, runs_extra_dir
from gam_extra import gam_forecasts_extra
from load import NEWMARKET_FILE, load_demand
from report import load as load_scored
from train import (DEV_END, DEV_START, FEATURES, HOLIDAYS_FILE, LADDER, LGBM_PARAMS, WEATHER, calendar_features,
                   day_slot_matrix, diebold_mariano, era5_temps, half_hours, history_features, ifs_temps,
                   load_holidays, replay, slot_matrix, to_half_hours, weather_features)

SCORED_FILE = Path("data/runs/dev_runs_frozen.csv")
OUT_FILE = Path("data/runs/dev_run13_ladder.csv")
# Rungs: name -> Open-Meteo variable, and whether it is a preceding-hour mean/sum (aligned, not interpolated)
RUNGS = {"13a": ("shortwave_radiation", True), "13b": ("cloud_cover", False), "13c": ("wind_speed_10m", False),
         "13d": ("relative_humidity_2m", False), "13e": ("precipitation", True)}
BANDS = [(0, 12, "00-06"), (12, 20, "06-10"), (20, 32, "10-16"), (32, 40, "16-20"), (40, 48, "20-24")]
TOLERANCE = 1e-9


def read_columns(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["time_utc"]).set_index("time_utc")


def to_half(hourly: pd.Series, at: pd.DatetimeIndex, preceding: bool) -> pd.Series:
    """Hourly values at half-hours stamped with their start: instantaneous ones interpolated like temperature;
    preceding-hour means or sums take the hour containing the half-hour (stamped at the floored hour plus one hour)"""
    if not preceding:
        return to_half_hours(hourly, at)
    return pd.Series(hourly.reindex(at.floor("h") + pd.Timedelta(hours=1)).to_numpy(), index=at)


def era5_series(rows: pd.DataFrame, variable: str, preceding: bool) -> pd.Series:
    hourly = read_columns(era5_extra_file("newmarket"))[variable]
    return to_half(hourly, rows.index.tz_convert("UTC"), preceding).set_axis(rows.index)


def ifs_series(rows: pd.DataFrame, variable: str, preceding: bool) -> pd.Series:
    """For each day D, the value the 00 UTC run of D-1 forecast; NaN where that run is missing"""
    parts = []
    for path in sorted(runs_extra_dir("newmarket").glob("*.csv")):
        on_day = rows.index[rows["date"] == pd.Timestamp(path.stem) + pd.Timedelta(days=1)]
        if len(on_day):
            hourly = read_columns(path)[variable]
            parts.append(to_half(hourly, on_day.tz_convert("UTC"), preceding).set_axis(on_day))
    return pd.concat(parts).reindex(rows.index)


def nmae(frame: pd.DataFrame, col: str) -> float:
    return (frame[col] - frame["mw"]).abs().mean() / frame["mw"].mean()


def margin_table(frame: pd.DataFrame, new: str, old: str) -> str:
    def m(part):
        return 1 - (part[new] - part["mw"]).abs().sum() / (part[old] - part["mw"]).abs().sum()
    months = "  ".join(f"{p.strftime('%b')} {m(part):+.1%}" for p, part in frame.groupby(frame["date"].dt.to_period("M")))
    slots = frame.index.hour * 2 + frame.index.minute // 30
    bands = "  ".join(f"{name} {m(frame[(slots >= a) & (slots < b)]):+.1%}" for a, b, name in BANDS)
    return f"    by month: {months}\n    by band:  {bands}"


if __name__ == "__main__":
    demand = load_demand(NEWMARKET_FILE)
    rows = half_hours(demand)
    holidays = load_holidays(HOLIDAYS_FILE)
    table = rows.join(history_features(rows), on=["date", "slot"]).join(calendar_features(rows, holidays))
    era5, ifs = era5_temps(rows), ifs_temps(rows)
    actual = table.join(weather_features(rows, era5))
    forecast = table.join(weather_features(rows, ifs))
    days = day_slot_matrix(rows)
    era5_day, ifs_day = era5.groupby(rows["date"]).mean(), ifs.groupby(rows["date"]).mean()
    era5_slot, ifs_slot = slot_matrix(rows, era5), slot_matrix(rows, ifs)

    # Each rung's two inputs, on ERA5 (training) and the IFS run of D-1 (forecast)
    extra = {}
    for rung, (variable, preceding) in RUNGS.items():
        a, f = era5_series(rows, variable, preceding), ifs_series(rows, variable, preceding)
        extra[rung] = {"actual": a, "forecast": f, "actual_day": a.groupby(rows["date"]).mean(),
                       "forecast_day": f.groupby(rows["date"]).mean(), "variable": variable}
        actual[variable], forecast[variable] = a, f
        actual[f"{variable}_day_mean"] = a.groupby(rows["date"]).transform("mean")
        forecast[f"{variable}_day_mean"] = f.groupby(rows["date"]).transform("mean")

    # The alignment check (README notebook): a clear summer day, radiation by UTC hour after alignment
    check_day = pd.Timestamp("2024-07-19")
    rad = extra["13a"]["actual"][rows["date"] == check_day]
    by_hour = rad.groupby(rad.index.tz_convert("UTC").hour).mean()
    print("Alignment check, ERA5 radiation on 2024-07-19 by UTC hour (W/m2):",
          " ".join(f"{h:02d}:{v:.0f}" for h, v in by_hour.items()))

    frame = load_scored(SCORED_FILE)
    l1 = {**LGBM_PARAMS, "objective": "regression_l1"}
    w_features = [f for f in FEATURES + LADDER["4a"] if f != "d364"] + WEATHER

    def to_frame(series: pd.Series) -> np.ndarray:
        return series.reindex(frame.index).to_numpy()

    def fit_w(added: list) -> tuple[np.ndarray, np.ndarray]:
        """Forecasts from the IFS table, and (information only) from the ERA5 table with the same trained models"""
        out = replay(actual, w_features + added, {"f": forecast, "a": actual}, params=l1, start=DEV_START, end=DEV_END)
        return to_frame(out["f"]), to_frame(out["a"])

    def fit_gam(rungs: list) -> tuple[np.ndarray, int]:
        out, ranks = gam_forecasts_extra(days, holidays, era5_slot, era5_day, ifs_slot, ifs_day, DEV_START, DEV_END,
                                         [extra[r]["actual_day"] for r in rungs],
                                         [extra[r]["forecast_day"] for r in rungs])
        joined = rows.join(out.rename("f"), on=["date", "slot"])["f"]
        return to_frame(joined), int((ranks["rank"] < ranks["columns"]).sum())

    # Baselines must reproduce the frozen columns before anything is scored
    frame["W"], frame["W_era5"] = fit_w([])
    frame["GAM"], base_deficient = fit_gam([])
    for mine, frozen in (("W", "f4a_l1_no364"), ("GAM", "f7")):
        diff = np.nanmax(np.abs(frame[mine] - frame[frozen]))
        print(f"baseline {mine} vs frozen {frozen}: largest difference {diff:.2e}, "
              f"missing {int(frame[mine].isna().sum())}")
        if not diff < TOLERANCE or frame[mine].isna().any():
            raise SystemExit(f"{mine} does not reproduce {frozen}; stopping before any rung is scored")
    print(f"GAM baseline rank-deficient fits: {base_deficient}")

    kept = {"W": [], "GAM": []}
    print(f"\n{'rung':5s} {'model':4s} {'NMAE':>8s} {'base':>8s} {'DM':>6s} {'p':>8s}  kept")
    for rung, spec in extra.items():
        v = spec["variable"]
        frame[f"W_{rung}"], frame[f"W_{rung}_era5"] = fit_w([v, f"{v}_day_mean"])
        frame[f"GAM_{rung}"], deficient = fit_gam([rung])
        for model in ("W", "GAM"):
            col = f"{model}_{rung}"
            if frame[col].isna().any():
                raise SystemExit(f"{col}: {int(frame[col].isna().sum())} scored half-hours without a forecast")
            dm, p = diebold_mariano(frame, model, col)
            keep = nmae(frame, col) < nmae(frame, model) and p < 0.05
            if keep:
                kept[model].append(rung)
            note = (f"  (rank-deficient fits {deficient})" if model == "GAM" else
                    f"  (information: fed ERA5 {nmae(frame, col + '_era5'):.3%} against W fed ERA5 {nmae(frame, 'W_era5'):.3%})")
            print(f"{rung:5s} {model:4s} {nmae(frame, col):8.3%} {nmae(frame, model):8.3%} {dm:6.2f} {p:8.2g}  "
                  f"{'yes' if keep else 'no'}  {v}{note}")
            if keep:
                print(margin_table(frame, col, model))

    print(f"\nkept for W: {kept['W'] or 'none'}; kept for the GAM: {kept['GAM'] or 'none'}")
    w_added = [x for r in kept["W"] for x in (extra[r]["variable"], f"{extra[r]['variable']}_day_mean")]
    frame["W_13f"], frame["W_13f_era5"] = fit_w(w_added) if kept["W"] else (frame["W"], frame["W_era5"])
    gam_13f, deficient = fit_gam(kept["GAM"]) if kept["GAM"] else (frame["GAM"].to_numpy(), base_deficient)
    frame["GAM_13f"] = gam_13f
    frame["run9_13g"] = 0.5 * frame["GAM_13f"] + 0.5 * frame["W_13f"]
    print(f"13f W {nmae(frame, 'W_13f'):.3%} (W {nmae(frame, 'W'):.3%}); "
          f"13f GAM {nmae(frame, 'GAM_13f'):.3%} (GAM {nmae(frame, 'GAM'):.3%}, rank-deficient fits {deficient})")
    for a, b in (("W", "W_13f"), ("GAM", "GAM_13f"), ("f9", "run9_13g")):
        if a != b:
            dm, p = diebold_mariano(frame, a, b)
            print(f"  {b} vs {a}: DM {dm:.2f} (p = {p:.2g})")
    print(f"13g run 9 recomputed {nmae(frame, 'run9_13g'):.3%} against run 9 {nmae(frame, 'f9'):.3%}")
    print(margin_table(frame, "run9_13g", "f9"))

    out = frame.drop(columns=["date"]).copy()
    out.index = out.index.tz_convert("UTC")
    out.to_csv(OUT_FILE)
    print(f"saved {OUT_FILE}")
