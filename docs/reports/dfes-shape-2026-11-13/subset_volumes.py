"""Work 8.2, step 1: read NGED's per-ESA DFES volumes (the owner's browser download, a 948 MB CSV inside the ZIP) in
chunks, keep Bicker Fen's 21 ESAs, and record what establishes the edition (scenario names, years, ESA count). Writes
`dfes_volumes_bicker_fen.csv` and `volumes_edition.json` beside the download. Read-only on the ZIP. Supported by NGED
Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/dfes-shape-2026-11-13/subset_volumes.py
"""

import json
import zipfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DIR = HERE.parents[2] / "apps" / "pipeline" / "warehouse" / "nged-flows" / "dfes-2025"
ESAS = {r["ESA"] for r in json.loads((HERE.parents[2] / "packages" / "optimizer" / "src" / "gridify_optimizer" / "data" / "nged" / "dfes.json").read_text())}
keep, scen, years, esas, rows = [], set(), set(), set(), 0
with zipfile.ZipFile(DIR / "dfes_volume_projections_esa_v2.zip") as z, z.open("dfes_volume_projections_ESA.csv") as f:
    for c in pd.read_csv(f, chunksize=2_000_000, dtype=str):
        rows += len(c)
        scen |= set(c["scenario"].unique()); years |= set(c["year"].unique()); esas |= set(c["ESA"].unique())
        keep.append(c[c["ESA"].isin(ESAS)])
        print(rows, flush=True)
sub = pd.concat(keep)
sub.to_csv(DIR / "dfes_volumes_bicker_fen.csv", index=False)
ed = {"rows": rows, "scenarios": sorted(scen), "years": sorted(years, key=int), "esa_count": len(esas),
      "bicker_fen_esas_found": sorted(set(sub["ESA"])), "bicker_fen_rows": len(sub),
      "technologies": sorted(set(sub["technology"]))}
(DIR / "volumes_edition.json").write_text(json.dumps(ed, indent=1), encoding="utf-8")
print(json.dumps({k: v for k, v in ed.items() if k != "technologies"}, indent=1)[:2000])
