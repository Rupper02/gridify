"""The freeze-specification analysis (README section 12) of one output file of `train.py --frozen`.

    uv run python report.py data/runs/dev_runs_frozen.csv      (development, shown before the test)
    uv run python report.py data/runs/test_runs_frozen.csv     (the final test, same command)

Comparator: the lowest NMAE among the no-weather models. Reports every model's NMAE, MAE and peak MAE; run 9's margin
over the comparator with a moving-block bootstrap interval over days; the margin by month; January-February separately;
the peak-error margin; H1-H4 with the corrected DM test. Nothing here is chosen after seeing the file.
"""
import sys

import numpy as np
import pandas as pd

from train import FROZEN, MODELS, WORKING, WORKING_NW, diebold_mariano

NO_WEATHER = ["f0a", "f0b", "f1a", WORKING_NW, "f9_nw"]
CANDIDATE = "f9"
BLOCK_DAYS, RESAMPLES, SEED = 7, 4000, 0
PASS, STRONG = 0.10, 0.20


def load(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0)
    local = pd.to_datetime(frame.index, utc=True).tz_convert("Europe/London")
    frame.index = local
    frame["date"] = pd.DatetimeIndex(local.date)
    return frame


def day_lengths(dates: pd.Index) -> pd.Series:
    """Half-hours in each local day: 48, or 46 and 50 on the clock-change days"""
    return pd.Series({d: len(pd.date_range(pd.Timestamp(d).tz_localize("Europe/London"),
                                            (pd.Timestamp(d) + pd.Timedelta(days=1)).tz_localize("Europe/London"),
                                            freq="30min", inclusive="left")) for d in dates})


def peak_error(frame: pd.DataFrame, col: str) -> float:
    """Mean absolute error at each complete day's highest metered half-hour"""
    per_day = frame.groupby("date").size()
    complete = per_day.index[per_day == day_lengths(per_day.index).reindex(per_day.index)]
    days = frame[frame["date"].isin(complete)]
    peaks = days.loc[days.groupby("date")["mw"].idxmax()]
    return float((peaks[col] - peaks["mw"]).abs().mean()), len(complete)


def margin(frame: pd.DataFrame, comparator: str) -> float:
    return 1 - (frame[CANDIDATE] - frame["mw"]).abs().sum() / (frame[comparator] - frame["mw"]).abs().sum()


def block_bootstrap(frame: pd.DataFrame, comparator: str) -> np.ndarray:
    """Run 9's margin over resampled days: blocks of 7 consecutive scored days, drawn with replacement"""
    err = frame.assign(c=(frame[CANDIDATE] - frame["mw"]).abs(), b=(frame[comparator] - frame["mw"]).abs())
    daily = err.groupby("date")[["c", "b"]].sum().to_numpy()
    n = len(daily)
    rng = np.random.default_rng(SEED)
    starts = np.arange(n - BLOCK_DAYS + 1)
    out = np.empty(RESAMPLES)
    for i in range(RESAMPLES):
        picks = np.concatenate([np.arange(s, s + BLOCK_DAYS) for s in rng.choice(starts, n // BLOCK_DAYS + 1)])[:n]
        sample = daily[picks].sum(axis=0)
        out[i] = 1 - sample[0] / sample[1]
    return out


def dm_line(frame: pd.DataFrame, a: str, b: str) -> str:
    dm, p = diebold_mariano(frame, a, b)
    return f"{MODELS[b]} vs {MODELS[a]}: DM {dm:.2f} (p = {p:.2g})"


if __name__ == "__main__":
    frame = load(sys.argv[1])
    models = [c for c in FROZEN if c in frame.columns]
    mean_mw = frame["mw"].mean()
    print(f"{sys.argv[1]}: {len(frame)} half-hours on {frame['date'].nunique()} days, "
          f"{frame.index.min():%Y-%m-%d} to {frame.index.max():%Y-%m-%d}, mean {mean_mw:.2f} MW")
    print(f"\n{'model':28s} {'MAE':>8s} {'NMAE':>8s} {'peak MAE':>9s}")
    for col in models:
        mae = (frame[col] - frame["mw"]).abs().mean()
        peak, n_peak = peak_error(frame, col)
        print(f"{MODELS[col]:28s} {mae:8.3f} {mae / mean_mw:8.3%} {peak:9.3f}")
    print(f"(peak MAE on {n_peak} complete days, at each day's highest metered half-hour)")

    nmae = {c: (frame[c] - frame["mw"]).abs().mean() / mean_mw for c in NO_WEATHER}
    comparator = min(nmae, key=nmae.get)
    m = margin(frame, comparator)
    dm, p = diebold_mariano(frame, comparator, CANDIDATE)
    boot = block_bootstrap(frame, comparator)
    peak_9, _ = peak_error(frame, CANDIDATE)
    peak_c, _ = peak_error(frame, comparator)
    peak_m = 1 - peak_9 / peak_c
    level = lambda x: "strong" if x >= STRONG else "pass" if x >= PASS else "miss"
    verdict = level(m) if p < 0.05 and m > 0 else "miss (DM not significant at 5%)" if m > 0 else "miss"
    print(f"\nSUCCESS CRITERION: comparator = {MODELS[comparator]} (lowest no-weather NMAE, {nmae[comparator]:.3%})")
    print(f"  run 9 margin {m:.2%}; DM {dm:.2f} (p = {p:.2g}) -> {verdict}")
    print(f"  {BLOCK_DAYS}-day moving-block bootstrap ({RESAMPLES} resamples, seed {SEED}): median {np.median(boot):.1%}, "
          f"95% interval {np.quantile(boot, 0.025):.1%} to {np.quantile(boot, 0.975):.1%}; "
          f"share >= 20%: {(boot >= STRONG).mean():.0%}, share >= 10%: {(boot >= PASS).mean():.0%}")
    print(f"  peak-error margin {peak_m:.2%} -> {level(peak_m)} (second check)")

    print("\nMARGIN BY MONTH")
    for month, part in frame.groupby(frame["date"].dt.to_period("M")):
        print(f"  {month}: {margin(part, comparator):6.1%}  ({part['date'].nunique()} days)")
    winter = frame[frame["date"].dt.month.isin([1, 2])]
    print("  January-February: " + (f"{margin(winter, comparator):.1%} ({winter['date'].nunique()} days)"
                                    if len(winter) else "none in this file"))

    print("\nHYPOTHESES (corrected DM; positive = the second model better)")
    print("  H1 weather helps, same model:")
    for a, b in ((WORKING_NW, WORKING), ("f9_nw", "f9"), ("f11_nw", "f11")):
        print("    " + dm_line(frame, a, b))
    if "fW_actual" in frame.columns:
        print("  H2 forecast against actual weather, same trained model:")
        print("    " + dm_line(frame, "fW_actual", WORKING))
    print("  H3 our models against the simple and decomposition baselines:")
    for b in ("f9", WORKING):
        for a in ("f0a", "f0b", "f1a"):
            print("    " + dm_line(frame, a, b))
    better_chronos = min(("f11_nw", "f11"), key=lambda c: (frame[c] - frame["mw"]).abs().mean())
    holds = (frame["f9"] - frame["mw"]).abs().mean() <= (frame[better_chronos] - frame["mw"]).abs().mean()
    print(f"  H4 run 9 against the better Chronos-2 ({MODELS[better_chronos]}): "
          f"{'holds' if holds else 'does not hold'}; " + dm_line(frame, better_chronos, "f9"))
