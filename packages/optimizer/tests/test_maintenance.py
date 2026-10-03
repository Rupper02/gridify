"""Planned works (maintenance.py): work types, combined windows, the verdict and the "after".

Grid-agnostic: every element is found from the network itself (the most loaded line, a circuit whose
loss strands demand, a window that needs curtailment), never by a hardcoded id."""

import pytest
from _grid import base_net

from gridforge_optimizer import OptimizeParams, Outage
from gridforge_optimizer.config import N1_ISLAND_MIN_MW
from gridforge_optimizer.maintenance import WORKS, study_windows
from gridforge_optimizer.network import (
    _case_reason,
    _gsp_reason,
    _islanded_mw,
    _run_case,
    _study_cases,
    feasibility,
    n1_screen,
)
from gridforge_optimizer.years import evaluate_year

PARAMS = OptimizeParams()
YEAR = 2030


def _year(year, outages=(), **kw):
    return evaluate_year(year, [], PARAMS, {}, outages=list(outages), n1=False, **kw)


@pytest.fixture(scope="module")
def plain():
    return {y: _year(y) for y in (YEAR - 1, YEAR, YEAR + 1)}


@pytest.fixture(scope="module")
def settled():
    """A base net with its taps settled, as evaluate_year hands it to study_windows."""
    net = base_net()
    feasibility(net)
    return net


def _window(oid, element_kind, element_id, season="Summer", year=YEAR, **kw):
    return Outage(outage_id=oid, element_kind=element_kind, element_id=str(element_id), season=season, year=year, **kw)


def _first_line_with(net, verdict, season="Summer"):
    """The first line (highest voltage first) whose window alone gets `verdict`, with its study."""
    for lid in sorted(net.line.index, key=lambda i: (-net.bus.at[net.line.at[i, "from_bus"], "vn_kv"], i)):
        s = study_windows(net, [_window("probe", "line", int(lid), season=season)])[0]
        if s.verdict == verdict:
            return int(lid), s
    pytest.skip(f"no single-line {season} window is '{verdict}' on this grid")


# --- the after ---------------------------------------------------------------------------------
def test_repowering_a_line_raises_its_rating_from_the_following_year_only(plain):
    line = max(plain[YEAR].line_loading, key=plain[YEAR].line_loading.get)
    rp = _window("rp", "line", line, year=YEAR - 1, work="repowering", repower="uprate", factor=2.0)
    before, during, after = _year(YEAR - 2, [rp]), _year(YEAR - 1, [rp]), _year(YEAR, [rp])
    assert before.line_loading == _year(YEAR - 2).line_loading
    assert during.line_loading == plain[YEAR - 1].line_loading  # the window year is as it was
    assert after.line_loading[line] == pytest.approx(plain[YEAR].line_loading[line] / 2, abs=0.2)
    assert after.bus_vm == plain[YEAR].bus_vm  # an uprate is thermal only: impedance, and so voltage, unchanged
    assert during.outage_studies[0].after.startswith(f"from {YEAR}")


def test_add_parallel_repowering_relieves_the_line_in_later_years(plain):
    line = max(plain[YEAR].line_loading, key=plain[YEAR].line_loading.get)
    rp = _window("rp", "line", line, year=YEAR - 1, work="repowering", repower="add_parallel")
    assert _year(YEAR, [rp]).line_loading[line] < plain[YEAR].line_loading[line]


def test_repowering_a_generator_raises_its_export_in_later_years(plain):
    rp = _window("g", "gen", "EX-3000", year=YEAR - 1, work="repowering", repower="uprate", factor=1.5)
    assert _year(YEAR, [rp]).gsp_export_mw > plain[YEAR].gsp_export_mw


def test_replacement_and_maintenance_leave_later_years_as_they_were(plain):
    line = max(plain[YEAR].line_loading, key=plain[YEAR].line_loading.get)
    for work in ("replacement", "maintenance"):
        w = _window("w", "line", line, year=YEAR - 1, work=work)
        later = _year(YEAR, [w])
        assert later.line_loading == plain[YEAR].line_loading and later.bus_vm == plain[YEAR].bus_vm
    assert WORKS["replacement"].after is None and WORKS["maintenance"].after is None


def test_replacement_takes_the_element_fully_out_even_if_asked_to_derate(settled):
    line = int(settled.line.index[0])
    derate = study_windows(settled, [_window("d", "line", line, kind="derate")])[0]
    replace = study_windows(settled, [_window("r", "line", line, kind="derate", work="replacement")])[0]
    out = study_windows(settled, [_window("o", "line", line)])[0]
    assert replace.worst_line_loading_pct == out.worst_line_loading_pct != derate.worst_line_loading_pct


