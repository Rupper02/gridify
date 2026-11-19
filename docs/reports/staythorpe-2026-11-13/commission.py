"""Step 4, Stage C: Staythorpe's commissioning check on its 2025 year, by Bicker Fen's rules, unchanged
(docs/reports/timeseries-step1-spec-2026-11-12.md, as `measured-year-2024/analyse.py` applies them), with its classes
defined from the network instead of listed by hand. Writes `commission.json` and `commission_groups.csv`.
Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/staythorpe-2026-11-13/commission.py

Classes (Bicker Fen's, defined generally):
- input: a radial element whose far side holds only injections derived from NGED's own flows (it carries them by
  construction);
- excluded: beyond a cluster held at 0 (Staythorpe holds none);
- backbone: an element with an end at 132 kV or above (132 kV circuits, the 132/33 and 132/11 kV transformers);
- radial: a bridge of the network that is none of the above; meshed: the rest.
Rules:
- the radial rule (rule 4 at Bicker Fen): every radial group within 0.5 MW + 2% of NGED's flow on every solved half-hour;
- rule 1, closure: the engine's import against the flow NGED's five 132 kV circuits at Staythorpe C carry out of its
  busbar (Hawton x 2, Staythorpe B x 3, the circuits into the infeed busbar, as Bicker Fen's four were), within the larger
  of 2 MW and 3% on 95% of solved half-hours;
- rule 2: every backbone group within 5% of its rating on 95% of solved half-hours, the same direction on 95%;
- rule 3: 80% of meshed groups pass rule 2's test.
"""

import json
import warnings
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import pandapower.topology as top

from gridify_optimizer import nged
from gridify_optimizer.nged_points import STAYTHORPE

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
SNAP = HERE.parents[2] / "apps" / "pipeline" / "warehouse" / "supply-points" / "staythorpe"
T = {n: json.loads((SNAP / "tables" / f"{n}.json").read_text(encoding="utf-8")) for n in nged.TABLE_NAMES}
from rules import evaluate  # noqa: E402

net = nged.build_nged_net(T, point=STAYTHORPE)
F, C = evaluate(SNAP / "measured-year-2025-screened.npz", SNAP / "flows-2025", net, "STAY1")
C.to_csv(HERE / "commission_groups.csv", index=False)
(HERE / "commission.json").write_text(json.dumps(F, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: F[k] for k in ("half_hours", "solved", "groups", "radial_rule", "rule1", "rule2", "rule3", "input_check", "nged_import", "engine_import", "closure_reference")}, indent=1, default=str))
