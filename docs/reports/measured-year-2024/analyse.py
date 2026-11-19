"""The measured year 2024: every figure in the report, recomputed from the saved results file.

    cd packages/optimizer && uv run python ../../docs/reports/measured-year-2024/analyse.py \
        ../../apps/pipeline/warehouse/nged-flows/measured-year-2024.npz ../../docs/reports/measured-year-2024

Reads the run (`gridify_optimizer.timeseries`) and NGED's bus names; builds today's network for names, ratings and
the planning cases. Writes `figures.json` (every headline number) and `elements.csv` (one row per line and
transformer). The pass rule is the specification's (docs/reports/timeseries-step1-spec-2026-11-12.md), fixed before
any result. Supported by NGED Open Data.
"""

import json
import math
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import pandapower.topology as top

from gridify_optimizer import network, nged
from gridify_optimizer.config import LINE_LOADING_MAX_PCT, TRAFO_LOADING_MAX_PCT

RUN, OUT = Path(sys.argv[1]), Path(sys.argv[2]) / sys.argv[3]  # the run file, the report folder, the run's label
OUT.mkdir(parents=True, exist_ok=True)
YEAR = int(sys.argv[4]) if len(sys.argv) > 4 else 2024  # Work 12: 2025, the same rules on the second measured year
FLOWS = RUN.parent / f"bicker-fen-{YEAR}"
z = np.load(RUN)
meta = json.loads(str(z["meta"]))
T = pd.DatetimeIndex(pd.to_datetime(z["times"]))
season = pd.Series(z["season"])
conv = z["converged"]
net = network.build_base_net()
L, TR, B = net.line, net.trafo, net.bus
lp = pd.DataFrame(z["line_p_mw"], columns=z["line_ids"])
tp = pd.DataFrame(z["trafo_p_mw"], columns=z["trafo_ids"])
lpct = pd.DataFrame(z["line_pct"], columns=z["line_ids"])
tpct = pd.DataFrame(z["trafo_pct"], columns=z["trafo_ids"])
vm = pd.DataFrame(z["vm"], columns=z["bus_ids"])
bmw = pd.DataFrame(z["branch_mw"], columns=list(z["branch_cols"]))
bus_p = pd.DataFrame(z["bus_p"], columns=meta["anchor_buses"])
unpl = pd.DataFrame(z["unplaced_p"], columns=list(z["unplaced_cols"]))
p_ext = pd.Series(z["p_ext_mw"])
ratio = {s: pd.Series(z[f"line_ratio_{s}"], index=z["line_ids"]) for s in ("winter", "intermediate_cool", "intermediate_warm", "summer")}
bm = meta["branch_map"]
F: dict = {"run": sys.argv[3], "reactive": meta.get("reactive", "published"), "rows": meta["rows"], "seconds": meta["seconds"], "converged": int(conv.sum()), "half_hours": int(len(conv)),
           "inputs_per_half_hour": meta["inputs_per_half_hour"], "notes": meta["notes"]}

# ---- nodes whose reactive input is unreliable for the year: the screen flags more than 1% of the year's half-hours there
# (from the screened run's flags: the inputs are the same in every run). Their transformers, their busbars and any
# radial 33 kV circuit that feeds only them are labelled "reactive input unreliable" in every run: not findings.
UNRELIABLE_SHARE = 0.01
zs = np.load(RUN.parent / f"measured-year-{YEAR}-screened.npz")
qf_all = pd.DataFrame(zs["q_flags"], columns=json.loads(str(zs["meta"]))["anchor_buses"])
unreliable_nodes = [int(a) for a in qf_all.columns if float((qf_all[a] > 0).mean()) > UNRELIABLE_SHARE]
F["reactive_unreliable"] = {"rule": f"screen flags on more than {UNRELIABLE_SHARE:.0%} of the year's half-hours",
                            "nodes": {int(a): f"{int((qf_all[a] > 0).sum())} of {len(qf_all)}" for a in qf_all.columns if (qf_all[a] > 0).any()}}

