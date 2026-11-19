"""Work 16a, an experiment, not a change to the engine: a measured year with Sleaford's two 132/33 kV transformers at an
impedance like their neighbours' (6.6 % on rating against the published 11.2 %), to test the one lead on the mismatch
with NGED's model. The built network, the bundled data and the planning cases are untouched: the change lives in this
run's `net_factory` only. Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/measured-year-2024/experiment_sleaford.py <year>

Writes `measured-year-<year>-screened-sleaford-vk.npz`. Both vk and vkr are scaled by 6.6 / 11.2, so X/R is kept.
"""

import sys
from pathlib import Path

from gridify_optimizer import network
from gridify_optimizer.timeseries import run_year

SCALE = 6.6 / 11.2
W = Path("../../apps/pipeline/warehouse/nged-flows")


def sleaford_at_neighbours_impedance():
    net = network.build_base_net()
    gts = [i for i in net.trafo.index
           if net.bus.at[int(net.trafo.at[i, "hv_bus"]), "name"].startswith("Sleaford 132kV")
           and float(net.bus.at[int(net.trafo.at[i, "lv_bus"]), "vn_kv"]) == 33.0]
    assert len(gts) == 2, gts
    net.trafo.loc[gts, "vk_percent"] *= SCALE
    net.trafo.loc[gts, "vkr_percent"] *= SCALE
    return net


if __name__ == "__main__":
    year = int(sys.argv[1])
    n = sleaford_at_neighbours_impedance()
    gts = [i for i in n.trafo.index if n.bus.at[int(n.trafo.at[i, "hv_bus"]), "name"].startswith("Sleaford 132kV")]
    print("Sleaford GTs:", n.trafo.loc[gts, ["vk_percent", "vkr_percent"]].round(4).to_dict("index"), flush=True)
    out = W / f"measured-year-{year}-screened-sleaford-vk.npz"
    run_year(W / f"bicker-fen-{year}", out, reactive="screened", net_factory=sleaford_at_neighbours_impedance,
             about={"label": f"{year}, Sleaford 132/33 kV at 6.6 % (experiment)", "experiment": "Work 16a"})
    print("saved", out, flush=True)
