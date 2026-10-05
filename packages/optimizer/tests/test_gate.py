"""The merge gate: a pure policy over two results. Blocks what the branch introduces or worsens in
any plan year; what the parent already carries is context. Levels come from config.MERGE_GATE_LEVELS."""

from _grid import base_net, saturating_candidates
from gridforge_optimizer import (
    Alert,
    OptimizeParams,
    OptimizeResult,
    OutageStudy,
    QueueItem,
    Reason,
    YearResult,
    diff_results,
    evaluate_year,
    extract_findings,
    merge_verdict,
)
from gridforge_optimizer.config import (
    GATE_GSP_WORSEN_MW,
    GATE_VM_WORSEN_PU,
    GATE_WORSEN_PTS,
    GSP_NEAR_LIMIT_FRACTION,
    MERGE_GATE_LEVELS,
    PLAN_END_YEAR,
    PLAN_START_YEAR,
)
from gridforge_optimizer.gate import MERGE_CHECKS

PLAN = range(PLAN_START_YEAR, PLAN_END_YEAR + 1)


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


def _full(make, queue=(), scenario="ht"):
    """A result with every plan year, each built by `make(year)`."""
    return OptimizeResult(params=OptimizeParams(scenario=scenario), queue=list(queue), phases={},
                          years={str(y): make(y) for y in PLAN})


def _plain(year, **kw):
    return _yr(year, **kw)


def _kinds(xs):
    return [f.kind for f in xs]


def _n1(oid, kind="islanded", value=2.5, eid=3):
    return {"outage_type": "line", "outage_id": oid, "outage_name": f"l{oid}", "type": kind, "element_id": eid,
            "value": value, "message": f"line {oid} out breaks {eid}"}


# --- freshness and completeness -------------------------------------------------------------------
def test_no_result_blocks():
    v = merge_verdict(None, _full(_plain))
    assert not v.ok and _kinds(v.blockers) == ["no_result"] and "This branch" in v.blockers[0].message


def test_stale_blocks_with_its_reasons_and_silences_the_content_checks():
    head = _full(lambda y: _plain(y, line={1: 150.0}))  # would block on overloads if it were judged
    v = merge_verdict(head, _full(_plain), fresh=False, stale_reasons=["an energisation year changed"])
    assert _kinds(v.blockers) == ["stale"] and "energisation year" in v.blockers[0].message
    assert v.warnings == [] and v.context == []


def test_unstudied_years_block_and_name_the_side():
    head = OptimizeResult(params=OptimizeParams(), queue=[], phases={}, years={"2030": _plain(2030)})
    v = merge_verdict(head, _full(_plain))
    [b] = v.blockers
    assert b.kind == "unstudied_years" and b.message.startswith("This branch") and "2026 to 2029" in b.message
    v2 = merge_verdict(_full(_plain), head)
    assert v2.blockers[0].message.startswith("main")


# --- thermal, voltage, GSP -------------------------------------------------------------------------
def test_a_new_overload_blocks_and_a_preexisting_one_is_context():
    base = _full(lambda y: _plain(y, line={1: 90.0, 2: 105.0}))
    head = _full(lambda y: _plain(y, line={1: 104.0, 2: 105.0}) if y == 2031 else _plain(y, line={1: 90.0, 2: 105.0}))
    v = merge_verdict(head, base)
    assert not v.ok
    [b] = v.blockers
    assert (b.kind, b.element_kind, b.element_id, b.year, b.value, b.base_value) == ("new_overload", "line", "1", 2031, 104.0, 90.0)
    assert "line 1 newly over its rating in 2031" in b.message
    assert all(c.kind == "preexisting" and c.element_id == "2" for c in v.context) and len(v.context) == len(PLAN)
    assert v.years_compared == list(PLAN)


