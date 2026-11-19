"""Run 11: Chronos-2, zero-shot (README section 8 has the specification, written before running).

For each development day D, on the UTC half-hour grid: the context is every half-hour before 09:00 local on D-1 (ending
with the reading labelled 08:30), at most the model's context length; the forecast runs from 09:00 on D-1 to the end of
D; only D's half-hours are kept. Missing readings are passed as NaN, which Chronos-2 masks itself. 11_nw uses demand
alone; 11 adds the half-hour temperature as a known-future covariate (ERA5 over the context, the IFS 00 UTC run of D-1
over the forecast window). Point forecast = the 0.5 quantile.
"""
import time
from pathlib import Path

import numpy as np
import pandas as pd

MODEL_ID = "amazon/chronos-2"
# The frozen model: loads exactly this Hugging Face commit, whatever the repository holds later
REVISION = "29ec3766d36d6f73f0696f85560a422f50e8498c"


def chronos_forecasts(demand: pd.Series, era5: pd.Series, ifs_run: callable, start: str, end: str) -> dict:
    """Forecasts indexed by local half-hour, {"f11_nw": Series, "f11": Series}, plus "seconds" and "context_length".

    `demand` and `era5` are half-hourly on the local (tz-aware) grid; `ifs_run(run_day, instants)` returns the IFS 00 UTC
    run of `run_day` interpolated to the given UTC instants, or None if that run is missing.
    """
    import torch
    from chronos import Chronos2Pipeline

    torch.manual_seed(0)
    pipeline = Chronos2Pipeline.from_pretrained(MODEL_ID, revision=REVISION, device_map="cpu")
    context_length = pipeline.model_context_length
    target = demand.tz_convert("UTC")
    temp = era5.tz_convert("UTC")

    jobs = []
    for day in pd.date_range(start, end, freq="D"):
        origin = pd.Timestamp(day - pd.Timedelta(days=1)).replace(hour=9).tz_localize("Europe/London").tz_convert("UTC")
        day_end = pd.Timestamp(day + pd.Timedelta(days=1)).tz_localize("Europe/London").tz_convert("UTC")
        horizon = pd.date_range(origin, day_end, freq="30min", inclusive="left")
        context = target[target.index < origin].iloc[-context_length:]
        jobs.append({"day": day, "horizon": horizon, "context": context,
                     "future_temp": ifs_run(day - pd.Timedelta(days=1), horizon)})

    began = time.perf_counter()
    out = {"f11_nw": [], "f11": []}
    by_length = {}
    for job in jobs:
        by_length.setdefault(len(job["horizon"]), []).append(job)
    for length, group in by_length.items():
        plain = [job["context"].to_numpy(dtype=np.float32) for job in group]
        quantiles, _ = pipeline.predict_quantiles(plain, prediction_length=length, quantile_levels=[0.5],
                                                  cross_learning=False)
        for job, q in zip(group, quantiles):
            out["f11_nw"].append(day_part(job, q))
        with_temp = [job for job in group if job["future_temp"] is not None]
        inputs = [{"target": job["context"].to_numpy(dtype=np.float32),
                   "past_covariates": {"temp": temp.reindex(job["context"].index).to_numpy(dtype=np.float32)},
                   "future_covariates": {"temp": job["future_temp"].astype(np.float32)}} for job in with_temp]
        if inputs:
            quantiles, _ = pipeline.predict_quantiles(inputs, prediction_length=length, quantile_levels=[0.5],
                                                      cross_learning=False)
            for job, q in zip(with_temp, quantiles):
                out["f11"].append(day_part(job, q))
    seconds = time.perf_counter() - began
    return {**{name: pd.concat(parts).sort_index() for name, parts in out.items()},
            "seconds": seconds, "context_length": context_length, "days": len(jobs)}


def day_part(job: dict, quantiles) -> pd.Series:
    """The median over the horizon, kept only for local day D"""
    median = pd.Series(quantiles[0, :, 0].numpy(), index=job["horizon"].tz_convert("Europe/London"))
    return median[median.index.normalize().tz_localize(None) == job["day"]]
