"""Work 12: the second measured year (2025) beside 2024, from the two screened runs' analyses (`analyse.py`, the same
rules) and NGED's published files. Writes `screened-2025/compare.json`. Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/measured-year-2024/compare_2025.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
W = HERE.parents[2] / "apps" / "pipeline" / "warehouse" / "nged-flows"
Y = {2024: HERE / "screened", 2025: HERE / "screened-2025"}
F = {y: json.loads((p / "figures.json").read_text(encoding="utf-8")) for y, p in Y.items()}
E = {y: pd.read_csv(p / "elements.csv").set_index(["kind", "id"]) for y, p in Y.items()}
out: dict = {}

out["rules"] = {y: {k: F[y][k] for k in ("rule1", "rule2", "rule3", "rule4")} for y in Y}
out["labels"] = {y: E[y].label.value_counts().to_dict() for y in Y}

# analyse.py measures an offset along the first NGED column of the element's group (`branch_map` order), and 2025 lists
# many branches the other way round: put both years in the engine element's own direction (from_bus -> to_bus, hv -> lv)
def engine_sign(year: int) -> dict:
    bm = json.loads(str(np.load(W / f"measured-year-{year}-screened.npz")["meta"]))["branch_map"]
    first: dict = {}
    for c, m in bm.items():
        first.setdefault((m["kind"], int(m["ids"][0]) if len(m["ids"]) == 1 else tuple(m["ids"])), m["sign"])
    return {k: v for k, v in first.items() if not isinstance(k[1], tuple)}


SIGN = {y: engine_sign(y) for y in Y}
# elements whose flow differs from NGED's model in either year: the offset (engine - NGED, median MW) in both
both = E[2024].join(E[2025], lsuffix="_24", rsuffix="_25", how="inner")
dif = both[(both.label_24 == "flow differs") | (both.label_25 == "flow differs")]
rows = []
for (k, i), r in dif.iterrows():
    o24 = r.offset_mw_24 * SIGN[2024].get((k, int(i)), np.nan)
    o25 = r.offset_mw_25 * SIGN[2025].get((k, int(i)), np.nan)
    rows.append(dict(kind=k, id=int(i), name=r.name_24, label_2024=r.label_24, label_2025=r.label_25,
                     offset_mw_2024=o24, offset_mw_2025=o25,
                     same_sign=bool(o24 * o25 > 0) if pd.notna(o24) and pd.notna(o25) else None))
d = pd.DataFrame(rows)
out["differs"] = d.sort_values("offset_mw_2024", key=abs, ascending=False).round(2).to_dict("records")
out["differs_summary"] = {"elements": len(d), "differs_both": int(((d.label_2024 == "flow differs") & (d.label_2025 == "flow differs")).sum()),
                          "differs_2024_only": int(((d.label_2024 == "flow differs") & (d.label_2025 != "flow differs")).sum()),
                          "differs_2025_only": int(((d.label_2024 != "flow differs") & (d.label_2025 == "flow differs")).sum()),
                          "same_sign_where_both": int(d[(d.label_2024 == "flow differs") & (d.label_2025 == "flow differs")].same_sign.sum())}

# utilisation: the most loaded elements in each year, and the year-to-year move of the hours at the top
cols = ["name", "label", "peak_pct", "h80", "h90", "h100"]
out["top"] = {y: E[y].sort_values("peak_pct", ascending=False)[cols].head(12).reset_index().round(1).to_dict("records") for y in Y}
u = both[(both.h80_24 > 0) | (both.h80_25 > 0)][["name_24", "label_24", "label_25", "peak_pct_24", "peak_pct_25", "h80_24", "h80_25", "h90_24", "h90_25"]]
out["hours_80_moves"] = u.sort_values("h80_24", ascending=False).reset_index().round(1).to_dict("records")

# firm capacity, and the input screens
fc = {y: {r["primary"]: r for r in F[y]["firm_capacity_context"]} for y in Y}
out["firm"] = {p: {y: {k: fc[y].get(p, {}).get(k) for k in ("peak_mva_2024", "hours_above_firm", "at")} for y in Y}
               for p in sorted(set(fc[2024]) | set(fc[2025]))}
out["screens"] = {y: {"reactive": F[y]["reactive_screen"]["per_node"], "unreliable": F[y]["reactive_unreliable"],
                      "identical_runs": F[y]["flags"]["per_node"]} for y in Y}
out["gsp"] = {y: F[y]["gsp"] for y in Y}
out["voltage"] = {y: {k: F[y]["voltage"][k] for k in ("min_pu", "min_at", "max_pu", "max_at", "buses_ever_outside")} for y in Y}

# Ash Farm's spur and Manor Farm's spur in NGED's own branch files
def spur(year: int, token: str) -> dict:
    br = pd.read_csv(W / f"bicker-fen-{year}" / "branch_load.csv", index_col=0)
    names = {int(x["bus_number"]): x["bus_name"] for x in json.loads((W / f"bicker-fen-{year}" / "bus_mapping.json").read_text(encoding="utf-8"))}
    res = {}
    for c in br.columns:
        f, t = (int(v) for v in c.split("_")[:2])
        if token in names.get(f, str(f)) or token in names.get(t, str(t)) or str(f) == token or str(t) == token:
            s = br[c]
            res[c] = {"ends": [names.get(f, f), names.get(t, t)], "min": round(float(s.min()), 2), "max": round(float(s.max()), 2),
                      "share_nonzero": round(float((s.abs() > 0.05).mean()), 3), "mwh_abs": round(float(s.abs().sum() / 2), 0)}
    return res

out["manor_farm_spur"] = {y: spur(y, "MAII3") for y in Y}
out["ash_farm_spur"] = {2025: spur(2025, "323226")}
(Y[2025] / "compare.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: out[k] for k in ("rules", "labels", "differs_summary", "firm", "gsp", "manor_farm_spur", "ash_farm_spur")}, indent=1, default=str))