# --- combined windows ------------------------------------------------------------------------------
def test_windows_in_the_same_season_and_year_are_studied_together(settled):
    a, b = (int(i) for i in settled.line.index[:2])
    w1, w2 = _window("a", "line", a), _window("b", "line", b)
    w3 = _window("c", "line", a, season="Winter")
    studies = study_windows(settled, [w1, w2, w3])
    assert [s.outage_id for s in studies] == ["a", "b", "c"]
    assert studies[0].with_ids == ["b"] and studies[1].with_ids == ["a"] and studies[2].with_ids == []
    # together they are one study: the same figures for both
    assert studies[0].worst_line_loading_pct == studies[1].worst_line_loading_pct
    assert "studied together with b" in studies[0].message


# --- verdicts ------------------------------------------------------------------------------------
def test_a_benign_window_is_feasible(settled):
    _, s = _first_line_with(settled, "feasible")
    assert s.ok and s.verdict == "feasible" and s.curtailment == [] and s.demand_at_risk_mw == 0.0
    assert s.message.split(". ")[1].startswith("Feasible")


def test_a_window_that_strands_demand_puts_it_at_risk(settled):
    _, s = _first_line_with(settled, "demand_at_risk", season="Winter")
    assert not s.ok and s.demand_at_risk_mw >= N1_ISLAND_MIN_MW
    assert s.violations and s.curtailment == [] and s.message.split(". ")[1].startswith("Demand at risk")


def test_a_thermal_breach_with_generation_nearby_is_cleared_by_curtailment(settled):
    line, s = _first_line_with(settled, "curtailment")
    assert not s.ok and s.violations and s.curtailed_mw > 0
    assert s.curtailed_mw == pytest.approx(sum(c.mw for c in s.curtailment))
    assert all(c.case == "summer_min" for c in s.curtailment)
    assert "first-order estimate" in s.message

    # the reported curtailment really holds every limit: apply it and re-solve
    net = settled
    case = next(c for c in _study_cases(net) if c.name == "summer_min")
    ratio = net.line["summer_ratio"] if "summer_ratio" in net.line.columns else case.rating_ratio
    rated0 = net.sgen["p_rated_mw"].copy()
    net.line.at[line, "in_service"] = False
    try:
        for c in s.curtailment:
            rows = net.sgen.index[(net.sgen.get("fleet_id") == c.id) | (net.sgen["name"] == c.id)]
            total = float(net.sgen.loc[rows, "p_rated_mw"].sum())
            net.sgen.loc[rows, "p_rated_mw"] = net.sgen.loc[rows, "p_rated_mw"] * max(0.0, 1 - c.mw / total)
        res = _run_case(net, "summer_min", case.load_scale, ratio)
        assert _islanded_mw(net, res["vm"])[0] < N1_ISLAND_MIN_MW
        assert (_case_reason(net, "summer_min", res["vm"], res["line_pct"], res["trafo_pct"])
                or _gsp_reason(net, -res["p_ext_mw"], "summer_min")) is None
    finally:
        net.line.at[line, "in_service"] = True
        net.sgen["p_rated_mw"] = rated0


def test_a_curtailment_study_leaves_the_years_own_results_untouched(settled, plain):
    line, _ = _first_line_with(settled, "curtailment")
    yr = _year(YEAR, [_window("c", "line", line)])
    assert yr.outage_studies[0].verdict == "curtailment"
    assert yr.bus_vm == plain[YEAR].bus_vm and yr.line_loading == plain[YEAR].line_loading
    assert yr.gsp_export_mw == plain[YEAR].gsp_export_mw  # the generators' ratings are put back


@pytest.mark.n1
def test_the_n1_screen_runs_with_the_window_in_place(settled):
    line = int(settled.line.index[0])
    s = study_windows(settled, [_window("n", "line", line, season="Spring")], screen=n1_screen)[0]
    assert s.n1_during is not None and s.n1_during.cases == s.cases == ["winter_peak", "summer_min"]
    assert s.n1_during.screened > 0 and s.n1_during.second_fault_at_risk_mw >= 0.0
    # without a screen (a year solved without N-1) there is no N-1 during the window
    assert study_windows(settled, [_window("n", "line", line)])[0].n1_during is None
