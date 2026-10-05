import pytest

from _grid import stiff_bus, weak_buses
from gridforge_optimizer import Reinforcement
from gridforge_optimizer.config import MAX_CONNECTION_MW
from gridforge_optimizer.network import (
    _study_cases,
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


def test_bus_voltages_cover_every_bus_and_in_band_at_base():
    net = build_base_net()
    feasibility(net)  # solves
    vm = bus_voltages(net)
    assert len(vm) == len(net.res_bus)
    assert all(0.9 <= v <= 1.1 for v in vm.values())  # base network is feasible
    assert voltage_violation_bus_ids(net) == []


def test_apply_reinforcement_lowers_line_loading():
    # push a modest, convergent amount of current through the feeder, then reinforce its most-loaded
    # line. A fixed small injection keeps the solve well-conditioned regardless of the base fleet/cap.
    b = weak_buses(build_base_net(), 1)[0]
    mw = 15.0
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


def _exporting_net():
    """The base net, made to export to transmission (adds generation at the stiff bus if needed)."""
    net = build_base_net()
    _, _, m = feasibility(net)
    if m["gsp_export_mw"] <= 0:
        inject_sgen(net, stiff_bus(net), m["gsp_import_mw"] + 10.0)
    return net


def test_feasibility_reports_gsp_exchange_and_worst_case_envelope():
    net = build_base_net()
    ok, _, m = feasibility(net)
    assert ok
    assert m["gsp_export_mw"] >= 0 and m["gsp_import_mw"] >= 0
    # per-element results left on the net are the worst case across the study cases
    assert max(line_loadings(net).values()) == pytest.approx(m["max_line_pct"], abs=0.1)


def test_summer_minimum_case_pushes_export_up():
    # generation is judged at minimum demand too: less local load to soak it up -> more export
    both = _exporting_net()
    both.load["min_scale"], both.line["summer_ratio"] = 0.5, 1.0
    assert [c[0] for c in _study_cases(both)] == ["winter_peak", "summer_min"]
    winter_only = _exporting_net()
    winter_only.load = winter_only.load.drop(columns=["min_scale"], errors="ignore")
    winter_only.line = winter_only.line.drop(columns=["summer_ratio"], errors="ignore")
    assert [c[0] for c in _study_cases(winter_only)] == ["winter_peak"]
    assert feasibility(both)[2]["gsp_export_mw"] > feasibility(winter_only)[2]["gsp_export_mw"]


def test_gsp_export_limit_binds_and_a_new_sgt_relieves_it():
    net = _exporting_net()
    _, _, m = feasibility(net)
    net["gsp_export_limit_mw"] = m["gsp_export_mw"] - 1.0  # just below what the region exports
    net["gsp_sgt_mw"] = 100.0
    ok, reason, _ = feasibility(net)
    assert not ok and reason.type == "gsp" and reason.value == pytest.approx(m["gsp_export_mw"], abs=0.2)
    apply_reinforcement(net, Reinforcement(kind="gsp", element_id=0))  # one more supergrid transformer
    assert feasibility(net)[0]


def test_growing_to_a_horizon_adds_no_generation():
    # the base is what exists today; anything not built yet enters only as a queue project —
    # bringing the network to 2035 grows demand but never pre-loads generation
    from gridforge_optimizer.network import grow_demand

    net = build_base_net()
    n0, p0 = len(net.sgen), float(net.sgen.p_mw.sum())
    grow_demand(net, 1.35, "ht", 2035)
    assert len(net.sgen) == n0 and float(net.sgen.p_mw.sum()) == pytest.approx(p0)


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
