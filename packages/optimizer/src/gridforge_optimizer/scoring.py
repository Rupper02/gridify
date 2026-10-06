"""Deterministic 'grid need' at a bus: areas with growing demand and weak voltage benefit most
from local generation ('first needed')."""

from __future__ import annotations

from .config import (
    GRID_NEED_DEMAND_FULL_MW,
    GRID_NEED_DEMAND_WEIGHT,
    GRID_NEED_VOLTAGE_WEIGHT,
)
from .network import voltage_band


def grid_need_from_solved(solved_net, bus_id: int) -> float:
    """Combine local demand served and voltage depression at the bus, each normalized to 0..1.

    `solved_net` must already have power flow run (under the growth scenario). The two terms are
    blended by the GRID_NEED_*_WEIGHT config values; demand saturates at GRID_NEED_DEMAND_FULL_MW
    and voltage depression is normalized over the bus's own statutory band down to its vmin.
    """
    try:
        vm = float(solved_net.res_bus["vm_pu"].loc[int(bus_id)])
        vmin = voltage_band(float(solved_net.bus.at[int(bus_id), "vn_kv"]), solved_net)[0]
    except KeyError:  # a bus the solve has no result for (out of service): neutral, as before
        vm, vmin = 1.0, 0.94

    loads = solved_net.load
    at_bus = loads["bus"] == int(bus_id)
    local_demand = float((loads.loc[at_bus, "p_mw"] * loads.loc[at_bus, "scaling"]).sum())  # as grown to the horizon, not today's

    demand_term = min(local_demand / GRID_NEED_DEMAND_FULL_MW, 1.0)
    volt_depr = max(0.0, min((1.0 - vm) / (1.0 - vmin), 1.0))
    return round(GRID_NEED_DEMAND_WEIGHT * demand_term + GRID_NEED_VOLTAGE_WEIGHT * volt_depr, 4)
