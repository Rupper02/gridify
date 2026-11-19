"""Work 16b: each run's hours of GSP import above the supergrid transformers' published import limit, counted against
the limit of each half-hour's own season (the run file's `season`, NGED's four), beside the earlier count against the
summer limit all year. Both SGTs in service, and one out (a single SGT's limit), for context. Import is the engine's
infeed (`p_ext_mw`), without Ash Farm, as in section 4. Writes `import_hours.json`. Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/grown-year-2026-11-13/import_hours.py
"""

import json
from pathlib import Path

import numpy as np

from gridify_optimizer.nged_points import BICKER_FEN
from gridify_optimizer.nged_runs import CATALOGUE

W = Path("../../apps/pipeline/warehouse/nged-flows")
LIM = BICKER_FEN.boundary["import_limit_mw"]  # both SGTs, per season
SGTS = BICKER_FEN.boundary["sgt_count"]
out = {"limits_both_sgts_mw": LIM}
for run_id, (f, label, *_rest) in CATALOGUE.runs.items():
    if not (W / f).exists():
        continue
    with np.load(W / f) as z:
        imp = np.asarray(z["p_ext_mw"], float)
        season = z["season"].astype(str)
    lim = np.array([LIM[s] for s in season])
    ok = ~np.isnan(imp)
    h = lambda m: float((m & ok).sum() / 2)  # noqa: E731
    out[run_id] = {
        "label": label, "import_peak_mw": round(float(np.nanmax(imp)), 1),
        "both_sgts": {"before_summer_limit_all_year": h(imp > LIM["summer"]), "after_own_season": h(imp > lim),
                      "after_by_season": {s: h((imp > lim) & (season == s)) for s in LIM}},
        "one_sgt_out": {"before_winter_limit_all_year": h(imp > LIM["winter"] / SGTS), "before_summer_limit_all_year": h(imp > LIM["summer"] / SGTS),
                        "after_own_season": h(imp > lim / SGTS),
                        "after_by_season": {s: h((imp > lim / SGTS) & (season == s)) for s in LIM}},
    }
Path(__file__).with_name("import_hours.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
for r, v in out.items():
    if r != "limits_both_sgts_mw":
        print(f"{r:24s} peak {v['import_peak_mw']:6.1f} | both SGTs: {v['both_sgts']['before_summer_limit_all_year']:6.1f} -> {v['both_sgts']['after_own_season']:5.1f}"
              f" | one SGT out: winter-all-year {v['one_sgt_out']['before_winter_limit_all_year']:6.1f}, own season {v['one_sgt_out']['after_own_season']:6.1f} {v['one_sgt_out']['after_by_season']}")
