"""Work 6b: one branch's year beside main's, both 2030 Holistic Transition grown.

    cd packages/optimizer && uv run python ../../docs/reports/grown-year-2026-11-13/compare_branch.py <variant>

Reads `2030-ht/` and `2030-ht-<variant>/` (run `analyse.py` on both first) and the two run files. Prints and writes
`2030-ht-<variant>/branch.json`:
- every element whose hours above rating change, before and after, with the planning cases' figure with the branch;
- the MVAh above rating on the worst element: a crude first indication of the export that would have to be held back
  (the overload is MVA on one branch, not MW at the project; curtailing one project shifts the others' flows; one
  weather year);
- busbar voltage, firm capacity and the GSP exchange.
Supported by NGED Open Data.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gridify_optimizer import network

VARIANT = sys.argv[1]
HERE = Path(__file__).resolve().parent
W = Path("../../apps/pipeline/warehouse/nged-flows")
A, B = HERE / "2030-ht", HERE / f"2030-ht-{VARIANT}"
ea, eb = (pd.read_csv(d / "elements.csv").set_index(["kind", "id"]) for d in (A, B))
fa, fb = (json.loads((d / "figures.json").read_text(encoding="utf-8")) for d in (A, B))
z = np.load(W / f"grown-2030-ht-{VARIANT}.npz")
meta = json.loads(str(z["meta"]))
net = network.build_base_net()
out = {"variant": VARIANT, "connections": meta["connections"], "in_service": meta["in_service"],
       "voltage_control_at_unity": meta["voltage_control_at_unity"]}
cp = z["conn_p_mw"]
out["connection_output"] = {"peak_mw": round(float(cp.max()), 1), "min_mw": round(float(cp.min()), 1),
                            "energy_gwh": round(float(cp.sum() / 2 / 1000), 1)}
for c in meta["connections"]:
    if int(c["bus_id"]) == int(net.ext_grid.bus.iloc[0]):
        out.setdefault("on_slack", []).append(f"{c['request_id']}: moves only the GSP exchange and loads no circuit in this model")

# elements whose hours above rating change; the planning cases' figure is with the branch (analyse.py)
d = eb[["name", "label", "peak_pct", "peak_at", "h90", "h100", "plan_envelope_pct", "plan_breach_cases"]].join(
    ea[["peak_pct", "h90", "h100", "plan_envelope_pct"]], rsuffix="_main")
d["d_h100"] = d.h100 - d.h100_main
changed = d[(d.d_h100 != 0) | ((d.peak_pct - d.peak_pct_main).abs() > 5)].sort_values(["d_h100", "peak_pct"], ascending=False)
out["changed"] = changed.reset_index().to_dict("records")

# MVAh above rating on the worst element (most hours above rating with the branch)
season = z["season"].astype(str)
kind, i = changed.index[0] if len(changed) else (None, None)
if kind is not None:
    if kind == "line":
        pct = z["line_pct"][:, list(z["line_ids"]).index(i)]
        ln = net.line.loc[i]
        base = float(ln.max_i_ka) * float(net.bus.at[int(ln.from_bus), "vn_kv"]) * np.sqrt(3) * float(ln.get("parallel", 1) or 1)
        rating = base * np.array([z[f"line_ratio_{s}"][list(z["line_ids"]).index(i)] for s in season])
    else:
        pct = z["trafo_pct"][:, list(z["trafo_ids"]).index(i)]
        rating = np.full(len(pct), float(net.trafo.at[i, "sn_mva"]))
    over = np.clip(np.nan_to_num(pct) - 100.0, 0, None) / 100.0 * rating
    out["worst"] = {"element": f"{kind} {i} {changed.loc[(kind, i), 'name']}", "hours_above_rating": float((over > 0).sum() / 2),
                    "mvah_above_rating": round(float(over.sum() / 2), 0), "largest_mva_above": round(float(over.max()), 1),
                    "rating_mva_winter_summer": [round(float(rating.max()), 1), round(float(rating.min()), 1)]}

va, vb = fa["voltage"]["hours_outside_by_bus"], fb["voltage"]["hours_outside_by_bus"]
out["voltage"] = {"min_pu": [fa["voltage"]["min_pu"], fb["voltage"]["min_pu"]], "max_pu": [fa["voltage"]["max_pu"], fb["voltage"]["max_pu"]],
                  "changed": {k: [va.get(k, 0), vb.get(k, 0)] for k in sorted(set(va) | set(vb)) if va.get(k, 0) != vb.get(k, 0)}}
ff = {r["substation"]: r["hours_above_firm"] for r in fa["firm_capacity"]}
out["firm_changed"] = {r["substation"]: [ff.get(r["substation"], 0), r["hours_above_firm"]] for r in fb["firm_capacity"]
                       if r["hours_above_firm"] != ff.get(r["substation"], 0)}
out["gsp"] = {k: [fa["gsp"][k], fb["gsp"][k]] for k in ("export_max_mw", "export_max_at", "import_max_mw", "hours_above_export_limit")}
out["planning_cases_with_branch"] = {"breaches": fb["planning_cases"]["breaches"], "list": fb["planning_cases"]["list"]}
(B / "branch.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
with pd.option_context("display.width", 250, "display.max_columns", 20, "display.max_colwidth", 55):
    print(changed[["name", "label", "peak_pct_main", "peak_pct", "h100_main", "h100", "plan_envelope_pct_main", "plan_envelope_pct", "plan_breach_cases"]].head(25).to_string())
print(json.dumps({k: v for k, v in out.items() if k != "changed"}, indent=1, default=str))
