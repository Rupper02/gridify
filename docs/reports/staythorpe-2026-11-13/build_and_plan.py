"""Step 4, Stage C, item 3 and the planning cases: Staythorpe built from its snapshot with an empty exceptions record,
the 132/11 kV transformers checked against a hand calculation from their LTDS rows, and both planning cases solved
(the supply point alone, an island in normal running by NGED's own model). Writes `build_and_plan.json`.
Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/staythorpe-2026-11-13/build_and_plan.py
"""

import json
import math
import warnings
from pathlib import Path

from gridify_optimizer import network, nged
from gridify_optimizer.config import OLTC_SETPOINT_PU, OLTC_TAP_STEP_PERCENT
from gridify_optimizer.nged_points import STAYTHORPE
from gridify_optimizer.types import PlanParams
from gridify_optimizer.years import evaluate_year

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
SNAP = HERE.parents[2] / "apps" / "pipeline" / "warehouse" / "supply-points" / "staythorpe"
T = {n: json.loads((SNAP / "tables" / f"{n}.json").read_text(encoding="utf-8")) for n in nged.TABLE_NAMES}
factory = lambda: nged.build_nged_net(T, point=STAYTHORPE)  # noqa: E731
ctx = nged._ctx(T, point=STAYTHORPE)
net, nb = ctx["net"], ctx["net"]["node_bus"]
out: dict = {}
slack = int(net.ext_grid.bus.iloc[0])
out["built"] = {"buses": len(net.bus), "lines": len(net.line), "trafos": len(net.trafo), "loads": len(net.load),
                "load_mw": round(float(net.load.p_mw.sum()), 2), "sgens": len(net.sgen), "sgen_mw": round(float(net.sgen.p_mw.sum()), 2),
                "infeed": [slack, str(net.bus.at[slack, "name"])], "peak_published_mw": STAYTHORPE.peak_demand_mw}
out["assumptions"] = {a.key: {"count": a.count, "message": a.message} for a in nged.builder_assumptions(T, point=STAYTHORPE)}

# item 3: the 132/11 kV units, by hand from their LTDS rows against what the builder made
hand = []
for r in T["t2a"]:
    if (r["Operating Voltage 1"], r["Operating Voltage 2"]) != (132, 11):
        continue
    sn, r1, x1 = float(r["Nominal Rating"]), float(r["R1"]), float(r["X1"])
    z100 = math.hypot(r1, x1)
    h = {"from": r["Node 1"], "to": r["Node 2"], "sn_mva": sn, "R1_pct_100MVA": r1, "X1_pct_100MVA": x1,
         "Z_pct_100MVA": round(z100, 3), "vk_pct_on_rating": round(z100 * sn / 100, 4), "vkr_pct_on_rating": round(r1 * sn / 100, 4),
         "ratio": "132/11", "taps": [r["Min Tap"], r["Max Tap"]],
         "tap_span_pct": [r["Min Tap"] * OLTC_TAP_STEP_PERCENT, r["Max Tap"] * OLTC_TAP_STEP_PERCENT]}
    hv, lv = nb[r["Node 1"]], nb[r["Node 2"]]
    i = net.trafo[(net.trafo.hv_bus == hv) & (net.trafo.lv_bus == lv)].index
    if len(i):
        t = net.trafo.loc[i[0]]
        h["built"] = {"id": int(i[0]), "vk": round(float(t.vk_percent), 4), "vkr": round(float(t.vkr_percent), 4), "vn": [float(t.vn_hv_kv), float(t.vn_lv_kv)],
                      "tap_side": t.tap_side, "taps": [int(t.tap_min), int(t.tap_max)], "step": float(t.tap_step_percent),
                      "lv_bus": [int(lv), str(net.bus.at[lv, "name"]), float(net.bus.at[lv, "vn_kv"])]}
    hand.append(h)
out["t132_11"] = hand
vmin, vmax = network.voltage_limits(net)
out["band_11kV_buses_fed_from_132"] = {str(net.bus.at[h["built"]["lv_bus"][0], "name"]): [float(vmin[h["built"]["lv_bus"][0]]), float(vmax[h["built"]["lv_bus"][0]])]
                                       for h in hand if "built" in h}
