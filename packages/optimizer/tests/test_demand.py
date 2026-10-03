"""The demand side (demand.py): regions, firm headroom, P2/8-style classes, N-1 stranding, alerts.

Grid-agnostic: regions and buses are read from whatever build_base_net() returns; NGED-specific
data rules (which substation, which firm figure) live in test_nged.py."""

import pytest
from _grid import base_net

from gridforge_optimizer import Candidate, OptimizeParams
from gridforge_optimizer.demand import (
    ALERT_CHECKS,
    alerts_for,
    assess_regions,
    p2_class,
    p2_loss_allowed,
    regions_of,
)
from gridforge_optimizer.network import build_base_net, feasibility, n1_screen, tap_positions
from gridforge_optimizer.types import RegionYear
from gridforge_optimizer.years import evaluate_year

PARAMS = OptimizeParams()


@pytest.fixture(scope="module")
def net():
    return base_net()


@pytest.fixture(scope="module")
def years():
    return {y: evaluate_year(y, [], PARAMS, {}, n1=False) for y in (2026, 2035)}


def _region_loads(net, rid):
    return net.load.index[net.load["region_id"] == rid]


def _primaries(net):
    return [r for r in regions_of(net) if r["level"] == "primary"]


def test_regions_cover_every_load_exactly_once(net):
    regions = regions_of(net)
    assert regions, "the base network's loads carry their demand group"
    ids = [r["region_id"] for r in regions]
    assert len(ids) == len(set(ids))
    primaries = _primaries(net)
    assert set(net.load["region_id"]) == {r["region_id"] for r in primaries}  # every load in one primary group
    assert sum(r["base_demand_mw"] for r in primaries) == pytest.approx(float(net.load["p_mw"].sum()), abs=0.01 * len(ids))
    for r in primaries:
        assert set(r["buses"]) == {int(b) for b in net.load.loc[_region_loads(net, r["region_id"]), "bus"]}


def test_a_bsp_group_is_its_primaries_seen_from_above_never_extra_demand(net):
    bsps = [r for r in regions_of(net) if r["level"] == "bsp"]
    if not bsps:
        pytest.skip("this network tags no BSP groups")
    for r in bsps:
        members = net.load.index[net.load["bsp_region_id"] == r["region_id"]]
        assert len(members), "a BSP group is made of the loads of its primaries"
        # its demand is theirs (no load of its own), at its own busbar
        assert r["base_demand_mw"] == pytest.approx(float(net.load.loc[members, "p_mw"].sum()), abs=1e-3)
        assert r["buses"], "it sits at its own busbar(s)"


def test_demand_grows_with_the_years(years):
    early = {r.region_id: r for r in years[2026].regions}
    late = {r.region_id: r for r in years[2035].regions}
    assert early.keys() == late.keys()
    assert sum(r.demand_mw for r in late.values()) > sum(r.demand_mw for r in early.values())
    assert all(late[k].demand_mw >= early[k].demand_mw for k in early)
    assert all(r.modelled_mw <= r.demand_mw for r in late.values())  # the power flow carries the diversified share


def test_headroom_is_firm_minus_demand(years):
    for r in years[2035].regions:
        assert r.headroom_mw == pytest.approx(r.firm_mw - r.demand_mw, abs=0.02)
        assert r.p2_class == p2_class(r.demand_mw)
        if r.demand_room_mw is not None:
            assert r.demand_room_mw >= 0
            if r.firm_mw > 0:
                assert r.demand_room_mw <= max(r.headroom_mw, 0.0) + 0.01


def test_p2_8_class_bands():
    bands = [(0.5, "A"), (1.0, "A"), (1.01, "B"), (12.0, "B"), (12.1, "C"), (60.0, "C"),
             (60.5, "D"), (300.0, "D"), (301.0, "E"), (1500.0, "E"), (1501.0, "F")]
    for mw, cls in bands:
        assert p2_class(mw) == cls, mw
    assert p2_loss_allowed("A", 0.8) is None and p2_loss_allowed("B", 8.0) is None
    assert p2_loss_allowed("C", 30.0) == pytest.approx(12.0)  # max(12 MW, 1/3 of the group)
    assert p2_loss_allowed("C", 45.0) == pytest.approx(15.0)
    assert p2_loss_allowed("D", 200.0) == pytest.approx(20.0)
    assert p2_loss_allowed("E", 800.0) == 0.0


def _biggest_region(net):
    """The biggest primary-level group (its buses are its loads' buses)."""
    return max(_primaries(net), key=lambda r: r["peak_demand_mw"])


def test_a_group_whose_firm_capacity_is_below_its_demand_raises_the_firm_alert():
    rid = _biggest_region(base_net())["region_id"]

    def starved():
        n = build_base_net()
        rows = n.load["region_id"] == rid
        n.load.loc[rows, "firm_mw"] = 0.25 * float((n.load.loc[rows, "peak_mw"]).sum())
        return n

    yr = evaluate_year(2026, [], PARAMS, {}, n1=False, net_factory=starved)
    r = next(x for x in yr.regions if x.region_id == rid)
    assert r.headroom_mw < 0
    alerts = [a for a in yr.alerts if a.region_id == rid and a.kind == "firm_capacity"]
    assert len(alerts) == 1
    a = alerts[0]
    assert a.value > a.limit and a.year == 2026 and a.level in ("warn", "breach")
    assert f"{a.limit:.1f} MW firm capacity" in a.message


