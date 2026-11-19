"""The commissioning rules (Bicker Fen's, docs/reports/timeseries-step1-spec-2026-11-12.md), with the classes defined
from the network instead of listed by hand, for any supply point's measured-year run: `evaluate(run, flows, net, site)`.
Used by `commission.py` (Staythorpe) and `l0_experiment.py` (both supply points). Supported by NGED Open Data."""

import json
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import pandapower.topology as top


def evaluate(run_path, flows, net, site: str) -> tuple[dict, pd.DataFrame]:
    """`site`: the NGED node-code prefix of the infeed busbar (closure is judged on the circuits out of it)."""
    z = np.load(run_path)
    meta = json.loads(str(z["meta"]))
    conv = z["converged"].astype(bool)
    L, TR, B = net.line, net.trafo, net.bus
    lp = pd.DataFrame(z["line_p_mw"], columns=z["line_ids"])
    tp = pd.DataFrame(z["trafo_p_mw"], columns=z["trafo_ids"])
    bmw = pd.DataFrame(z["branch_mw"], columns=list(z["branch_cols"]))
    p_ext = pd.Series(z["p_ext_mw"])
    bm = meta["branch_map"]
    notes = meta["notes"]
    season = list(z["season"].astype(str))
    seasons = ("winter", "intermediate_cool", "intermediate_warm", "summer")
    ratio = np.array([z[f"line_ratio_{s}"] for s in seasons])
    s_idx = np.array([seasons.index(s) for s in season])
    winter_mva = np.sqrt(3) * B.loc[L.from_bus, "vn_kv"].to_numpy() * L.max_i_ka.to_numpy()
    line_rating = pd.DataFrame(ratio[s_idx] * winter_mva, columns=z["line_ids"])
    F: dict = {"run": str(run_path), "half_hours": int(len(conv)), "solved": int(conv.sum()),
               "notes_counts": {k: (len(v) if hasattr(v, "__len__") else v) for k, v in notes.items()}}

    # clusters (what NGED's file treats as one node) and the far side of each bridge
    cl: dict[int, int] = {}
    for k, m in notes["multi_bus_clusters"].items():
        for b in m:
            cl[int(b)] = int(k)
    c_of = lambda b: cl.get(int(b), int(b))  # noqa: E731
    metered = {c_of(b) for b in notes["metered"]}
    derived = {c_of(b) for b in notes["derived"]}
    held = {int(k) for k in notes["held_at_zero"]}
    slack = {int(b) for b in net.ext_grid.bus}
    g = top.create_nxgraph(net, multi=True, include_switches=True)  # connectors (closed bus-bus switches) join their buses
    G = nx.Graph()
    for u, v, _k in g.edges(keys=True):
        G.add_edge(u, v, n=G[u][v]["n"] + 1 if G.has_edge(u, v) else 1)


    def far_side(a: int, b: int):
        if G[a][b]["n"] > 1:
            return None
        H = G.copy()
        H.remove_edge(a, b)
        if nx.has_path(H, a, b):
            return None
        side = nx.node_connected_component(H, b)
        return set(nx.node_connected_component(H, a)) if side & slack else set(side)


    groups: dict[tuple, list[str]] = {}
    for c, m in bm.items():
        groups.setdefault((m["kind"], tuple(m["ids"])), []).append(c)
    rows = []
    for (kind, ids), cols in groups.items():
        ids = list(ids)
        tab = L if kind == "line" else TR
        a, b = (int(tab.at[ids[0], "from_bus"]), int(tab.at[ids[0], "to_bus"])) if kind == "line" else (int(tab.at[ids[0], "hv_bus"]), int(tab.at[ids[0], "lv_bus"]))
        is_open = kind == "line" and not bool(tab.loc[ids, "in_service"].all())  # a circuit run open (SupplyPoint.normally_open)
        side = None if is_open else far_side(a, b)
        s0 = bm[cols[0]]["sign"]
        eng = (lp if kind == "line" else tp)[ids].sum(axis=1) * s0
        ng = sum(bmw[c] * (bm[c]["sign"] * s0) for c in cols)
        rating = line_rating[ids].sum(axis=1) if kind == "line" else pd.Series(float(TR.loc[ids, "sn_mva"].sum()), index=eng.index)
        d = (eng - ng)[conv]
        eng, ng, rating = eng[conv], ng[conv], rating[conv]
        within5 = float((d.abs() <= 0.05 * rating).mean())
        big = (eng.abs() > 1) | (ng.abs() > 1)
        same_dir = float((np.sign(eng[big]) == np.sign(ng[big])).mean()) if big.any() else 1.0
        within_rad = float((d.abs() <= 0.5 + 0.02 * ng.abs()).mean())
        clusters = {c_of(x) for x in side} if side is not None else set()
        hv = max(float(B.at[a, "vn_kv"]), float(B.at[b, "vn_kv"]))
        if kind == "line" and "connector" in tab.columns and bool(tab.loc[ids, "connector"].any()):
            cls = "connector"  # a connector (closed switch): not compared; files mapped before the mapper skipped them
        elif is_open:
            cls = "open"
        elif side is not None and clusters & held:
            cls = "excluded"
        elif side is not None and not (clusters & metered) and clusters & derived:
            cls = "input"
        elif hv >= 132:
            cls = "backbone"
        elif side is not None:
            cls = "radial"
        else:
            cls = "meshed"
        ok = (within_rad == 1.0) if cls in ("radial", "input", "open") else (within5 >= 0.95 and same_dir >= 0.95) if cls in ("backbone", "meshed") else None
        name = (f"{B.at[a, 'name']} - {B.at[b, 'name']}")
        rows.append(dict(cols=" ".join(cols), kind=kind, ids=" ".join(map(str, ids)), name=name, cls=cls, kv=hv, within5=round(within5, 4),
                         same_dir=round(same_dir, 4), within_rad=round(within_rad, 4), ok=ok, offset_mw=round(float(d.median()), 3),
                         offset_p95_mw=round(float(d.abs().quantile(.95)), 3), ng_max=round(float(ng.abs().max()), 2), eng_max=round(float(eng.abs().max()), 2)))
    C = pd.DataFrame(rows)
    F["groups"] = C.cls.value_counts().to_dict()
    ra, bb, me, inp = (C[C.cls == k] for k in ("radial", "backbone", "meshed", "input"))
    F["radial_rule"] = {"groups": len(ra), "pass": int(ra.ok.sum()), "verdict": bool(ra.ok.all()) if len(ra) else None,
                        "fail": ra[~ra.ok.astype(bool)][["name", "within_rad", "offset_mw", "offset_p95_mw", "ng_max", "eng_max"]].to_dict("records")}
    F["input_check"] = {"groups": len(inp), "within_0.5+2%_every_half_hour": int((inp.within_rad == 1).sum()),
                        "fail": inp[inp.within_rad < 1][["name", "within_rad", "offset_p95_mw"]].to_dict("records")}

    # rule 1: closure on the five circuits out of Staythorpe C's busbar (+ = into the busbar, i.e. NGED's export)
    nm = {}
    for r in json.loads((Path(flows) / "bus_mapping.json").read_text(encoding="utf-8")):
        nm[int(r["bus_number"])] = r["bus_name"]
    into_cols = []
    for c in bmw.columns:
        f, t = (int(x) for x in c.split("_")[:2])
        nf, nt = nm.get(f, ""), nm.get(t, "")
        if c.split("_")[-1].startswith("S"):
            continue
        if nt.startswith(site) and not nf.startswith(site):
            into_cols.append((c, +1))
        elif nf.startswith(site) and not nt.startswith(site):
            into_cols.append((c, -1))
    into = sum(bmw[c] * s for c, s in into_cols)
    F["closure_reference"] = [[c, nm.get(int(c.split("_")[0])), nm.get(int(c.split("_")[1])), s] for c, s in into_cols]
    gap = (p_ext + into)[conv]
    tol = np.maximum(2.0, 0.03 * into.abs())[conv]
    F["rule1"] = {"share_within": round(float((gap.abs() <= tol).mean()), 4), "verdict": bool((gap.abs() <= tol).mean() >= 0.95),
                  "abs_gap_p50": round(float(gap.abs().median()), 3), "abs_gap_p95": round(float(gap.abs().quantile(.95)), 3),
                  "abs_gap_max": round(float(gap.abs().max()), 3), "gap_median_signed": round(float(gap.median()), 3)}
    F["nged_import"] = {"max": round(float(-into.max()), 1), "mean": round(float(-into.mean()), 1)}  # NGED: what its circuits take out of the busbar
    F["engine_import"] = {"max": round(float(p_ext[conv].max()), 1), "mean": round(float(p_ext[conv].mean()), 1), "min": round(float(p_ext[conv].min()), 1)}
    F["rule2"] = {"groups": len(bb), "pass": int(bb.ok.sum()), "verdict": bool(bb.ok.all())}
    F["rule3"] = {"groups": len(me), "pass": int(me.ok.sum()), "share": round(float(me.ok.mean()), 4) if len(me) else None,
                  "verdict": bool(me.ok.mean() >= 0.8) if len(me) else None}
    F["backbone_fail"] = bb[~bb.ok.astype(bool)][["name", "within5", "same_dir", "offset_mw", "offset_p95_mw"]].to_dict("records")

    # what the check exposes: unmapped branches, unplaced balances, group totals, the screens
    F["unmapped_branches"] = [[c, nm.get(int(c.split("_")[0]), c.split("_")[0]), nm.get(int(c.split("_")[1]), c.split("_")[1])] for c in bmw.columns if c not in bm]
    F["unplaced_mw_max"] = notes["unplaced"]
    F["group_totals"] = notes["group_totals"]
    F["held_at_zero"] = notes["held_at_zero"]
    qf = pd.DataFrame(z["q_flags"], columns=meta["anchor_buses"])
    F["reactive_screen"] = {f"{a} {B.at[int(a), 'name']}": {"implausible": int((qf[a] == 2).sum()), "suspect": int((qf[a] == 1).sum())} for a in qf.columns if (qf[a] > 0).any()}
    nf = pd.DataFrame(z["node_flags"], columns=list(z["node_cols"]))
    F["identical_runs"] = {c: int(nf[c].sum()) for c in nf.columns if nf[c].any()}
    F["metered_nodes"], F["derived_nodes"] = len(notes["metered"]), len(notes["derived"])

    return F, C
