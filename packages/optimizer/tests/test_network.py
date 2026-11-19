import pytest

from _grid import stiff_bus, weak_buses
from gridify_optimizer.config import MAX_CONNECTION_MW
from gridify_optimizer.network import (
    _study_cases,
    build_base_net,
    bus_voltages,
    feasibility,
    inject_sgen,
    line_loadings,
    voltage_violation_bus_ids,
)
from gridify_optimizer.readiness import score_from_checklist


def test_base_feasible():
    ok, breaches, m = feasibility(build_base_net())
    assert ok and breaches == []
    assert 0.9 <= m["min_vm"] <= m["max_vm"] <= 1.1
    assert m["max_line_pct"] < 100


def test_cluster_overload_is_infeasible():
    # heavy generation at the weakest connection buses overloads any finite network
    net = build_base_net()
    for b in weak_buses(net, 3):
        inject_sgen(net, b, MAX_CONNECTION_MW * 2)
    ok, breaches, _ = feasibility(net)
    assert not ok
    assert breaches[0].type in ("voltage", "line", "trafo", "non_convergent")


def test_bus_voltages_cover_every_bus_and_in_band_at_base():
    net = build_base_net()
    feasibility(net)  # solves
    vm = bus_voltages(net)
    assert len(vm) == len(net.res_bus)
    assert all(0.9 <= v <= 1.1 for v in vm.values())  # base network is feasible
    assert voltage_violation_bus_ids(net) == []


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


def test_gsp_export_limit_binds():
    net = _exporting_net()
    _, _, m = feasibility(net)
    net["gsp_export_limit_mw"] = m["gsp_export_mw"] - 1.0  # just below what the region exports
    ok, breaches, _ = feasibility(net)
    gsp = [r for r in breaches if r.type == "gsp"]
    assert not ok and gsp and gsp[0].value == pytest.approx(m["gsp_export_mw"], abs=0.2)


def test_growing_to_a_horizon_adds_no_generation():
    # the base is what exists today; anything not built yet enters only as a connection on a branch —
    # bringing the network to 2035 grows demand but never pre-loads generation
    from gridify_optimizer.network import grow_for
    from gridify_optimizer.types import PlanParams

    net = build_base_net()
    n0, p0 = len(net.sgen), float(net.sgen.p_mw.sum())
    assert grow_for(net, PlanParams(), 2035) > 1.0
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


def test_a_technology_name_is_read_whatever_its_case_or_spacing():
    """Regression: "Solar" was not found in the per-case factors and ran as firm generation (full output at winter
    peak) instead of nil."""
    from gridify_optimizer import Connection
    from gridify_optimizer.config import GENERATION_FACTORS

    c = Connection(request_id="CR-1", bus_id=0, technology=" Solar ", rating_mw=1.0, year=2026)
    assert c.technology == "solar"
    assert c.technology in GENERATION_FACTORS["winter_peak"]