def test_an_existing_overload_that_worsens_blocks_only_past_the_threshold():
    base = _full(lambda y: _plain(y, trafo={5: 105.0}))
    a_little = _full(lambda y: _plain(y, trafo={5: 105.0 + GATE_WORSEN_PTS * 0.5}))
    a_lot = _full(lambda y: _plain(y, trafo={5: 105.0 + GATE_WORSEN_PTS * 3}))
    assert merge_verdict(a_little, base).ok
    v = merge_verdict(a_lot, base)
    assert {b.kind for b in v.blockers} == {"overload_worse"} and v.blockers[0].element_kind == "trafo"
    assert "transformer 5" in v.blockers[0].message


def test_voltage_new_blocks_and_worse_warns():
    base = _full(lambda y: _plain(y, vm={9: 0.935, 8: 1.0}, viol=[9]))
    head = _full(lambda y: _plain(y, vm={9: 0.935 - GATE_VM_WORSEN_PU * 2, 8: 0.92}, viol=[8, 9]))
    v = merge_verdict(head, base)
    assert {b.kind for b in v.blockers} == {"new_voltage_violation"} and {b.element_id for b in v.blockers} == {"8"}
    assert {w.kind for w in v.warnings} == {"voltage_worse"} and v.warnings[0].element_id == "9"
    steady = _full(lambda y: _plain(y, vm={9: 0.935, 8: 1.0}, viol=[9]))
    v2 = merge_verdict(steady, base)
    assert v2.ok and v2.warnings == [] and all(c.kind == "preexisting" for c in v2.context)


def test_gsp_newly_over_blocks_near_limit_warns_and_a_preexisting_breach_is_context():
    limit = 500.0
    base = _full(lambda y: _plain(y, gsp=400.0, limit=limit))
    over = _full(lambda y: _plain(y, gsp=510.0, limit=limit) if y == 2035 else _plain(y, gsp=400.0, limit=limit))
    near = _full(lambda y: _plain(y, gsp=limit * GSP_NEAR_LIMIT_FRACTION + 1, limit=limit) if y == 2035 else _plain(y, gsp=400.0, limit=limit))
    v = merge_verdict(over, base)
    assert _kinds(v.blockers) == ["gsp_over_limit"] and v.blockers[0].year == 2035
    v = merge_verdict(near, base)
    assert v.ok and _kinds(v.warnings) == ["gsp_near_limit"]
    already = _full(lambda y: _plain(y, gsp=510.0, limit=limit))
    same = merge_verdict(already, already)
    assert same.ok and {c.kind for c in same.context} == {"preexisting"}
    worse = _full(lambda y: _plain(y, gsp=510.0 + GATE_GSP_WORSEN_MW * 2, limit=limit))
    assert {b.kind for b in merge_verdict(worse, already).blockers} == {"gsp_worse"}


# --- N-1, demand alerts, works ---------------------------------------------------------------------
def test_n1_regressions_follow_the_policy_table():
    base = _full(lambda y: _plain(y, n1=[_n1(1), _n1(2, "line", 110.0)]))
    head = _full(lambda y: _plain(y, n1=[_n1(1), _n1(2, "line", 125.0), _n1(3), _n1(4, "voltage", 0.9)]) if y == 2033 else _plain(y, n1=[_n1(1), _n1(2, "line", 110.0)]))
    v = merge_verdict(head, base)
    found = {(f.kind, f.element_id): f.level for f in v.blockers + v.warnings}
    assert found[("n1_new_islanded", "3")] == MERGE_GATE_LEVELS["n1_new_islanded"]
    assert found[("n1_new_limit", "4")] == MERGE_GATE_LEVELS["n1_new_limit"]
    assert found[("n1_worse", "2")] == MERGE_GATE_LEVELS["n1_worse"]
    assert all(f.year == 2033 for f in v.blockers + v.warnings)
    # the untouched finding is summarised as context, once per year
    assert sum(1 for c in v.context if c.kind == "preexisting" and c.year == 2033) == 1


