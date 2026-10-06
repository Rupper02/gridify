"""The best-window search (windows.best_windows): every (year, season) studied against that year's
plan, ranked deterministically. Grid-agnostic: the element is the network's own most loaded line."""

import pytest

from gridforge_optimizer import OptimizeParams, OptimizeResult, Outage, best_windows
from gridforge_optimizer.types import VERDICT_SEVERITY as VERDICT_RANK
from gridforge_optimizer.windows import SEASONS, rank_key
from gridforge_optimizer.years import evaluate_year

PARAMS = OptimizeParams()
EMPTY = OptimizeResult(params=PARAMS, queue=[], phases={})
YEARS = (2029, 2030)
SEAS = ("Winter", "Summer")


def _plain(year):
    return evaluate_year(year, [], PARAMS, {}, n1=False)


@pytest.fixture(scope="module")
def element():
    yr = _plain(YEARS[0])
    return ("line", str(max(yr.line_loading, key=yr.line_loading.get)))


@pytest.fixture(scope="module")
def ranked(element):
    return best_windows(EMPTY, [], PARAMS, element, YEARS, SEAS, n1=False)


def test_every_year_and_season_is_studied_once_and_ranked(ranked):
    assert sorted((o.year, o.season) for o in ranked) == sorted((y, s) for y in YEARS for s in SEAS)
    assert [o.rank for o in ranked] == list(range(1, len(ranked) + 1))
    keys = [rank_key(o) for o in ranked]
    assert keys == sorted(keys)
    assert all(o.verdict in VERDICT_RANK and o.message == o.study.message for o in ranked)


def test_each_window_is_the_same_study_the_year_would_report(ranked, element):
    o = ranked[-1]
    w = Outage(outage_id="w", element_kind=element[0], element_id=element[1], season=o.season, year=o.year)
    s = evaluate_year(o.year, [], PARAMS, {}, outages=[w], n1=False).outage_studies[0]
    assert (s.verdict, s.curtailed_mw, s.demand_at_risk_mw, s.worst_line_loading_pct) == (
        o.verdict, o.curtailed_mw, o.demand_at_risk_mw, o.worst_line_loading_pct)


def test_without_n1_no_window_is_screened(ranked):
    assert all(o.n1_findings is None and o.study.n1_during is None for o in ranked)


def test_n1_is_screened_for_the_shortlist_only(element):
    opts = best_windows(EMPTY, [], PARAMS, element, [YEARS[0]], SEAS, n1_shortlist=1)
    assert opts[0].n1_findings is not None and opts[0].study.n1_during is not None
    assert all(o.n1_findings is None for o in opts[1:])
    plain = best_windows(EMPTY, [], PARAMS, element, [YEARS[0]], SEAS, n1=False)
    assert (opts[0].year, opts[0].season) == (plain[0].year, plain[0].season)  # the shortlist is the best of pass 1


def test_the_shortlist_takes_the_best_of_each_season_first(ranked):
    from gridforge_optimizer.windows import _shortlist
    short = _shortlist(ranked, 2)
    assert {o.season for o in short} == set(SEAS)
    assert short[0] is ranked[0]
    assert len(_shortlist(ranked, 3)) == 3 and _shortlist(ranked, 1) == [ranked[0]]


def test_a_window_in_the_same_season_is_studied_together(element):
    other = Outage(outage_id="keep", element_kind=element[0], element_id=element[1], season="Summer", year=YEARS[0])
    opts = best_windows(EMPTY, [], PARAMS, element, [YEARS[0]], ["Summer", "Winter"], outages=[other], n1=False)
    by_season = {o.season: o for o in opts}
    assert by_season["Summer"].study.with_ids == ["keep"] and by_season["Winter"].study.with_ids == []


def test_a_repowering_probed_in_one_year_does_not_change_the_next(element):
    rp = dict(work="repowering", repower="uprate", factor=2.0, n1=False)
    both = best_windows(EMPTY, [], PARAMS, element, YEARS, ["Summer"], **rp)
    alone = best_windows(EMPTY, [], PARAMS, element, [YEARS[1]], ["Summer"], **rp)
    later = next(o for o in both if o.year == YEARS[1])
    assert later.worst_line_loading_pct == alone[0].worst_line_loading_pct


def test_ranking_prefers_verdict_then_curtailment_then_the_earliest_window(ranked):
    # the order, from a clean window (the grid's own best window may already put demand at risk)
    a = ranked[0].model_copy(update={"verdict": "feasible", "curtailed_mw": 0.0, "demand_at_risk_mw": 0.0})
    worse = a.model_copy(update={"verdict": "not_feasible"})
    curtailed = a.model_copy(update={"verdict": "curtailment", "curtailed_mw": 1.0})
    more = a.model_copy(update={"verdict": "curtailment", "curtailed_mw": 5.0})
    later = a.model_copy(update={"year": a.year + 1})
    assert rank_key(a) < rank_key(curtailed) < rank_key(more) < rank_key(worse)
    assert rank_key(a) < rank_key(later)


def test_bad_requests_are_refused(element):
    with pytest.raises(ValueError, match="not in the network model"):
        best_windows(EMPTY, [], PARAMS, ("line", "999999"), [YEARS[0]], ["Summer"], n1=False)
    with pytest.raises(ValueError, match="seasons"):
        best_windows(EMPTY, [], PARAMS, element, [YEARS[0]], ["Monsoon"], n1=False)
    with pytest.raises(ValueError, match="work"):
        best_windows(EMPTY, [], PARAMS, element, [YEARS[0]], SEASONS, work="demolition", n1=False)
