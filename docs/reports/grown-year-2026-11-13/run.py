"""Work 4: the grown years. Computes each metered primary's growth multiplier from the engine's own DFES ratios and runs
the year through `timeseries.run_year(..., scale=)`.

    cd packages/optimizer && uv run python ../../docs/reports/grown-year-2026-11-13/run.py check
    cd packages/optimizer && uv run python ../../docs/reports/grown-year-2026-11-13/run.py <year> <pathway id> [variant]

A variant is `warth-ltds` (Work 6a), a Work 6b example in `branches.EXAMPLES` (one branch's connections on the year), or
`flows-2025` (Work 13: the same year grown from 2025's measured flows instead of 2024's).
"""

import json
import sys
from pathlib import Path

import numpy as np

from gridify_optimizer.timeseries import growth_scale, run_year

from branches import EXAMPLES

W = Path("../../apps/pipeline/warehouse/nged-flows")
FLOWS = W / "bicker-fen-2024"


def multipliers(year: int, fid: str, folder: Path = FLOWS) -> dict[int, float]:
    """Per metered anchor bus: the engine's growth multiplier for its loads, weighted by their LTDS own maximum."""
    return growth_scale(folder, year, fid)


if sys.argv[1] == "check":
    b = np.load(W / "measured-year-2024-screened.npz")
    m1 = {a: 1.0 for a in multipliers(2030, "ht")}
    for label, sc in (("scale=None", None), ("every multiplier 1.0", m1)):
        p = run_year(FLOWS, W / "check.npz", rows=slice(0, 48), reactive="screened", scale=sc)
        with np.load(p) as z:
            print(label, {k: float(np.nanmax(np.abs(z[k] - b[k][:48]))) for k in ("line_pct", "trafo_pct", "vm", "p_ext_mw")})
    (W / "check.npz").unlink()
else:
    year, fid = int(sys.argv[1]), sys.argv[2]
    variant = sys.argv[3] if len(sys.argv) > 3 else ""
    flows = W / "bicker-fen-2025" if variant == "flows-2025" else FLOWS
    m = multipliers(year, fid, flows)
    if variant == "warth-ltds":
        # Work 6a: Warth Lane's multiplier from NGED's own LTDS forecast for 2030 (Forecast Year 5, 81.588 MW) over its own
        # maximum (18.61 MW); every other substation as the engine's DFES ratios give it
        from gridify_optimizer import nged
        d = next(r for r in nged.load_bundled_tables()["demand"] if r["Node"] == "WALN5_MAIN1")
        m[94] = nged._num(d["Forecast Year 5"]) / nged._num(d["Current Year Max Demand"])
    extra = {}
    if variant in EXAMPLES:
        conns, factory = EXAMPLES[variant]
        extra = {"connections": conns(), "plan_year": year, "net_factory": factory}
        print("connections:", [c.model_dump(mode="json") for c in extra["connections"]], flush=True)
    print("multipliers:", json.dumps({k: round(v, 3) for k, v in m.items()}), flush=True)
    out = W / f"grown-{year}-{fid}{'-' + variant if variant else ''}.npz"
    run_year(flows, out, reactive="screened", scale=m, **extra, progress=lambda j, n, s: print(f"{j}/{n}, {s:.0f} s", flush=True) if j % 5000 == 0 else None)
    print("saved", out, flush=True)
