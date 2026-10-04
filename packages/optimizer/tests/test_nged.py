"""NGED data rules: the base network is what exists TODAY; everything else is an optional project."""

import pytest

from gridforge_optimizer.config import MAX_CONNECTION_MW
from gridforge_optimizer.nged import GSP_PEAK_DEMAND_MW, _bsp_aggregates, _bsp_base, _load, _num, build_nged_net, nged_candidates


def _live(rows, col):
    return [r for r in rows if str(r.get(col) or "").strip().lower() != "removed"]


def _own_demand(rows):
    """Table 3 rows that are demand of their own: not a BSP's aggregate of the primaries below it."""
    agg = _bsp_aggregates(rows)
    return [d for d in rows if str(d.get("BSP Group") or "").strip() not in agg]


def test_ltds_removed_equipment_is_not_in_todays_network():
    net = build_nged_net()
    mw = lambda rows: sum(_num(d["Current Year Max Demand"]) or 0.0 for d in rows)
    live_mw, all_mw = mw(_live(_load("demand"), "Status")), mw(_load("demand"))
    assert all_mw > live_mw  # the data does flag some demand as Removed…
    # …none of it is modelled, and every live MW of its own is (incl. rows naming several busbars)
    assert float(net.load.peak_mw.sum()) == pytest.approx(mw(_own_demand(_live(_load("demand"), "Status"))), rel=1e-6)
    removed_trafos = [t for t in _load("t2a") if str(t.get("Status")).lower() == "removed"]
    assert removed_trafos and len(net.trafo) <= len(_live(_load("t2a"), "Status"))


def test_the_structure_the_ltds_leaves_open_is_recorded_not_filled():
    """NGED publishes the connectivity, not the running arrangement: the 132 kV bars of a substation
    are separate nodes with no coupler row, and the 33 kV network has no normal-open points. The
    model keeps both as published and says so, per element, instead of inventing a coupler or an
    open point."""
    net = build_nged_net()
    recs = net["assumptions"]
    split = recs["bus_sections_split"]
    names = {str(net.bus.at[b, "name"]) for b in split["element_ids"]}
    assert split["element_kind"] == "bus" and {"Boston 132kV 603", "Boston 132kV 503"} <= names
    joined = {frozenset((int(a), int(b))) for a, b in zip(net.line.from_bus, net.line.to_bus)}
    joined |= {frozenset((int(a), int(b))) for a, b in zip(net.trafo.hv_bus, net.trafo.lv_bus)}
    by_name = {str(net.bus.at[b, "name"]): int(b) for b in split["element_ids"]}
    assert frozenset((by_name["Boston 132kV 603"], by_name["Boston 132kV 503"])) not in joined  # nothing was invented between them
    assert len(net.switch) == 0
    # a substation whose bars are joined (Bicker Fen's one 132 kV bar, every 11 kV bar) is not flagged
    assert not any(n.startswith("Bicker Fen") for n in by_name)
    mesh = recs["mv_mesh_closed"]
    assert mesh["element_kind"] == "line" and len(mesh["element_ids"]) >= 2
    assert all(11.0 < float(net.bus.at[int(net.line.at[i, "from_bus"]), "vn_kv"]) < 132.0 for i in mesh["element_ids"])


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
    own = _own_demand(live)
    net = build_nged_net()
    regions = {r["name"]: r for r in regions_of(net)}
    bsps = {_bsp_base(d["BSP Group"]) + " BSP" for d in live if d not in own}
    assert set(regions) == {_demand_group(d) for d in own} | bsps  # one region per live demand group, none Removed
    assert "Warth Lane" not in regions  # LTDS marks it Removed
    for d in own:
        r = regions[_demand_group(d)]
        # firm capacity read as MVA, converted at the row's own power factor; peak is the row's own max demand
        pf = min(max(_num(d["Current Year Power Factor"]) or 0.95, 0.5), 1.0)
        assert r["firm_mw"] == pytest.approx((_num(d["Firm Capacity of Substation"]) or 0.0) * pf, abs=1e-3)
        assert r["peak_demand_mw"] == pytest.approx(_num(d["Current Year Max Demand"]), abs=1e-3)
        k = float(net.load.loc[net.load["region_id"] == r["region_id"], "coincidence"].iloc[0])
        assert r["base_demand_mw"] == pytest.approx(_num(d["Current Year Max Demand"]) * k, abs=1e-3)
    m = nged_model()
    assert {ld["region_id"] for ld in m["loads"]} == {r["region_id"] for r in m["regions"] if r["level"] == "primary"}


