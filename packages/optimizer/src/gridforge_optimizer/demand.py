"""The demand side: the customers (homes, farms, factories) the network exists to supply, judged
region by region and year by year.

A region is a demand group as the LTDS publishes it (Table 3), at one of two levels (`LEVELS`): a
primary substation (or a customer's own connection), with its firm capacity; and a bulk supply
point over the primaries it feeds, with the firm capacity of its 132/33 kV transformers. The builder
tags every load with its groups (`region_id`, `region`, `bsp`, `firm_mw`, `peak_mw`, and `bsp_*` for
the parent BSP, columns on net.load, see nged._add_loads); this module only reads the net, so it
works for any network that carries those columns (and reports no regions for one that does not).
A load belongs to one primary-level group and at most one BSP: a BSP's demand is its primaries',
never counted twice.

Per year (`assess_demand`, called by years.evaluate_year on the year's solved net):
  * demand: the group's own peak (LTDS maximum demand grown to the year, plus any plan project that
    draws power at winter peak on the group's buses), and what the power flow carries for it;
  * firm headroom and the P2/8 demand class (by group demand);
  * N-1: the most demand one 132 kV backbone outage cuts off in the group (from the N-1 screen's
    islanded buses, winter peak);
  * voltage: the group's load buses outside the statutory band with the network intact;
  * demand room: a first-order (≈) bound on new demand, the smaller of the firm headroom and the
    spare winter-peak capacity of the transformers feeding the group. No extra power-flow probe.

This is a SIMPLIFIED P2/8-STYLE check: restoration times, switching, transfer capacity and second
circuit outages are not modelled, and every figure is MW of demand (the open data has no customer
counts). Alerts come from ALERT_CHECKS: a new kind of alert is one function plus one entry there.
"""

from __future__ import annotations

from typing import NamedTuple

import pandas as pd

from .config import HEADROOM_WARN_FRACTION, N1_ISLAND_MIN_MW, P2_8_CLASSES
from .network import dispatch_for_case, solve_case, voltage_limits
from .types import Alert, RegionYear


class _Level(NamedTuple):
    """Where one level of demand group lives on net.load: the id/name/firm columns, the column of
    its site buses (None: the group's own load buses) and of the factor that scales its members' own
    peaks to the group's peak (None: 1, the group's peak is the sum of its loads' own)."""
    name: str
    id: str
    label: str
    firm_mw: str
    firm_mva: str
    sites: str | None
    scale: str | None


LEVELS = (
    _Level("primary", "region_id", "region", "firm_mw", "firm_mva", None, None),
    _Level("bsp", "bsp_region_id", "bsp_region", "bsp_firm_mw", "bsp_firm_mva", "bsp_sites", "bsp_coincidence"),
)


# --- P2/8 demand classes ---------------------------------------------------------------------------
def p2_class(group_mw: float) -> str:
    """The P2/8 demand class of a group demand (A up to 1 MW ... F above 1500 MW)."""
    for name, upper, _, _ in P2_8_CLASSES:
        if group_mw <= upper:
            return name
    return P2_8_CLASSES[-1][0]


def p2_loss_allowed(cls: str, group_mw: float) -> float | None:
    """MW of the group a first circuit outage may leave waiting beyond the fast-restoration window
    under a simplified reading of P2/8 Table 1. None = the whole group may wait (class A and B)."""
    for name, _, loss_mw, frac in P2_8_CLASSES:
        if name == cls:
            return None if loss_mw is None else max(loss_mw, frac * group_mw)
    return 0.0


# --- the groups on a net --------------------------------------------------------------------------
class _Group(NamedTuple):
    region_id: str
    name: str
    bsp: str
    level: str
    loads: pd.Index  # net.load rows
    buses: list[int]  # its site: where it is drawn, its voltage is judged and its transformers feed
    area: list[int]  # the buses whose new project demand counts toward it (load buses and site)
    firm_mw: float
    firm_mva: float | None
    scale: float  # members' own peaks x scale = the group's peak