def test_new_breach_alerts_block_and_new_warnings_warn():
    def alert(level, kind="firm_capacity", value=12.0, limit=10.0):
        return Alert(kind=kind, level=level, region_id="R1", year=2032, value=value, limit=limit, message=f"R1 {kind} {level}")
    base = _full(lambda y: _plain(y, alerts=[alert("warn", "headroom", 0.9, 1.0)]))
    head = _full(lambda y: _plain(y, alerts=[alert("breach"), alert("warn", "headroom", 0.9, 1.0), alert("warn", "n1_stranded", 3.0, 2.0)]))
    v = merge_verdict(head, base)
    assert _kinds(v.blockers) == ["alert_new_breach"] * len(PLAN)
    assert {w.kind for w in v.warnings} == {"alert_new_warn"}
    assert {c.kind for c in v.context} == {"preexisting"}
    escalated = _full(lambda y: _plain(y, alerts=[alert("breach", "headroom", 0.5, 1.0)]))
    assert {b.kind for b in merge_verdict(escalated, base).blockers} == {"alert_new_breach"}
    deeper = _full(lambda y: _plain(y, alerts=[alert("warn", "headroom", 0.2, 1.0)]))
    assert {w.kind for w in merge_verdict(deeper, base).warnings} == {"alert_worse"}


def test_a_window_made_severe_blocks_and_more_curtailment_warns():
    def study(verdict, curtailed=0.0, at_risk=0.0):
        return OutageStudy(outage_id="w", year=2031, cases=["summer_min"], ok=verdict == "feasible", message=f"w {verdict}",
                           verdict=verdict, curtailed_mw=curtailed, demand_at_risk_mw=at_risk)
    base = _full(lambda y: _plain(y, studies=[study("curtailment", 10.0)]) if y == 2031 else _plain(y))
    severe = _full(lambda y: _plain(y, studies=[study("demand_at_risk", at_risk=6.0)]) if y == 2031 else _plain(y))
    more = _full(lambda y: _plain(y, studies=[study("curtailment", 25.0)]) if y == 2031 else _plain(y))
    v = merge_verdict(severe, base)
    assert _kinds(v.blockers) == ["work_worse_severe"] and v.blockers[0].value == 6.0 and v.blockers[0].base_value == 10.0
    v = merge_verdict(more, base)
    assert v.ok and _kinds(v.warnings) == ["work_worse"]
    both = merge_verdict(severe, severe)
    assert both.ok and _kinds(both.warnings) == ["work_infeasible"]


# --- the plan itself ---------------------------------------------------------------------------------
def test_a_branch_behind_its_base_blocks():
    base = _full(_plain, queue=[_qi("A", "Phase1"), _qi("NEW", "Phase1", 2)])
    head = _full(_plain, queue=[_qi("A", "Phase1")])
    v = merge_verdict(head, base)
    [b] = v.blockers
    assert b.kind == "behind_base" and b.element_id == "NEW" and "Open a new branch" in b.message


def test_schedule_profile_and_removed_proposals_warn():
    head = _full(_plain, queue=[_qi("A", "Phase1", recommended=2030), _qi("B", "Phase2", 2, recommended=None)], scenario="ee")
    base = _full(_plain, scenario="ht")
    v = merge_verdict(head, base, scheduled={"A": 2028, "B": 2034}, removed_works=["o-1"], removed_reinforcements=["r-1", "r-2"])
    assert v.ok
    kinds = sorted(_kinds(v.warnings))
    assert kinds == ["against_recommendation", "against_recommendation", "profile_differs", "proposals_removed", "proposals_removed"]
    texts = " ".join(w.message for w in v.warnings)
    assert "earlier than the 2030" in texts and "no year it can host it" in texts and "ht to ee" in texts and "r-1, r-2" in texts
    assert v.summary.startswith("Ready to merge with 5 warnings")


def test_a_non_convergent_year_blocks_unless_the_base_has_it_too():
    base = _full(_plain)
    head = _full(lambda y: _plain(y, converged=y != 2034))
    v = merge_verdict(head, base)
    assert _kinds(v.blockers) == ["non_convergent"] and v.blockers[0].year == 2034
    both = merge_verdict(head, head)
    assert both.ok and _kinds(both.context) == ["preexisting"]


