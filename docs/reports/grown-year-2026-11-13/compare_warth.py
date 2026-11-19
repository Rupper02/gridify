"""Work 6a: 2030 Holistic Transition with Warth Lane at NGED's LTDS forecast, beside the same year on the DFES ratio.

    cd packages/optimizer && uv run python ../../docs/reports/grown-year-2026-11-13/compare_warth.py

Reads `2030-ht/` and `2030-ht-warth-ltds/` (run `analyse.py 2030 ht` and `analyse.py 2030 ht warth-ltds` first) and
prints every element whose peak moved by more than one point, the busbars, firm capacity and the GSP. Supported by NGED
Open Data.
"""

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
A, B = HERE / "2030-ht", HERE / "2030-ht-warth-ltds"
ea, eb = (pd.read_csv(d / "elements.csv").set_index(["kind", "id"]) for d in (A, B))
fa, fb = (json.loads((d / "figures.json").read_text(encoding="utf-8")) for d in (A, B))

print("multiplier at Warth Lane (bus 94):", fa["multipliers"].get("94"), "->", fb["multipliers"].get("94"))
d = eb[["name", "label", "peak_pct", "peak_at", "h80", "h90", "h100"]].join(ea[["peak_pct", "h80", "h90", "h100"]], rsuffix="_dfes")
d["d_peak"] = d.peak_pct - d.peak_pct_dfes
moved = d[d.d_peak.abs() > 1].sort_values("d_peak", ascending=False)
print(f"\nelements whose peak moved by more than 1 point: {len(moved)}")
with pd.option_context("display.width", 250, "display.max_columns", 20, "display.max_colwidth", 60):
    print(moved[["name", "label", "peak_pct_dfes", "peak_pct", "peak_at", "h90_dfes", "h90", "h100_dfes", "h100"]].to_string())
print("\nover rating:", fa["overloads"]["grown_elements_over_100"], "->", fb["overloads"]["grown_elements_over_100"],
      "| grown only:", fb["overloads"]["grown_only"])
print("\nvoltage min:", fa["voltage"]["min_pu"], fa["voltage"]["min_at"], "->", fb["voltage"]["min_pu"], fb["voltage"]["min_at"])
va, vb = fa["voltage"]["hours_outside_by_bus"], fb["voltage"]["hours_outside_by_bus"]
for k in sorted(set(va) | set(vb), key=lambda k: -vb.get(k, 0)):
    print(f"  {k}: {va.get(k, 0)} -> {vb.get(k, 0)} h")
print("\nfirm capacity (hours above firm):")
fa_f = {r["substation"]: r for r in fa["firm_capacity"]}
for r in fb["firm_capacity"]:
    o = fa_f.get(r["substation"], {})
    if r["hours_above_firm"] or o.get("hours_above_firm"):
        print(f"  {r['substation']}: firm {r['firm_mva']} MVA, peak {o.get('peak_mva')} -> {r['peak_mva']} MVA, "
              f"{o.get('hours_above_firm', 0)} -> {r['hours_above_firm']} h")
print("\nGSP:", {k: (fa["gsp"][k], fb["gsp"][k]) for k in ("export_max_mw", "import_max_mw", "import_max_at", "hours_above_export_limit")})
print("planning cases (engine, DFES):", fb["planning_cases"]["breaches"], "breaches")
