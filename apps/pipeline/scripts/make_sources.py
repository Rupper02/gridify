"""Generate the messy raw source files GridForge ingests.

Run once:  uv run python scripts/make_sources.py

It produces two files under data/raw/ from the mv_oberrhein network:

  substations.geojson  - bus coordinates (the "GIS layer"), with a few buses
                         deliberately MISSING so the coverage check has a target.
  asset_register.csv   - the "field team spreadsheet" of line ratings, with
                         deliberate mess so the Stage-3 checks have something to
                         bite on.

Nothing here is clever - it's fixture prep.

IMPORTANT: pandapower element indices are NOT contiguous (mv_oberrhein skips
line ids 9, 13, 19..., and bus ids run up to 319 for only 179 buses). So we pick
each defect target by its POSITION in the index and resolve it to a real id at
runtime - otherwise a planted defect lands on an id that doesn't exist and
silently disappears.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandapower.networks as nw

# scripts/ lives one level under the repo root; data/raw sits at the root.
DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

# --- the answer key: positions (not ids) of what we deliberately break -------
BUS_DROP_POSITIONS = [5, 42, 77, 120, 168]  # buses dropped from the GeoJSON
VOLTAGE_VARIANTS = ["20 kV", "20kv", "20 KV", " 20 kV ", "20kV"]  # inconsistent formatting
DUPLICATE_POSITIONS = [0, 5]     # line rows repeated verbatim
WHITESPACE_NAME_POS = 3          # name padded with spaces
BLANK_RATING_POS = 7             # rating left empty
UNIT_IN_RATING_POS = 8           # rating typed as "362 A" (forces string dtype)
ZERO_RATING_POS = 9              # rating 0  -> fails "rating > 0"
NEGATIVE_RATING_POS = 10         # rating -50 -> fails "rating > 0"
PHANTOM_LINE_ID = 9999           # a line id that does not exist in the network
# ---------------------------------------------------------------------------


def build_geojson(net) -> dict:
    """A GeoJSON FeatureCollection of bus locations, minus a few buses."""
    bus_ids = net.bus.index.tolist()
    drop_bus_ids = {bus_ids[p] for p in BUS_DROP_POSITIONS}  # positions -> real ids

    features = []
    for bus_id, row in net.bus.iterrows():
        if bus_id in drop_bus_ids:
            continue  # simulate a bus the GIS system never got coordinates for
        point = json.loads(row["geo"])  # {"coordinates": [lon, lat], "type": "Point"}
        features.append(
            {
                "type": "Feature",
                "geometry": point,
                "properties": {
                    "bus_id": int(bus_id),
                    "name": row["name"],
                    "vn_kv": float(row["vn_kv"]),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def build_register_rows(net) -> list[dict]:
    """The line asset register - clean values first, then messed up per the answer key."""
    line_ids = net.line.index.tolist()
    # resolve each position to a real, existing line id
    whitespace_id = line_ids[WHITESPACE_NAME_POS]
    blank_id = line_ids[BLANK_RATING_POS]
    unit_id = line_ids[UNIT_IN_RATING_POS]
    zero_id = line_ids[ZERO_RATING_POS]
    neg_id = line_ids[NEGATIVE_RATING_POS]
    duplicate_ids = [line_ids[p] for p in DUPLICATE_POSITIONS]

    rows: list[dict] = []
    for line_id, row in net.line.iterrows():
        rating_a = round(row["max_i_ka"] * 1000)  # kA -> A, human-friendly integer

        name = row["name"]
        if line_id == whitespace_id:
            name = f"  {name}  "

        rating: str = str(rating_a)
        if line_id == blank_id:
            rating = ""
        elif line_id == unit_id:
            rating = f"{rating_a} A"
        elif line_id == zero_id:
            rating = "0"
        elif line_id == neg_id:
            rating = "-50"

        rows.append(
            {
                "line_id": line_id,
                "line_name": name,
                "voltage": VOLTAGE_VARIANTS[line_id % len(VOLTAGE_VARIANTS)],
                "rating_a": rating,
                "length_km": round(row["length_km"], 4),
            }
        )

    # duplicate a couple of rows verbatim
    by_id = {r["line_id"]: r for r in rows}
    for dup in duplicate_ids:
        rows.append(dict(by_id[dup]))

    # a phantom line that exists in the spreadsheet but not in the network
    rows.append(
        {
            "line_id": PHANTOM_LINE_ID,
            "line_name": "Line 9999",
            "voltage": "20 kV",
            "rating_a": "300",
            "length_km": 1.0,
        }
    )
    return rows, {"blank": blank_id, "unit": unit_id, "zero": zero_id, "neg": neg_id}


def main() -> None:
    net = nw.mv_oberrhein()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    geojson = build_geojson(net)
    (DATA_DIR / "substations.geojson").write_text(json.dumps(geojson, indent=2))

    rows, planted = build_register_rows(net)
    with (DATA_DIR / "asset_register.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {DATA_DIR / 'substations.geojson'}")
    print(f"  {len(geojson['features'])} of {len(net.bus)} buses "
          f"({len(BUS_DROP_POSITIONS)} intentionally missing coords)")
    print(f"Wrote {DATA_DIR / 'asset_register.csv'}")
    print(f"  {len(rows)} rows for {len(net.line)} real lines "
          f"({len(DUPLICATE_POSITIONS)} duplicates + 1 phantom line {PHANTOM_LINE_ID})")
    print(f"  planted bad ratings on line ids -> "
          f"blank={planted['blank']}, zero={planted['zero']}, neg={planted['neg']} "
          f"(unit={planted['unit']} stays valid)")


if __name__ == "__main__":
    main()
