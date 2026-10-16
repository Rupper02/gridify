"""The plan year by year (years.py)."""

import pytest
from _grid import base_net, stiff_bus

from gridforge_optimizer import Connection, PlanParams, simulate, year_order
from gridforge_optimizer.network import interpolate_growth_for_year
from gridforge_optimizer.years import evaluate_year

PARAMS = PlanParams()


def test_growth_interpolates_between_the_plan_anchors():
    assert interpolate_growth_for_year(2026, 1.08, 1.35) == 1.0
    assert interpolate_growth_for_year(2028, 1.08, 1.35) == pytest.approx(1.04)
    assert interpolate_growth_for_year(2030, 1.08, 1.35) == pytest.approx(1.08)
    assert interpolate_growth_for_year(2032, 1.08, 1.35) == pytest.approx(1.188)
    assert interpolate_growth_for_year(2035, 1.08, 1.35) == pytest.approx(1.35)
    assert interpolate_growth_for_year(2040, 1.08, 1.35) == pytest.approx(1.35)


def test_year_order_solves_the_viewed_year_first():
    assert year_order(2028) == [2028, 2026, 2027, 2029, 2030, 2031, 2032, 2033, 2034, 2035]
    assert year_order(None) == list(range(2026, 2036))


@pytest.fixture(scope="module")
def stiff():
    return stiff_bus(base_net())


def test_a_connection_is_in_service_only_from_its_year(stiff):
    pv = Connection(request_id="PV", bus_id=stiff, technology="solar", rating_mw=20.0, year=2029)
    before = evaluate_year(2028, [pv], PARAMS)
    after = evaluate_year(2029, [pv], PARAMS)
    assert before.energised == [] and after.energised == ["PV"]
    # summer minimum, everything exporting: the 20 MW shows up at the GSP
    assert after.gsp_export_mw - before.gsp_export_mw == pytest.approx(20.0, abs=3.0)


def test_a_demand_connection_lowers_the_gsp_export(stiff):
    load = Connection(request_id="DC", bus_id=stiff, technology="demand", rating_mw=0.0, import_mw=40.0, year=2030)
    without = evaluate_year(2030, [], PARAMS)
    with_dc = evaluate_year(2030, [load], PARAMS)
    assert with_dc.gsp_export_mw < without.gsp_export_mw  # it soaks up export at summer minimum too
    assert with_dc.energised == ["DC"]


def test_simulate_reports_each_year_as_it_lands(stiff):
    pv = [Connection(request_id="PV", bus_id=stiff, technology="solar", rating_mw=10.0, year=2030)]
    seen = []
    res = simulate(pv, PARAMS, view_year=2033, years=[2027, 2030, 2033], on_year=lambda y: seen.append(y.year))
    assert seen == [2033, 2027, 2030]
    assert list(res.years) == ["2027", "2030", "2033"]
    assert all(("PV" in y.energised) == (int(k) >= 2030) for k, y in res.years.items())


def test_the_year_cache_resolves_only_the_years_an_edit_touches(monkeypatch, stiff):
    import gridforge_optimizer.years as years_mod

    solved = []
    real = years_mod.evaluate_year
    monkeypatch.setattr(years_mod, "evaluate_year", lambda y, *a, **k: solved.append(y) or real(y, *a, **k))
    cache: dict = {}
    span = [2029, 2030, 2031]
    pv = Connection(request_id="PV", bus_id=stiff, technology="solar", rating_mw=10.0, year=2030)
    first = simulate([pv], PARAMS, years=span, cache=cache)
    assert sorted(solved) == span
    solved.clear()
    # moving the connection to 2031 re-solves only 2030, the one year whose energised set changes
    again = simulate([pv.model_copy(update={"year": 2031})], PARAMS, years=span, cache=cache)
    assert solved == [2030]
    assert again.years["2029"] == first.years["2029"] and again.years["2031"] == first.years["2031"]
