import pytest

from _grid import weak_buses
from gridforge_optimizer import Reinforcement
from gridforge_optimizer.config import MAX_CONNECTION_MW
from gridforge_optimizer.network import (
    apply_growth,
    apply_reinforcement,
    build_base_net,
    bus_voltages,
    feasibility,
    inject_sgen,
    line_loadings,
    per_bus_growth,
    voltage_violation_bus_ids,
)
from gridforge_optimizer.readiness import score_from_checklist


def test_base_feasible():
    ok, reason, m = feasibility(build_base_net())
    assert ok and reason is None
    assert 0.9 <= m["min_vm"] <= m["max_vm"] <= 1.1
    assert m["max_line_pct"] < 100


def test_apply_growth_increases_load():
    net = build_base_net()
    before = float((net.load["p_mw"] * net.load["scaling"]).sum())
    apply_growth(net, 1.25)
    after = float((net.load["p_mw"] * net.load["scaling"]).sum())
    assert after > before


def test_cluster_overload_is_infeasible():
    # heavy generation at the weakest connection buses overloads any finite network
    net = build_base_net()
    for b in weak_buses(net, 3):
        inject_sgen(net, b, MAX_CONNECTION_MW * 2)
    ok, reason, _ = feasibility(net)
    assert not ok
    assert reason.type in ("voltage", "line", "trafo", "non_convergent")


def test_per_bus_growth_preserves_feeder_total():
    """Spatial growth diverges per bus but the load-weighted mean equals the scenario multiplier."""
    net = build_base_net()
    p = net.load["p_mw"].astype(float)
    for m in (1.10, 1.30, 1.36):
        f = per_bus_growth(net, m, scenario="ht", horizon=2035)
        realised = float((f * p).sum() / p.sum())
        assert abs(realised - m) < 1e-6
        assert f.max() > f.min()  # genuinely heterogeneous, not uniform


def test_per_bus_growth_is_deterministic():
    net = build_base_net()
    a = per_bus_growth(net, 1.30, "ht", 2035)
    b = per_bus_growth(net, 1.30, "ht", 2035)
    assert a.equals(b)


def test_line_loadings_cover_every_line():
    net = build_base_net()
    feasibility(net)  # solves
    ll = line_loadings(net)
    assert len(ll) == len(net.line)
    assert all(v >= 0 for v in ll.values())


def test_bus_voltages_cover_every_bus_and_in_band_at_base():
    net = build_base_net()
    feasibility(net)  # solves
    vm = bus_voltages(net)
    assert len(vm) == len(net.res_bus)
    assert all(0.9 <= v <= 1.1 for v in vm.values())  # base network is feasible
    assert voltage_violation_bus_ids(net) == []


def test_apply_reinforcement_lowers_line_loading():
    # push current through the feeder from a weak bus, then reinforce its most-loaded line
    b = weak_buses(build_base_net(), 1)[0]
    mw = MAX_CONNECTION_MW * 0.5
    net = build_base_net()
    inject_sgen(net, b, mw)
    feasibility(net)  # solve
    ll = line_loadings(net)
    lid = max(ll, key=ll.get)
    before = ll[lid]
    assert before > 0

    # uprate doubles the thermal rating WITHOUT changing impedance -> current unchanged, loading halves
    up = build_base_net()
    inject_sgen(up, b, mw)
    apply_reinforcement(up, Reinforcement(kind="line", element_id=lid, action="uprate", factor=2.0))
    feasibility(up)
    assert line_loadings(up)[lid] == pytest.approx(before / 2, rel=0.02)

    # add_parallel (halves impedance AND doubles rating) also relieves the line
    par = build_base_net()
    inject_sgen(par, b, mw)
    apply_reinforcement(par, Reinforcement(kind="line", element_id=lid, action="add_parallel"))
    feasibility(par)
    assert line_loadings(par)[lid] < before


def test_readiness_rubric_is_monotonic_and_bounded():
    full = {"land_rights": "secured", "planning_status": "granted",
            "grid_connection_agreement": "signed", "financing": "committed", "commissioning_year": 2027}
    none = {"land_rights": "none", "planning_status": "none",
            "grid_connection_agreement": "none", "financing": "none", "commissioning_year": None}
    hi = score_from_checklist(full, reference_year=2026)["readiness_score"]
    lo = score_from_checklist(none, reference_year=2026)["readiness_score"]
    assert hi == 1.0  # every milestone secured, near-term -> full marks
    assert hi > lo
    assert 0.0 <= lo < 0.2
