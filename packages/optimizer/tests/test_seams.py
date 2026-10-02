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
    assert len(built) == 3  # the need study + one net per phase (2030, 2035)


def test_every_study_case_has_a_label_and_the_plain_net_gets_the_unconditional_ones():
    assert set(_CASE_LABEL) == {s.name for s in CASE_SPECS}
    net = build_base_net()
    for col in ("min_scale",):
        net.load = net.load.drop(columns=[col], errors="ignore")
    net.line = net.line.drop(columns=["summer_ratio"], errors="ignore")
    unconditional = [s.name for s in CASE_SPECS if s.load_column is None and s.rating_column is None]
    assert [c.name for c in _study_cases(net)] == unconditional