# ---- ratings in force (MVA), per half-hour ---------------------------------------------------------------------
line_mva_winter = math.sqrt(3) * B.loc[L.from_bus, "vn_kv"].to_numpy() * L.max_i_ka.to_numpy()
line_mva_winter = pd.Series(line_mva_winter, index=L.index)
season_ratio = pd.DataFrame({s: ratio[s] for s in ratio}).T  # season x line
line_rating_t = pd.DataFrame(season_ratio.loc[season.values].to_numpy() * line_mva_winter.to_numpy(), columns=L.index)
trafo_mva = TR.sn_mva.astype(float)

# ---- the comparison sets (spec, Stage 0 (ii)) ----------------------------------------------------------------
INPUT_FEEDERS = {"42410_424101_0_L1", "425200_425202_0_L1", "427500_427502_0_L1", "427914_424200_0_L1", "429400_429402_0_L1",
                 "434500_434502_0_L1", "435401_42410_0_L1", "439300_439302_0_L1", "439600_439602_0_L1", "464601_46460_0_L1",
                 "467501_46751_0_L1", "476901_427904_0_L1", "476902_427916_0_L1", "494001_493902_0_L1"}
EXCLUDED = {"464902_439105_0_L1", "464904_439102_0_L1",  # Middlemarsh 132 kV: radial, carry only the input wind
            "475600_443409_0_G1", "475601_443411_0_G2", "429607_443408_0_L1", "443410_429609_0_L1"}  # the railway, held at 0
RAILWAY = {"475600_443409_0_G1", "475601_443411_0_G2", "429607_443408_0_L1", "443410_429609_0_L1"}
BACKBONE = {"432706_489916_0_L1", "432702_489912_0_L1", "44033_489910_0_L1", "44030_489906_0_L1", "44033_440302_0_L1",
            "44030_440305_0_L1", "429608_44033_0_L1", "429610_44030_0_L1", "461003_432705_0_L1", "461003_464900_0_L1",
            "464901_432709_0_L1", "429602_429606_0_L1", "427908_440301_0_G1", "427909_440304_0_G2", "464903_420614_0_G1",
            "464905_420615_0_G2", "429603_433910_0_G1", "433911_429604_0_G2"}
INTO_GSP = ["432706_489916_0_L1", "432702_489912_0_L1", "44033_489910_0_L1", "44030_489906_0_L1"]  # same way round in 2025


def _either_way(cols: set[str]) -> set[str]:
    """2025's file lists many branches the other way round ("to_from_..."): a set names a branch whichever way."""
    return cols | {"_".join([c.split("_")[1], c.split("_")[0], *c.split("_")[2:]]) for c in cols}


INPUT_FEEDERS, EXCLUDED, RAILWAY, BACKBONE = (_either_way(s) for s in (INPUT_FEEDERS, EXCLUDED, RAILWAY, BACKBONE))
unmapped = [c for c in bmw.columns if c not in bm]

g = top.create_nxgraph(net, multi=True, include_switches=True)  # connectors (closed bus-bus switches) join their buses
G = nx.Graph()
for u, v, k in g.edges(keys=True):
    G.add_edge(u, v, n=G[u][v]["n"] + 1 if G.has_edge(u, v) else 1)
bridges = {frozenset(e) for e in nx.bridges(G) if G[e[0]][e[1]]["n"] == 1}

groups: dict[tuple, list[str]] = {}
for c, m in bm.items():
    groups.setdefault((m["kind"], tuple(m["ids"])), []).append(c)
