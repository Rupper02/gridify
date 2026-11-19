"""Step 4, Stage C, item 2: three facts about Staythorpe's topology before anything is solved, from the builder as it
stands and NGED's own files. Writes `topology_facts.json`. Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/staythorpe-2026-11-13/topology_facts.py
"""

import json
import warnings
from pathlib import Path

import pandas as pd
import pandapower.toolbox as tb

from gridify_optimizer import nged
from gridify_optimizer.nged_points import BICKER_FEN, STAYTHORPE

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
WH = HERE.parents[2] / "apps" / "pipeline" / "warehouse"
SNAP = WH / "supply-points" / "staythorpe"
T = {n: json.loads((SNAP / "tables" / f"{n}.json").read_text(encoding="utf-8")) for n in nged.TABLE_NAMES}
out: dict = {}

# (b) what the builder drops as unreachable from its infeed: recorded by wrapping drop_buses for this build only
dropped: list = []
_drop = tb.drop_buses
def _recording_drop(net, buses, *a, **k):
    dropped.append([(int(b), str(net.bus.at[b, "name"]), float(net.bus.at[b, "vn_kv"])) for b in buses])
    return _drop(net, buses, *a, **k)
tb.drop_buses = _recording_drop
try:
    ctx = nged._build(T, point=STAYTHORPE)
finally:
    tb.drop_buses = _drop
net = ctx["net"]
out["built"] = {"buses": len(net.bus), "lines": len(net.line), "trafos": len(net.trafo), "loads": len(net.load),
                "load_mw": round(float(net.load.p_mw.sum()), 2), "sgens": len(net.sgen), "sgen_mw": round(float(net.sgen.p_mw.sum()), 2)}
out["dropped_as_unreachable"] = dropped[0] if dropped else []

# (a) the infeed: the builder's pick against the supergrid transformers' landing nodes in the published limits table
def infeed(ctx, td_rows, point):
    net, nb = ctx["net"], ctx["net"]["node_bus"]
    slack = int(net.ext_grid.bus.iloc[0])
    landing = sorted({r["To Bus Name"] for r in td_rows})
    land_bus = {n: nb.get(n) for n in landing}
    return {"builder_picks": [slack, str(net.bus.at[slack, "name"])], "td_landing_nodes": land_bus,
            "same": all(b == slack for b in land_bus.values() if b is not None) and any(b is not None for b in land_bus.values())}
td_st = json.loads((SNAP / "td_limits.json").read_text(encoding="utf-8"))
out["infeed_staythorpe"] = infeed(ctx, td_st, STAYTHORPE)
bf_td = [{"To Bus Name": "BICF1_#180"}, {"To Bus Name": "BICF1_#280"}]  # Bicker Fen Td Limits rows (read 13 November): To Bus Name
out["infeed_bicker_fen"] = infeed(nged._ctx(), bf_td, BICKER_FEN)

# how Staythorpe B (STAB1) joins C (STAY1) in the LTDS
circ = [r for r in T["circuit"] if str(r.get("Circuit Status")).lower() != "removed"]
out["stab_stay_links"] = [{k: r[k] for k in ("Node 1", "Node 2", "Circuit Code", "Circuit Status", "R1", "X1", "Winter")}
                          for r in circ if {r["Node 1"][:4], r["Node 2"][:4]} == {"STAB", "STAY"}]
stab = sorted({b for c, b in net["node_bus"].items() if c.startswith("STAB1")})
stay = sorted({b for c, b in net["node_bus"].items() if c.startswith("STAY1")})
out["stab_buses"] = [[b, str(net.bus.at[b, "name"])] for b in stab if b in net.bus.index]
out["stay_buses"] = [[b, str(net.bus.at[b, "name"])] for b in stay if b in net.bus.index]

# (c) the circuits that leave the group: in NGED's own Staythorpe branch files, do they carry flow?
nodes = {n["Code"] for n in T["node"]}
ends = sorted({r[k] for r in T["circuit"] for k in ("Node 1", "Node 2") if r[k] not in nodes})
busmap_all = json.loads((Path(__file__).resolve().parents[0] / "busmap_all.json").read_text(encoding="utf-8"))
num_of = {}
for r in busmap_all:
    num_of.setdefault(r["bus_name"], set()).add(int(r["bus_number"]))
gsp_of = {r["bus_name"]: r["grid_supply_point"] for r in busmap_all}
edges = []
for e in ends:
    row = next(r for r in T["circuit"] if e in (r["Node 1"], r["Node 2"]))
    inside = row["Node 2"] if row["Node 1"] == e else row["Node 1"]
    rec = {"outside_node": e, "inside_node": inside, "kv": row["Operating Voltage (kV)"], "code": row["Circuit Code"],
           "status": row["Circuit Status"], "R1": row["R1"], "X1": row["X1"], "winter": row["Winter"], "outside_gsp": gsp_of.get(e)}
    for year in (2024, 2025):
        br = pd.read_csv(SNAP / f"flows-{year}" / "branch_load.csv", index_col=0)
        nums = num_of.get(e, set())
        cols = [c for c in br.columns if {int(x) for x in c.split("_")[:2]} & nums]
        rec[f"in_file_{year}"] = {c: {"min": round(float(br[c].min()), 2), "max": round(float(br[c].max()), 2), "mean": round(float(br[c].mean()), 2),
                                      "nonzero_share": round(float((br[c].abs() > 0.05).mean()), 3)} for c in cols}
    edges.append(rec)
out["boundary_ends"] = edges
(HERE / "topology_facts.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(json.dumps(out, indent=1, default=str))
