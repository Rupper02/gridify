"""Step 4, Stage C, decision 1(c): a supply point's coincident metered peak from NGED's own half-hourly files, tested at
Bicker Fen against NESO's figure before it is used anywhere. The quantity: the sum of the metered primary node series
(NGED's 11 kV nodes, "<site>5_*": the primaries; the 33 kV BSP group totals, the 132 kV supply-point node and the 25 kV
railway nodes are left out), at the half-hour that sum is greatest, in each year's file. Writes `metered_peak.json`.
Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/staythorpe-2026-11-13/metered_peak.py
"""

import json
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
WH = HERE.parents[2] / "apps" / "pipeline" / "warehouse"
SOURCES = {
    "bicker-fen": {2024: WH / "nged-flows" / "bicker-fen-2024", 2025: WH / "nged-flows" / "bicker-fen-2025"},
    "staythorpe": {2024: WH / "supply-points" / "staythorpe" / "flows-2024", 2025: WH / "supply-points" / "staythorpe" / "flows-2025"},
}
NESO = {"bicker-fen": 149.235, "staythorpe": 261.169}
LEVEL = re.compile(r"^[A-Z0-9]{4}(\d)")  # NGED's node code: four characters of site, then the voltage level digit
out = {}
for key, years in SOURCES.items():
    out[key] = {"neso_peak_mw": NESO[key]}
    for year, folder in years.items():
        names = {int(r["bus_number"]): r["bus_name"] for r in json.loads((folder / "bus_mapping.json").read_text(encoding="utf-8"))}
        sub = pd.read_csv(folder / "substation_load.csv", index_col=0)
        sub.index = pd.to_datetime(sub.index)
        mw = [c for c in sub.columns if c.startswith("MW_")]
        level = {c: (m.group(1) if (m := LEVEL.match(names.get(int(c[3:]), ""))) else "?") for c in mw}
        prim = [c for c in mw if level[c] == "5"]
        left_out = {c: f"{names.get(int(c[3:]))} (level {level[c]})" for c in mw if level[c] != "5"}
        s = sub[prim].sum(axis=1)
        t = s.idxmax()
        neg = {names.get(int(c[3:])): round(float(sub.at[t, c]), 2) for c in prim if sub.at[t, c] < 0}
        out[key][year] = {"primary_nodes": len(prim), "peak_mw": round(float(s.max()), 2), "at": str(t),
                          "ratio_to_neso": round(float(s.max()) / NESO[key], 3), "left_out": left_out,
                          "nodes_net_negative_at_peak": neg, "mean_mw": round(float(s.mean()), 2)}
(HERE / "metered_peak.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
for key, v in out.items():
    for y in (2024, 2025):
        r = v[y]
        print(f"{key} {y}: {r['primary_nodes']} primary nodes, peak {r['peak_mw']} MW at {r['at']}, x{r['ratio_to_neso']} of NESO's {v['neso_peak_mw']}; "
              f"left out {len(r['left_out'])}: {list(r['left_out'].values())[:8]}; net-negative at peak: {r['nodes_net_negative_at_peak']}")
