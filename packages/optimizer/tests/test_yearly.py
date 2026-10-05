"""The plan year by year (years.py) and planned outages (maintenance.study_windows; work types,
verdicts and repowering in test_maintenance.py)."""

import pytest
from _grid import base_net, fleet_generator, stiff_bus

from gridforge_optimizer import Candidate, OptimizeParams, Outage, evaluate_years, optimize, year_order
from gridforge_optimizer.network import interpolate_growth_for_year
from gridforge_optimizer.years import energisation_years, evaluate_year

PARAMS = OptimizeParams()


def test_growth_interpolates_between_the_plan_anchors():
    assert interpolate_growth_for_year(2026, 1.08, 1.35) == 1.0
    assert interpolate_growth_for_year(2028, 1.08, 1.35) == pytest.approx(1.04)
    assert interpolate_growth_for_year(2030, 1.08, 1.35) == pytest.approx(1.08)
    assert interpolate_growth_for_year(2032, 1.08, 1.35) == pytest.approx(1.188)
    assert interpolate_growth_for_year(2035, 1.08, 1.35) == pytest.approx(1.35)
    assert interpolate_growth_for_year(2040, 1.08, 1.35) == pytest.approx(1.35)


def test_year_order_solves_the_viewed_year_first_then_the_horizons():
    assert year_order(2028) == [2028, 2030, 2035, 2026, 2027, 2029, 2031, 2032, 2033, 2034]
    assert year_order(None)[:2] == [2030, 2035]
    assert sorted(year_order(2031)) == list(range(2026, 2036))


def test_energisation_follows_the_schedule_else_the_recommendation():
    sb = stiff_bus(base_net())
    cands = [Candidate(request_id=f"P{i}", bus_id=sb, technology="solar", rating_mw=5.0, commissioning_year=2028)
             for i in range(2)]
    res = optimize(cands, PARAMS)
    years = energisation_years(res, {"P1": 2033})
    assert years["P0"] == next(q.recommended_year for q in res.queue if q.request_id == "P0")
    assert years["P1"] == 2033


@pytest.fixture(scope="module")
def stiff():
    return stiff_bus(base_net())


def test_a_project_is_in_service_only_from_its_year(stiff):
    cand = Candidate(request_id="PV", bus_id=stiff, technology="solar", rating_mw=20.0)
    before = evaluate_year(2028, [cand], PARAMS, {"PV": 2029}, n1=False)
    after = evaluate_year(2029, [cand], PARAMS, {"PV": 2029}, n1=False)
    assert before.energised == [] and after.energised == ["PV"]
    # summer minimum, everything exporting: the 20 MW shows up at the GSP
    assert after.gsp_export_mw - before.gsp_export_mw == pytest.approx(20.0, abs=3.0)


def test_a_demand_connection_lowers_the_gsp_export(stiff):
    load = Candidate(request_id="DC", bus_id=stiff, technology="demand", rating_mw=0.0, import_mw=40.0)
    without = evaluate_year(2030, [], PARAMS, {}, n1=False)
    with_dc = evaluate_year(2030, [load], PARAMS, {"DC": 2030}, n1=False)
    assert with_dc.gsp_export_mw < without.gsp_export_mw  # it soaks up export at summer minimum too
    assert with_dc.energised == ["DC"]


def test_a_demand_connection_is_rankable_with_zero_export(stiff):
    load = Candidate(request_id="DC", bus_id=stiff, technology="demand", rating_mw=0.0, import_mw=10.0)
    res = optimize([load], PARAMS)
    assert res.queue[0].status in ("Phase1", "Phase2")


def _intact(year=2030):
    return evaluate_year(year, [], PARAMS, {}, n1=False)


def test_a_summer_outage_is_studied_at_summer_minimum_only():
    net = base_net()
    line = int(net.line.index[0])
    o = Outage(outage_id="o1", element_kind="line", element_id=str(line), season="Summer", year=2030)
    yr = evaluate_year(2030, [], PARAMS, {}, outages=[o], n1=False)
    assert [s.cases for s in yr.outage_studies] == [["summer_min"]]


def test_a_winter_outage_is_studied_at_winter_peak_and_spring_at_both():
    net = base_net()
    line = str(int(net.line.index[0]))
    w = Outage(outage_id="w", element_kind="line", element_id=line, season="Winter", year=2030)
    s = Outage(outage_id="s", element_kind="line", element_id=line, season="Spring", year=2030)
    yr = evaluate_year(2030, [], PARAMS, {}, outages=[w, s], n1=False)
    assert [x.cases for x in yr.outage_studies] == [["winter_peak"], ["winter_peak", "summer_min"]]


def test_derating_the_most_loaded_line_raises_its_loading():
    intact = _intact()
    worst = max(intact.line_loading, key=intact.line_loading.get)
    o = Outage(outage_id="d", element_kind="line", element_id=str(worst), season="Summer", year=2030, kind="derate")
    study = evaluate_year(2030, [], PARAMS, {}, outages=[o], n1=False).outage_studies[0]
    assert study.worst_line_loading_pct > 1.8 * intact.line_loading[worst]


