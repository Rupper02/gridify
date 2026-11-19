"""Work 8.2 addendum (spec.md): 2035 Holistic Transition on 2024's flows, shaped at the eight areas that passed the gate,
grown uniformly elsewhere as in the catalogued `grown-2035-ht`. The increments are added to the measured year here,
before the engine's `run_year`; the engine is unchanged. Writes `nged-flows/sensitivity-2035-ht-shaped8.npz` (not
catalogued). Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/dfes-shape-2026-11-13/sensitivity.py [check]
"""

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate import DAY, ROOT, SEASON_MONTHS, increments  # noqa: E402

from gridify_optimizer import nged  # noqa: E402
from gridify_optimizer.sources import NgedSource  # noqa: E402
from gridify_optimizer.timeseries import growth_scale, run_year  # noqa: E402

warnings.filterwarnings("ignore")
W = ROOT / "apps" / "pipeline" / "warehouse" / "nged-flows"
FLOWS = W / "bicker-fen-2024"
EIGHT = ["ALFORD", "CRANWELL", "EASTON", "INGOLDMELLS", "NEW BEACON ROAD GRANTHAM", "SKILLINGTON", "TATTERSHALL", "TRUSTHORPE"]
EIGHT = [f"{n} 33 11kV S STN" for n in EIGHT]
SEASON_DAY = {"Winter": DAY["Winter"], "Intermediate Cool": DAY["Intermediate Cool"],
              "Intermediate Warm": DAY["Intermediate Warm"], "Summer": DAY["Summer"]}


class Shaped:
    """The NGED source with the increments added to its measured year at the eight anchors."""

    def __init__(self, inner, add_p: pd.DataFrame, add_q: pd.DataFrame):
        self.inner, self.add_p, self.add_q = inner, add_p, add_q

    def __getattr__(self, k):
        return getattr(self.inner, k)

    def measured_year(self, folder, net, reactive="published"):
        y = self.inner.measured_year(folder, net, reactive)
        for c in self.add_p.columns:
            y.bus_p[c] = y.bus_p[c].to_numpy(float) + self.add_p[c].to_numpy(float)
            y.bus_q[c] = y.bus_q[c].to_numpy(float) + self.add_q[c].to_numpy(float)
        return y


src = NgedSource()
net = src.build_net()
y = src.measured_year(FLOWS, net, "screened")
cl = {int(b): int(b) for b in net.bus.index}
for k, m in y.notes["multi_bus_clusters"].items():
    for b in m:
        cl[int(b)] = int(k)
metered = {cl.get(int(a), int(a)): int(a) for a in y.notes["metered"]}
esas = sorted({r["ESA"] for r in json.loads((ROOT / "packages/optimizer/src/gridify_optimizer/data/nged/dfes.json").read_text())})
anchor_of, tanphi = {}, {}
for i, ld in net.load.iterrows():
    e = nged.dfes_esa(str(ld["primary"] or ""), esas)
    a = metered.get(cl.get(int(ld.bus), int(ld.bus)))
    if e in EIGHT and a is not None:
        anchor_of.setdefault(e, set()).add(a)
        tanphi[e] = float(ld.q_mvar) / float(ld.p_mw) if float(ld.p_mw) else 0.0
assert all(len(anchor_of.get(e, ())) == 1 for e in EIGHT), anchor_of
mid = pd.DatetimeIndex(y.times) - pd.Timedelta(minutes=15)  # NGED stamps the end of each half-hour
k_of = ((mid.hour * 60 + mid.minute - 15) // 30).to_numpy()
MONTH_SEASON = {m: s for s, ms in SEASON_MONTHS.items() for m in ms}
seasons = np.array([MONTH_SEASON[m] for m in mid.month])  # by the half-hour's own month, as spec.md fixes
day_inc = {e: {s: increments(e, 2035, d)[0] for s, d in SEASON_DAY.items()} for e in EIGHT}
add_p = pd.DataFrame(index=y.bus_p.index)
add_q = pd.DataFrame(index=y.bus_p.index)
for e in EIGHT:
    (a,) = anchor_of[e]
    v = np.array([day_inc[e][s][k] for s, k in zip(seasons, k_of)])
    add_p[a], add_q[a] = v, v * tanphi[e]
mult = growth_scale(FLOWS, 2035, "ht")
for e in EIGHT:
    mult[next(iter(anchor_of[e]))] = 1.0
about = {"label": "2035 HT, shaped at the eight areas that passed the gate (a sensitivity, not catalogued)",
         "shaped": {e: next(iter(anchor_of[e])) for e in EIGHT}}
print(json.dumps({"anchors": about["shaped"], "season_names": sorted(set(seasons)),
                  "added_peak_mw": {e: round(float(add_p[next(iter(anchor_of[e]))].max()), 2) for e in EIGHT}}), flush=True)
shaped = Shaped(src, add_p, add_q)
if sys.argv[1:] == ["check"]:
    p = run_year(FLOWS, W / "check-shaped.npz", source=shaped, rows=slice(0, 48), reactive="screened", scale=mult, about=about)
    with np.load(p) as z:
        print("check: 48 half-hours solved", int(z["converged"].sum()))
    p.unlink()
else:
    out = W / "sensitivity-2035-ht-shaped8.npz"
    run_year(FLOWS, out, source=shaped, reactive="screened", scale=mult, about=about,
             progress=lambda j, n, s: print(f"{j}/{n}, {s:.0f} s", flush=True) if j % 5000 == 0 else None)
    print("saved", out, flush=True)
