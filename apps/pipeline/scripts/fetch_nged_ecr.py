"""Fetch NGED's Embedded Capacity Register (ECR) rows for the Bicker Fen GSP and bundle them.

The ECR lists every embedded generation/storage site ≥1 MW (and many smaller) that is connected or
ACCEPTED TO CONNECT, with location, connection voltage, export capacity and target energisation.
The accepted sites are the real connection queue the planner's registry is built from.

Source: NGED Connected Data Portal (CKAN), dataset "Embedded Capacity Register", resource
82a4ae83-77a3-4e7b-9060-8072ed96de9d. Only the columns the model needs are kept — no customer
names, street addresses or MPANs are bundled.

Run: `uv run --directory apps/api python ../pipeline/scripts/fetch_nged_ecr.py`
"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
RESOURCE_ID = "82a4ae83-77a3-4e7b-9060-8072ed96de9d"
GSP = "Bicker Fen 132Kv S Stn"
KEEP = [
    "reference", "customer_site", "grid_supply_point", "bulk_supply_point", "primary",
    "point_of_connection(poc)_voltage(kv)", "energy_source_1", "Energy Conversion Technology 1",
    "energy_source_2", "storage_capacity_1(mwh)", "flexible_connection (Yes/No)", "connection_status",
    "connected_maximum_export_capacity(mw)", "accepted_to_connect_registered_capacity(mw)",
    "accepted_change_to_maximum_export_capacity(mw)", "accepted_change_to_maximum_import_capacity(mw)",
    "date_accepted", "target_energisation_date", "date_connected", "in_a_connection_queue(y/n)",
    "transmission_reinforcement_reference", "last_updated", "lat", "lon",
]
DST = (Path(__file__).resolve().parents[3] / "packages" / "optimizer" / "src" / "gridforge_optimizer"
       / "data" / "nged" / "ecr.json")

url = ("https://connecteddata.nationalgrid.co.uk/api/3/action/datastore_search?"
       + urllib.parse.urlencode({"resource_id": RESOURCE_ID, "limit": 5000,
                                 "filters": json.dumps({"grid_supply_point": GSP})}))
with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
    records = json.load(r)["result"]["records"]

rows = [{k: rec.get(k) for k in KEEP} for rec in records]
rows.sort(key=lambda x: (x["connection_status"] or "", str(x["reference"] or "")))
DST.write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
by_status: dict[str, int] = {}
for x in rows:
    by_status[x["connection_status"]] = by_status.get(x["connection_status"], 0) + 1
print(f"wrote {DST} ({len(rows)} rows: {by_status})")
