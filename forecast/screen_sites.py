"""Item C (README section 14.1): screen Eastern primaries and split them into development and held-out sites with a
fixed seed, before any site's demand is downloaded. Only aggregate queries and site metadata; the ECR query reads
non-personal columns only.

    uv run python screen_sites.py      -> data/raw/ukpn/sites_screen.csv, sites_dev.csv, sites_heldout.csv
"""
import json
import re
import socket
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda host, port, family=0, *args, **kw: _getaddrinfo(host, port, socket.AF_INET, *args, **kw)

BASE = "https://ukpowernetworks.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
HALF_HOURLY = "ukpn-primary-transformer-power-flow-historic-half-hourly-epn"
MONTHLY = "ukpn-primary-transformer-power-flow-historic-monthly"
OUT_DIR = Path("data/raw/ukpn")
FULL = 52608          # half-hours in 2023-2025
# Guide's overnight decision (README 14.1): 95% completeness, 15 development sites, the rest held out
COMPLETE, SEED, N_DEV = 0.95, 20261112, 15
# A real reverse flow, not metering noise around zero while a transformer is out of service
REVERSE_MW = -0.5
ALREADY_DEV = {"Newmarket Primary 11kV", "Bungay Primary 11kV"}


def api_key() -> str:
    env = Path("../apps/pipeline/.env").read_text().splitlines()
    return next(l.split("=", 1)[1].strip().strip('"') for l in env if l.startswith("UKPN_API_KEY="))


def query(path: str, **params) -> list:
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Authorization": f"Apikey {api_key()}"})
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = json.load(response)
    return payload["results"] if isinstance(payload, dict) else payload


def export(dataset: str, **params) -> pd.DataFrame:
    return pd.DataFrame(query(f"{dataset}/exports/json", **params))


if __name__ == "__main__":
    counts = pd.DataFrame(query(f"{HALF_HOURLY}/records", select="tx_id, count(active_power_mw) as mw",
                                where="timestamp >= date'2023-01-01' and timestamp < date'2026-01-01'",
                                group_by="tx_id", limit=20000))
    monthly = export(MONTHLY, select="tx_id, ltds_name, redacted, timestamp, active_power_month_min_mw",
                     where="licence_area='EPN' and timestamp >= date'2023-01-01' and timestamp < date'2026-01-01'")
    sites_meta = export("grid-and-primary-sites", select="sitename, sitefunctionallocation, powertransformercount, "
                        "spatial_coordinates", where="licencearea='Eastern Power Networks (EPN)'")
    ecr = export("ukpn-embedded-capacity-register", select="primary, connection_status",
                 where="licence_area='Eastern Power Networks (EPN)'")

    names = monthly.groupby("tx_id")["ltds_name"].first()
    counts["site"] = counts["tx_id"].map(names)
    counts["share"] = counts["mw"] / FULL
    tx = monthly.groupby("tx_id").agg(site=("ltds_name", "first"), redacted=("redacted", lambda r: (r == "True").any()))
    min_mw = monthly[monthly["timestamp"] < "2025-01-01"].groupby("tx_id")["active_power_month_min_mw"].min()
    tx["negative"] = min_mw.reindex(tx.index) < REVERSE_MW
    connected = ecr[ecr["connection_status"].str.contains("Connected", case=False, na=False)
                    & ~ecr["connection_status"].str.contains("not", case=False, na=False)]
    with_generation = set(connected["primary"])

    def find_meta(site: str):
        # "Bungay Primary 11kV" is "BUNGAY PRIMARY 33/11kV": the stem, then any upper voltage, then the site's own
        found = re.search(r"(\d+(\.\d+)?)kV$", site, re.IGNORECASE)
        if found is None:
            return None
        voltage = found.group(1)
        stem = re.sub(r"\s*\d+(\.\d+)?kV$", "", site, flags=re.IGNORECASE).upper()
        pattern = re.escape(stem) + r" \d+(\.\d+)?/" + re.escape(voltage) + r"KV$"
        hits = sites_meta[sites_meta["sitename"].str.upper().str.match(pattern)]
        return hits.iloc[0] if len(hits) == 1 else None

    rows = []
    for site, group in counts.dropna(subset=["site"]).groupby("site"):
        meta = find_meta(site)
        published = tx[tx["site"] == site]
        rows.append({
            "site": site,
            "transformers": len(group),
            "min_share": group["share"].min(),
            "complete": bool((group["share"] >= COMPLETE).all()),
            "redacted": bool(published["redacted"].any()),
            "count_matches": meta is not None and int(meta["powertransformercount"] or 0) == len(group),
            "generation": site in with_generation,
            "reverse_flow": bool(published["negative"].any()),
            "located": meta is not None,
            "site_id": meta["sitefunctionallocation"] if meta is not None else None,
            "lat": meta["spatial_coordinates"]["lat"] if meta is not None else None,
            "lon": meta["spatial_coordinates"]["lon"] if meta is not None else None,
            "tx_ids": " ".join(sorted(group["tx_id"])),
        })
    screen = pd.DataFrame(rows)
    screen["kept"] = (screen["complete"] & ~screen["redacted"] & screen["count_matches"] & ~screen["generation"]
                      & ~screen["reverse_flow"] & screen["located"])
    screen.to_csv(OUT_DIR / "sites_screen.csv", index=False)
    candidates = screen[screen["complete"]]
    print(f"sites: {len(screen)}; at least {COMPLETE:.0%} complete: {len(candidates)}")
    for reason in ("redacted", "generation", "reverse_flow"):
        print(f"  of those, {reason}: {int(candidates[reason].sum())}")
    print(f"  transformer count differs: {int((~candidates['count_matches'] & candidates['located']).sum())}; "
          f"not located: {int((~candidates['located']).sum())}")

    # The draw: site ids ascending, shuffled with the fixed seed
    in_draw = screen[screen["kept"] & ~screen["site"].isin(ALREADY_DEV)]
    survivors = in_draw.sort_values("site_id")["site"].tolist()
    print(f"kept: {int(screen['kept'].sum())} (Newmarket/Bungay among them: "
          f"{sorted(ALREADY_DEV & set(screen.loc[screen['kept'], 'site']))}); in the draw: {len(survivors)}")
    order = np.random.default_rng(SEED).permutation(len(survivors))
    shuffled = [survivors[i] for i in order]
    dev, held = shuffled[:N_DEV], shuffled[N_DEV:]
    keyed = screen.set_index("site")
    dev_frame = keyed.loc[dev, ["site_id", "lat", "lon", "tx_ids"]].reset_index()
    dev_frame["key"] = [re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") for s in dev]
    dev_frame.to_csv(OUT_DIR / "sites_dev.csv", index=False)
    keyed.loc[held, ["site_id"]].reset_index().to_csv(OUT_DIR / "sites_heldout.csv", index=False)
    print(f"development: {len(dev)}; held out: {len(held)}")
