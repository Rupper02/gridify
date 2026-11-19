"""Hourly 2 m temperature at a primary substation from Open-Meteo (README sections 6 and 13): ERA5 actuals, and every
00 UTC ECMWF IFS run of D-1 as issued (Single Runs API, archived from 14 March 2024). Resumable: each run is cached.

    uv run python fetch_weather.py [--site bungay]      (default newmarket; sites and coordinates in load.SITES)
"""
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

from load import SITES

WEATHER_DIR = Path("data/raw/weather")
ERA5_START, ERA5_END = "2022-12-01", "2025-12-31"
FIRST_RUN, LAST_RUN = "2024-03-14", "2025-12-30"

# The Open-Meteo hosts time out over IPv6 from here; resolve IPv4 only
_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda host, port, family=0, *args, **kw: _getaddrinfo(host, port, socket.AF_INET, *args, **kw)


def get_json(url: str, params: dict, tries: int = 30) -> dict:
    """GET with a growing pause while the service reports itself overloaded or rate-limited"""
    full = f"{url}?{urllib.parse.urlencode(params)}"
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(full, timeout=120) as response:
                return json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as err:
            wait = min(30 * (attempt + 1), 300)
            print(f"  {err}; retrying in {wait} s")
            time.sleep(wait)
    raise RuntimeError(f"gave up on {full}")


def hourly_frame(payload: dict) -> pd.DataFrame:
    hourly = payload["hourly"]
    return pd.DataFrame({"time_utc": pd.to_datetime(hourly["time"]).tz_localize("UTC"),
                         "temperature_c": hourly["temperature_2m"]})


def era5_file(site: str = "newmarket") -> Path:
    return WEATHER_DIR / f"{site}_era5_hourly.csv"


def runs_dir(site: str = "newmarket") -> Path:
    return WEATHER_DIR / f"{site}_ifs_00z_runs"


ERA5_FILE, RUNS_DIR = era5_file(), runs_dir()


def fetch_era5(site: str) -> None:
    out = era5_file(site)
    if out.exists():
        return
    payload = get_json("https://archive-api.open-meteo.com/v1/archive", {
        "latitude": SITES[site]["lat"], "longitude": SITES[site]["lon"], "start_date": ERA5_START, "end_date": ERA5_END,
        "hourly": "temperature_2m", "models": "era5", "timezone": "GMT",
    })
    hourly_frame(payload).to_csv(out, index=False)
    print(f"ERA5 saved: {out}")


def fetch_runs(site: str) -> None:
    folder = runs_dir(site)
    folder.mkdir(parents=True, exist_ok=True)
    for run_day in pd.date_range(FIRST_RUN, LAST_RUN, freq="D"):
        out = folder / f"{run_day:%Y-%m-%d}.csv"
        if out.exists():
            continue
        try:
            payload = get_json("https://single-runs-api.open-meteo.com/v1/forecast", {
                "latitude": SITES[site]["lat"], "longitude": SITES[site]["lon"], "hourly": "temperature_2m",
                "run": f"{run_day:%Y-%m-%d}T00:00", "models": "ecmwf_ifs", "timezone": "GMT",
            }, tries=10)
        except RuntimeError as err:
            # A run the archive doesn't hold is listed, not filled
            print(f"run {run_day:%Y-%m-%d} missing: {err}")
            continue
        hourly_frame(payload).to_csv(out, index=False)
        print(f"run {run_day:%Y-%m-%d} saved")
        time.sleep(1)


if __name__ == "__main__":
    import sys

    site = sys.argv[sys.argv.index("--site") + 1] if "--site" in sys.argv else "newmarket"
    WEATHER_DIR.mkdir(parents=True, exist_ok=True)
    fetch_era5(site)
    fetch_runs(site)