def _level_groups(net, lv: _Level) -> list[_Group]:
    load = net.load
    if lv.id not in load.columns or lv.label not in load.columns or lv.firm_mw not in load.columns:
        return []
    load = load[load[lv.id].notna()]
    firm = pd.to_numeric(load[lv.firm_mw], errors="coerce").fillna(0.0)
    mva = pd.to_numeric(load[lv.firm_mva], errors="coerce") if lv.firm_mva in load.columns else None
    bsp = load["bsp"] if "bsp" in load.columns else pd.Series("", index=load.index)
    out = []
    for rid, idx in sorted(load.groupby(lv.id).groups.items()):
        i0 = idx[0]
        m = mva.loc[idx].min() if mva is not None else float("nan")
        own = {int(b) for b in load.loc[idx, "bus"]}
        sites = sorted({int(b) for b in load.at[i0, lv.sites] if int(b) in net.bus.index}) if lv.sites else []
        scale = float(pd.to_numeric(load.at[i0, lv.scale], errors="coerce")) if lv.scale else 1.0
        out.append(_Group(
            region_id=str(rid), name=str(load.at[i0, lv.label]), bsp=str(bsp.at[i0] or ""), level=lv.name, loads=idx,
            buses=sites or sorted(own), area=sorted(own | set(sites)), firm_mw=float(firm.loc[idx].min()),
            firm_mva=None if m != m else float(m), scale=scale if scale == scale else 1.0,
        ))
    return out


def _groups(net) -> list[_Group]:
    """The demand groups tagged on net.load, level by level, each in region_id order (deterministic)."""
    if not len(net.load):
        return []
    return [g for lv in LEVELS for g in _level_groups(net, lv)]


def _peak(net) -> pd.Series:
    """Each load's own peak demand before growth (`peak_mw`, else the modelled p_mw)."""
    if "peak_mw" in net.load.columns:
        return pd.to_numeric(net.load["peak_mw"], errors="coerce").fillna(net.load["p_mw"]).astype(float)
    return net.load["p_mw"].astype(float)


def regions_of(net) -> list[dict]:
    """The demand groups of a net, as they stand today (before growth), for the map/API."""
    peak, base = _peak(net), net.load["p_mw"].astype(float)
    out = []
    for g in _groups(net):
        peak_mw = float(peak.loc[g.loads].sum()) * g.scale
        out.append({"region_id": g.region_id, "name": g.name, "bsp": g.bsp, "level": g.level, "buses": g.buses,
                    "firm_mw": round(g.firm_mw, 3), "firm_mva": g.firm_mva,
                    "base_demand_mw": round(float(base.loc[g.loads].sum()), 3),
                    "peak_demand_mw": round(peak_mw, 3), "p2_class": p2_class(peak_mw)})
    return out


def _project_import_by_bus(net) -> pd.Series:
    """MW each bus's plan projects draw at winter peak (demand connections, charging batteries).
    The existing fleet (sgens with a `fleet_id`) is left out: its import is already in LTDS demand."""
    if not len(net.sgen):
        return pd.Series(dtype=float)
    p = dispatch_for_case(net, "winter_peak")
    sel = net.sgen["in_service"].astype(bool) & (p < 0)
    if "fleet_id" in net.sgen.columns:
        sel &= net.sgen["fleet_id"].isna()
    if not sel.any():
        return pd.Series(dtype=float)
    return (-p[sel]).groupby(net.sgen.loc[sel, "bus"].astype(int)).sum()


def _bus_owner(groups: list[_Group]) -> dict[tuple[str, int], str]:
    """Which group of each level a bus's project demand counts toward: the first (by region_id)
    whose area has the bus, so one project is counted once per level."""
    owner: dict[tuple[str, int], str] = {}
    for g in groups:
        for b in g.area:
            owner.setdefault((g.level, b), g.region_id)
    return owner


def _owned(g: _Group, buses, imports: pd.Series, owner) -> float:
    """MW of project demand on `buses` that counts toward group `g`."""
    return sum(float(imports.get(b, 0.0)) for b in buses if owner.get((g.level, b)) == g.region_id)


def _stranded(net, groups, own: pd.Series, imports: pd.Series, owner, n1_violations) -> dict[str, tuple[float, str]]:
    """Per group, the most own-peak demand one N-1 outage cuts off, and which outage."""
    worst: dict[str, tuple[float, str]] = {}
    for v in n1_violations:
        ids = v.get("islanded_bus_ids") if v.get("type") == "islanded" else None
        if not ids:
            continue
        island = set(int(b) for b in ids)
        label = f"{v.get('outage_type')} {v.get('outage_id')}"
        for g in groups:
            on = [i for i in g.loads if int(net.load.at[i, "bus"]) in island]
            mw = float(own.loc[on].sum()) * g.scale if on else 0.0
            mw += _owned(g, island, imports, owner)
            if mw > worst.get(g.region_id, (0.0, ""))[0]:
                worst[g.region_id] = (mw, label)
    return worst


