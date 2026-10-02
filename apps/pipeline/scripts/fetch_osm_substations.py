"""Geolocate the NGED network's substations from OpenStreetMap and bundle a coords join table.

NGED's own substation-location datasets are access-restricted (403 via both the portal and the
CKAN API), so bus positions came from a placeholder layout. OpenStreetMap maps most UK substations
with real coordinates and names. This script queries OSM (Overpass) for power substations in the
Bicker Fen GSP area, matches them to the network's substation names EXACTLY (after stripping words
like "Substation"), and writes packages/optimizer/.../data/nged/coords.csv, which the NGED builder
reads (name, latitude, longitude, source). Buses it can't match — mostly line tee-points such as
"Pole 90ZB1E17" — are placed by the builder between their connected neighbours.

Data © OpenStreetMap contributors, available under the Open Database Licence (ODbL).
Run: `uv run --directory apps/api python ../pipeline/scripts/fetch_osm_substations.py`
"""
import csv
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from gridforge_optimizer.nged import _built, _substation

BBOX = (52.6, -0.9, 53.45, 0.45)  # south, west, north, east — covers the Bicker Fen GSP region
ENDPOINTS = ("https://overpass.private.coffee/api/interpreter", "https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter")
DST = (Path(__file__).resolve().parents[3] / "packages" / "optimizer" / "src" / "gridforge_optimizer"
       / "data" / "nged" / "coords.csv")

query = f"""[out:json][timeout:90];
nwr["power"="substation"]["name"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
out center tags;"""
elements = None
for ep in ENDPOINTS:
    try:
        req = urllib.request.Request(ep, data=urllib.parse.urlencode({"data": query}).encode(),
                                     headers={"User-Agent": "gridforge/0.1 (grid planning research)"})
        with urllib.request.urlopen(req, timeout=150) as r:
            elements = json.load(r)["elements"]
        print(f"OSM: {len(elements)} named substations from {ep}")
        break
    except Exception as e:  # mirrors are flaky — try the next one
        print(f"{ep}: {e}")
if elements is None:
    raise SystemExit("no Overpass endpoint answered")


def key(name: str) -> str:
    n = re.sub(r"\b(substation|grid|primary|bsp|s\.? ?stn|33kv|132kv|11kv|local|main)\b", "", (name or "").lower())
    return " ".join(re.sub(r"[^a-z ]", " ", n).split())


osm: dict[str, dict] = {}
for e in elements:
    c = e.get("center") or {"lat": e.get("lat"), "lon": e.get("lon")}
    k = key(e["tags"]["name"])
    if k and c["lat"] is not None:
        osm.setdefault(k, {"name": e["tags"]["name"], "lat": c["lat"], "lon": c["lon"]})

net = _built()["net"]
subs = sorted({_substation(net.bus.at[b, "name"]) for b in net.bus.index})
rows = [{"name": s, "latitude": round(osm[key(s)]["lat"], 6), "longitude": round(osm[key(s)]["lon"], 6),
         "source": f"OpenStreetMap: {osm[key(s)]['name']}"} for s in subs if key(s) in osm]
with DST.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["name", "latitude", "longitude", "source"])
    w.writeheader()
    w.writerows(rows)
print(f"wrote {DST}: {len(rows)} of {len(subs)} network substations geolocated")
print("unmatched:", ", ".join(s for s in subs if key(s) not in osm))
