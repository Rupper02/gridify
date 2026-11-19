"""Work 13: the size of "one weather year". 2035 Holistic Transition grown on 2024's flows (`2035-ht`) against the same
year grown on 2025's (`2035-ht-flows-2025`), element by element, from each run's `analyse.py` output. Writes
`2035-ht-flows-2025/compare.json`. Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/grown-year-2026-11-13/compare_base_year.py
"""

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
A, B = HERE / "2035-ht", HERE / "2035-ht-flows-2025"
M = HERE.parent / "measured-year-2024"
OK = {"flow agrees with NGED's model", "flow differs"}
# reliable in both measured years: the element's flow is compared with NGED's model, its input usable, in 2024 and 2025
lab = {y: pd.read_csv(M / d / "elements.csv").set_index(["kind", "id"]).label for y, d in ((2024, "screened"), (2025, "screened-2025"))}
reliable = {k for k in lab[2024].index if lab[2024][k] in OK and lab[2025].get(k) in OK}
# places where the two bases are not comparable, by input (second-year-2025.md): named, kept out of the spread
NOT_COMPARABLE = {
    ("trafo", 43): "Wrangle 33/11 kV T3: NGED's 2025 Wrangle series is zero for 99% of the year",
    ("line", 86): "Wrangle tee - Wrangle: the same",
    ("trafo", 33): "Spilsby T1: reactive power corrupt in 2024, usable in 2025",
    ("trafo", 34): "Spilsby T2: the same",
    ("line", 76): "Skegness - Manor Farm tee: Manor Farm's solar reads zero in 2024, flows in 2025",
    ("line", 67): "Manor Farm tee - Spilsby: the same",
    ("line", 68): "Manor Farm tee - Manor Farm: the same",
}
ea = pd.read_csv(A / "elements.csv").set_index(["kind", "id"])
eb = pd.read_csv(B / "elements.csv").set_index(["kind", "id"])
j = ea.join(eb, lsuffix="_24", rsuffix="_25", how="inner")
cols = ["name_24", "peak_pct_24", "peak_pct_25", "h80_24", "h80_25", "h90_24", "h90_25", "h100_24", "h100_25"]
rel = j[[k in reliable and k not in NOT_COMPARABLE for k in j.index]]
over = rel[(rel.h100_24 > 0) | (rel.h100_25 > 0)].sort_values("h100_24", ascending=False)
d_peak = rel.peak_pct_25 - rel.peak_pct_24
out = {
    "reliable_elements": len(rel),
    "over_rating": {"on_2024": int((rel.h100_24 > 0).sum()), "on_2025": int((rel.h100_25 > 0).sum()),
                    "hours_on_2024": float(rel.h100_24.sum()), "hours_on_2025": float(rel.h100_25.sum())},
    "elements_over": over[cols].reset_index().round(1).to_dict("records"),
    "peak_move_pts": {"median_abs": round(float(d_peak.abs().median()), 1), "p90_abs": round(float(d_peak.abs().quantile(.9)), 1),
                      "max_abs": round(float(d_peak.abs().max()), 1), "mean": round(float(d_peak.mean()), 1)},
    "not_comparable": {f"{k[0]} {k[1]}": dict(why=v, **{c: (None if pd.isna(j.loc[k, c]) else float(j.loc[k, c])) for c in cols[1:]})
                       for k, v in NOT_COMPARABLE.items() if k in j.index},
}
fa, fb = (json.loads((p / "figures.json").read_text(encoding="utf-8")) for p in (A, B))
firm = {r["substation"]: {"on_2024": r} for r in fa["firm_capacity"]}
for r in fb["firm_capacity"]:
    firm.setdefault(r["substation"], {})["on_2025"] = r
out["firm"] = {s: {y: (v[y]["peak_mva"], v[y]["hours_above_firm"]) if y in v else None for y in ("on_2024", "on_2025")} for s, v in firm.items()}
out["voltage"] = {y: {k: f["voltage"][k] for k in ("min_pu", "min_at", "hours_outside_by_bus")} for y, f in (("on_2024", fa), ("on_2025", fb))}
out["gsp"] = {"on_2024": fa["gsp"], "on_2025": fb["gsp"]}
out["converged"] = {"on_2024": [fa["converged"], fa["half_hours"]], "on_2025": [fb["converged"], fb["half_hours"]]}
(B / "compare.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(json.dumps(out, indent=1, default=str))