rows = []
for (kind, ids), cols in groups.items():
    ids = list(ids)
    tab = L if kind == "line" else TR
    a, b = ("from_bus", "to_bus") if kind == "line" else ("hv_bus", "lv_bus")
    radial = frozenset((int(tab.at[ids[0], a]), int(tab.at[ids[0], b]))) in bridges
    # engine flow in the direction of the first column's NGED from -> to; NGED's columns summed in that direction
    s0 = bm[cols[0]]["sign"]
    eng = (lp if kind == "line" else tp)[ids].sum(axis=1) * s0
    ng = sum(bmw[c] * (bm[c]["sign"] * s0) for c in cols)
    rating = line_rating_t[ids].sum(axis=1) if kind == "line" else pd.Series(float(trafo_mva[ids].sum()), index=eng.index)
    d = (eng - ng)[conv]  # statistics over the half-hours that solved (an unsolved one has no engine figure)
    eng, ng, rating = eng[conv], ng[conv], rating[conv]
    within5 = float((d.abs() <= 0.05 * rating).mean())
    big = (eng.abs() > 1) | (ng.abs() > 1)
    same_dir = float((np.sign(eng[big]) == np.sign(ng[big])).mean()) if big.any() else 1.0
    within_rad = float((d.abs() <= 0.5 + 0.02 * ng.abs()).mean())
    cls = ("connector" if kind == "line" and "connector" in L.columns and bool(L.loc[ids, "connector"].any())  # not compared
           else "input" if any(c in INPUT_FEEDERS for c in cols) else "excluded" if any(c in EXCLUDED for c in cols)
           else "backbone" if any(c in BACKBONE for c in cols) else "radial" if radial else "meshed")
    ok = (within_rad == 1.0) if cls == "radial" else (within5 >= 0.95 and same_dir >= 0.95) if cls in ("backbone", "meshed") else None
    rows.append(dict(cols=" ".join(cols), kind=kind, ids=ids, cls=cls, within5=within5, same_dir=same_dir, within_rad=within_rad, ok=ok,
                     offset_mw=float(d.median()), offset_p95_mw=float(d.abs().quantile(.95)),
                     offset_pct=float((d / rating * 100).median()), ng_max=float(ng.abs().max()), eng_max=float(eng.abs().max())))
C = pd.DataFrame(rows)
F["groups"] = C.cls.value_counts().to_dict()
bb, me, ra = C[C.cls == "backbone"], C[C.cls == "meshed"], C[C.cls == "radial"]
F["rule2"] = {"groups": len(bb), "pass": int(bb.ok.sum()), "verdict": bool(bb.ok.all())}
F["rule3"] = {"groups": len(me), "pass": int(me.ok.sum()), "share": float(me.ok.mean()), "verdict": bool(me.ok.mean() >= 0.8)}
F["rule4"] = {"groups": len(ra), "pass": int(ra.ok.sum()), "verdict": bool(ra.ok.all()), "worst_p95_mw": float(ra.offset_p95_mw.max())}
inp = C[C.cls == "input"]
F["input_feeders_check"] = {"groups": len(inp), "within_0.5+2%_every_half_hour": int((inp.within_rad == 1).sum())}

# ---- rule 1: closure, and its decomposition ---------------------------------------------------------------------
into = bmw[INTO_GSP].sum(axis=1)  # + = towards Bicker Fen (export)
gap = (p_ext + into)[conv]  # engine infeed minus NGED's four circuits (engine import + NGED export), solved half-hours
tol = np.maximum(2.0, 0.03 * into.abs())[conv]
F["unsolved"] = [str(T[i]) for i in np.where(~conv)[0]]
F["rule1"] = {"share_within": float((gap.abs() <= tol).mean()), "verdict": bool((gap.abs() <= tol).mean() >= 0.95),
              "abs_gap_p50": float(gap.abs().median()), "abs_gap_p95": float(gap.abs().quantile(.95)), "abs_gap_max": float(gap.abs().max())}
