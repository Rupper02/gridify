"""Fault levels, informational: the three-phase short-circuit current at every switchgear busbar, per plan year.

What a DNO checks beside thermal loading and voltage (every Network Development Plan locates limits "including
thermal, voltage and fault level"; Ofgem's LTDS form publishes the system impedance, the existing fault currents and
the switchgear ratings per node, Table 4). The method here is IEC 60909 as pandapower implements it (the equivalent
voltage source at the fault, maximum case): the initial symmetrical current Ik'' with the network as it stands in the
year, every generator in service, inverter units as current sources at FAULT_INVERTER_K times their rated current,
synchronous units through a sub-transient reactance (config.FAULT_*).

Absolute figures from a planning model and a DNO's own differ (the DNO decrements the break current to its protection
time and applies ER G74; the model's primary transformers and the decrement are not the DNO's), so the figure judged
against the published rating is the DNO's published current scaled by the modelled change from today's network
(`projected_ka` = published × modelled / today): what the plan adds or removes, on the DNO's own baseline. The modelled
current is reported beside it. Where no current is published (an imported grid), the modelled figure stands alone and
the rating, when the file carries none, is None: a figure, never a verdict. Reported, never a connection gate.
"""

from __future__ import annotations

import math

import pandapower as pp
import pandapower.shortcircuit as sc
import pandas as pd

from .config import FAULT_INVERTER_K, FAULT_INVERTER_TECHS, FAULT_MIN_KV, FAULT_SYNC_COS_PHI, FAULT_SYNC_XDSS_PU
from .types import FaultLevel

RATING_COLS = ("fault_rating_ka", "fault_published_ka", "fault_make_rating_ka", "fault_published_make_ka")


def can_study(net) -> str | None:
    """None when the network carries what the calculation needs, else what it lacks: the external grid's short-circuit
    power (an imported file's, or the built-in grid's from LTDS Table 4), and a sub-transient reactance for every power
    station the file models as a generator (never assumed for an import)."""
    if "s_sc_max_mva" not in net.ext_grid or not net.ext_grid["s_sc_max_mva"].notna().any():
        return "the source gives no short-circuit power at the external grid"
    if len(net.gen) and ("xdss_pu" not in net.gen or net.gen["xdss_pu"].isna().any()):
        return "the file gives no sub-transient reactance for its power stations"
    return None


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def ikss(net) -> pd.Series:
    """Ik'' in kA at every bus (IEC 60909, maximum case) with the network as it stands; the net's inputs are left as
    found. Inverter units (FAULT_INVERTER_TECHS) contribute as current sources at FAULT_INVERTER_K × rated; every other
    unit (gas engines, biomass, waste) as a synchronous machine with FAULT_SYNC_XDSS_PU, modelled for the calculation
    as a generator at its bus."""
    sgen0, gen0 = net.sgen.copy(), net.gen.copy()
    try:
        inv = net.sgen["type"].isin(FAULT_INVERTER_TECHS) if len(net.sgen) else pd.Series(dtype=bool)
        rated = net.sgen["p_rated_mw"] if "p_rated_mw" in net.sgen else net.sgen["p_mw"]
        net.sgen["sn_mva"] = rated.fillna(net.sgen["p_mw"]).abs().clip(lower=0.01)
        net.sgen["k"] = FAULT_INVERTER_K
        net.sgen["rx"] = 0.1
        net.sgen["generator_type"] = "current_source"
        sync = net.sgen[~inv & net.sgen["in_service"].astype(bool)]
        net.sgen.loc[~inv, "in_service"] = False
        for i, r in sync.iterrows():
            bus = int(r["bus"])
            pp.create_gen(net, bus=bus, p_mw=float(r["p_mw"]), vm_pu=1.0, sn_mva=float(net.sgen.at[i, "sn_mva"]),
                          vn_kv=float(net.bus.at[bus, "vn_kv"]), xdss_pu=FAULT_SYNC_XDSS_PU, rdss_ohm=0.0, cos_phi=FAULT_SYNC_COS_PHI,
                          name=f"sc-{r['name']}")
        if len(net.gen):  # a file's power stations: their own x''d (can_study refused the import without it), the rest filled for the solver
            net.gen["vn_kv"] = net.bus.loc[net.gen["bus"].astype(int), "vn_kv"].values
            if "sn_mva" not in net.gen:
                net.gen["sn_mva"] = float("nan")
            net.gen["sn_mva"] = net.gen["sn_mva"].fillna(net.gen["p_mw"].abs().clip(lower=0.01))
            if "rdss_ohm" not in net.gen:
                net.gen["rdss_ohm"] = 0.0
            net.gen["rdss_ohm"] = net.gen["rdss_ohm"].fillna(0.0)
            if "cos_phi" not in net.gen:
                net.gen["cos_phi"] = FAULT_SYNC_COS_PHI
            net.gen["cos_phi"] = net.gen["cos_phi"].fillna(FAULT_SYNC_COS_PHI)
        sc.calc_sc(net, fault="3ph", case="max", ip=False)
        return net.res_bus_sc["ikss_ka"].astype(float).copy()
    finally:
        net.sgen, net.gen = sgen0, gen0


def today_levels(net) -> dict[int, float]:
    """Ik'' per bus on the network as built (today): the anchor the published figure is scaled from. Builders store it
    as `net["fault_today_ka"]` once; an empty dict when the network cannot be studied."""
    if can_study(net):
        return {}
    return {int(b): round(float(v), 4) for b, v in ikss(net).items() if v == v}


def fault_levels(net) -> list[FaultLevel]:
    """Every switchgear busbar's fault level with the network as it stands: the buses the source publishes ratings or
    currents for when it publishes any (`RATING_COLS` on `net.bus`), else every bus at FAULT_MIN_KV and above."""
    if can_study(net):
        return []
    now = ikss(net)
    today = net.get("fault_today_ka") or {}
    published_any = any(c in net.bus and net.bus[c].notna().any() for c in RATING_COLS)
    out: list[FaultLevel] = []
    for b in net.bus.index:
        kv = float(net.bus.at[b, "vn_kv"])
        rating = _num(net.bus.at[b, "fault_rating_ka"]) if "fault_rating_ka" in net.bus else None
        published = _num(net.bus.at[b, "fault_published_ka"]) if "fault_published_ka" in net.bus else None
        if published_any and rating is None and published is None:
            continue
        if not published_any and kv < FAULT_MIN_KV:
            continue
        modelled = _num(now.get(b))
        if modelled is None:
            continue
        t = _num(today.get(int(b)))
        projected = published * modelled / t if published is not None and t else None
        basis = projected if projected is not None else modelled
        out.append(FaultLevel(
            bus=int(b), name=str(net.bus.at[b, "name"]), kv=kv, published_ka=published, rating_ka=rating,
            modelled_ka=round(modelled, 2), today_ka=round(t, 2) if t is not None else None,
            projected_ka=round(projected, 2) if projected is not None else None,
            utilisation_pct=round(100.0 * basis / rating, 1) if rating else None,
            published_over_rating=bool(published is not None and rating is not None and published > rating),
        ))
    return out