out["tap_target_pu"] = OLTC_SETPOINT_PU

# both planning cases, 2026 on each pathway's demand; the three Staythorpe B to C circuits' loading
bc = [int(i) for i in net.line.index if {str(net.bus.at[int(net.line.at[i, "from_bus"]), "name"])[:12], str(net.bus.at[int(net.line.at[i, "to_bus"]), "name"])[:12]} == {"Staythorpe B", "Staythorpe C"}]
out["b_c_circuits"] = [[i, str(net.bus.at[int(net.line.at[i, "from_bus"]), "name"]), str(net.bus.at[int(net.line.at[i, "to_bus"]), "name"]),
                        round(float(net.line.at[i, "max_i_ka"]) * 1000, 0)] for i in bc]
plans = {}
for year in range(2026, 2036):
    y = evaluate_year(year, [], PlanParams(scenario="ht"), net_factory=factory)
    plans[year] = {"converged": y.converged, "worst_line": round(y.worst_line_loading_pct, 1), "worst_trafo": round(y.worst_trafo_loading_pct, 1),
                   "vm": [round(y.min_vm_pu, 4), round(y.max_vm_pu, 4)], "gsp_export": y.gsp_export_mw, "gsp_import": y.gsp_import_mw,
                   "breaches": [(v.type, v.element_id, v.case, v.value, v.limit) for v in y.violations],
                   "b_c_loading_pct": {i: round(y.line_loading.get(i, float("nan")), 1) for i in bc},
                   "trafo": {int(k): v for k, v in y.trafo_loading.items()},
                   "b_c_case": {c: [i for i in bc if i in d.get("lines", [])] for c, d in y.envelope_case.items()}}
out["planning_cases_ht"] = plans
# each case separately for 2026, so the B to C loading is reported per case
cases = {}
for spec in network.CASE_SPECS:
    n = network.plan_net(factory, PlanParams(scenario="ht"), 2026)
    res = network._run_case(n, spec.name, *[s for c, *s in network._study_cases(n) if c == spec.name][0])
    if res is None:
        cases[spec.name] = "did not converge"
        continue
    lp = res["line_pct"]
    cases[spec.name] = {"b_c_loading_pct": {i: round(float(lp.get(i)), 1) for i in bc}, "gsp_import_mw": round(float(res["p_ext_mw"]), 1),
                        "worst_line": [int(lp.idxmax()), round(float(lp.max()), 1)], "vm": [round(float(res["vm"].min()), 4), round(float(res["vm"].max()), 4)]}
out["cases_2026_ht"] = cases
# Tuxford and Westborough: the DFES growth the build applies beside the LTDS's own five-year forecast
fc = {}
for name in ("Tuxford", "Westborough"):
    row = next(r for r in T["demand"] if r["Primary Substation"] == name)
    cur = float(row["Current Year Max Demand"])
    ld = net.load[net.load.name == name]
    curves = ld.growth_curves.iloc[0]
    tr = [int(i) for i in net.trafo.index if str(net.bus.at[int(net.trafo.at[i, "lv_bus"]), "name"]).startswith(name)]
    fc[name] = {"ltds_current_mw": cur, "firm_mva": row["Firm Capacity of Substation"], "trafo_mva": [float(net.trafo.at[i, "sn_mva"]) for i in tr],
                "ltds_forecast_mw": {2025 + k: float(row[f"Forecast Year {k}"]) for k in range(1, 6)},
                "ltds_ratio_2030": round(float(row["Forecast Year 5"]) / cur, 3),
                "dfes_ht_ratio": {y: curves.get("ht", {}).get(y) for y in (2025, 2026, 2030, 2035)},
                "dfes_ht_2030_over_2025": round(curves["ht"][2030] / curves["ht"][2025], 3) if "ht" in curves else None,
                "plan_trafo_loading_pct": {y: [round(plans[y].get("trafo", {}).get(i, float("nan")), 1) for i in tr] for y in plans}}
out["tuxford_westborough"] = fc
(HERE / "build_and_plan.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(json.dumps(out, indent=1, default=str))