eng_losses = (p_ext - bus_p.sum(axis=1))[conv]  # what the engine imports minus what its inputs draw
held = unpl[[c for c in unpl.columns if c.startswith("held@")]].sum(axis=1)[conv]
unplaced = unpl[[c for c in unpl.columns if c.startswith("unplaced@")]].sum(axis=1)[conv]
# NGED's own balance telescopes: what its four circuits export = -(every injection it shows, placed or not) - what is left
nged_rest = (-into - bus_p.sum(axis=1))[conv] - (unplaced + held)  # NGED losses not shown at any node (0 if every loss sits at a node)
resid = gap - (eng_losses - unplaced - held - nged_rest)
q = lambda s: {k: round(float(v), 3) for k, v in s.quantile([.05, .5, .95]).items()} | {"mean": round(float(s.mean()), 3)}
F["decomposition"] = {"engine_losses": q(eng_losses), "unplaced": q(unplaced), "held_at_zero": q(held), "nged_losses_not_at_a_node": q(nged_rest),
                      "residual": q(resid), "residual_abs_p95": float(resid.abs().quantile(.95)),
                      "by_season": {s: {"gap_abs_p50": round(float(gap[sc].abs().median()), 3), "gap_abs_p95": round(float(gap[sc].abs().quantile(.95)), 3),
                                        "engine_losses_p50": round(float(eng_losses[sc].median()), 3), "unplaced_p50": round(float(unplaced[sc].median()), 3),
                                        "rule1_share": round(float((gap[sc].abs() <= tol[sc]).mean()), 3)}
                                    for s in sorted(set(season)) for sc in [(season == s)[conv]]}}
# the reading to test: unplaced at a 132 kV tee = the losses of the branches that END there (NGED's value at the from end)
ctx = nged._ctx()
busid, uf = ctx["busid"], ctx["uf"]
names = {int(r["bus_number"]): str(r["bus_name"]) for r in json.loads((FLOWS / "bus_mapping.json").read_text(encoding="utf-8"))}
def ebus(num):
    code = names.get(int(num), "")
    b = busid.get(code)
    return int(b) if b is not None and int(b) in B.index else None
cl_of = {b: b for b in B.index}
for k, members in meta["notes"]["multi_bus_clusters"].items():
    for m in members:
        cl_of[int(m)] = int(k)
tee_tests = []
for col in unpl.columns:
    if not col.startswith("unplaced@"):
        continue
    cl = int(col.split("@")[1])
    if float(unpl[col].abs().max()) < 0.5:
        continue
    to_here, from_here = [], []
    for c in bmw.columns:
        f, t = c.split("_")[:2]
        fb, tb = ebus(f), ebus(t)
        if fb is None or tb is None:
            continue
        if cl_of.get(tb) == cl and cl_of.get(fb) != cl:
            to_here.append(c)
        elif cl_of.get(fb) == cl and cl_of.get(tb) != cl:
            from_here.append(c)
    y = unpl[col]
    def r2(cols):
        if not cols:
            return None, None
        x = (bmw[cols] ** 2).sum(axis=1)
        k = float((x * y).sum() / (x * x).sum())
        return round(float(np.corrcoef(x, y)[0, 1]), 3), k
    rt, kt = r2(to_here)
    rf, kf = r2(from_here)
    # what the engine says the loss is: R of the branches ending here, P^2 R / V^2
    rv = []
    for c in to_here:
        m = bm.get(c)
        if m and m["kind"] == "line":
            i = m["ids"][0]
            rv.append(float(L.at[i, "r_ohm_per_km"] * L.at[i, "length_km"] / len(m["ids"])) / float(B.at[int(L.at[i, "from_bus"]), "vn_kv"]) ** 2)
    tee_tests.append(dict(cluster=cl, bus=str(B.at[cl, "name"]), unplaced_p50=round(float(y.median()), 3), unplaced_max=round(float(y.abs().max()), 3),
                          corr_with_flow2_of_branches_ending_here=rt, corr_with_flow2_of_branches_starting_here=rf,
                          fitted_k_ending=kt, engine_R_over_V2_ending=(round(sum(rv) / max(len(rv), 1), 6) if rv else None)))
F["tee_tests"] = tee_tests
F["unplaced_per_bus_year_mwh"] = {c: round(float(unpl[c].sum() / 2), 1) for c in unpl.columns}

