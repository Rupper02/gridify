"""Run 12: Timestral, zero-shot, beside Chronos-2 (README section 14 has the specification, written before running).

Mirrors run 11 (chronos_run.py): for each development day D, on the UTC half-hour grid, the context is every half-hour
before 09:00 local on D-1, at most the model's context length; the forecast runs from 09:00 on D-1 to the end of D and
only D's half-hours are kept. Missing readings are passed as NaN, which Timestral masks itself. 12_nw uses demand alone;
12 adds the half-hour temperature as one known-future covariate row (ERA5 over the context, the IFS 00 UTC run of D-1
over the forecast window). Point forecast = the 0.5 quantile. Library defaults, one day per call.

    uv run python timestral_run.py --time 209M     (size choice: five days, timed, not scored or saved)
    uv run python timestral_run.py --run 209M      (the run: forecasts, then the score on the development table)

Weights: Modified MIT licence, attribution notice "2026 - Mistral AI" (kept with any copy of the weights).
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from fetch_weather import era5_file, runs_dir
from load import NEWMARKET_FILE, load_demand
from report import load as load_scored, peak_error
from train import DEV_END, DEV_START, diebold_mariano, era5_temps, half_hours, read_hourly, to_half_hours

# Pinned Hugging Face commits, chosen before the run (README section 14)
REVISIONS = {"209M": "9874d252ab0aae16f7f7c999f98f98d6ad7d8365", "123M": "5a147287addda85f6acd8da3fb8858fe9af7e8f7"}
SCORED_FILE = Path("data/runs/dev_runs_frozen.csv")
OUT_FILE = Path("data/runs/dev_run12_timestral.csv")
TIME_LIMIT_HOURS = 3


def ifs_run(run_day: pd.Timestamp, instants: pd.DatetimeIndex):
    """The IFS 00 UTC run of `run_day` at the given UTC instants, or None if that run is missing"""
    path = runs_dir("newmarket") / f"{run_day:%Y-%m-%d}.csv"
    return to_half_hours(read_hourly(path), instants).to_numpy() if path.exists() else None


def timestral_forecasts(demand: pd.Series, era5: pd.Series, days: pd.DatetimeIndex, size: str) -> dict:
    """{"f12_nw": Series, "f12": Series} indexed by local half-hour, plus "seconds" and "context_length"."""
    import torch
    from timestral import TimestralForecaster

    torch.manual_seed(0)
    forecaster = TimestralForecaster.from_pretrained(f"mistralai/Timestral-{size}", revision=REVISIONS[size])
    context_length = forecaster.max_context
    target = demand.tz_convert("UTC")
    temp = era5.tz_convert("UTC")

    out = {"f12_nw": [], "f12": []}
    began = time.perf_counter()
    for day in days:
        origin = pd.Timestamp(day - pd.Timedelta(days=1)).replace(hour=9).tz_localize("Europe/London").tz_convert("UTC")
        day_end = pd.Timestamp(day + pd.Timedelta(days=1)).tz_localize("Europe/London").tz_convert("UTC")
        horizon = pd.date_range(origin, day_end, freq="30min", inclusive="left")
        context = target[target.index < origin].iloc[-context_length:]
        values = context.to_numpy(dtype=np.float32)
        plain = forecaster.forecast(values, prediction_length=len(horizon))
        out["f12_nw"].append(day_part(plain.median[0, 0].numpy(), horizon, day))
        future = ifs_run(day - pd.Timedelta(days=1), horizon)
        if future is not None:
            known = np.concatenate([temp.reindex(context.index).to_numpy(), future]).astype(np.float32)[None, None]
            with_temp = forecaster.forecast(values, prediction_length=len(horizon), known_covariates=known)
            out["f12"].append(day_part(with_temp.median[0, 0].numpy(), horizon, day))
    seconds = time.perf_counter() - began
    return {**{name: pd.concat(parts).sort_index() for name, parts in out.items()},
            "seconds": seconds, "context_length": context_length, "days": len(days)}


def day_part(median: np.ndarray, horizon: pd.DatetimeIndex, day: pd.Timestamp) -> pd.Series:
    """The median over the horizon, kept only for local day D"""
    series = pd.Series(median, index=horizon.tz_convert("Europe/London"))
    return series[series.index.normalize().tz_localize(None) == day]


def score(frame: pd.DataFrame) -> None:
    names = {"f12_nw": "12 Timestral no weather", "f12": "12 Timestral + fcst temp", "f11_nw": "11 Chronos-2 no weather",
             "f11": "11 Chronos-2 + fcst temp", "f9": "9 avg GAM+W + fcst temp", "f4a_l1_no364": "W + fcst temp",
             "f7": "7 GAM + fcst temp"}
    mean_mw = frame["mw"].mean()
    print(f"\n{'model':28s} {'MAE':>8s} {'NMAE':>8s} {'peak MAE':>9s}")
    for col, name in names.items():
        mae = (frame[col] - frame["mw"]).abs().mean()
        peak, n_peak = peak_error(frame, col)
        print(f"{name:28s} {mae:8.3f} {mae / mean_mw:8.3%} {peak:9.3f}")
    print(f"(peak MAE on {n_peak} complete days)")
    print("\nCorrected DM (positive = the second model better)")
    pairs = [("f12_nw", "f12")] + [(other, mine) for mine in ("f12_nw", "f12")
                                   for other in ("f11_nw", "f11", "f9", "f4a_l1_no364", "f7")]
    for a, b in pairs:
        dm, p = diebold_mariano(frame, a, b)
        print(f"  {names[b]} vs {names[a]}: DM {dm:.2f} (p = {p:.2g})")


if __name__ == "__main__":
    mode, size = sys.argv[1], sys.argv[2]
    demand = load_demand(NEWMARKET_FILE)
    era5 = era5_temps(half_hours(demand), era5_file("newmarket"))
    all_days = pd.date_range(DEV_START, DEV_END, freq="D")
    if mode == "--time":
        # Five days spread over the period (the context grows, so later days cost more); timed only, never scored
        picks = all_days[np.linspace(0, len(all_days) - 1, 5).round().astype(int)]
        result = timestral_forecasts(demand, era5, picks, size)
        estimate = result["seconds"] / result["days"] * len(all_days) / 3600
        print(f"Timestral-{size}: {result['seconds']:.1f} s for {result['days']} days, both versions; "
              f"full run of {len(all_days)} days about {estimate:.2f} h (limit {TIME_LIMIT_HOURS} h)")
    elif mode == "--run":
        result = timestral_forecasts(demand, era5, all_days, size)
        print(f"Timestral-{size} ({REVISIONS[size][:12]}): {result['days']} days, context {result['context_length']}, "
              f"{result['seconds']:.0f} s predicting ({result['seconds'] / result['days']:.1f} s per day, both versions)")
        frame = load_scored(SCORED_FILE)
        for col in ("f12_nw", "f12"):
            frame[col] = result[col].reindex(frame.index).to_numpy()
            missing = int(frame[col].isna().sum())
            # Every model must score on the same half-hours; a gap would silently change the set
            if missing:
                raise SystemExit(f"{col}: {missing} scored half-hours without a forecast; not scoring")
        out = frame[["mw", "f12_nw", "f12"]].copy()
        out.index = out.index.tz_convert("UTC")
        out.to_csv(OUT_FILE)
        print(f"saved {OUT_FILE} ({len(out)} half-hours)")
        score(frame)
