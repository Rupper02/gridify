"""Step 4, Stage D: a grown year for Staythorpe on its own 2025 flows, the method Bicker Fen's grown years use
(docs/reports/grown-year-2026-11-13/run.py): each metered primary's 2025 series multiplied by the engine's DFES growth
for the year and pathway (`timeseries.growth_scale`), reactive power screened, through the source seam. Writes
`apps/pipeline/warehouse/supply-points/staythorpe/grown-<year>-<pathway>.npz`. Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/staythorpe-2026-11-13/grown.py <year> <pathway>
"""

import json
import sys
import warnings
from pathlib import Path

from gridify_optimizer import nged
from gridify_optimizer.nged_points import STAYTHORPE
from gridify_optimizer.sources import NgedSource
from gridify_optimizer.timeseries import growth_scale, run_year

warnings.filterwarnings("ignore")
SNAP = Path(__file__).resolve().parents[2].parent / "apps" / "pipeline" / "warehouse" / "supply-points" / "staythorpe"
T = {n: json.loads((SNAP / "tables" / f"{n}.json").read_text(encoding="utf-8")) for n in nged.TABLE_NAMES}
src = NgedSource(tables=T, point=STAYTHORPE)
year, fid = int(sys.argv[1]), sys.argv[2]
folder = SNAP / "flows-2025"
m = growth_scale(folder, year, fid, source=src)
print("multipliers:", json.dumps({k: round(v, 3) for k, v in m.items()}), flush=True)
out = SNAP / f"grown-{year}-{fid}.npz"
run_year(folder, out, source=src, reactive="screened", scale=m,
         about={"label": f"Staythorpe {year}, {fid} (grown on 2025's flows)", "supply_point": STAYTHORPE.key},
         progress=lambda j, n, s: print(f"{j}/{n}, {s:.0f} s", flush=True) if j % 5000 == 0 else None)
print("saved", out, flush=True)