# ---- closure in context ----------------------------------------------------------------------------------------
gross = (bus_p.abs().sum(axis=1) + unpl.abs().sum(axis=1))[conv]
bb_lines = [i for r in bb.itertuples() if r.kind == "line" for i in r.ids]
smallest = float(line_mva_winter[bb_lines].min() * min(float(ratio["summer"][i]) for i in bb_lines))
F["closure_context"] = {"gap_share_of_gross_p50_pct": round(float((gap.abs() / gross).median() * 100), 2),
                        "gap_share_of_gross_p95_pct": round(float((gap.abs() / gross).quantile(.95) * 100), 2),
                        "smallest_backbone_circuit_summer_mva": round(smallest, 1),
                        "gap_p95_pct_of_smallest_backbone_rating": round(float(gap.abs().quantile(.95)) / smallest * 100, 2)}

# ---- imputation flags -> BSP group --------------------------------------------------------------------------------
tables = nged.load_bundled_tables()
code_bsp = {}
for d in nged.live_demand_rows(tables["demand"]):
    for n in nged._demand_nodes(d):
        code_bsp[n] = nged._bsp_base(str(d.get("BSP Group") or "").strip())
node_cols = list(z["node_cols"])
flags = pd.DataFrame(z["node_flags"], columns=node_cols)
node_grp = {}
for c in node_cols:
    nm = names.get(int(c[3:]), "")
    node_grp[c] = ("ANY" if nm.startswith("BICF") else {"SKEG3": "Skegness", "SLEA3": "Sleaford", "GRTH3": "Grantham"}.get(nm[:5], code_bsp.get(nm, "ANY")))
grp_flag = {g_: flags[[c for c in node_cols if node_grp[c] == g_]].any(axis=1) for g_ in set(node_grp.values())}
any_flag = flags.any(axis=1)
F["flags"] = {"half_hours_flagged_any": int(any_flag.sum()), "by_group": {k: int(v.sum()) for k, v in grp_flag.items()},
              "per_node": {c: int(flags[c].sum()) for c in node_cols if flags[c].any()}}
# an element's BSP group: the LTDS circuit rows' BSP Group, by the engine buses they join; transformers by their LV bus
bus_grp: dict[int, str] = {}
for c in tables["circuit"]:
    if str(c.get("Circuit Status") or "").lower() == "removed":
        continue
    for n in (c["Node 1"], c["Node 2"]):
        b = busid.get(n)
        if b is not None:
            bus_grp.setdefault(int(b), nged._bsp_base(str(c.get("BSP Group") or "").strip()))
def elem_grp(a, b):
    if float(B.at[a, "vn_kv"]) >= 132 and float(B.at[b, "vn_kv"]) >= 132:
        return "ANY"
    gg = bus_grp.get(b) or bus_grp.get(a) or "ANY"
    return gg if gg in grp_flag else "ANY"

# ---- the planning cases (today's network, as built) ------------------------------------------------------------------
plan = {}
pn = network.build_base_net()
for spec in network.CASE_SPECS:
    ls, rr = network._column(pn.load, spec.load_column), network._column(pn.line, spec.rating_column)
    r = network._run_case(pn, spec.name, ls, rr)
    plan[spec.name] = r

# ---- utilisation per element, with the validation label -------------------------------------------------------------
elem_label = {}
for r in C.itertuples():
    for i in r.ids:
        railway = any(c in RAILWAY for c in r.cols.split())
        lab = ("not compared (railway input held at 0)" if railway else
               "input: carries NGED's own flow by construction" if r.cls in ("input", "excluded") else
               "flow agrees with NGED's model" if r.ok else "flow differs")
        elem_label[(r.kind, i)] = (lab, r.offset_mw, r.offset_pct, r.cls)
summer_scale = pd.DataFrame({i: (season_ratio.loc[season.values, i].to_numpy() / float(ratio["summer"][i])) for i in L.index})
E = []
cl_members = {}
for b, c in cl_of.items():
    cl_members.setdefault(c, set()).add(int(b))
