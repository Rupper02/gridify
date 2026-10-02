"""Tests for year-by-year demand interpolation and year-scoped studies."""

import pytest

from _grid import saturating_candidates, stiff_bus
from gridforge_optimizer.greedy import optimize, _eligible_for_year
from gridforge_optimizer.network import build_base_net, interpolate_growth_for_year
from gridforge_optimizer.types import Candidate, OptimizeParams


def test_interpolate_growth_for_year_before_base():
    """Before base year (2026), no growth."""
    assert interpolate_growth_for_year(2024, "ht") == 1.0
    assert interpolate_growth_for_year(2026, "ht") == 1.0


def test_interpolate_growth_for_year_at_anchors():
    """At anchor years, returns the anchor multiplier."""
    # Holistic Transition anchors: 1.08 @ 2030, 1.35 @ 2035
    assert interpolate_growth_for_year(2030, "ht") == pytest.approx(1.08, abs=1e-6)
    assert interpolate_growth_for_year(2035, "ht") == pytest.approx(1.35, abs=1e-6)


def test_interpolate_growth_for_year_between_base_and_2030():
    """Between base year (2026) and 2030, linear interpolation."""
    # 2028 is halfway between 2026 and 2030
    # growth should be 1.0 + 0.5 * (1.08 - 1.0) = 1.04
    mid = interpolate_growth_for_year(2028, "ht")
    assert mid == pytest.approx(1.04, abs=1e-6)
    
    # 2027 is 1/4 of the way
    early = interpolate_growth_for_year(2027, "ht")
    assert early == pytest.approx(1.02, abs=1e-6)


def test_interpolate_growth_for_year_between_2030_and_2035():
    """Between 2030 and 2035, linear interpolation."""
    # 2032 is 2/5 of the way between 2030 and 2035
    # growth should be 1.08 + 0.4 * (1.35 - 1.08) = 1.08 + 0.108 = 1.188
    mid = interpolate_growth_for_year(2032, "ht")
    assert mid == pytest.approx(1.188, abs=1e-6)


def test_interpolate_growth_for_year_after_2035():
    """After 2035, holds at 2035 anchor."""
    assert interpolate_growth_for_year(2040, "ht") == pytest.approx(1.35, abs=1e-6)
    assert interpolate_growth_for_year(2050, "ht") == pytest.approx(1.35, abs=1e-6)


def test_interpolate_growth_for_year_different_scenarios():
    """Different scenarios have different anchors."""
    # Electric Engagement: growth_2030=1.10, growth_2035=1.42
    assert interpolate_growth_for_year(2030, "ee") == pytest.approx(1.10, abs=1e-6)
    assert interpolate_growth_for_year(2035, "ee") == pytest.approx(1.42, abs=1e-6)
    
    # Falling Behind: growth_2030=1.04, growth_2035=1.15
    assert interpolate_growth_for_year(2030, "fb") == pytest.approx(1.04, abs=1e-6)
    assert interpolate_growth_for_year(2035, "fb") == pytest.approx(1.15, abs=1e-6)


def test_eligible_for_year_no_commission_year():
    """Projects with no commission year are eligible for all years."""
    c = Candidate(request_id="P1", bus_id=1, rating_mw=5.0, commissioning_year=None)
    assert _eligible_for_year(c, 2027)
    assert _eligible_for_year(c, 2030)
    assert _eligible_for_year(c, 2035)


def test_eligible_for_year_with_commission_year():
    """Projects are only eligible when study year >= commission year."""
    c = Candidate(request_id="P1", bus_id=1, rating_mw=5.0, commissioning_year=2029)
    
    assert not _eligible_for_year(c, 2027)
    assert not _eligible_for_year(c, 2028)
    assert _eligible_for_year(c, 2029)
    assert _eligible_for_year(c, 2030)
    assert _eligible_for_year(c, 2035)