def _transformer_spare_by_bus(net, trafo_pct: pd.Series | None) -> dict[int, float]:
    """Spare winter-peak capacity (MVA, ≈ MW) of the in-service transformers feeding each LV bus."""
    if trafo_pct is None or not len(net.trafo):
        return {}
    t = net.trafo[net.trafo["in_service"].astype(bool)]
    pct = trafo_pct.reindex(t.index)
    cap = t["sn_mva"].astype(float) * (t["parallel"].astype(float) if "parallel" in t.columns else 1.0)
    spare = ((100.0 - pct) / 100.0 * cap).clip(lower=0.0)[pct.notna()]
    return {int(b): float(v) for b, v in spare.groupby(t.loc[spare.index, "lv_bus"].astype(int)).sum().items()}


def assess_regions(net, n1_violations: list[dict] = ()) -> list[RegionYear]:
    """Every demand group on a solved net. Call it right after feasibility(): it reads the intact
    envelope voltages from net.res_bus, then solves winter peak once more (taps left as found) for the
    transformers' spare capacity. `n1_violations` are the N-1 screen's (islanded ones carry bus ids)."""
    groups = _groups(net)
    if not groups:
        return []
    scaling = net.load["scaling"].astype(float)
    own, modelled = _peak(net) * scaling, net.load["p_mw"].astype(float) * scaling
    imports = _project_import_by_bus(net)
    owner = _bus_owner(groups)
    vm = net.res_bus["vm_pu"].reindex(net.bus.index) if len(net.res_bus) else pd.Series(dtype=float)
    vmin, vmax = voltage_limits(net)
    stranded = _stranded(net, groups, own, imports, owner, n1_violations)
    winter = solve_case(net, "winter_peak")
    spare_at = _transformer_spare_by_bus(net, winter["trafo_pct"] if winter is not None else None)

    out = []
    for g in groups:
        extra = _owned(g, g.area, imports, owner)
        demand = float(own.loc[g.loads].sum()) * g.scale + extra
        headroom = g.firm_mw - demand
        v = vm.reindex(g.buses).dropna() if len(vm) else pd.Series(dtype=float)
        bad = [int(b) for b in v.index if v[b] < vmin[b] or v[b] > vmax[b]]
        worst_bus = int((v - 1.0).abs().idxmax()) if len(v) else None
        worst_vm = float(v.loc[worst_bus]) if worst_bus is not None else None
        edge = None if worst_bus is None else float(vmin[worst_bus] if worst_vm < 1.0 else vmax[worst_bus])
        fed = [spare_at[b] for b in g.buses if b in spare_at]
        caps = [c for c in (max(headroom, 0.0) if g.firm_mw > 0 else None, sum(fed) if fed else None)
                if c is not None]
        mw_n1, outage = stranded.get(g.region_id, (0.0, None))
        out.append(RegionYear(
            region_id=g.region_id, name=g.name, bsp=g.bsp,
            demand_mw=round(demand, 2), modelled_mw=round(float(modelled.loc[g.loads].sum()) + extra, 2),
            firm_mw=round(g.firm_mw, 2), headroom_mw=round(headroom, 2), p2_class=p2_class(demand),
            n1_at_risk_mw=round(mw_n1, 2), n1_outage=outage if mw_n1 > 0 else None,
            voltage_violation_bus_ids=bad, worst_vm_pu=round(worst_vm, 4) if worst_vm is not None else None,
            worst_vm_limit_pu=round(edge, 2) if edge is not None else None,
            demand_room_mw=round(min(caps), 2) if caps else None,
        ))
    return out