unrel_buses = set().union(*[cl_members.get(cl_of.get(a, a), {a}) for a in unreliable_nodes]) if unreliable_nodes else set()
unrel_elems = {("trafo", int(i)) for i in TR.index if int(TR.at[i, "lv_bus"]) in unrel_buses}
for i in L.index:  # a radial line whose far side holds nothing but an unreliable node's buses
    a_, b_ = int(L.at[i, "from_bus"]), int(L.at[i, "to_bus"])
    if frozenset((a_, b_)) in bridges:
        H = G.copy(); H.remove_edge(a_, b_)
        for side in nx.connected_components(H):
            if not (side & set(int(x) for x in net.ext_grid.bus)) and side <= (unrel_buses | {int(t) for t in TR.hv_bus[TR.lv_bus.isin(unrel_buses)]}) and side & unrel_buses:
                unrel_elems.add(("line", int(i)))
F["reactive_unreliable"]["elements"] = sorted(f"{k} {i}" for k, i in unrel_elems)
F["reactive_unreliable"]["buses"] = sorted(unrel_buses)
for kind, pct, tab in (("line", lpct, L), ("trafo", tpct, TR)):
    for i in tab.index:
        if kind == "line" and not bool(tab.at[i, "in_service"]):
            continue  # a line out of service (a connector, an open point) carries nothing: it is not an element with a loading
        a, b = (int(tab.at[i, "from_bus"]), int(tab.at[i, "to_bus"])) if kind == "line" else (int(tab.at[i, "hv_bus"]), int(tab.at[i, "lv_bus"]))
        x = pct[i]
        grp = elem_grp(a, b)
        keep = ~grp_flag[grp] if grp != "ANY" else ~any_flag
        xs = x * summer_scale[i] if kind == "line" else x
        lab = elem_label.get((kind, i), ("not compared (not in NGED's file)", None, None, None))
        if (kind, i) in unrel_elems:
            lab = ("reactive input unreliable",) + tuple(lab[1:])
        k = int(x.idxmax()) if x.notna().any() else 0
        E.append(dict(kind=kind, id=i, name=f"{B.at[a, 'name']} - {B.at[b, 'name']}", kv=f"{B.at[a, 'vn_kv']:g}/{B.at[b, 'vn_kv']:g}",
                      label=lab[0], offset_mw=lab[1], offset_pct_of_rating=lab[2], cls=lab[3], bsp_group=grp,
                      peak_pct=float(x.max()), peak_at=str(T[k]), h80=float((x >= 80).sum() / 2), h90=float((x >= 90).sum() / 2), h100=float((x >= 100).sum() / 2),
                      peak_pct_unflagged=float(x[keep].max()), h80_unflagged=float((x[keep] >= 80).sum() / 2), h100_unflagged=float((x[keep] >= 100).sum() / 2),
                      unflagged_half_hours=int(keep.sum()),
                      peak_pct_summer_rating=float(xs.max()), h100_summer_rating=float((xs >= 100).sum() / 2),
                      plan_winter_peak_pct=float(plan["winter_peak"]["line_pct" if kind == "line" else "trafo_pct"][i]),
                      plan_summer_min_pct=float(plan["summer_min"]["line_pct" if kind == "line" else "trafo_pct"][i])))
E = pd.DataFrame(E).sort_values("peak_pct", ascending=False)
E.to_csv(OUT / "elements.csv", index=False, float_format="%.2f")
F["utilisation"] = {"elements": len(E), "labels": E.label.value_counts().to_dict(),
                    "any_over_100": int((E.h100 > 0).sum()), "any_over_100_summer_rating": int((E.h100_summer_rating > 0).sum()),
                    "top10": E.head(10)[["kind", "id", "name", "label", "peak_pct", "peak_at", "h80", "h90", "h100", "peak_pct_summer_rating", "plan_winter_peak_pct", "plan_summer_min_pct"]].round(1).to_dict("records")}
# duration curves for the ten most loaded elements (sorted loading, every 1% of the year)
dc = {}
for r in E.head(10).itertuples():
    x = (lpct if r.kind == "line" else tpct)[r.id].sort_values(ascending=False).to_numpy()
    dc[f"{r.kind} {r.id}"] = [round(float(x[min(int(p / 100 * len(x)), len(x) - 1)]), 1) for p in range(0, 101, 5)]