def test_deferred_on_grid_is_context_and_a_clean_pair_is_ready():
    head = _full(_plain, queue=[_qi("A", "Phase1", recommended=2029),
                                _qi("B", "Deferred", 2, reason=Reason(type="trafo", element_id=3, value=120.0, limit=100.0, message="transformer 3 overloaded")),
                                _qi("C", "Deferred", 3, reason=Reason(type="rejected", message="needs review"))])
    v = merge_verdict(head, _full(_plain))
    assert v.ok and v.warnings == [] and _kinds(v.context) == ["deferred_on_grid"] and v.context[0].element_id == "B"
    assert v.summary.startswith("Ready to merge:")


# --- invariants ------------------------------------------------------------------------------------
def test_blockers_do_not_rely_on_the_diffs_display_caps():
    base = _full(_plain)
    head = _full(lambda y: _plain(y, n1=[_n1(i) for i in range(12)]) if y == 2030 else _plain(y))
    d = diff_results(base, head)
    assert len(d.years["2030"].n1_new) == 10  # the diff lists ten for display
    v = merge_verdict(head, base, d)
    assert sum(1 for b in v.blockers if b.kind == "n1_new_islanded") == 12  # the gate reports all twelve


def test_verdict_is_deterministic_and_links_to_the_ledger():
    base = _full(lambda y: _plain(y, line={1: 90.0}))
    head = _full(lambda y: _plain(y, line={1: 104.0}, vm={9: 0.93}, viol=[9]) if y == 2031 else _plain(y, line={1: 90.0}))
    v1, v2 = merge_verdict(head, base), merge_verdict(head, base)
    assert v1.model_dump() == v2.model_dump()
    ledger = {f.fingerprint for f in extract_findings(head)}
    assert all(b.finding_fingerprint in ledger for b in v1.blockers)


def test_every_check_is_registered_and_every_kind_has_a_level():
    assert len({c.__name__ for c in MERGE_CHECKS}) == len(MERGE_CHECKS)
    assert set(MERGE_GATE_LEVELS.values()) == {"blocker", "warning", "info"}
    # a busy pair exercises many kinds; each must be in the policy table and land in the right bucket
    base = _full(lambda y: _plain(y, line={2: 105.0}, gsp=400.0, limit=500.0), queue=[_qi("A", "Phase1"), _qi("OLD", "Phase1", 2)])
    head = _full(lambda y: _plain(y, line={1: 104.0, 2: 108.0}, vm={8: 0.92}, viol=[8], gsp=510.0, limit=500.0, n1=[_n1(3)],
                                  converged=y != 2035),
                 queue=[_qi("A", "Phase1", recommended=2030)], scenario="ee")
    v = merge_verdict(head, base, scheduled={"A": 2027}, removed_works=["o"])
    for bucket, level in ((v.blockers, "blocker"), (v.warnings, "warning"), (v.context, "info")):
        for f in bucket:
            assert MERGE_GATE_LEVELS[f.kind] == level == f.level


def test_a_real_pair_on_the_live_grid():
    """Base: nothing new; head: a saturating project energised in 2030 (grid-agnostic). Single-year
    results, so the gate must say the other years are unstudied, and every kind must be registered."""
    net = base_net()
    cand = saturating_candidates(net, n=1)[0]
    params = OptimizeParams()
    b = evaluate_year(2030, [cand], params, {}, n1=False)
    h = evaluate_year(2030, [cand], params, {cand.request_id: 2030}, n1=False)
    queue = [_qi(cand.request_id, "Phase1", recommended=2030)]
    base = OptimizeResult(params=params, queue=[], phases={}, years={"2030": b})
    head = OptimizeResult(params=params, queue=queue, phases={}, years={"2030": h})
    v = merge_verdict(head, base)
    assert not v.ok and {f.kind for f in v.blockers} >= {"unstudied_years"}
    assert {f.kind for f in v.blockers + v.warnings + v.context} <= set(MERGE_GATE_LEVELS)
    ids = lambda xs: {(f.kind, f.element_kind, f.element_id, f.year) for f in xs}  # noqa: E731
    assert not (ids(v.blockers) & ids(v.warnings))
    newly = set(h.overloaded_line_ids) - set(b.overloaded_line_ids)
    if newly:
        assert {b_.element_id for b_ in v.blockers if b_.kind == "new_overload"} >= {str(i) for i in newly}
