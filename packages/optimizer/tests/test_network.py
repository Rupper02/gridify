from gridforge_optimizer.network import apply_growth, build_base_net, feasibility, inject_sgen


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
