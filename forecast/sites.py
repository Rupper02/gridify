"""Development sites of README section 14.1: demand with every published transformer required (load.load_demand is
frozen and requires exactly two)."""
from pathlib import Path

import pandas as pd

DEV_SITES = Path("data/raw/ukpn/sites_dev.csv")


def load_site_demand(path: Path, transformers: int) -> pd.Series:
    """MW per half-hour on a complete UTC grid, in UK local time; NaN unless every transformer reported"""
    raw = pd.read_csv(path, parse_dates=["timestamp"])
    wide = raw.pivot(index="timestamp", columns="tx_id", values="active_power_mw")
    total = wide.sum(axis=1, min_count=transformers)
    grid = pd.date_range(start=total.index.min(), end=total.index.max(), freq="30min")
    return total.reindex(grid).tz_convert("Europe/London")


def dev_sites() -> pd.DataFrame:
    frame = pd.read_csv(DEV_SITES)
    frame["transformers"] = frame["tx_ids"].str.split().str.len()
    frame["file"] = [Path("data/raw/ukpn") / f"{k}_half_hourly.csv" for k in frame["key"]]
    return frame