F["duration_curves_pct_at_0_5_10_100pct_of_year"] = dc
# voltages
vmin, vmax = network.voltage_limits(net)
vm_unrel = vm[[b for b in vm.columns if int(b) in unrel_buses]]
F["voltage_unreliable_buses"] = {int(b): [round(float(vm_unrel[b].min()), 4), round(float(vm_unrel[b].max()), 4)] for b in vm_unrel.columns}
vm = vm[[b for b in vm.columns if int(b) not in unrel_buses]]
out_band = ((vm < vmin.reindex(vm.columns).to_numpy()) | (vm > vmax.reindex(vm.columns).to_numpy()))
F["voltage"] = {"buses_ever_outside": int(out_band.any().sum()), "hours_outside_by_bus": {int(b): float(out_band[b].sum() / 2) for b in vm.columns if out_band[b].any()},
                "min_pu": round(float(vm.min().min()), 4), "min_at": [str(B.at[int(vm.min().idxmin()), "name"]), str(T[int(vm.min(axis=1).idxmin())])],
                "max_pu": round(float(vm.max().max()), 4), "max_at": [str(B.at[int(vm.max().idxmax()), "name"]), str(T[int(vm.max(axis=1).idxmax())])]}
# the GSP: engine infeed and NGED's GSP node series (shown, not judged)
F["gsp"] = {"engine_export_max_mw": round(float(-p_ext.min()), 1), "engine_import_max_mw": round(float(p_ext.max()), 1),
            "nged_four_circuits_export_max": round(float(into.max()), 1), "nged_four_circuits_import_max": round(float(-into.min()), 1),
            "export_limit_mw": net.get("gsp_export_limit_mw")}
# firm capacity context: peak flow through each primary's transformers (MVA) beside its LTDS firm capacity
bq_all = pd.DataFrame(z["bus_q"], columns=meta["anchor_buses"]) if "bus_q" in z.files else None
fc = []
for (region, firm), grp in net.load[net.load.firm_mva.fillna(0) > 0].groupby(["region", "firm_mva"]):
    bs = set(int(b) for b in grp.bus)
    if bs & unrel_buses:
        continue  # reactive input unreliable: left out of the firm-capacity context
    cl = {c for b in bs for c in [cl_of.get(b, b)]}
    members = {b for b in B.index if cl_of.get(int(b), int(b)) in cl}
    tr = [int(i) for i in TR.index if int(TR.at[i, "lv_bus"]) in members]
    if not tr:
        continue
    mva = (tpct[tr] / 100 * trafo_mva[tr]).sum(axis=1)  # each transformer's MVA (its loading x its rating), summed
    k = int(mva.idxmax())
    p_hv = float(tp.loc[k, tr].sum())
    fc.append(dict(primary=region, firm_mva=float(firm), installed_mva=float(trafo_mva[tr].sum()), peak_mva_2024=round(float(mva.max()), 2), at=str(T[k]),
                   peak_share_of_firm_pct=round(float(mva.max() / firm * 100), 1), peak_share_of_installed_pct=round(float(mva.max() / trafo_mva[tr].sum() * 100), 1),
                   p_mw_hv_at_peak=round(p_hv, 2), q_mvar_hv_at_peak_magnitude=round(float(math.sqrt(max(float(mva.max()) ** 2 - p_hv ** 2, 0.0))), 2),
                   per_transformer_mva_at_peak={int(i): round(float(tpct.loc[k, i] / 100 * trafo_mva[i]), 2) for i in tr},
                   hours_above_firm=float((mva > firm).sum() / 2), transformers=tr,
                   node_input_at_peak={int(x): [round(float(bus_p.loc[k, x]), 2), (round(float(bq_all.loc[k, x]), 2) if bq_all is not None else None)]
                                       for x in bus_p.columns if int(x) in members},
                   nged_mw_at_peak={c: round(float(bmw.loc[k, c]), 2) for c, m in bm.items() if m["kind"] == "trafo" and set(m["ids"]) & set(tr)},
                   engine_p_hv_mw_at_peak={int(i): round(float(tp.loc[k, i]), 2) for i in tr}))
