"""Step 4, Stage C: Staythorpe's commissioning year, 2025, screened, on its build with no exceptions beyond those its record
holds (the Hawton alias). The same driver as Bicker Fen's measured years (`timeseries.run_year`), through the source
seam (`NgedSource(tables, STAYTHORPE)`). Writes `apps/pipeline/warehouse/supply-points/staythorpe/measured-year-2025-screened.npz`.
Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/staythorpe-2026-11-13/run_2025.py
"""

import json
import warnings
from pathlib import Path

from gridify_optimizer import nged
from gridify_optimizer.nged_points import STAYTHORPE
from gridify_optimizer.sources import NgedSource
from gridify_optimizer.timeseries import run_year

warnings.filterwarnings("ignore")
SNAP = Path(__file__).resolve().parents[2].parent / "apps" / "pipeline" / "warehouse" / "supply-points" / "staythorpe"
T = {n: json.loads((SNAP / "tables" / f"{n}.json").read_text(encoding="utf-8")) for n in nged.TABLE_NAMES}
src = NgedSource(tables=T, point=STAYTHORPE)
out = SNAP / "measured-year-2025-screened.npz"
run_year(SNAP / "flows-2025", out, source=src, reactive="screened",
         about={"label": "Staythorpe 2025, reactive power screened (commissioning)", "supply_point": STAYTHORPE.key},
         progress=lambda j, n, s: print(f"{j}/{n}, {s:.0f} s", flush=True) if j % 5000 == 0 else None)
print("saved", out, flush=True)
