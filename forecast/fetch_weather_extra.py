"""Run 13's extra weather (README section 14): solar radiation, cloud cover, wind, humidity, dew point, precipitation,
from Open-Meteo, at a site in load.SITES or a development site in data/raw/ukpn/sites_dev.csv. ERA5 hourly actuals
and every 00 UTC ECMWF IFS run as issued, into new files (the temperature files and their fingerprints are untouched).

    uv run python fetch_weather_extra.py newmarket [--era5-only] [--runs-from 2024-03-14] [--runs-to 2024-12-31]

Open-Meteo free tier: under 600 calls a minute, 5,000 an hour, 10,000 a day; one run per second stays well inside.
Units: shortwave_radiation W/m2, mean of the preceding hour; precipitation mm, sum of the preceding hour; cloud cover
%, relative humidity %, dew point degC, wind speed at 10 m in m/s: instantaneous at the hour.
"""
import sys
import time
from pathlib import Path

import pandas as pd

from fetch_weather import ERA5_END, ERA5_START, FIRST_RUN, LAST_RUN, WEATHER_DIR, get_json
from load import SITES

VARIABLES = ["shortwave_radiation", "cloud_cover", "wind_speed_10m", "relative_humidity_2m", "dew_point_2m",
             "precipitation"]
DEV_SITES_FILE = Path("data/raw/ukpn/sites_dev.csv")


def site_location(site: str) -> tuple[float, float]:
    if site in SITES:
        return SITES[site]["lat"], SITES[site]["lon"]
    row = pd.read_csv(DEV_SITES_FILE).set_index("key").loc[site]
    return float(row["lat"]), float(row["lon"])


def era5_extra_file(site: str) -> Path:
    return WEATHER_DIR / f"{site}_era5_extra_hourly.csv"


def runs_extra_dir(site: str) -> Path:
    return WEATHER_DIR / f"{site}_ifs_00z_extra_runs"


def frame(payload: dict, variables: list) -> pd.DataFrame:
    hourly = payload["hourly"]
    out = pd.DataFrame({"time_utc": pd.to_datetime(hourly["time"]).tz_localize("UTC")})
    for v in variables:
        out[v] = hourly[v]
    return out


def fetch_era5(site: str, variables: list = VARIABLES, out: Path | None = None) -> None:
    out = out or era5_extra_file(site)
    if out.exists():
        return
    lat, lon = site_location(site)
    payload = get_json("https://archive-api.open-meteo.com/v1/archive", {
        "latitude": lat, "longitude": lon, "start_date": ERA5_START, "end_date": ERA5_END,
        "hourly": ",".join(variables), "models": "era5", "timezone": "GMT", "wind_speed_unit": "ms",
    })
    frame(payload, variables).to_csv(out, index=False)
    print(f"ERA5 saved: {out}")


def fetch_runs(site: str, first: str = FIRST_RUN, last: str = LAST_RUN, variables: list = VARIABLES,
               folder: Path | None = None) -> None:
    folder = folder or runs_extra_dir(site)
    folder.mkdir(parents=True, exist_ok=True)
    lat, lon = site_location(site)
    for run_day in pd.date_range(first, last, freq="D"):
        out = folder / f"{run_day:%Y-%m-%d}.csv"
        if out.exists():
            continue
        try:
            payload = get_json("https://single-runs-api.open-meteo.com/v1/forecast", {
                "latitude": lat, "longitude": lon, "hourly": ",".join(variables), "run": f"{run_day:%Y-%m-%d}T00:00",
                "models": "ecmwf_ifs", "timezone": "GMT", "wind_speed_unit": "ms",
            }, tries=10)
        except RuntimeError as err:
            # A run the archive doesn't hold is listed, not filled
            print(f"run {run_day:%Y-%m-%d} missing: {err}")
            continue
        frame(payload, variables).to_csv(out, index=False)
        time.sleep(1)


if __name__ == "__main__":
    site = sys.argv[1]
    arg = lambda name, default: sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default
    fetch_era5(site)
    if "--era5-only" not in sys.argv:
        fetch_runs(site, arg("--runs-from", FIRST_RUN), arg("--runs-to", LAST_RUN))
