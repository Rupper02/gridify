"""Step 4, Stage C, decision 2: an experiment, changing nothing in the engine. LTDS circuits with code "L0" (resistance 0,
reactance 0.01% or 0, winter rating "0") are read as connectors for the run only: the tables passed to the builder carry
them with no impedance ("-"), which the builder already merges as one bus. The 2025 measured year is rerun at a supply
point and judged by the same rules (`rules.evaluate`) as the year as built. Elements are matched across the two runs by
NGED's branch columns, which merging does not renumber. Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/staythorpe-2026-11-13/l0_experiment.py <bicker|staythorpe> run
    cd packages/optimizer && uv run python ../../docs/reports/staythorpe-2026-11-13/l0_experiment.py <bicker|staythorpe> eval
"""

import copy
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from gridify_optimizer import nged
from gridify_optimizer.nged_points import BICKER_FEN, STAYTHORPE
from gridify_optimizer.sources import NgedSource
from gridify_optimizer.timeseries import run_year

from rules import evaluate

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
WH = HERE.parents[2] / "apps" / "pipeline" / "warehouse"
which, mode = sys.argv[1], sys.argv[2]
if which == "bicker":
    P, T = BICKER_FEN, nged.load_bundled_tables()
    flows, site = WH / "nged-flows" / "bicker-fen-2025", "BICF1"
    built_run, l0_run = WH / "nged-flows" / "measured-year-2025-screened.npz", WH / "nged-flows" / "measured-year-2025-screened-l0.npz"
else:
    SNAP = WH / "supply-points" / "staythorpe"
    P, T = STAYTHORPE, {n: json.loads((SNAP / "tables" / f"{n}.json").read_text(encoding="utf-8")) for n in nged.TABLE_NAMES}
    flows, site = SNAP / "flows-2025", "STAY1"
    built_run, l0_run = SNAP / "measured-year-2025-screened.npz", SNAP / "measured-year-2025-screened-l0.npz"

T_l0 = copy.deepcopy(T)
l0_rows = []
for r in T_l0["circuit"]:
    if str(r.get("Circuit Code")) == "L0" and str(r.get("Circuit Status")).lower() != "removed":
        l0_rows.append({k: r[k] for k in ("Node 1", "Node 2", "Operating Voltage (kV)", "R1", "X1", "Winter")})
        r["R1"], r["X1"] = "-", "-"

if mode == "run":
    print("L0 rows read as connectors:", json.dumps(l0_rows), flush=True)
    run_year(flows, l0_run, source=NgedSource(tables=T_l0, point=P), reactive="screened",
             about={"label": f"{P.gsp_name} 2025, L0 rows as connectors (experiment)", "experiment": "Work: L0 rows"})
    print("saved", l0_run, flush=True)
    sys.exit(0)

built_net = nged.build_nged_net(None if which == "bicker" else T, point=P)
l0_net = nged.build_nged_net(T_l0, point=P)
Fb, Cb = evaluate(built_run, flows, built_net, site)
Fl, Cl = evaluate(l0_run, flows, l0_net, site)
key = lambda C: C.assign(key=C.cols.str.split().str[0]).set_index("key")  # noqa: E731
J = key(Cb).join(key(Cl), lsuffix="_b", rsuffix="_l", how="outer")
lab = lambda r, s: "n/a" if pd.isna(r[f"cls{s}"]) else f"{r[f'cls{s}']}:{'pass' if r[f'ok{s}'] is True or r[f'ok{s}'] == 1.0 else 'fail' if r[f'ok{s}'] is False or r[f'ok{s}'] == 0.0 else '-'}"  # noqa: E731
changes = [dict(col=k, name=r.name_b if isinstance(r.name_b, str) else r.name_l, built=lab(r, "_b"), l0=lab(r, "_l"),
                offset_built=r.offset_mw_b, offset_l0=r.offset_mw_l) for k, r in J.iterrows() if lab(r, "_b") != lab(r, "_l")]


def sharing(run, cols):
    z = np.load(run)
    meta = json.loads(str(z["meta"]))
    bmw = pd.DataFrame(z["branch_mw"], columns=list(z["branch_cols"]))
    lp = pd.DataFrame(z["line_p_mw"], columns=z["line_ids"])
    out = {}
    for c in cols:
        m = meta["branch_map"].get(c)
        eng = (lp[m["ids"]].sum(axis=1) * m["sign"]).mean() if m and m["kind"] == "line" else None
        out[c] = {"nged_mean": round(float(bmw[c].mean()), 2), "engine_mean": None if eng is None else round(float(eng), 2)}
    return out


out = {"l0_rows": l0_rows, "rules": {r: {"built": Fb[r], "l0": Fl[r]} for r in ("radial_rule", "rule1", "rule2", "rule3", "input_check")},
       "label_changes": changes}
if which == "staythorpe":
    twin = ["348709_490429_0_L1", "348711_490431_0_L1", "490309_490427_0_L1"]
    out["b_c_sharing"] = {"built": sharing(built_run, twin), "l0": sharing(l0_run, twin)}
else:
    cluster = [c for c in Cb.cols if any(t in Cb.set_index("cols").at[c, "name"] for t in ("Sleaford", "Grantham", "Cranwell", "Leadenham", "Tattershall"))]
    sub = J.loc[[c.split()[0] for c in cluster if c.split()[0] in J.index]]
    out["sleaford_grantham_cluster"] = sub[["name_b", "cls_b", "offset_mw_b", "offset_mw_l", "ok_b", "ok_l"]].reset_index().to_dict("records")
(HERE / f"l0_experiment_{which}.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: out[k] for k in ("l0_rows", "rules")}, indent=1, default=str))
print("label changes:", len(changes))
for c in changes:
    print("  ", c)
if which == "staythorpe":
    print("B-C sharing:", json.dumps(out["b_c_sharing"]))
