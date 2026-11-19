"""Item C (README section 14.1): half-hourly demand up to 31 December 2024 and weather for the 15 development sites in
data/raw/ukpn/sites_dev.csv. Never touches the held-out sites. Resumable: existing files are skipped.

    uv run python fetch_dev_sites.py demand      (UKPN exports, one file per site, the format load.py reads)
    uv run python fetch_dev_sites.py weather     (ERA5 temperature + extras, then IFS runs site by site, seeded order)
"""
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

from fetch_weather_extra import VARIABLES, fetch_era5, fetch_runs
from fetch_weather import WEATHER_DIR
from screen_sites import BASE, HALF_HOURLY, api_key

DEV = pd.read_csv("data/raw/ukpn/sites_dev.csv")
DEMAND_END = "2025-01-01"
ALL = ["temperature_2m"] + VARIABLES


def fetch_demand(key: str, tx_ids: list) -> None:
    out = Path("data/raw/ukpn") / f"{key}_half_hourly.csv"
    if out.exists():
        return
    where = "tx_id in (" + ",".join(f'"{t}"' for t in tx_ids) + f") and timestamp < date'{DEMAND_END}'"
    url = (BASE + f"{HALF_HOURLY}/exports/csv?" + urllib.parse.urlencode(
        {"select": "timestamp, tx_id, active_power_mw, current_amps", "where": where, "delimiter": ",",
         "order_by": "timestamp, tx_id"}))
    request = urllib.request.Request(url, headers={"Authorization": f"Apikey {api_key()}"})
    with urllib.request.urlopen(request, timeout=600) as response:
        out.write_bytes(response.read())
    print(f"{key}: saved {out}")


if __name__ == "__main__":
    if sys.argv[1] == "demand":
        for _, row in DEV.iterrows():
            fetch_demand(row["key"], row["tx_ids"].split())
    elif sys.argv[1] == "weather":
        for key in DEV["key"]:
            fetch_era5(key, ALL, WEATHER_DIR / f"{key}_era5_all_hourly.csv")
        # IFS runs for the development period, site by site in the seeded order, as far as the rate limit allows
        for key in DEV["key"]:
            fetch_runs(key, "2024-03-14", "2024-12-31", ALL, WEATHER_DIR / f"{key}_ifs_00z_all_runs")
            print(f"{key}: IFS runs done")
