"""Deterministic 'grid need' at a bus: areas with growing demand and weak voltage benefit most
from local generation ('first needed')."""

from __future__ import annotations

from .config import (
    GRID_NEED_DEMAND_FULL_MW,
    GRID_NEED_DEMAND_WEIGHT,
    GRID_NEED_VOLTAGE_WEIGHT,
    VOLTAGE_MIN_PU,
)


def grid_need_from_solved(solved_net, bus_id: int) -> float:
    """Combine local demand served and voltage depression at the bus, each normalized to 0..1.

    `solved_net` must already have power flow run (under the growth scenario). The two terms are
    blended by the GRID_NEED_*_WEIGHT config values; demand saturates at GRID_NEED_DEMAND_FULL_MW
    and voltage depression is normalized over the allowed band down to VOLTAGE_MIN_PU.
    """
    try:
        vm = float(solved_net.res_bus["vm_pu"].loc[int(bus_id)])
    except Exception:
        vm = 1.0

    loads = solved_net.load
    local_demand = float(loads.loc[loads["bus"] == int(bus_id), "p_mw"].sum())

    demand_term = min(local_demand / GRID_NEED_DEMAND_FULL_MW, 1.0)
    volt_depr = max(0.0, min((1.0 - vm) / (1.0 - VOLTAGE_MIN_PU), 1.0))
    return round(GRID_NEED_DEMAND_WEIGHT * demand_term + GRID_NEED_VOLTAGE_WEIGHT * volt_depr, 4)
