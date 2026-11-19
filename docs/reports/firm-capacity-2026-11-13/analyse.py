"""Each primary and BSP against its own peak and firm capacity, plan year by plan year. Reads the engine's build and
growth curves (nothing in the engine changes) and, for 2024, NGED's metered node series and the screened run.

    cd packages/optimizer && uv run python ../../docs/reports/firm-capacity-2026-11-13/analyse.py \
        ../../apps/pipeline/warehouse/nged-flows ../../docs/reports/firm-capacity-2026-11-13

Writes `substations.csv` (one row per LTDS demand group with a published firm capacity, and per BSP) and `figures.json`.
Supported by NGED Open Data.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gridify_optimizer import nged, network
from gridify_optimizer.config import FORECASTS, LTDS_FORECAST_FIRST_YEAR, PLAN_YEARS

FLOWS, OUT = Path(sys.argv[1]), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
ctx = nged._ctx()
net = ctx["net"]
busid, uf = ctx["busid"], ctx["uf"]
rows = nged.live_demand_rows(nged.load_bundled_tables()["demand"])
agg = nged._bsp_aggregates(rows)
YEARS = list(PLAN_YEARS)
PATHS = [f for f in FORECASTS]  # every selectable DFES pathway
pf = lambda d: nged._pf(d)  # noqa: E731  the LTDS power factor (0.95 lagging where blank, as the engine)


def bus_of(code):
    b = busid.get(code)
    return int(b) if b is not None and int(b) in net.bus.index else None


# engine bus clusters joined by in-substation links NGED treats as one node (from the screened run's meta)
zs = np.load(FLOWS / "measured-year-2024-screened.npz")
meta = json.loads(str(zs["meta"]))
cl = {int(b): int(b) for b in net.bus.index}
for k, m in meta["notes"]["multi_bus_clusters"].items():
    for b in m:
        cl[int(b)] = int(k)
members = lambda b: [x for x in net.bus.index if cl.get(int(x), int(x)) == cl.get(int(b), int(b))]  # noqa: E731

# growth multipliers per load, per pathway and year, exactly as the engine applies them
mult = {fid: {y: network.per_load_growth(net, fid, y) for y in YEARS} for fid in PATHS}

# NGED's metered 2024 node series (MW, MVAr) by LTDS node code
names = {int(r["bus_number"]): str(r["bus_name"]) for r in json.loads((FLOWS / "bicker-fen-2024" / "bus_mapping.json").read_text(encoding="utf-8"))}
sub = pd.read_csv(FLOWS / "bicker-fen-2024" / "substation_load.csv")
node_series = {names[int(c[3:])]: (sub[c], sub["MVAr_" + c[3:]]) for c in sub.columns if c.startswith("MW_") and int(c[3:]) in names}
UNRELIABLE_Q = {"SPIL5_MAIN1": "NGED's reactive power is unreliable here (report 4.1): 2024 MVA shown from MW alone, a lower bound"}
CAVEAT = {"Spilsby": "reactive input unreliable in NGED's 2024 series",
          "Wrangle (T2)": "NGED's 2024 series peaks at 2x its LTDS maximum and reads 0 from 1 August (report 4.2)"}

tp = pd.DataFrame(zs["trafo_pct"], columns=zs["trafo_ids"])
gen_mw = net.sgen.groupby("bus")["p_rated_mw"].sum()


def assess(label, bsp, nodes, own_mw, pf_, firm, ltds_fc, load_mask, kind):
    buses = sorted({cl.get(b, b) for b in (bus_of(n) for n in nodes) if b is not None})
    site = sorted({int(x) for b in buses for x in members(b)})
    trafos = [int(i) for i in net.trafo.index if int(net.trafo.at[i, "lv_bus"]) in site]
    installed = float(net.trafo.loc[trafos, "sn_mva"].sum()) if trafos else None
    gen = float(sum(gen_mw.get(b, 0.0) for b in site))
    own_mva = own_mw / pf_
    r = {"kind": kind, "substation": label, "bsp": bsp, "nodes": ",".join(nodes), "firm_mva": firm, "installed_mva_site": installed,
         "own_max_mw": round(own_mw, 2), "pf": pf_, "own_max_mva": round(own_mva, 2), "generation_behind_mw": round(gen, 2),
         "caveat": CAVEAT.get(label, "")}
    for fid in PATHS:
        m = {y: float(mult[fid][y][load_mask].mean()) if load_mask.any() else 1.0 for y in YEARS}
        first = next((y for y in YEARS if own_mva * m[y] > firm), None)
        first_inst = next((y for y in YEARS if installed and own_mva * m[y] > installed), None)
        r[f"{fid}_first_above_firm"] = ("now" if own_mva > firm else first)
        r[f"{fid}_first_above_installed"] = ("now" if installed and own_mva > installed else first_inst)
        for y in (2026, 2030, 2035):
            r[f"{fid}_{y}_mva"] = round(own_mva * m[y], 2)
    for k, y in enumerate(range(LTDS_FORECAST_FIRST_YEAR, LTDS_FORECAST_FIRST_YEAR + 5)):
        r[f"ltds_{y}_mva"] = round(ltds_fc[k] / pf_, 2) if ltds_fc[k] is not None else None
    r["ltds_first_above_firm"] = next((LTDS_FORECAST_FIRST_YEAR + k for k, v in enumerate(ltds_fc) if v is not None and v / pf_ > firm), None)
    # 2024: NGED's metered series at the row's node(s) (net of any generation behind it)
    ser = [node_series[n] for n in nodes if n in node_series]
    if ser and kind != "bsp":
        P = sum(s[0] for s in ser); Q = sum(s[1] for s in ser)
        if kind == "bsp":
            ser = []  # a BSP's node columns are group totals (report 3), not its transformers' load: run B is used instead
        cap = installed or 0.0
        bad = ((np.hypot(P, Q) > 1.5 * cap) if cap else False) | ((Q.abs() > 2 * P.abs()) & (Q.abs() > 2))
        Q = Q.where(~bad, P * np.tan(np.arccos(pf_)))  # the reactive screen, as run B applies it
        S = P.abs() if any(n in UNRELIABLE_Q for n in nodes) else np.hypot(P, Q)
        r["metered_2024_peak_mva"] = round(float(S.max()), 2)
        r["metered_2024_peak_at"] = str(pd.to_datetime(sub.iloc[int(S.idxmax()), 0]))
        r["metered_2024_hours_above_firm"] = float((S > firm).sum() / 2)
    if trafos:  # run B: MVA through the substation's transformers (each unit's loading x its rating), whole site
        mva = (tp[trafos] / 100 * net.trafo.loc[trafos, "sn_mva"].to_numpy()).sum(axis=1)
        r["runB_site_peak_mva"] = round(float(mva.max()), 2)
    return r


out = []
loads = net.load
for d in rows:
    bsp = str(d.get("BSP Group") or "").strip()
    firm = nged._num(d.get("Firm Capacity of Substation")) or 0.0
    if bsp in agg or firm <= 0:
        continue
    if str(d.get("Primary Substation") or "").strip() in ("", "-"):
        continue  # a generator's own station supply (Middlemarsh), not a substation's customers: listed in the report
    prim = str(d.get("Primary Substation") or "").strip()
    nodes = nged._demand_nodes(d)
    mask = loads.bus.isin([bus_of(n) for n in nodes]) & (loads.name == d.get("Primary Substation", ""))
    fc = [nged._num(d.get(f"Forecast Year {k}")) for k in range(1, 6)]
    out.append(assess(prim, bsp, nodes, nged._num(d["Current Year Max Demand"]), pf(d), firm, fc, mask, "primary"))
# BSPs: own maximum = the sum of its GT rows (the engine's reading); growth = its primaries' DFES ratios, weighted by
# their own maxima (no DFES area covers a BSP); firm as its rows publish it
for base in sorted({nged._bsp_base(b) for b in agg}):
    gts = [d for d in rows if str(d.get("BSP Group") or "").strip() in agg and nged._bsp_base(str(d["BSP Group"]).strip()) == base]
    own = sum(nged._num(d["Current Year Max Demand"]) for d in gts)
    firm = nged._num(gts[0].get("Firm Capacity of Substation"))
    pf_ = pf(gts[0])
    fc = [sum(nged._num(d.get(f"Forecast Year {k}")) or 0 for d in gts) for k in range(1, 6)]
    mask = loads.bsp == base
    w = loads.loc[mask, "peak_mw"].astype(float)
    nodes = [n for d in gts for n in nged._demand_nodes(d)]
    r = assess(f"{base} BSP", base, nodes, own, pf_, firm, fc, pd.Series(False, index=loads.index), "bsp")
    for fid in PATHS:
        m = {y: float((mult[fid][y][mask] * w).sum() / w.sum()) for y in YEARS}
        own_mva = own / pf_
        r[f"{fid}_first_above_firm"] = "now" if own_mva > firm else next((y for y in YEARS if own_mva * m[y] > firm), None)
        inst = r["installed_mva_site"]
        r[f"{fid}_first_above_installed"] = "now" if inst and own_mva > inst else next((y for y in YEARS if inst and own_mva * m[y] > inst), None)
        for y in (2026, 2030, 2035):
            r[f"{fid}_{y}_mva"] = round(own_mva * m[y], 2)
    # 2024 for a BSP: the group total through its 132/33 kV pair in run B (metered BSP columns are group totals too)
    gt = [int(i) for i in net.trafo.index if float(net.bus.at[int(net.trafo.at[i, "hv_bus"]), "vn_kv"]) >= 132
          and str(net.bus.at[int(net.trafo.at[i, "lv_bus"]), "name"]).startswith(f"{base} 33kV")]
    if gt:
        mva = (tp[gt] / 100 * net.trafo.loc[gt, "sn_mva"].to_numpy()).sum(axis=1)
        r["runB_site_peak_mva"] = round(float(mva.max()), 2)
        r["runB_hours_above_firm"] = float((mva > firm).sum() / 2)
        r["installed_mva_site"] = float(net.trafo.loc[gt, "sn_mva"].sum())
    out.append(r)

R = pd.DataFrame(out)
order = lambda v: -1 if v == "now" else (9999 if v is None or (isinstance(v, float) and np.isnan(v)) else int(v))  # noqa: E731
R["_k"] = R["ht_first_above_firm"].map(order)
R = R.sort_values(["_k", "substation"]).drop(columns="_k")
R.to_csv(OUT / "substations.csv", index=False)
labels = {fid: FORECASTS[fid]["label"] for fid in PATHS}
no_firm = sorted({str(d.get("Primary Substation")) for d in rows if str(d.get("BSP Group") or "").strip() not in agg
                  and (nged._num(d.get("Firm Capacity of Substation")) or 0) <= 0 and (nged._num(d["Current Year Max Demand"]) or 0) >= 1})
(OUT / "figures.json").write_text(json.dumps({"pathways": labels, "rows": len(R), "no_firm_published_over_1mw": no_firm}, indent=1), encoding="utf-8")
cols = ["substation", "kind", "firm_mva", "installed_mva_site", "own_max_mva"] + [f"{f}_first_above_firm" for f in PATHS] + \
       ["ltds_first_above_firm", "ht_2030_mva", "ht_2035_mva", "ltds_2030_mva", "metered_2024_peak_mva", "metered_2024_hours_above_firm", "runB_site_peak_mva", "generation_behind_mw", "caveat"]
pd.set_option("display.width", 320, "display.max_columns", 40, "display.max_colwidth", 30)
print(labels)
print(R[[c for c in cols if c in R.columns]].to_string(index=False))
print("no firm capacity published (>= 1 MW):", no_firm)
