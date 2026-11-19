"""Run 14: holiday flags for the pretrained models (README section 14.1, item E; specification written before running).

Chronos-2 (run 11's setup) and, if included, Timestral (run 12's setup), each with temperature plus two known-future
0/1 rows: bank holiday and the Christmas period (24 December - 2 January), by the local date of each half-hour.

    uv run python holidays_run.py chronos            (Chronos-2 only)
    uv run python holidays_run.py chronos timestral  (both)
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from chronos_run import MODEL_ID, REVISION
from load import NEWMARKET_FILE, load_demand
from report import load as load_scored, peak_error
from timestral_run import REVISIONS, day_part, ifs_run
from train import DEV_END, DEV_START, HOLIDAYS_FILE, diebold_mariano, era5_temps, half_hours, load_holidays

SCORED_FILE = Path("data/runs/dev_runs_frozen.csv")
RUN12_FILE = Path("data/runs/dev_run12_timestral.csv")
OUT_FILE = Path("data/runs/dev_run14_holidays.csv")
TIMESTRAL_SIZE = "123M"


def flags(instants: pd.DatetimeIndex, holidays: set) -> tuple[np.ndarray, np.ndarray]:
    """Bank holiday and Christmas period (as train.calendar_features), by the local date of each UTC instant"""
    local = pd.DatetimeIndex(instants.tz_convert("Europe/London").date)
    bank = local.isin(holidays).astype(np.float32)
    christmas = (((local.month == 12) & (local.day >= 24)) | ((local.month == 1) & (local.day <= 2))).astype(np.float32)
    return bank, christmas


def jobs(demand: pd.Series, context_length: int) -> list:
    target = demand.tz_convert("UTC")
    out = []
    for day in pd.date_range(DEV_START, DEV_END, freq="D"):
        origin = pd.Timestamp(day - pd.Timedelta(days=1)).replace(hour=9).tz_localize("Europe/London").tz_convert("UTC")
        day_end = pd.Timestamp(day + pd.Timedelta(days=1)).tz_localize("Europe/London").tz_convert("UTC")
        horizon = pd.date_range(origin, day_end, freq="30min", inclusive="left")
        future_temp = ifs_run(day - pd.Timedelta(days=1), horizon)
        if future_temp is not None:
            out.append({"day": day, "horizon": horizon, "context": target[target.index < origin].iloc[-context_length:],
                        "future_temp": future_temp.astype(np.float32)})
    return out


def chronos_with_flags(demand: pd.Series, temp: pd.Series, holidays: set) -> pd.Series:
    import torch
    from chronos import Chronos2Pipeline

    torch.manual_seed(0)
    pipeline = Chronos2Pipeline.from_pretrained(MODEL_ID, revision=REVISION, device_map="cpu")
    parts = []
    by_length = {}
    for job in jobs(demand, pipeline.model_context_length):
        by_length.setdefault(len(job["horizon"]), []).append(job)
    for length, group in by_length.items():
        inputs = []
        for job in group:
            past_bank, past_xmas = flags(job["context"].index, holidays)
            fut_bank, fut_xmas = flags(job["horizon"], holidays)
            inputs.append({"target": job["context"].to_numpy(dtype=np.float32),
                           "past_covariates": {"temp": temp.reindex(job["context"].index).to_numpy(dtype=np.float32),
                                               "bank_holiday": past_bank, "christmas": past_xmas},
                           "future_covariates": {"temp": job["future_temp"], "bank_holiday": fut_bank,
                                                 "christmas": fut_xmas}})
        quantiles, _ = pipeline.predict_quantiles(inputs, prediction_length=length, quantile_levels=[0.5],
                                                  cross_learning=False)
        for job, q in zip(group, quantiles):
            parts.append(day_part(q[0, :, 0].numpy(), job["horizon"], job["day"]))
    return pd.concat(parts).sort_index()


def timestral_with_flags(demand: pd.Series, temp: pd.Series, holidays: set) -> pd.Series:
    import torch
    from timestral import TimestralForecaster

    torch.manual_seed(0)
    forecaster = TimestralForecaster.from_pretrained(f"mistralai/Timestral-{TIMESTRAL_SIZE}",
                                                     revision=REVISIONS[TIMESTRAL_SIZE])
    parts = []
    for job in jobs(demand, forecaster.max_context):
        instants = job["context"].index.append(job["horizon"])
        bank, christmas = flags(instants, holidays)
        temp_row = np.concatenate([temp.reindex(job["context"].index).to_numpy(), job["future_temp"]])
        known = np.stack([temp_row, bank, christmas]).astype(np.float32)[None]
        result = forecaster.forecast(job["context"].to_numpy(dtype=np.float32), prediction_length=len(job["horizon"]),
                                     known_covariates=known)
        parts.append(day_part(result.median[0, 0].numpy(), job["horizon"], job["day"]))
    return pd.concat(parts).sort_index()


if __name__ == "__main__":
    which = sys.argv[1:]
    demand = load_demand(NEWMARKET_FILE)
    temp = era5_temps(half_hours(demand)).tz_convert("UTC")
    holidays = load_holidays(HOLIDAYS_FILE)
    frame = load_scored(SCORED_FILE)
    pairs = []
    if "chronos" in which:
        began = time.perf_counter()
        frame["f14_chronos"] = chronos_with_flags(demand, temp, holidays).reindex(frame.index).to_numpy()
        print(f"Chronos-2 + flags: {time.perf_counter() - began:.0f} s")
        pairs.append(("f11", "f14_chronos"))
    if "timestral" in which:
        run12 = pd.read_csv(RUN12_FILE, index_col=0)
        run12.index = pd.to_datetime(run12.index, utc=True).tz_convert("Europe/London")
        frame["f12"] = run12["f12"].reindex(frame.index).to_numpy()
        began = time.perf_counter()
        frame["f14_timestral"] = timestral_with_flags(demand, temp, holidays).reindex(frame.index).to_numpy()
        print(f"Timestral-{TIMESTRAL_SIZE} + flags: {time.perf_counter() - began:.0f} s")
        pairs.append(("f12", "f14_timestral"))
    mean_mw = frame["mw"].mean()
    holiday_days = frame["date"].isin(holidays)
    for base, new in pairs:
        if frame[new].isna().any():
            raise SystemExit(f"{new}: {int(frame[new].isna().sum())} scored half-hours without a forecast")
        dm, p = diebold_mariano(frame, base, new)
        n_new, n_base = ((frame[c] - frame["mw"]).abs().mean() / mean_mw for c in (new, base))
        keep = n_new < n_base and p < 0.05
        on_hol = frame[holiday_days]
        # Normalised by the mean demand on those days, so it is an NMAE of that subset
        hol = {c: (on_hol[c] - on_hol["mw"]).abs().mean() / on_hol["mw"].mean() for c in (base, new)}
        print(f"{new}: NMAE {n_new:.3%} against {base} {n_base:.3%}; peak MAE {peak_error(frame, new)[0]:.3f} against "
              f"{peak_error(frame, base)[0]:.3f}; DM {dm:.2f} (p = {p:.2g}) -> {'kept' if keep else 'not kept'}; "
              f"on the {on_hol['date'].nunique()} bank-holiday days {hol[new]:.2%} against {hol[base]:.2%}")
    out = frame.drop(columns=["date"]).copy()
    out.index = out.index.tz_convert("UTC")
    out.to_csv(OUT_FILE)
    print(f"saved {OUT_FILE}")
