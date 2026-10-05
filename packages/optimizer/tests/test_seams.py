"""The engine's extension seams: the network is injected, study cases are a registry."""

from gridforge_optimizer import OptimizeParams, optimize
from gridforge_optimizer.network import CASE_SPECS, _CASE_LABEL, _study_cases, build_base_net


def test_optimize_builds_its_networks_from_the_injected_factory():
    built = []

    def factory():
        built.append(1)
        return build_base_net()

    result = optimize([], OptimizeParams(), net_factory=factory)
    assert result.queue == []
    assert built  # every network came from the injected factory


def test_every_study_case_has_a_label_and_the_plain_net_gets_the_unconditional_ones():
    assert set(_CASE_LABEL) == {s.name for s in CASE_SPECS}
    net = build_base_net()
    for col in ("min_scale",):
        net.load = net.load.drop(columns=[col], errors="ignore")
    net.line = net.line.drop(columns=["summer_ratio"], errors="ignore")
    unconditional = [s.name for s in CASE_SPECS if s.load_column is None and s.rating_column is None]
    assert [c.name for c in _study_cases(net)] == unconditional


def test_n1_screen_starts_from_taps_settled_for_the_screened_case():
    """feasibility() leaves the taps settled for the LAST study case (summer minimum). The N-1 screen
    must not judge winter peak from those: after it, the intact winter-peak state is within limits."""
    from gridforge_optimizer.network import _case_reason, _run_case, feasibility, n1_screen

    net = build_base_net()
    assert feasibility(net)[0]
    winter = next(c for c in _study_cases(net) if c.name == "winter_peak")
    n1_screen(net)  # leaves the net with the pre-fault taps it settled for winter peak
    res = _run_case(net, "winter_peak", winter.load_scale, winter.rating_ratio, regulate=False)
    assert _case_reason(net, "winter_peak", res["vm"], res["line_pct"], res["trafo_pct"]) is None
