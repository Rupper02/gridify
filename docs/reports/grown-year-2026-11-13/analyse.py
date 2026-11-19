"""Work 4: the figures of a grown year, from its run file, beside the same plan year's planning cases.

    cd packages/optimizer && uv run python ../../docs/reports/grown-year-2026-11-13/analyse.py <year> <pathway id> [variant]

Writes `<year>-<pathway>[-<variant>]/figures.json` and `elements.csv` (a variant is `run.py`'s, e.g. `warth-ltds`). Labels are step 1's (the measured year's
comparison with NGED's model, `docs/reports/measured-year-2024/screened/elements.csv`). Supported by NGED Open Data.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gridify_optimizer import network, nged
from gridify_optimizer.types import PlanParams
from gridify_optimizer.years import simulate

from branches import EXAMPLES

YEAR, FID = int(sys.argv[1]), sys.argv[2]
VARIANT = sys.argv[3] if len(sys.argv) > 3 else ""
TAG = f"{YEAR}-{FID}" + (f"-{VARIANT}" if VARIANT else "")
# a Work 6b example: its branch's connections in the planning cases too, on the same network as its run
conns, factory = EXAMPLES[VARIANT] if VARIANT in EXAMPLES else (lambda: [], None)
W = Path("../../apps/pipeline/warehouse/nged-flows")
HERE = Path(__file__).resolve().parent
OUT = HERE / TAG
OUT.mkdir(exist_ok=True)
z = np.load(W / f"grown-{TAG}.npz")
meta = json.loads(str(z["meta"]))
T = pd.DatetimeIndex(pd.to_datetime(z["times"]))
start = T - pd.Timedelta(minutes=30)  # each half-hour's own start: its month and hour of day
conv = z["converged"]
net = (factory or network.build_base_net)()
L, TR, B = net.line, net.trafo, net.bus
lpct = pd.DataFrame(z["line_pct"], columns=z["line_ids"])
tpct = pd.DataFrame(z["trafo_pct"], columns=z["trafo_ids"])
vm = pd.DataFrame(z["vm"], columns=z["bus_ids"])
p_ext = pd.Series(z["p_ext_mw"])
step1 = {(r["kind"], int(r["id"])): r for r in pd.read_csv(HERE.parent / "measured-year-2024" / "screened" / "elements.csv").to_dict("records")}
F = {"year": YEAR, "pathway": FID, "variant": VARIANT, "converged": int(conv.sum()), "half_hours": int(len(conv)), "seconds": meta["seconds"],
     "multipliers": meta.get("scale")}

# the same plan year's planning cases (winter peak, summer minimum), worst of the two per element, and every breach
plan = simulate(conns(), PlanParams(scenario=FID), years=(YEAR,), net_factory=factory or network.build_base_net).years[str(YEAR)]
breaches = [(v.type, v.element_id, v.case, v.value) for v in plan.violations]
F["planning_cases"] = {"breaches": len(breaches), "worst_line": plan.worst_line_loading_pct, "worst_trafo": plan.worst_trafo_loading_pct,
                       "gsp_export": plan.gsp_export_mw, "gsp_import": plan.gsp_import_mw, "list": breaches}

rows = []
for kind, pct, tab, ploading in (("line", lpct, L, plan.line_loading), ("trafo", tpct, TR, plan.trafo_loading)):
    for i in tab.index:
        x = pct[i]
        a, b = (int(tab.at[i, "from_bus"]), int(tab.at[i, "to_bus"])) if kind == "line" else (int(tab.at[i, "hv_bus"]), int(tab.at[i, "lv_bus"]))
        over = x >= 100
        s1 = step1.get((kind, int(i)), {})
        pb = [c for (t, e, c, v) in breaches if t == kind and e == int(i)]
        rows.append(dict(kind=kind, id=int(i), name=f"{B.at[a, 'name']} - {B.at[b, 'name']}", label=s1.get("label", ""),
                         offset_mw=s1.get("offset_mw"), offset_pct_of_rating=s1.get("offset_pct_of_rating"),
                         peak_pct=round(float(x.max()), 1), peak_at=str(T[int(x.idxmax())]),
                         h80=float((x >= 80).sum() / 2), h90=float((x >= 90).sum() / 2), h100=float((x > 100).sum() / 2),
                         over_months=",".join(str(m) for m in sorted(set(start[over.to_numpy()].month))),
                         over_hours=",".join(f"{h:02d}" for h in sorted(set(start[over.to_numpy()].hour))),
                         plan_envelope_pct=round(float(ploading.get(int(i), np.nan)), 1), plan_breach_cases=",".join(pb)))
E = pd.DataFrame(rows).sort_values(["h100", "peak_pct"], ascending=False)
E.to_csv(OUT / "elements.csv", index=False)
grown_over = set((r.kind, r.id) for r in E.itertuples() if r.h100 > 0)
plan_over = set((t, e) for (t, e, c, v) in breaches if t in ("line", "trafo"))
F["overloads"] = {"grown_elements_over_100": len(grown_over), "planning_breach_elements": len(plan_over),
                  "in_both": sorted(f"{k} {i}" for k, i in grown_over & plan_over),
                  "planning_only": sorted(f"{k} {i}" for k, i in plan_over - grown_over),
                  "grown_only": sorted(f"{k} {i}" for k, i in grown_over - plan_over)}
F["top"] = E.head(15)[["kind", "id", "name", "label", "peak_pct", "peak_at", "h80", "h90", "h100", "over_months", "over_hours", "plan_envelope_pct", "plan_breach_cases"]].to_dict("records")

# voltage: hours outside the statutory band per busbar (Spilsby 11 kV apart: its reactive input is unreliable)
vmin, vmax = network.voltage_limits(net)
unrel = {88}
vv = vm[[b for b in vm.columns if int(b) not in unrel]]
out_band = (vv < vmin.reindex(vv.columns).to_numpy()) | (vv > vmax.reindex(vv.columns).to_numpy())
plan_v = sorted({e for (t, e, c, v) in breaches if t == "voltage"})
F["voltage"] = {"min_pu": round(float(vv.min().min()), 4), "min_at": [str(B.at[int(vv.min().idxmin()), "name"]), str(T[int(vv.min(axis=1).idxmin())])],
                "max_pu": round(float(vv.max().max()), 4),
                "hours_outside_by_bus": {f"{int(b)} {B.at[int(b), 'name']}": float(out_band[b].sum() / 2) for b in vv.columns if out_band[b].any()},
                "planning_voltage_breach_buses": [f"{b} {B.at[b, 'name']}" for b in plan_v],
                "planning_only_buses": [f"{b} {B.at[b, 'name']}" for b in plan_v if b not in vv.columns or not out_band[b].any()]}

# firm capacity: hours above firm per substation, the MVA through its transformers (each unit's loading x rating)
cl = {int(b): int(b) for b in B.index}
for k, m in meta["notes"]["multi_bus_clusters"].items():
    for b in m:
        cl[int(b)] = int(k)
firm = []
for (region, f_mva), grp in net.load[net.load.firm_mva.fillna(0) > 0].groupby(["region", "firm_mva"]):
    bs = {cl.get(int(b), int(b)) for b in grp.bus}
    site = [int(x) for x in B.index if cl.get(int(x), int(x)) in bs]
    tr = [int(i) for i in TR.index if int(TR.at[i, "lv_bus"]) in site and float(B.at[int(TR.at[i, "hv_bus"]), "vn_kv"]) < 132]
    if not tr or set(site) & unrel:
        continue
    mva = (tpct[tr] / 100 * TR.loc[tr, "sn_mva"].to_numpy()).sum(axis=1)
    firm.append(dict(substation=region, firm_mva=float(f_mva), peak_mva=round(float(mva.max()), 2), at=str(T[int(mva.idxmax())]),
                     hours_above_firm=float((mva > f_mva).sum() / 2)))
F["firm_capacity"] = sorted(firm, key=lambda r: -r["hours_above_firm"])

# the GSP through the year, with Ash Farm (2025) at Gorse Lane's per-unit 2024 shape x 48.38 MW
bmw = pd.DataFrame(z["branch_mw"], columns=list(z["branch_cols"]))
def _out_of_gorse(col: str) -> pd.Series:
    """A Gorse Lane feeder's export, whichever way NGED lists it (2025 lists it Sleaford -> Gorse Lane)."""
    f, t, *rest = col.split("_")
    return bmw[col] if col in bmw else -bmw["_".join([t, f, *rest])]


gorse = (_out_of_gorse("476901_427904_0_L1") + _out_of_gorse("476902_427916_0_L1")).clip(lower=0) / 38.39
ash = 48.38255 * gorse
export = (-p_ext + ash)
limit = float(net["gsp_export_limit_mw"])
F["gsp"] = {"export_max_mw": round(float(export.max()), 1), "export_max_at": str(T[int(export.idxmax())]),
            "import_max_mw": round(float((-export).max()), 1), "import_max_at": str(T[int((-export).idxmax())]),
            "hours_above_export_limit": float((export > limit).sum() / 2), "export_limit_mw": limit,
            "ash_farm_peak_mw": round(float(ash.max()), 1), "ash_farm_energy_gwh": round(float(ash.sum() / 2 / 1000), 1)}
(OUT / "figures.json").write_text(json.dumps(F, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: F[k] for k in ("year", "pathway", "converged", "planning_cases", "overloads", "voltage", "gsp")}, indent=1, default=str)[:6000])
print("firm:", json.dumps(F["firm_capacity"][:8]))
print(E.head(15)[["kind", "id", "name", "label", "peak_pct", "h80", "h90", "h100", "over_months", "over_hours", "plan_envelope_pct", "plan_breach_cases"]].to_string(index=False))