def test_a_demand_connection_counts_toward_its_group(net):
    bus = _biggest_region(net)["buses"][0]
    # a bus shared by several groups of a level counts its projects toward the first (by region id)
    region = min((r for r in _primaries(net) if bus in r["buses"]), key=lambda r: r["region_id"])
    dc = Candidate(request_id="DC", bus_id=bus, technology="demand", rating_mw=0.0, import_mw=10.0)
    without = next(r for r in evaluate_year(2030, [], PARAMS, {}, n1=False).regions if r.region_id == region["region_id"])
    with_dc = next(r for r in evaluate_year(2030, [dc], PARAMS, {"DC": 2030}, n1=False).regions
                   if r.region_id == region["region_id"])
    assert with_dc.demand_mw - without.demand_mw == pytest.approx(10.0, abs=0.05)


def test_n1_stranding_is_attributed_to_the_islanded_group():
    n = build_base_net()
    feasibility(n)
    region = _biggest_region(n)
    fake = [{"outage_type": "line", "outage_id": 7, "type": "islanded", "islanded_bus_ids": region["buses"]}]
    taps = tap_positions(n)
    regions = {r.region_id: r for r in assess_regions(n, fake)}
    assert tap_positions(n) == taps  # the extra winter-peak solve leaves the year's taps as found
    hit = regions[region["region_id"]]
    assert hit.n1_at_risk_mw == pytest.approx(hit.demand_mw, abs=0.02) and hit.n1_outage == "line 7"
    island = set(region["buses"])
    for r in regions.values():
        if not island & set(next(x["buses"] for x in regions_of(n) if x["region_id"] == r.region_id)) \
                and not any(x["region_id"] == r.region_id and x["level"] == "bsp" for x in regions_of(n)):
            assert r.n1_at_risk_mw == 0.0 and r.n1_outage is None


@pytest.mark.n1
def test_the_real_n1_screen_reports_islanded_buses_the_regions_pick_up():
    n = build_base_net()
    feasibility(n)
    screen = n1_screen(n)
    islands = [v for v in screen["violations"] if v["type"] == "islanded"]
    assert all(v["islanded_bus_ids"] for v in islands)
    feasibility(n)
    regions = assess_regions(n, screen["violations"])
    loaded = {int(b) for b in n.load["bus"]}
    for v in islands:
        if loaded & set(v["islanded_bus_ids"]):
            assert any(r.n1_at_risk_mw > 0 for r in regions)


def _region(**kw):
    base = dict(region_id="r1", name="Somewhere", demand_mw=10.0, modelled_mw=5.5, firm_mw=20.0,
                headroom_mw=10.0, p2_class="B")
    return RegionYear(**{**base, **kw})


def test_alert_checks_are_one_function_each_and_restate_engine_figures():
    assert len(ALERT_CHECKS) == 4
    quiet = _region()
    assert alerts_for([quiet], 2030) == []
    # class C, firm far below demand: breach (more than P2/8 lets wait)
    big = _region(demand_mw=40.0, firm_mw=10.0, headroom_mw=-30.0, p2_class="C")
    (a,) = [x for x in alerts_for([big], 2031) if x.kind == "firm_capacity"]
    assert a.level == "breach" and a.value == 40.0 and a.limit == 10.0 and "40.0 MW" in a.message
    # class B a little over firm: a warning (restoration within 3 hours is allowed)
    (w,) = alerts_for([_region(demand_mw=10.5, firm_mw=10.0, headroom_mw=-0.5)], 2031)
    assert w.kind == "firm_capacity" and w.level == "warn"
    # no firm capacity published on a small group: nothing to judge
    assert alerts_for([_region(firm_mw=0.0, headroom_mw=-10.0)], 2031) == []
    # N-1 strands demand in a class C group beyond what may wait
    (s,) = alerts_for([_region(demand_mw=30.0, firm_mw=60.0, headroom_mw=30.0, p2_class="C",
                               n1_at_risk_mw=20.0, n1_outage="line 3")], 2031)
    assert s.kind == "n1_stranded" and s.level == "breach" and s.limit == 12.0 and "line 3" in s.message
    # load buses outside the band
    (v,) = alerts_for([_region(voltage_violation_bus_ids=[4], worst_vm_pu=0.93, worst_vm_limit_pu=0.94)], 2031)
    assert v.kind == "voltage" and v.level == "breach" and v.limit == 0.94
    # firm headroom under the warning margin
    (h,) = alerts_for([_region(demand_mw=19.5, headroom_mw=0.5)], 2031)
    assert h.kind == "headroom" and h.level == "warn"
    for x in (a, w, s, v, h):
        assert "—" not in x.message  # plain text, no em-dashes