F["firm_capacity_context"] = sorted(fc, key=lambda r: -r["peak_share_of_firm_pct"])
F["model_findings_offsets"] = C[(C.cls.isin(["backbone", "meshed", "radial"])) & (C.ok == False)].sort_values("offset_p95_mw", ascending=False)[  # noqa: E712
    ["cols", "kind", "ids", "cls", "within5", "same_dir", "offset_mw", "offset_p95_mw", "offset_pct"]].round(3).to_dict("records")
# ---- the reactive-power screen (runs that carry it) ---------------------------------------------------------------
if "q_flags" in z.files:
    qf = pd.DataFrame(z["q_flags"], columns=meta["anchor_buses"])
    F["reactive_screen"] = {"notes": meta["notes"].get("reactive"),
                            "per_node": {f"{int(a)} {B.at[int(a), 'name']}": {"implausible": int((qf[a] == 2).sum()), "suspect": int((qf[a] == 1).sum())}
                                         for a in qf.columns if (qf[a] > 0).any()}}
# ---- the BSP transformer offsets: what sits below each BSP that the two models place differently ----------------
bsp_pairs = {"Sleaford": [29, 30], "Skegness": [26, 27], "Grantham": [12, 13]}
cl_grp = {}
for col in unpl.columns:
    c = int(col.split("@")[1])
    cl_grp[col] = bus_grp.get(c, "ANY")
bo = {}
for bsp, ids in bsp_pairs.items():
    rws = C[(C.kind == "trafo") & C.ids.apply(lambda v: set(v) <= set(ids) and len(set(v) & set(ids)) > 0)]
    d = pd.Series(0.0, index=lp.index)
    for r in rws.itertuples():
        cols = r.cols.split()
        s0 = bm[cols[0]]["sign"]
        eng = tp[r.ids].sum(axis=1) * s0
        ng = sum(bmw[c] * (bm[c]["sign"] * s0) for c in cols)
        # orient both as 132 -> 33 kV: the engine's HV->LV direction
        d = d + (eng - ng) * s0
    d = d[conv]
    cands = {"unplaced in group": unpl[[c for c in unpl.columns if cl_grp[c] == bsp and c.startswith("unplaced@")]].sum(axis=1)[conv],
             "held at 0 (railway)": unpl[[c for c in unpl.columns if c.startswith("held@")]].sum(axis=1)[conv],
             "engine losses": eng_losses}
    bo[bsp] = {"pair_offset_132_to_33_mw": q(d), "corr": {k: (round(float(np.corrcoef(d, v)[0, 1]), 3) if float(v.std()) > 0 else None) for k, v in cands.items()},
               "candidate_medians_mw": {k: round(float(v.median()), 3) for k, v in cands.items()}}
F["bsp_transformer_offsets"] = bo
# ---- the unsolved half-hours and their inputs ------------------------------------------------------------------------
bq = pd.DataFrame(z["bus_q"], columns=meta["anchor_buses"]) if "bus_q" in z.files else None
F["unsolved_inputs"] = [{"at": str(T[i]), "largest_inputs": {f"{int(a)} {B.at[int(a), 'name']}": [round(float(bus_p.loc[i, a]), 2), (round(float(bq.loc[i, a]), 2) if bq is not None else None)]
                                                              for a in bus_p.loc[i].abs().sort_values(ascending=False).index[:3]}}
                        for i in np.where(~conv)[0]]
C.to_csv(OUT / "comparison.csv", index=False, float_format="%.4f")
(OUT / "figures.json").write_text(json.dumps(F, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: F[k] for k in ("converged", "half_hours", "rule1", "rule2", "rule3", "rule4", "closure_context")}, indent=1))
print("decomposition:", json.dumps(F["decomposition"], indent=1))
print("tee tests:", json.dumps(F["tee_tests"], indent=1))
print("utilisation:", json.dumps({k: F["utilisation"][k] for k in ("labels", "any_over_100", "any_over_100_summer_rating")}, indent=1))