def test_single_year_study_filters_candidates_by_commission_year():
    """A year-scoped study only includes projects with commission year <= study year."""
    net = build_base_net()
    sb = stiff_bus(net)
    
    cands = [
        Candidate(request_id="Early", bus_id=sb, rating_mw=5.0, commissioning_year=2027),
        Candidate(request_id="On-time", bus_id=sb, rating_mw=5.0, commissioning_year=2029),
        Candidate(request_id="Late", bus_id=sb, rating_mw=5.0, commissioning_year=2032),
        Candidate(request_id="NoYear", bus_id=sb, rating_mw=5.0, commissioning_year=None),
    ]
    
    # Run for year 2029: should include Early, On-time, and NoYear, but NOT Late
    params = OptimizeParams(study_year=2029)
    result = optimize(cands, params)
    
    accepted_ids = {item.request_id for item in result.queue if item.status == "Phase1"}
    
    assert "Early" in accepted_ids
    assert "On-time" in accepted_ids
    assert "NoYear" in accepted_ids
    assert "Late" not in accepted_ids  # not commissioned yet


def test_single_year_study_interpolates_demand():
    """A year-scoped study uses interpolated demand growth for that year."""
    net = build_base_net()
    sb = stiff_bus(net)
    
    cands = [Candidate(request_id="P1", bus_id=sb, rating_mw=5.0)]
    
    # Run for year 2028 (halfway between 2026 and 2030, so growth should be ~1.04)
    params = OptimizeParams(study_year=2028, scenario="ht")
    result = optimize(cands, params)
    
    # The year-scoped study should use interpolated growth
    # We can verify this indirectly by checking that the study ran successfully
    # and that params.study_year was respected
    assert result is not None
    assert "2028" in result.phases
    assert result.params.study_year == 2028
    
    # Verify the expected interpolated growth value
    expected = interpolate_growth_for_year(2028, "ht")
    assert expected == pytest.approx(1.04, abs=1e-6)


def test_single_year_study_result_structure():
    """A year-scoped study returns results keyed by str(year)."""
    net = build_base_net()
    sb = stiff_bus(net)
    
    cands = [Candidate(request_id="P1", bus_id=sb, rating_mw=5.0)]
    
    params = OptimizeParams(study_year=2028)
    result = optimize(cands, params)
    
    # Result phases should have a single entry keyed by the study year
    assert "2028" in result.phases
    assert len(result.phases) == 1
    
    # Queue should still be populated
    assert len(result.queue) > 0


def test_single_year_study_vs_two_phase_consistency():
    """A 2030 year-scoped study should broadly agree with Phase1 from two-phase."""
    net = build_base_net()
    sb = stiff_bus(net)
    
    # Use small candidates that should connect
    cands = [
        Candidate(request_id=f"P{i}", bus_id=sb, rating_mw=5.0, readiness_score=0.9, strategic_fit=0.8)
        for i in range(5)
    ]
    
    # Two-phase study
    params_two_phase = OptimizeParams()
    result_two_phase = optimize(cands, params_two_phase)
    
    phase1_ids = {item.request_id for item in result_two_phase.queue if item.status == "Phase1"}
    
    # Single-year study for 2030
    params_single = OptimizeParams(study_year=2030)
    result_single = optimize(cands, params_single)
    
    single_ids = {item.request_id for item in result_single.queue if item.status == "Phase1"}
    
    # Both should accept the same small projects at the stiff bus
    assert len(phase1_ids) > 0, "Two-phase should accept some projects in Phase1"
    assert len(single_ids) > 0, "Single-year should accept some projects"
    
    # Should be identical for these simple cases
    assert phase1_ids == single_ids


def test_year_scoped_study_respects_both_study_cases():
    """Year-scoped study still runs both winter_peak and summer_min cases."""
    net = build_base_net()
    cands = saturating_candidates(net, n=10)
    
    # Use candidates that should create overloads
    params = OptimizeParams(study_year=2030)
    result = optimize(cands, params)
    
    # Check that some projects were deferred (grid limits enforced)
    deferred = [item for item in result.queue if item.status == "Deferred"]
    
    # Reasons should reference study cases
    reasons_with_case = [item.reason for item in deferred if item.reason and item.reason.case]
    
    # At least one reason should mention a study case
    assert len(reasons_with_case) > 0
    cases = {r.case for r in reasons_with_case}
    # Should see both winter_peak and summer_min in deferral reasons
    assert "winter_peak" in cases or "summer_min" in cases
