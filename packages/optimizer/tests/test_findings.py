"""The findings ledger's input: a flat, stable, value-independent list of what a plan carries."""

import re

from _grid import base_net, saturating_candidates
from gridforge_optimizer import (
    Alert,
    OptimizeParams,
    OptimizeResult,
    OutageStudy,
    QueueItem,
    Reason,
    YearResult,
    against_recommendation,
    evaluate_year,
    extract_findings,
)
from gridforge_optimizer.findings import EXTRACTORS


def _qi(rid, status, rank=1, reason=None, recommended=None):
    return QueueItem(rank=rank, request_id=rid, bus_id=1, technology="solar", rating_mw=5.0, readiness_score=0.5,
                     strategic_fit=0.5, grid_need=0.5, rank_score=0.5, status=status, reason=reason,
                     recommended_year=recommended)


def _yr(year, line=None, trafo=None, *, vm=None, viol=(), gsp=0.0, limit=None, n1=(), alerts=(), studies=(),
        converged=True):
    line, trafo, vm = line or {1: 50.0}, trafo or {1: 50.0}, vm or {}
    return YearResult(
        year=year, growth=1.0, worst_line_loading_pct=max(line.values()), worst_trafo_loading_pct=max(trafo.values()),
        min_vm_pu=min(vm.values(), default=1.0), max_vm_pu=max(vm.values(), default=1.0), accepted=[],
        overloaded_line_ids=[i for i, v in line.items() if v > 100], line_loading=line, trafo_loading=trafo,
        bus_vm=vm, voltage_violation_bus_ids=list(viol), gsp_export_mw=gsp, gsp_limit_mw=limit,
        n1_violations=list(n1), alerts=list(alerts), outage_studies=list(studies), converged=converged,
    )


def _res(queue=(), years=()):
    return OptimizeResult(params=OptimizeParams(), queue=list(queue), phases={}, years={str(y.year): y for y in years})


_N1 = {"outage_type": "line", "outage_id": 7, "outage_name": "x", "type": "islanded", "element_id": 3, "value": 2.5,
       "case": "winter_peak", "message": "line 7 out islands 2.5 MW of demand at 1 bus(es)"}


def _busy():
    """A synthetic result exercising every extractor."""
    alert = Alert(kind="firm_capacity", level="breach", region_id="R1", year=2031, value=12.0, limit=10.0, message="R1 over firm")
    study = OutageStudy(outage_id="w1", year=2031, cases=["summer_min"], ok=False, message="w1 needs 4 MW curtailed",
                        verdict="curtailment", curtailed_mw=4.0)
    years = [
        _yr(2030, line={1: 104.0, 2: 90.0}, trafo={5: 101.5}, vm={9: 0.93}, viol=[9], gsp=520.0, limit=527.0),
        _yr(2031, gsp=530.0, limit=527.0, n1=[_N1], alerts=[alert], studies=[study], converged=False),
    ]
    queue = [
        _qi("A", "Phase1", 1, recommended=2029),
        _qi("B", "Deferred", 2, reason=Reason(type="line", element_id=4, value=120.0, limit=100.0, message="line 4 overloaded", case="summer_min")),
        _qi("C", "Rejected", None, reason=Reason(type="rejected", message="above the intake cap")),
    ]
    return _res(queue, years)


def test_extracts_each_kind_from_a_synthetic_result():
    fs = extract_findings(_busy(), scheduled={"A": 2027})
    kinds = {f.kind for f in fs}
    assert kinds == {"overload", "voltage", "gsp_near_limit", "gsp_over_limit", "n1", "alert", "work", "deferred",
                     "rejected", "against_recommendation", "non_convergent"}
    by = {(f.kind, f.element_kind, f.element_id, f.year): f for f in fs}
    over = by[("overload", "line", "1", 2030)]
    assert over.severity == "breach" and over.value == 104.0 and over.limit == 100.0 and "line 1" in over.message
    assert by[("overload", "trafo", "5", 2030)].message.startswith("transformer 5")
    assert by[("voltage", "bus", "9", 2030)].value == 0.93
    assert by[("gsp_near_limit", "gsp", "gsp", 2030)].severity == "warn"
    assert by[("gsp_over_limit", "gsp", "gsp", 2031)].severity == "breach"
    n1 = by[("n1", "line", "7", 2031)]
    assert n1.case == "winter_peak" and n1.context["breach_type"] == "islanded"
    assert by[("alert", "region", "R1", 2031)].severity == "breach"
    work = by[("work", "outage", "w1", 2031)]
    assert work.severity == "warn" and work.value == 4.0 and work.context["verdict"] == "curtailment"
    dfr = by[("deferred", "project", "B", None)]
    assert dfr.severity == "warn" and dfr.context["grid"] is True and dfr.case == "summer_min"
    assert by[("rejected", "project", "C", None)].severity == "info"
    sched = by[("against_recommendation", "project", "A", None)]
    assert sched.value == 2027 and sched.limit == 2029
    assert by[("non_convergent", None, None, 2031)].severity == "breach"
    # breaches first, then warnings, then info
    sev = [f.severity for f in fs]
    assert sev == sorted(sev, key=lambda s: {"breach": 0, "warn": 1, "info": 2}[s])


def test_fingerprints_are_stable_unique_and_value_independent():
    a = extract_findings(_busy())
    b = extract_findings(_busy())
    assert [f.fingerprint for f in a] == [f.fingerprint for f in b]
    assert len({f.fingerprint for f in a}) == len(a)
    # the same overload, hotter: one identity
    hotter = _res(years=[_yr(2030, line={1: 109.0})])
    cooler = _res(years=[_yr(2030, line={1: 104.0})])
    [h], [c] = extract_findings(hotter), extract_findings(cooler)
    assert h.fingerprint == c.fingerprint and h.value != c.value
    # a project that stays deferred is one finding whatever binds it
    d1 = extract_findings(_res([_qi("B", "Deferred", 1, reason=Reason(type="line", message="l"))]))
    d2 = extract_findings(_res([_qi("B", "Deferred", 1, reason=Reason(type="voltage", message="v", case="winter_peak"))]))
    assert d1[0].fingerprint == d2[0].fingerprint


def test_a_clean_result_has_no_findings_and_every_extractor_is_registered():
    clean = _res([_qi("A", "Phase1", 1, recommended=2029)], [_yr(2030, gsp=100.0, limit=527.0)])
    assert extract_findings(clean, scheduled={"A": 2029}) == []
    assert len({e.__name__ for e in EXTRACTORS}) == len(EXTRACTORS)


def test_against_recommendation_truth_table():
    assert not against_recommendation(2030, None)
    assert not against_recommendation(2030, 2030)
    assert not against_recommendation(2030, 2032)
    assert against_recommendation(2030, 2029)
    assert against_recommendation(None, 2030)


def test_findings_from_a_real_year_name_elements_by_index():
    net = base_net()
    cand = saturating_candidates(net, n=1)[0]
    yr = evaluate_year(2030, [cand], OptimizeParams(), {cand.request_id: 2030}, n1=False)
    fs = extract_findings(_res(years=[yr]))
    assert all(isinstance(f.year, int) for f in fs)
    for f in fs:
        if f.kind in ("overload", "voltage"):
            assert re.match(r"^(line|transformer|bus) \d+ ", f.message), f.message
            assert f.value is not None
