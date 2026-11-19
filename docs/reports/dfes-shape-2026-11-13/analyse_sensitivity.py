"""Work 8.2 addendum: the eight passing substations' own 33/11 kV transformers and firm capacity, shaped
(`sensitivity-2035-ht-shaped8.npz`) against uniform (the catalogued `grown-2035-ht.npz`), nothing else (spec.md,
addendum). Writes `sensitivity.json`. Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/dfes-shape-2026-11-13/analyse_sensitivity.py
"""

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate import ROOT  # noqa: E402

from gridify_optimizer import nged  # noqa: E402
from gridify_optimizer.runs import _clusters  # noqa: E402
from gridify_optimizer.sources import NgedSource  # noqa: E402

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
W = ROOT / "apps" / "pipeline" / "warehouse" / "nged-flows"
RUNS = {"uniform": W / "grown-2035-ht.npz", "shaped": W / "sensitivity-2035-ht-shaped8.npz"}
net = NgedSource().build_net()
esas = sorted({r["ESA"] for r in json.loads((ROOT / "packages/optimizer/src/gridify_optimizer/data/nged/dfes.json").read_text())})
z = {k: np.load(p) for k, p in RUNS.items()}
meta = json.loads(str(z["shaped"]["meta"]))
EIGHT = meta["about"]["shaped"]
cl = _clusters(meta)


def part(h):
    return "night" if h < 5 or h >= 23 else "morning" if h < 11 else "midday" if h < 16 else "evening"


out = {}
for esa in EIGHT:
    ld = net.load[[nged.dfes_esa(str(p or ""), esas) == esa for p in net.load["primary"]]]
    bs = {cl.get(int(b), int(b)) for b in ld.bus}
    site = [int(x) for x in net.bus.index if cl.get(int(x), int(x)) in bs]
    tr = [int(i) for i in net.trafo.index if int(net.trafo.at[i, "lv_bus"]) in site
          and float(net.bus.at[int(net.trafo.at[i, "hv_bus"]), "vn_kv"]) < 132]
    firm = float(ld.firm_mva.fillna(0).max())
    rec = {"transformers": {int(i): f"{net.bus.at[int(net.trafo.at[i, 'hv_bus']), 'name']} - {net.bus.at[int(net.trafo.at[i, 'lv_bus']), 'name']} ({net.trafo.at[i, 'sn_mva']} MVA)" for i in tr},
           "firm_mva": firm}
    for run, f in z.items():
        T = pd.DatetimeIndex(pd.to_datetime(f["times"])) - pd.Timedelta(minutes=15)
        ok = f["converged"].astype(bool)
        tp = pd.DataFrame(f["trafo_pct"], columns=f["trafo_ids"])[tr]
        r = {"solved": int(ok.sum())}
        for i in tr:
            s = tp[i].to_numpy(float)
            over = ok & (s > 100)
            r[f"trafo {i}"] = {"peak_pct": round(float(np.nanmax(s[ok])), 1), "peak_at": str(T[ok][int(np.nanargmax(s[ok]))]),
                               "h100": float(over.sum() / 2),
                               "months": {int(k): float(v / 2) for k, v in pd.Series(T[over].month).value_counts().sort_index().items()},
                               "part_of_day": {k: float(v / 2) for k, v in pd.Series([part(h) for h in T[over].hour]).value_counts().items()}}
        mva = (tp / 100 * net.trafo.loc[tr, "sn_mva"].to_numpy()).sum(axis=1).to_numpy(float)
        r["site_peak_mva"] = round(float(np.nanmax(mva[ok])), 2)
        r["site_peak_at"] = str(T[ok][int(np.nanargmax(mva[ok]))])
        r["hours_above_firm"] = float((ok & (mva > firm)).sum() / 2) if firm > 0 else None
        rec[run] = r
    out[esa] = rec
(HERE / "sensitivity.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
for esa, rec in out.items():
    print(f"== {esa[:26]} firm {rec['firm_mva']} MVA; units: {list(rec['transformers'].values())}")
    for run in ("uniform", "shaped"):
        r = rec[run]
        ts = {k: (v["peak_pct"], v["h100"], v["peak_at"][5:16]) for k, v in r.items() if k.startswith("trafo")}
        print(f"   {run:8s} site peak {r['site_peak_mva']} MVA at {r['site_peak_at'][5:16]}, above firm {r['hours_above_firm']} h; {ts}")
        for k, v in r.items():
            if k.startswith("trafo") and v["h100"]:
                print(f"      {k}: months {v['months']} parts {v['part_of_day']}")
