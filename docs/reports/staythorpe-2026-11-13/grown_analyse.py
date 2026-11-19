"""Step 4, Stage D: Staythorpe's 2025 reference and its two grown years read the way the planner reads Bicker Fen's
(`runs.RunFiles` with a catalogue built here, for this report only: Staythorpe's runs are not in the planner's catalogue),
plus the supply point's exchange against its seasonal import limits and the share of half-hours that solved. Writes
`grown_figures.json`. Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/staythorpe-2026-11-13/grown_analyse.py
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from gridify_optimizer import nged
from gridify_optimizer.nged_points import STAYTHORPE
from gridify_optimizer.runs import RunCatalogue, RunFiles

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
SNAP = HERE.parents[2] / "apps" / "pipeline" / "warehouse" / "supply-points" / "staythorpe"
T = {n: json.loads((SNAP / "tables" / f"{n}.json").read_text(encoding="utf-8")) for n in nged.TABLE_NAMES}
factory = lambda: nged.build_nged_net(T, point=STAYTHORPE)  # noqa: E731
cat = RunCatalogue(
    runs={"2025-screened": ("measured-year-2025-screened.npz", "Staythorpe 2025, screened", "measured", 2025, None, "run_2025.py"),
          "2030-ht": ("grown-2030-ht.npz", "Staythorpe 2030 HT (grown on 2025)", "grown", 2030, "ht", "grown.py 2030 ht"),
          "2035-ht": ("grown-2035-ht.npz", "Staythorpe 2035 HT (grown on 2025)", "grown", 2035, "ht", "grown.py 2035 ht")},
    bases=(), measured_flows="flows-2025", reference="2025-screened", source="NGED",
    measured_limits="", grown_limits="", branch_year_limits="")
rf = RunFiles(SNAP, cat, factory)
net = factory()
lim = STAYTHORPE.boundary["import_limit_mw"]
sgts = STAYTHORPE.boundary["sgt_count"]
exp_lim = STAYTHORPE.boundary["export_limit_mw"]
out = {}
for rid in cat.runs:
    if not rf.path(rid).exists():
        out[rid] = "no file"
        continue
    s = rf.summarise(rid)
    reliable = [e for e in s.elements if e.finding and e.label.startswith(("flow agrees", "flow differs"))]
    z = np.load(rf.path(rid))
    T_ = pd.DatetimeIndex(pd.to_datetime(z["times"]))
    conv = z["converged"].astype(bool)
    imp = pd.Series(z["p_ext_mw"])
    season = z["season"].astype(str)
    sl = np.array([lim[x] for x in season])
    unsolved = T_[~conv]
    name = lambda e: (f"{net.bus.at[int(net.line.at[e.element_id, 'from_bus']), 'name']} - {net.bus.at[int(net.line.at[e.element_id, 'to_bus']), 'name']}"  # noqa: E731
                      if e.kind == "line" else f"{net.bus.at[int(net.trafo.at[e.element_id, 'hv_bus']), 'name']} - {net.bus.at[int(net.trafo.at[e.element_id, 'lv_bus']), 'name']}")
    out[rid] = {
        "half_hours": s.half_hours, "solved": s.solved, "solved_share": round(s.solved / s.half_hours, 4),
        "unsolved_months": {str(k): int(v) for k, v in pd.Series(unsolved.month).value_counts().sort_index().items()},
        "unsolved_hours_of_day": {int(k): int(v) for k, v in pd.Series(unsolved.hour).value_counts().sort_index().items()},
        "over_rating": [{"kind": e.kind, "id": e.element_id, "name": name(e), "label": e.label, "peak_pct": e.peak_pct, "h100": e.h100, "h90": e.h90}
                        for e in sorted(reliable, key=lambda e: -e.h100) if e.h100 > 0],
        "not_findings_over": [{"kind": e.kind, "id": e.element_id, "label": e.label, "h100": e.h100} for e in s.elements if e.h100 > 0 and e not in reliable],
        "buses_out_of_band": [{"bus": b.bus_id, "name": str(net.bus.at[b.bus_id, "name"]), "hours": b.hours_outside, "vmin": b.vmin_pu, "vmax": b.vmax_pu}
                              for b in s.buses],
        "above_firm": [{"name": x.name, "firm_mva": x.firm_mva, "peak_mva": x.peak_mva, "hours": x.hours_above_firm} for x in s.substations],
        "import_peak_mw": round(float(imp[conv].max()), 1), "export_peak_mw": round(float(-imp[conv].min()), 1),
        "import_above_season_limit_h": float(((imp > sl) & conv).sum() / 2),
        "import_above_one_sgt_season_limit_h": float(((imp > sl / sgts) & conv).sum() / 2),
        "export_above_limit_h": float(((-imp > exp_lim) & conv).sum() / 2),
    }
(HERE / "grown_figures.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
for rid, v in out.items():
    if isinstance(v, str):
        print(rid, v)
        continue
    print(f"== {rid}: solved {v['solved']}/{v['half_hours']} ({v['solved_share']:.1%}); import peak {v['import_peak_mw']} MW, export peak {v['export_peak_mw']} MW; "
          f"import above season limit {v['import_above_season_limit_h']} h, above one SGT's {v['import_above_one_sgt_season_limit_h']} h")
    for e in v["over_rating"][:12]:
        print(f"   {e['name']} ({e['label'][:12]}): peak {e['peak_pct']}%, {e['h100']} h over")
    print("   busbars out of band:", [(b["name"], b["hours"], b["vmin"]) for b in v["buses_out_of_band"]][:8])
    print("   above firm:", [(x["name"], x["peak_mva"], x["hours"]) for x in v["above_firm"]])
    if v["unsolved_months"]:
        print("   unsolved by month:", v["unsolved_months"], "by hour:", v["unsolved_hours_of_day"])
