"""Merit-order dispatch of an imported grid's power stations, per study case.

Real power stations are dispatched to balance demand: the cheapest run first, each between its minimum and maximum
output. A grid imported from a file (`sources`, which sets `net["dispatch"] = "merit_order"`) is studied that way:

* embedded generation (`sgen`: fixed power factor, the distribution side) follows the study case as on any grid
  (`network.dispatch_for_case`: a DNO does not dispatch it; the weather, the season and its owner's schedule do);
  so do variable power stations (solar, wind, storage) and new connections;
* the power stations (`gen`: voltage-controlled, not solar, wind or storage) and a priced external grid share what is
  left of the case's demand by economic
  dispatch: loaded so their marginal costs are equal, within their limits (`economic_dispatch`). The costs are the
  file's (`poly_cost`, linear or quadratic). Every available unit stays synchronised: which units an operator keeps
  on for security is not modelled, and switching one off for cost alone can strip the voltage support the grid runs on;
* the external grid balances what the units do not supply, and the losses;
* a solar or wind unit under voltage control producing nothing is out of service in that case: an offline machine
  holds no voltage.

NGED's distribution builder keeps its own convention (embedded generation at its case factor), so its results do not
change.
"""

from __future__ import annotations

from typing import NamedTuple

import pandas as pd

VARIABLE_TECHS = frozenset({"solar", "wind", "battery", "hybrid", "electrolyser", "demand"})
_LAMBDA_ITERATIONS = 60  # bisection on the marginal cost: far below a kW of mismatch on any grid


class Unit(NamedTuple):
    key: tuple[str, int]  # (table, row): ("gen", 3), ("sgen", 7), ("ext_grid", 0)
    p_min: float
    p_max: float
    cp1: float  # marginal cost at zero output (cost per MWh)
    cp2: float  # its slope (cost per MW² per h): marginal cost = cp1 + 2 * cp2 * p

    def at(self, lam: float) -> float:
        """The output at which this unit's marginal cost reaches `lam`, within its limits."""
        if self.cp2 > 0:
            p = (lam - self.cp1) / (2 * self.cp2)
        else:
            p = self.p_max if lam > self.cp1 else self.p_min
        return min(self.p_max, max(self.p_min, p))


def economic_dispatch(units: list[Unit], need_mw: float) -> dict[tuple[str, int], float]:
    """Each unit's output so that together they meet `need_mw` at equal marginal cost, within their limits. Every
    available unit stays synchronised (at least at its minimum): which units an operator keeps on for security is
    not modelled, and taking one off for cost alone can strip the voltage support the grid runs on. With more need
    than every unit can give, all run flat out and the external grid supplies the rest."""
    if not units:
        return {}
    if need_mw <= sum(u.p_min for u in units):
        return {u.key: u.p_min for u in units}
    if need_mw >= sum(u.p_max for u in units):
        return {u.key: u.p_max for u in units}
    lo = min(u.cp1 for u in units)
    hi = max(u.cp1 + 2 * u.cp2 * u.p_max for u in units) + 1.0
    for _ in range(_LAMBDA_ITERATIONS):
        mid = (lo + hi) / 2
        if sum(u.at(mid) for u in units) < need_mw:
            lo = mid
        else:
            hi = mid
    p = {u.key: u.at(hi) for u in units}
    # linear offers are steps: the marginal unit(s) at lam give back what is over
    excess = sum(p.values()) - need_mw
    for u in sorted(units, key=lambda u: -u.cp1):
        if excess <= 1e-9:
            break
        give = min(excess, p[u.key] - u.p_min)
        p[u.key] -= give
        excess -= give
    return p


def _cost(net, et: str, idx: int) -> tuple[float, float] | None:
    """(cp1, cp2) from the file's `poly_cost` for one element, or None."""
    pc = net.get("poly_cost")
    if pc is None or not len(pc):
        return None
    row = pc[(pc["et"] == et) & (pc["element"].astype(int) == int(idx))]
    if not len(row):
        return None
    return float(row.iloc[0]["cp1_eur_per_mw"]), float(row.iloc[0]["cp2_eur_per_mw2"])


def market_units(net) -> pd.Index:
    """The power stations the merit order dispatches: the existing voltage-controlled units (`gen`) that are not solar,
    wind or storage, in service."""
    t = net.gen
    if not len(t) or "fleet_id" not in t.columns:
        return t.index[:0]
    tech = t["type"].astype(str).str.lower() if "type" in t.columns else pd.Series("", index=t.index)
    return t.index[t["fleet_id"].notna() & ~tech.isin(VARIABLE_TECHS) & t["in_service"].astype(bool)]


def _external_grid_units(net) -> list[Unit]:
    """The external grid as a supplier in the merit order: its price and limits (the import requires them when the
    grid has power stations; it stays the slack, so its share is what the units leave)."""
    units = []
    for i in net.ext_grid.index:
        cost = _cost(net, "ext_grid", i)
        p_max = net.ext_grid.at[i, "max_p_mw"] if "max_p_mw" in net.ext_grid.columns else None
        if cost is None or p_max is None or p_max != p_max:
            continue
        p_min = net.ext_grid.at[i, "min_p_mw"] if "min_p_mw" in net.ext_grid.columns else None
        units.append(Unit(("ext_grid", int(i)), float(p_min) if p_min == p_min and p_min is not None else 0.0, float(p_max), *cost))
    return units


def merit_order(net, case: str) -> None:
    """Set every generator's output for `case` in place (and switch off the solar or wind units under voltage control
    that produce nothing). The caller restores `p_mw` and `in_service` afterwards."""
    from .network import dispatch_for_case

    for table in ("sgen", "gen"):  # embedded and variable generation, storage and new connections: the case decides
        if len(net[table]):
            net[table]["p_mw"] = dispatch_for_case(net, case, table)
    stations = market_units(net)
    if len(stations):
        units = [Unit(("gen", int(i)), float(net.gen.at[i, "min_p_mw"]), float(net.gen.at[i, "p_rated_mw"]), *_cost(net, "gen", i))
                 for i in stations]  # the import refuses a power station without its limits and cost
        demand = float((net.load["p_mw"] * net.load["scaling"])[net.load["in_service"].astype(bool)].sum())
        # what the case already fixes: everything but the power stations (storage charging counts as demand)
        fixed = float(net.sgen["p_mw"].sum()) + float(net.gen.loc[net.gen.index.difference(stations), "p_mw"].sum())
        for (table, i), p in economic_dispatch(units + _external_grid_units(net), demand - fixed).items():
            if table == "gen":  # the external grid is the slack: it supplies its share and balances the rest
                net.gen.at[i, "p_mw"] = p
    if len(net.gen):  # a solar or wind unit producing nothing is offline, and an offline machine holds no voltage
        variable = net.gen.index.difference(stations)
        idle = variable[net.gen.loc[variable, "p_mw"].abs() < 1e-9]
        net.gen.loc[idle, "in_service"] = False