def test_winter_peak_demand_is_nesos_gsp_peak_and_summer_minimum_is_ltds_own():
    """No assumed diversity factor: today's winter-peak demand sums to NESO's FES figure for Bicker
    Fen at the GB peak, each BSP's primaries to the BSP's own published maximum (before the GSP
    step), and the summer minimum stays each row's maximum × its LTDS minimum-demand factor."""
    net = build_nged_net()
    load = net.load
    assert float(load.p_mw.sum()) == pytest.approx(GSP_PEAK_DEMAND_MW, rel=1e-9)
    live = _live(_load("demand"), "Status")
    agg = _bsp_aggregates(live)
    gsp = float(load.loc[load["bsp_region_id"].isna(), "coincidence"].iloc[0])  # rows with no BSP group: the GSP step only
    for base in {_bsp_base(b) for b in agg}:
        published = sum(_num(d["Current Year Max Demand"]) for d in live if d["BSP Group"] in agg and _bsp_base(d["BSP Group"]) == base)
        members = load[load["bsp"] == base]
        assert float(members.p_mw.sum()) / gsp == pytest.approx(published, rel=1e-9)
    has_min = load["min_scale"].notna()
    summer = float((load.loc[has_min, "p_mw"] * load.loc[has_min, "min_scale"].astype(float)).sum())
    rows = [d for d in _own_demand(live) if _num(d["Current Year Max Demand"])]
    own_min = sum(_num(d["Current Year Max Demand"]) * _num(str(d["Minimum demand Scaling Factor (%)"]).rstrip("%")) / 100.0
                  for d in rows if _num(str(d.get("Minimum demand Scaling Factor (%)") or "").rstrip("%")))
    assert summer == pytest.approx(own_min, rel=1e-9)


def test_a_bsps_own_rows_are_not_counted_twice():
    """Table 3 lists Sleaford's 132/33 kV transformers as rows of their own ("Sleaford (GT1)",
    "Sleaford (GT2)") and every primary they feed under "Sleaford": the GT rows are the same
    customers seen from the BSP. They add no load; the BSP is a parent group of its primaries,
    at its own busbar, with its published maximum demand and firm capacity."""
    from gridforge_optimizer.demand import regions_of

    live = _live(_load("demand"), "Status")
    agg = _bsp_aggregates(live)
    assert {"Sleaford (GT1)", "Sleaford (GT2)", "Grantham (GT1)", "Skegness (GT1)"} <= agg
    assert not any(_bsp_base(b) == b for b in agg)  # only a BSP's own transformer rows
    net = build_nged_net()
    agg_nodes = {d["Node"] for d in live if d["BSP Group"] in agg}
    regions = {r["name"]: r for r in regions_of(net)}
    gt = [d for d in live if _bsp_base(d["BSP Group"]) == "Sleaford" and d["BSP Group"] in agg]
    r = regions["Sleaford BSP"]
    assert r["level"] == "bsp"
    assert r["peak_demand_mw"] == pytest.approx(sum(_num(d["Current Year Max Demand"]) for d in gt), abs=1e-3)
    pf = min(max(_num(gt[0]["Current Year Power Factor"]) or 0.95, 0.5), 1.0)
    assert r["firm_mw"] == pytest.approx(min(_num(d["Firm Capacity of Substation"]) for d in gt) * pf, abs=1e-3)
    members = net.load[net.load["bsp_region_id"] == r["region_id"]]
    assert set(members["bsp"]) == {"Sleaford"}  # the primaries it feeds, nothing else
    assert agg_nodes and len(agg_nodes) == len(agg)


def test_new_beacon_road_is_above_its_firm_capacity_today():
    """NGED's own LTDS row: 14.38 MW maximum demand against a 14 MVA firm capacity (unity power factor)."""
    from gridforge_optimizer import OptimizeParams
    from gridforge_optimizer.years import evaluate_year

    yr = evaluate_year(2026, [], OptimizeParams(), {}, n1=False)
    r = next(x for x in yr.regions if x.name == "New Beacon Road")
    assert r.demand_mw == pytest.approx(14.38, abs=0.01) and r.firm_mw == pytest.approx(14.0)
    assert r.p2_class == "C" and r.headroom_mw < 0
    assert any(a.region_id == r.region_id and a.kind == "firm_capacity" for a in yr.alerts)