# --- alerts: one function per check -----------------------------------------------------------------
def _firm_alert(r: RegionYear, year: int) -> Alert | None:
    """Demand above firm capacity: a first circuit outage would interrupt the excess."""
    if r.firm_mw <= 0 and r.p2_class in ("A", "B"):
        return None  # no firm capacity published (a single-transformer site or a customer's own connection)
    shortfall = r.demand_mw - r.firm_mw
    if shortfall <= 0:
        return None
    allowed = p2_loss_allowed(r.p2_class, r.demand_mw)
    breach = allowed is not None and shortfall > allowed
    head = (f"{r.name} (class {r.p2_class}): peak demand {r.demand_mw:.1f} MW is {shortfall:.1f} MW above "
            f"its {r.firm_mw:.1f} MW firm capacity in {year}.")
    if breach:
        tail = (f" A simplified P2/8-style check lets only {allowed:.1f} MW wait for restoration after a first "
                "circuit outage. Reinforce the group or transfer demand to a neighbour.")
    else:
        tail = (" A first circuit outage would interrupt that demand until it is restored, which P2/8 can allow"
                " for this class (restoration and switching are not modelled). Plan reinforcement before it grows.")
    return Alert(kind="firm_capacity", level="breach" if breach else "warn", region_id=r.region_id, year=year,
                 value=round(r.demand_mw, 2), limit=round(r.firm_mw, 2), message=head + tail)


def _n1_alert(r: RegionYear, year: int) -> Alert | None:
    """A single 132 kV backbone outage cuts off demand in a class C or larger group."""
    allowed = p2_loss_allowed(r.p2_class, r.demand_mw)
    if allowed is None or r.n1_at_risk_mw < N1_ISLAND_MIN_MW:
        return None
    breach = r.n1_at_risk_mw > allowed
    return Alert(kind="n1_stranded", level="breach" if breach else "warn", region_id=r.region_id, year=year,
                 value=round(r.n1_at_risk_mw, 2), limit=round(allowed, 2),
                 message=(f"{r.name} (class {r.p2_class}): losing {r.n1_outage} at winter peak cuts off "
                          f"{r.n1_at_risk_mw:.1f} MW of its demand in {year}; a simplified P2/8-style check allows "
                          f"{allowed:.1f} MW to wait for restoration. Add a second supply route or automatic transfer."))


def _voltage_alert(r: RegionYear, year: int) -> Alert | None:
    """Customers' buses outside the statutory voltage band with the network intact."""
    if not r.voltage_violation_bus_ids or r.worst_vm_pu is None or r.worst_vm_limit_pu is None:
        return None
    low = r.worst_vm_pu < 1.0
    n = len(r.voltage_violation_bus_ids)
    return Alert(kind="voltage", level="breach", region_id=r.region_id, year=year, value=r.worst_vm_pu,
                 limit=r.worst_vm_limit_pu,
                 message=(f"{r.name}: {n} load bus{'es' if n != 1 else ''} outside the statutory voltage band in "
                          f"{year} with the network intact (worst {r.worst_vm_pu:.3f} pu, "
                          f"{'below' if low else 'above'} the {r.worst_vm_limit_pu:.2f} pu limit). "
                          "Check the tap changer range or reinforce the feeder."))


def _headroom_alert(r: RegionYear, year: int) -> Alert | None:
    """Firm headroom running low (but still positive)."""
    if r.firm_mw <= 0 or not (0 <= r.headroom_mw < HEADROOM_WARN_FRACTION * r.firm_mw):
        return None
    return Alert(kind="headroom", level="warn", region_id=r.region_id, year=year,
                 value=round(r.headroom_mw, 2), limit=round(HEADROOM_WARN_FRACTION * r.firm_mw, 2),
                 message=(f"{r.name}: only {r.headroom_mw:.1f} MW of firm headroom left in {year} "
                          f"({r.headroom_mw / r.firm_mw:.0%} of its {r.firm_mw:.1f} MW firm capacity). "
                          "New demand here will soon need reinforcement."))


# the demand-side checks, each (region, year) -> Alert | None; a new alert is one function + one entry
ALERT_CHECKS = (_firm_alert, _n1_alert, _voltage_alert, _headroom_alert)


def alerts_for(regions: list[RegionYear], year: int) -> list[Alert]:
    """Run every check in ALERT_CHECKS on every region; breaches first."""
    out = [a for r in regions for check in ALERT_CHECKS if (a := check(r, year)) is not None]
    return sorted(out, key=lambda a: (a.level != "breach", a.region_id, a.kind))


def assess_demand(net, year: int, n1_violations: list[dict] = ()) -> tuple[list[RegionYear], list[Alert]]:
    """The demand side of one solved year: its regions and their alerts (see the module docstring)."""
    regions = assess_regions(net, n1_violations)
    return regions, alerts_for(regions, year)
