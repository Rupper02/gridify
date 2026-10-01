"""pandapower helpers: build the network, grow demand, inject generation, test feasibility."""

from __future__ import annotations

import pandapower as pp
import pandapower.networks as nw

from .config import (
    LINE_LOADING_MAX_PCT,
    TRAFO_LOADING_MAX_PCT,
    VOLTAGE_MAX_PU,
    VOLTAGE_MIN_PU,
)
from .types import Reason


def build_base_net():
    """A fresh mv_oberrhein network (the validated canonical grid)."""
    return nw.mv_oberrhein()


def apply_growth(net, factor: float) -> None:
    """Scale every load by `factor` to model demand growth (keeps original p_mw)."""
    net.load["scaling"] = net.load["scaling"] * factor


def inject_sgen(net, bus: int, p_mw: float, name: str = "", tech: str | None = None) -> int:
    """Add a static generator (PQ) — DER does not regulate voltage, so violations surface.

    Returns the new sgen index so a trial injection can be dropped again.
    """
    return int(pp.create_sgen(net, bus=int(bus), p_mw=float(p_mw), q_mvar=0.0, name=name, type=tech))


def drop_sgen(net, idx: int) -> None:
    net.sgen = net.sgen.drop(index=idx)


def _solve(net) -> bool:
    try:
        pp.runpp(net)  # uses numba when installed (big speedup over the ~2N solves)
        return True
    except Exception:
        return False


def feasibility(net) -> tuple[bool, Reason | None, dict]:
    """Run power flow and check voltage band + line/transformer thermal limits.

    Returns (ok, reason_if_not_ok, metrics).
    """
    if not _solve(net):
        return False, Reason(type="non_convergent", message="power flow did not converge"), {}

    vm = net.res_bus["vm_pu"]
    line_pct = net.res_line["loading_percent"]
    trafo_pct = net.res_trafo["loading_percent"]
    metrics = {
        "min_vm": float(vm.min()),
        "max_vm": float(vm.max()),
        "max_line_pct": float(line_pct.max()),
        "max_trafo_pct": float(trafo_pct.max()),
    }

    if not vm.between(VOLTAGE_MIN_PU, VOLTAGE_MAX_PU).all():
        worst = (vm - 1.0).abs().idxmax()
        v = float(vm.loc[worst])
        return (
            False,
            Reason(type="voltage", element_id=int(worst), value=round(v, 4),
                   message=f"voltage {v:.3f} pu at bus {int(worst)} outside [{VOLTAGE_MIN_PU}, {VOLTAGE_MAX_PU}]"),
            metrics,
        )

    if (line_pct > LINE_LOADING_MAX_PCT).any():
        worst = line_pct.idxmax()
        v = float(line_pct.loc[worst])
        return (
            False,
            Reason(type="line", element_id=int(worst), value=round(v, 1),
                   message=f"line {int(worst)} overloaded at {v:.0f}%"),
            metrics,
        )

    if (trafo_pct > TRAFO_LOADING_MAX_PCT).any():
        worst = trafo_pct.idxmax()
        v = float(trafo_pct.loc[worst])
        return (
            False,
            Reason(type="trafo", element_id=int(worst), value=round(v, 1),
                   message=f"transformer {int(worst)} overloaded at {v:.0f}%"),
            metrics,
        )

    return True, None, metrics


def overloaded_line_ids(net) -> list[int]:
    lp = net.res_line["loading_percent"]
    return [int(i) for i in lp[lp > LINE_LOADING_MAX_PCT].index]
