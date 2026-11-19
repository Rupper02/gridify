"""Work 18: the collapse floor at Staythorpe. The plan years 2033-2035 under Holistic Transition as the engine now
reports them, and the half-hours of the saved grown years that converged below the floor (solved before the rule).
Writes `collapse_check.json`. Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/staythorpe-2026-11-13/collapse_check.py
"""

import json
import warnings
from pathlib import Path

import numpy as np

from gridify_optimizer import nged
from gridify_optimizer.config import COLLAPSE_VM_FLOOR_PU
from gridify_optimizer.nged_points import STAYTHORPE
from gridify_optimizer.types import PlanParams
from gridify_optimizer.years import evaluate_year

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
SNAP = HERE.parents[2] / "apps" / "pipeline" / "warehouse" / "supply-points" / "staythorpe"
T = {n: json.loads((SNAP / "tables" / f"{n}.json").read_text(encoding="utf-8")) for n in nged.TABLE_NAMES}
factory = lambda: nged.build_nged_net(T, point=STAYTHORPE)  # noqa: E731
out = {"plan_years": {}, "grown_files": {}}
for year in (2033, 2034, 2035):
    y = evaluate_year(year, [], PlanParams(scenario="ht"), net_factory=factory)
    out["plan_years"][year] = {"converged": y.converged, "violations": len(y.violations),
                               "first": y.violations[0].model_dump(mode="json") if y.violations else None,
                               "min_vm_pu": y.min_vm_pu}
    print(year, out["plan_years"][year], flush=True)
for f in ("measured-year-2025-screened.npz", "grown-2030-ht.npz", "grown-2035-ht.npz"):
    with np.load(SNAP / f) as z:
        ok = z["converged"].astype(bool)
        vmin = np.nanmin(z["vm"], axis=1)
        out["grown_files"][f] = {"solved": int(ok.sum()), "converged_below_floor": int((ok & (vmin < COLLAPSE_VM_FLOOR_PU)).sum()),
                                 "lowest_solved_vm_pu": round(float(np.nanmin(vmin[ok])), 4)}
    print(f, out["grown_files"][f], flush=True)
(HERE / "collapse_check.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
