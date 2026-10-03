"""NGED data rules: the base network is what exists TODAY; everything else is an optional project."""

import pytest

from gridforge_optimizer.config import MAX_CONNECTION_MW
from gridforge_optimizer.nged import DEMAND_DIVERSITY, _load, _num, build_nged_net, nged_candidates


def _live(rows, col):
    return [r for r in rows if str(r.get(col) or "").strip().lower() != "removed"]


def test_ltds_removed_equipment_is_not_in_todays_network():
    net = build_nged_net()
    mw = lambda rows: sum(_num(d["Current Year Max Demand"]) or 0.0 for d in rows)
    live_mw, all_mw = mw(_live(_load("demand"), "Status")), mw(_load("demand"))
    assert all_mw > live_mw  # the data does flag some demand as Removed…
    # …none of it is modelled, and every live MW is (incl. rows naming several busbars)
    assert float(net.load.p_mw.sum()) == pytest.approx(live_mw * DEMAND_DIVERSITY, rel=1e-6)
    removed_trafos = [t for t in _load("t2a") if str(t.get("Status")).lower() == "removed"]
    assert removed_trafos and len(net.trafo) <= len(_live(_load("t2a"), "Status"))


def test_projects_not_built_yet_are_registry_only():
    net = build_nged_net()
    registry = nged_candidates(MAX_CONNECTION_MW)
    tec = [c for c in registry if c["request_id"].startswith("TEC-")]
    assert tec, "the GSP-embedded transmission project is offered in the registry"
    # …but nothing from the registry is pre-loaded into today's network (only the existing fleet)
    names = set(net.sgen.name.astype(str))
    assert not any(c["request_id"] in names for c in registry)
    assert all(n.startswith("EX-") for n in names)


def test_demand_regions_are_the_live_ltds_table3_groups():
    from gridforge_optimizer.demand import regions_of
    from gridforge_optimizer.nged import _demand_group, nged_model

    live = [d for d in _live(_load("demand"), "Status") if _num(d["Current Year Max Demand"])]
    regions = {r["name"]: r for r in regions_of(build_nged_net())}
    assert set(regions) == {_demand_group(d) for d in live}  # one region per live demand group, none Removed
    assert "Warth Lane" not in regions  # LTDS marks it Removed
    for d in live:
        r = regions[_demand_group(d)]
        # firm capacity read as MVA, converted at the row's own power factor; peak is the row's own max demand
        pf = min(max(_num(d["Current Year Power Factor"]) or 0.95, 0.5), 1.0)
        assert r["firm_mw"] == pytest.approx((_num(d["Firm Capacity of Substation"]) or 0.0) * pf, abs=1e-3)
        assert r["peak_demand_mw"] == pytest.approx(_num(d["Current Year Max Demand"]), abs=1e-3)
        assert r["base_demand_mw"] == pytest.approx(_num(d["Current Year Max Demand"]) * DEMAND_DIVERSITY, abs=1e-3)
    m = nged_model()
    assert {ld["region_id"] for ld in m["loads"]} == {r["region_id"] for r in m["regions"]}


def test_new_beacon_road_is_above_its_firm_capacity_today():
    """NGED's own LTDS row: 14.38 MW maximum demand against a 14 MVA firm capacity (unity power factor)."""
    from gridforge_optimizer import OptimizeParams
    from gridforge_optimizer.years import evaluate_year

    yr = evaluate_year(2026, [], OptimizeParams(), {}, n1=False)
    r = next(x for x in yr.regions if x.name == "New Beacon Road")
    assert r.demand_mw == pytest.approx(14.38, abs=0.01) and r.firm_mw == pytest.approx(14.0)
    assert r.p2_class == "C" and r.headroom_mw < 0
    assert any(a.region_id == r.region_id and a.kind == "firm_capacity" for a in yr.alerts)