def test_an_existing_generator_outage_lowers_the_export():
    intact = _intact()
    o = Outage(outage_id="g", element_kind="gen", element_id=fleet_generator(base_net()), season="Summer", year=2030)
    study = evaluate_year(2030, [], PARAMS, {}, outages=[o], n1=False).outage_studies[0]
    assert study.gsp_export_mw < intact.gsp_export_mw


def test_an_outage_only_counts_in_its_own_year():
    o = Outage(outage_id="o", element_kind="line", element_id="0", season="Summer", year=2031)
    assert evaluate_year(2030, [], PARAMS, {}, outages=[o], n1=False).outage_studies == []


def test_evaluate_years_reports_each_year_as_it_lands(stiff):
    cands = [Candidate(request_id="PV", bus_id=stiff, technology="solar", rating_mw=10.0, commissioning_year=2028)]
    res = optimize(cands, PARAMS)
    seen = []
    years = evaluate_years(res, cands, PARAMS, view_year=2033, years=[2027, 2030, 2033],
                           on_year=lambda y: seen.append(y.year))
    assert seen == [2033, 2030, 2027]
    assert list(years) == ["2027", "2030", "2033"]
    rec = res.queue[0].recommended_year
    assert all(("PV" in y.energised) == (int(k) >= rec) for k, y in years.items())


def test_outage_studies_leave_the_years_own_results_untouched():
    """Regression: a study re-settles the tap changers with the element out; the year's intact
    results must not depend on whether an outage was studied in it."""
    net = base_net()
    outs = [Outage(outage_id=f"t{i}", element_kind="trafo", element_id=str(int(t)), season="Winter", year=2030)
            for i, t in enumerate(net.trafo.index[:6])]
    plain = evaluate_year(2030, [], PARAMS, {}, n1=False)
    studied = evaluate_year(2030, [], PARAMS, {}, outages=outs, n1=False)
    assert studied.bus_vm == plain.bus_vm and studied.line_loading == plain.line_loading


def test_an_outage_that_strands_demand_is_a_violation():
    """Regression: islanded demand used to vanish from the solve and read as 'within limits'."""
    from gridforge_optimizer.network import N1_ISLAND_MIN_MW, _islanded_mw, _run_case, _study_cases

    net = base_net()
    case = next(c for c in _study_cases(net) if c.name == "winter_peak")
    for lid in net.line.index:  # find a radial circuit whose loss strands material demand
        net.line.at[lid, "in_service"] = False
        res = _run_case(net, "winter_peak", case.load_scale, case.rating_ratio)
        net.line.at[lid, "in_service"] = True
        if res is not None and _islanded_mw(net, res["vm"])[0] >= N1_ISLAND_MIN_MW:
            break
    else:
        pytest.skip("no radial circuit strands demand on this grid")
    o = Outage(outage_id="isl", element_kind="line", element_id=str(int(lid)), season="Winter", year=2030)
    study = evaluate_year(2030, [], PARAMS, {}, outages=[o], n1=False).outage_studies[0]
    assert not study.ok and study.violations[0].type == "islanded"


def test_a_transformer_derate_keeps_its_impedance():
    from gridforge_optimizer.network import OUTAGE_APPLIERS

    net = base_net()
    t = int(net.trafo.index[0])
    vk, sn = float(net.trafo.at[t, "vk_percent"]), float(net.trafo.at[t, "sn_mva"])
    undo = OUTAGE_APPLIERS["trafo"](net, Outage(outage_id="d", element_kind="trafo", element_id=str(t), season="Summer", year=2030, kind="derate"))
    # ohmic impedance ~ vk% / sn: unchanged when both halve
    assert net.trafo.at[t, "vk_percent"] / net.trafo.at[t, "sn_mva"] == pytest.approx(vk / sn)
    undo()
    assert net.trafo.at[t, "sn_mva"] == sn and net.trafo.at[t, "vk_percent"] == vk


def test_the_year_cache_resolves_only_the_years_an_edit_touches(monkeypatch, stiff):
    import gridforge_optimizer.years as years_mod

    cands = [Candidate(request_id="PV", bus_id=stiff, technology="solar", rating_mw=10.0, commissioning_year=2028)]
    res = optimize(cands, PARAMS)
    solved = []
    real = years_mod.evaluate_year
    monkeypatch.setattr(years_mod, "evaluate_year", lambda y, *a, **k: solved.append(y) or real(y, *a, n1=False, **{x: v for x, v in k.items() if x != "n1"}))
    cache: dict = {}
    span = [2029, 2030, 2031]
    first = evaluate_years(res, cands, PARAMS, years=span, cache=cache)
    assert sorted(solved) == span
    solved.clear()
    # a maintenance window in 2030 touches 2030 only; nothing else re-solves
    o = Outage(outage_id="m", element_kind="line", element_id=str(int(base_net().line.index[0])), season="Summer", year=2030)
    again = evaluate_years(res, cands, PARAMS, years=span, outages=[o], cache=cache)
    assert solved == [2030]
    assert again["2029"] == first["2029"] and again["2030"].outage_studies
    solved.clear()
    # moving the project's year re-solves the years whose energised set changes
    evaluate_years(res, cands, PARAMS, years=span, outages=[o], scheduled={"PV": 2031}, cache=cache)
    rec = res.queue[0].recommended_year
    assert set(solved) == {y for y in span if (y >= rec) != (y >= 2031)}
