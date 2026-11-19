from pathlib import Path
import pandas as pd

# Point to the data dir
DATA_DIR = Path("data/raw/ukpn")
# Point to the file
NEWMARKET_FILE = DATA_DIR / "newmarket_primary_half_hourly.csv"
# The sites the experiment runs on: demand file, location (UKPN Grid and Primary Sites) and site id (README 6, 13)
SITES = {
    "newmarket": {"file": NEWMARKET_FILE, "lat": 52.242171, "lon": 0.39539, "site_id": "EPN-S0000000H1028"},
    "bungay": {"file": DATA_DIR / "bungay_primary_half_hourly.csv", "lat": 52.453032, "lon": 1.437208,
               "site_id": "EPN-S0000000H5004"},
}


def load_demand(path: Path) -> pd.Series:
    """Demand in MW per half-hour on a complete grid, in UK local time; NaN unless both transformers reported."""
    # Long format: one row per transformer per half-hour, timestamps typed as UTC
    raw = pd.read_csv(path, parse_dates=["timestamp"])
    # One row per timestamp, one MW column per transformer; a missing row or an empty MW cell becomes NaN
    wide = raw.pivot(index="timestamp", columns="tx_id", values="active_power_mw")
    # T1 + T2; min_count=2 keeps it NaN unless both reported (else a missing one counts as 0)
    total = wide.sum(axis=1, min_count=2)
    # Every UTC half-hour from first to last, so half-hours with no row at all show up as NaN
    grid = pd.date_range(start=total.index.min(), end=total.index.max(), freq="30min")
    # UTC has no clock changes, so converting the full grid only relabels the same instants:
    # the spring day gets 46 half-hours, the autumn day 50 (01:00 and 01:30 twice, +01:00 then +00:00)
    return total.reindex(grid).tz_convert("Europe/London")


def list_gaps(series: pd.Series) -> pd.DataFrame:
    """One row per run of missing half-hours: its first, its last, and its length in half-hours"""
    missing = series.isna()
    # A gap starts where a half-hour is missing and the one before it is not;
    # shift(1) moves every value down one row, so each row sees the previous row's value
    starts = missing & ~missing.shift(1, fill_value=False)
    # cumsum numbers the gaps 1, 2, 3...; every half-hour inside a gap carries that gap's number
    gap_id = starts.cumsum()[missing]
    # Group the missing timestamps by gap number and take each gap's first, last and size
    by_gap = series.index[missing].to_series().groupby(gap_id.to_numpy())
    return pd.DataFrame({
        "start": by_gap.min(),
        "end": by_gap.max(),
        "half_hours": by_gap.size(),
    }).reset_index(drop=True)


if __name__ == "__main__":
    demand = load_demand(NEWMARKET_FILE)
    period = demand.loc["2023":"2025"]
    print("half-hours, complete, share:", len(period), period.count(), round(period.notna().mean(), 3))
    print(period.describe())

    gaps = list_gaps(period)
    print("gaps:", len(gaps))
    print(gaps.sort_values("half_hours", ascending=False).head())

    # Half-hours per local day: 48, or 46 and 50 on the clock-change days
    days = period.groupby(period.index.date).size()
    print(days.value_counts())
    print(days[days != 48])
