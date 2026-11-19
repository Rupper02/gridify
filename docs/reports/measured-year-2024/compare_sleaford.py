"""Work 16a: the Sleaford impedance experiment against the year as built, by the same rules (`analyse.py` on both runs).
Writes `<experiment folder>/compare.json`. Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/measured-year-2024/compare_sleaford.py <year>
"""

import collections
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
YEAR = int(sys.argv[1])
BUILT = HERE / ("screened" if YEAR == 2024 else f"screened-{YEAR}")
EXP = HERE / f"screened-{YEAR}-sleaford-vk"
F = {k: json.loads((p / "figures.json").read_text(encoding="utf-8")) for k, p in (("built", BUILT), ("experiment", EXP))}
E = {k: pd.read_csv(p / "elements.csv").set_index(["kind", "id"]) for k, p in (("built", BUILT), ("experiment", EXP))}
TIES = {"Sleaford to Skegness (via Tattershall, Woodhall Spa, Horncastle)": [110, 114, 119, 121, 126, 96, 95, 98, 63],
        "Sleaford to Grantham (via North Rauceby, Cranwell, Leadenham, Mill Farm)": [111, 100, 89, 40, 36]}
short = lambda l: "agrees" if str(l).startswith("flow agrees") else "differs" if l == "flow differs" else str(l)  # noqa: E731
out = {"rules": {k: {r: F[k][r] for r in ("rule1", "rule2", "rule3", "rule4")} for k in F}}
j = E["built"].join(E["experiment"], lsuffix="_b", rsuffix="_x")
trans = collections.Counter((short(a), short(b)) for a, b in zip(j.label_b, j.label_x))
out["label_transitions"] = {f"{a} -> {b}": n for (a, b), n in trans.items()}
out["differs_to_agrees"] = [f"{k} {i} {r.name_b}" for (k, i), r in j.iterrows() if short(r.label_b) == "differs" and short(r.label_x) == "agrees"]
out["still_differs"] = [dict(el=f"{k} {i}", name=r.name_b, offset_built=r.offset_mw_b, offset_experiment=r.offset_mw_x)
                        for (k, i), r in j.iterrows() if short(r.label_b) == "differs" and short(r.label_x) == "differs"]
out["agrees_to_differs"] = [dict(el=f"{k} {i}", name=r.name_b, offset_experiment=r.offset_mw_x)
                            for (k, i), r in j.iterrows() if short(r.label_b) == "agrees" and short(r.label_x) == "differs"]
out["bsp_pair_offsets"] = {k: {b: v["pair_offset_132_to_33_mw"] for b, v in F[k]["bsp_transformer_offsets"].items()} for k in F}
out["ties"] = {t: {f"line {i}": [None if pd.isna(j.loc[("line", i), c]) else float(j.loc[("line", i), c]) for c in ("offset_mw_b", "offset_mw_x")]
                   + [short(j.loc[("line", i), "label_b"]), short(j.loc[("line", i), "label_x"])] for i in ids} for t, ids in TIES.items()}
out["sleaford_gts"] = {f"trafo {i}": {c: (None if pd.isna(j.loc[("trafo", i), c]) else j.loc[("trafo", i), c]) for c in
                                      ("label_b", "label_x", "offset_mw_b", "offset_mw_x", "peak_pct_b", "peak_pct_x")} for i in (29, 30)}
(EXP / "compare.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(json.dumps(out, indent=1, default=str))
