"""Run 15: two fixed blends with Timestral (README section 14.1, item G; specification written before running).

No model is fitted: saved columns are combined with fixed weights. GAM and W are run 13's 13f versions where run 13
kept an input for that model, otherwise the frozen f7 and f4a_l1_no364; run 9 is 13g if run 13 kept anything,
otherwise the frozen f9.

    uv run python blend.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

from ladder import margin_table
from report import load as load_scored, peak_error
from train import diebold_mariano

SCORED_FILE = Path("data/runs/dev_runs_frozen.csv")
RUN12_FILE = Path("data/runs/dev_run12_timestral.csv")
RUN13_FILE = Path("data/runs/dev_run13_ladder.csv")
OUT_FILE = Path("data/runs/dev_run15_blends.csv")


def column(path: Path, name: str, index: pd.DatetimeIndex) -> np.ndarray:
    other = load_scored(path)
    return other[name].reindex(index).to_numpy()


def kept(frame: pd.DataFrame, new: str, old: str) -> bool:
    """Run 13 kept an input for a model exactly when its 13f column differs from its baseline"""
    return not np.array_equal(frame[new].to_numpy(), frame[old].to_numpy())


if __name__ == "__main__":
    frame = load_scored(SCORED_FILE)
    frame["f12"] = column(RUN12_FILE, "f12", frame.index)
    for name in ("W", "GAM", "W_13f", "GAM_13f", "run9_13g"):
        frame[name] = column(RUN13_FILE, name, frame.index)
    w_kept, gam_kept = kept(frame, "W_13f", "W"), kept(frame, "GAM_13f", "GAM")
    w = "W_13f" if w_kept else "f4a_l1_no364"
    gam = "GAM_13f" if gam_kept else "f7"
    run9 = "run9_13g" if (w_kept or gam_kept) else "f9"
    print(f"run 13 kept an input for W: {w_kept}, for the GAM: {gam_kept}; using {gam}, {w} and {run9}")

    frame["f15a"] = (frame[gam] + frame[w] + frame["f12"]) / 3
    frame["f15b"] = 0.5 * frame[run9] + 0.5 * frame["f12"]
    cols = ["f15a", "f15b", "f12", "f9"] + (["run9_13g"] if run9 != "f9" else [])
    mean_mw = frame["mw"].mean()
    print(f"\n{'model':10s} {'MAE':>7s} {'NMAE':>8s} {'peak MAE':>9s}")
    for c in cols:
        if frame[c].isna().any():
            raise SystemExit(f"{c}: {int(frame[c].isna().sum())} scored half-hours without a forecast")
        mae = (frame[c] - frame["mw"]).abs().mean()
        peak, n_days = peak_error(frame, c)
        print(f"{c:10s} {mae:7.3f} {mae / mean_mw:8.3%} {peak:9.3f}")
    print(f"(peak MAE on {n_days} complete days)\n\nCorrected DM (positive = the second model better), margins by month and band")
    for blend in ("f15a", "f15b"):
        for base in [c for c in cols if c not in ("f15a", "f15b")]:
            dm, p = diebold_mariano(frame, base, blend)
            print(f"  {blend} vs {base}: DM {dm:.2f} (p = {p:.2g})")
            print(margin_table(frame, blend, base))

    out = frame.drop(columns=["date"]).copy()
    out.index = out.index.tz_convert("UTC")
    out.to_csv(OUT_FILE)
    print(f"saved {OUT_FILE}")
