from gridforge_optimizer.network import (
    apply_growth,
    build_base_net,
    feasibility,
    inject_sgen,
    line_loadings,
    per_bus_growth,
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
    net = build_base_net()
    for b in (155, 159, 157):
        inject_sgen(net, b, 18.0)
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
