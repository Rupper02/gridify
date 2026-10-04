from _grid import base_net, stiff_bus
from gridforge_optimizer import (
    Candidate,
    N1During,
    OptimizeParams,
    OptimizeResult,
    PhaseResult,
    QueueItem,
    Outage,
    OutageStudy,
    Reason,
    YearResult,
    diff_results,
    diff_works,
    diff_year,
    diff_years,
    evaluate_year,
    optimize,
)


# --- synthetic results: exercise the classification logic exactly, no power flow ----------
def _qi(request_id, status, rank, rating, reason=None):
    return QueueItem(
        rank=rank,
        request_id=request_id,
        bus_id=1,
        technology="solar",
        rating_mw=rating,
        readiness_score=0.5,
        strategic_fit=0.5,
        grid_need=0.5,
        rank_score=0.5,
        status=status,
        reason=reason,
    )


def _phase(accepted, worst_line, worst_trafo, min_vm, max_vm, overloaded, line_loading):
    return PhaseResult(
        accepted=accepted,
        worst_line_loading_pct=worst_line,
        worst_trafo_loading_pct=worst_trafo,
        min_vm_pu=min_vm,
        max_vm_pu=max_vm,
        overloaded_line_ids=overloaded,
        line_loading=line_loading,
    )


def _synthetic_pair():
    base = OptimizeResult(
        params=OptimizeParams(),
        queue=[
            _qi("A", "Phase1", 1, 5.0),
            _qi("B", "Phase1", 2, 4.0),
            _qi("C", "Deferred", 3, 10.0, reason=Reason(type="voltage", message="weak bus")),
            _qi("D", "Phase2", 4, 3.0),
        ],
        phases={
            "2030": _phase(["A", "B"], 80.0, 70.0, 0.98, 1.02, [], {10: 80.0, 11: 50.0}),
            "2035": _phase(["A", "B", "D"], 95.0, 85.0, 0.96, 1.03, [11], {10: 90.0, 11: 105.0}),
        },
    )
    head = OptimizeResult(
        params=OptimizeParams(w_readiness=0.1, w_need=0.1, w_strategic=0.8),
        queue=[
            _qi("A", "Phase1", 2, 5.0),
            _qi("B", "Deferred", 3, 4.0, reason=Reason(type="line", message="line 12 over")),
            _qi("C", "Phase1", 1, 10.0),
            _qi("E", "Phase2", 4, 2.0),
        ],
        phases={
            "2030": _phase(["A", "C"], 85.0, 72.0, 0.97, 1.025, [12], {10: 82.0, 11: 48.0, 12: 101.0}),
            "2035": _phase(["A", "C", "E"], 92.0, 80.0, 0.95, 1.035, [], {10: 88.0, 11: 70.0, 12: 60.0}),
        },
    )
    return base, head


def test_classifies_every_kind_of_move():
    d = diff_results(*_synthetic_pair())
    by_id = {p.request_id: p for p in d.projects}
    assert by_id["A"].change == "moved_down"   # Phase1 both, rank 1 -> 2
    assert by_id["B"].change == "slipped"       # Phase1 -> Deferred
    assert by_id["C"].change == "accelerated"   # Deferred -> Phase1
    assert by_id["D"].change == "dropped"       # present in base, absent in head
    assert by_id["E"].change == "added"         # absent in base, present in head
    # the deferral reason is carried through for the "what would it take" hook
    assert by_id["B"].head_reason is not None and by_id["B"].head_reason.type == "line"
    assert by_id["C"].head_reason is None


def test_headline_counts_and_mw():
    d = diff_results(*_synthetic_pair())
    h = d.headline
    assert h["mw_2030_base"] == 9.0 and h["mw_2030_head"] == 15.0 and h["mw_2030_delta"] == 6.0
    assert h["mw_2035_base"] == 12.0 and h["mw_2035_head"] == 17.0 and h["mw_2035_delta"] == 5.0
    assert h["n_accelerated"] == 1 and h["n_slipped"] == 1
    assert h["n_added"] == 1 and h["n_dropped"] == 1


def test_phase_network_deltas():
    d = diff_results(*_synthetic_pair())
    phases = {p.phase: p for p in d.phases}
    assert 12 in phases["2030"].newly_overloaded_line_ids  # line 12 crosses 100% in head
    assert phases["2030"].cleared_line_ids == []
    assert 11 in phases["2035"].cleared_line_ids           # line 11 drops back under 100%
    # newly-overloaded and cleared are always disjoint
    for p in d.phases:
        assert not (set(p.newly_overloaded_line_ids) & set(p.cleared_line_ids))
    # biggest mover in 2030 is line 12 (0 -> 101), flagged newly_overloaded
    top = phases["2030"].top_line_deltas[0]
    assert top.line_id == 12 and top.crossed == "newly_overloaded"


# --- real optimizer runs: invariants + determinism ----------------------------------------
def _cands():
    # small projects at the stiff infeed bus so they connect; differing readiness vs strategic so
    # flipping the ranking weights reorders them (grid-agnostic).
    sb = stiff_bus(base_net())
    return [
        Candidate(request_id="ready_x", bus_id=sb, technology="solar", rating_mw=5.0, readiness_score=0.9, strategic_fit=0.1),
        Candidate(request_id="strat_y", bus_id=sb, technology="solar", rating_mw=5.0, readiness_score=0.1, strategic_fit=0.9),
        Candidate(request_id="mid_z", bus_id=sb, technology="battery", rating_mw=3.0, readiness_score=0.5, strategic_fit=0.5),
    ]


def _reweighted_pair():
    # same grid + scenario; only the ranking weights differ -> reordering is guaranteed
    b = optimize(_cands(), OptimizeParams(w_readiness=1.0, w_need=0.0, w_strategic=0.0))
    h = optimize(_cands(), OptimizeParams(w_readiness=0.0, w_need=0.0, w_strategic=1.0))
    return b, h


def test_reweighting_produces_movers_and_holds_invariants():
    b, h = _reweighted_pair()
    d = diff_results(b, h)
    # flipping readiness vs strategic weights must move at least one project
    assert any(p.change != "unchanged" for p in d.projects)
    # cumulative connected capacity never shrinks from 2030 to 2035
    assert d.headline["mw_2035_base"] >= d.headline["mw_2030_base"]
    assert d.headline["mw_2035_head"] >= d.headline["mw_2030_head"]
    # headline delta is internally consistent
    assert d.headline["mw_2030_delta"] == round(d.headline["mw_2030_head"] - d.headline["mw_2030_base"], 1)
    # overloaded/cleared stay disjoint on real data too
    for p in d.phases:
        assert not (set(p.newly_overloaded_line_ids) & set(p.cleared_line_ids))


def test_diff_is_deterministic():
    b, h = _reweighted_pair()
    assert diff_results(b, h).model_dump() == diff_results(b, h).model_dump()


# --- year by year and planned works ---------------------------------------------------------------
def _yr(year, line_loading, trafo_loading, *, energised=(), gsp=0.0, n1=(), studies=()):
    over = [i for i, v in line_loading.items() if v > 100]
    return YearResult(
        year=year, growth=1.0, energised=list(energised), accepted=list(energised),
        worst_line_loading_pct=max(line_loading.values()), worst_trafo_loading_pct=max(trafo_loading.values()),
        min_vm_pu=0.97, max_vm_pu=1.03, overloaded_line_ids=over, line_loading=line_loading,
        trafo_loading=trafo_loading, gsp_export_mw=gsp, n1_violations=list(n1), outage_studies=list(studies),
    )


def _study(oid, year, verdict, curtailed=0.0, at_risk=0.0, n1=None):
    return OutageStudy(outage_id=oid, year=year, cases=["summer_min"], ok=verdict == "feasible", message=f"{oid} {verdict}",
                       verdict=verdict, curtailed_mw=curtailed, demand_at_risk_mw=at_risk,
                       n1_during=None if n1 is None else N1During(cases=["summer_min"], screened=27, findings=len(n1), violations=list(n1)))


def _fault(outage_id, element_id, value=150.0):
    return {"outage_type": "line", "outage_id": outage_id, "outage_name": "", "case": "summer_min", "type": "line", "element_id": element_id,
            "value": value, "message": f"line {element_id} overloaded at {value:.0f}% of its summer rating at summer minimum demand"}


_N1 = {"outage_type": "line", "outage_id": 7, "outage_name": "x", "type": "line", "element_id": 3, "value": 120.0, "message": "m"}


def test_year_delta_covers_lines_transformers_gsp_and_n1():
    base = _yr(2029, {1: 90.0, 2: 105.0, 3: 40.0}, {5: 95.0, 6: 50.0}, energised=["A"], gsp=30.0)
    head = _yr(2029, {1: 104.0, 2: 99.0, 3: 41.0}, {5: 101.0, 6: 50.0}, energised=["A", "B"], gsp=55.5, n1=[_N1])
    d = diff_years({"2029": base, "2030": base}, {"2029": head})
    assert list(d) == ["2029"]  # only years solved on both runs
    y = d["2029"]
    assert y.newly_overloaded_line_ids == [1] and y.cleared_line_ids == [2]
    assert y.newly_overloaded_trafo_ids == [5] and y.cleared_trafo_ids == []
    assert y.worst_line_delta == round(104.0 - 105.0, 1) and y.worst_trafo_delta == 6.0
    assert y.gsp_export_delta == 25.5 and y.gsp_export_head == 55.5
    assert y.n1_findings_delta == 1 and y.n1_new == [_N1] and y.n1_cleared == []
    assert y.energised_only_head == ["B"] and y.energised_only_base == []
    top = {t.element_id: t for t in y.top_line_deltas}
    assert top[1].crossed == "newly_overloaded" and top[1].delta == 14.0 and top[2].crossed == "cleared"
    assert y.top_trafo_deltas[0].element_id == 5 and y.top_trafo_deltas[0].crossed == "newly_overloaded"


def test_year_movers_keep_every_crossing_beyond_the_top_n():
    base = {i: 50.0 for i in range(30)} | {99: 99.0}
    head = {i: 80.0 for i in range(30)} | {99: 100.5}  # 30 lines move 30 points; line 99 crosses by 1.5
    y = diff_year(_yr(2031, base, {0: 10.0}), _yr(2031, head, {0: 10.0}))
    ids = [t.element_id for t in y.top_line_deltas]
    assert 99 in ids and len(ids) > 10 and y.newly_overloaded_line_ids == [99]


def test_works_compare_the_branch_window_with_the_same_window_on_main():
    on_main = [_study("w1", 2029, "feasible"), _study("w2", 2030, "curtailment", curtailed=40.0),
               _study("w3", 2031, "curtailment", curtailed=10.0)]
    on_branch = [_study("w1", 2029, "curtailment", curtailed=40.0), _study("w2", 2030, "feasible"),
                 _study("w3", 2031, "curtailment", curtailed=10.0), _study("w4", 2032, "not_feasible")]
    w = {x.outage_id: x for x in diff_works(on_main, on_branch)}
    assert w["w1"].change == "worse" and w["w1"].verdict_on_main == "feasible" and w["w1"].verdict_on_branch == "curtailment"
    assert w["w1"].consequence == "Feasible on main, but needs 40.0 MW of curtailment on this branch."
    assert w["w2"].change == "better" and w["w2"].curtailed_mw_main == 40.0
    assert w["w3"].change == "unchanged" and "alike" in w["w3"].consequence
    assert w["w4"].change == "unstudied" and w["w4"].verdict_on_main is None
    # more curtailment under the same verdict is still worse
    more = diff_works([_study("w", 2030, "curtailment", curtailed=10.0)], [_study("w", 2030, "curtailment", curtailed=25.0)])
    assert more[0].change == "worse"


def test_works_compare_the_second_faults_during_the_window_not_their_count():
    a, b, c = _fault(1, 63), _fault(4, 63, 149.0), _fault(5, 89, 112.0)
    # the same count on both sides, but a different fault: the branch adds one and clears one
    [w] = diff_works([_study("w", 2032, "feasible", n1=[a, c])], [_study("w", 2032, "feasible", n1=[a, b])])
    assert w.n1_findings_main == 2 and w.n1_findings_branch == 2
    assert w.n1_new == [b] and w.n1_cleared == [c] and w.change == "worse"
    assert "adds 1 problem" in w.consequence and "line 4 out as well" in w.consequence and "clears 1" in w.consequence
    # the same faults on both sides: unchanged, whatever their order
    [same] = diff_works([_study("w", 2032, "feasible", n1=[c, a])], [_study("w", 2032, "feasible", n1=[a, c])])
    assert same.change == "unchanged" and same.n1_new == [] and same.n1_cleared == []
    # fewer faults on the branch: better, and the consequence says what it clears
    [better] = diff_works([_study("w", 2032, "feasible", n1=[a, c])], [_study("w", 2032, "feasible", n1=[a])])
    assert better.change == "better" and better.n1_cleared == [c] and "clears 1" in better.consequence
    # main's plan not screened during the window: the branch's list stands, the change is not judged on it
    [unscreened] = diff_works([_study("w", 2032, "feasible")], [_study("w", 2032, "feasible", n1=[a])])
    assert unscreened.n1_findings_main is None and unscreened.n1_new == [a] and unscreened.change == "unchanged"
    # a verdict change still comes first
    [worse] = diff_works([_study("w", 2032, "feasible", n1=[a, c])], [_study("w", 2032, "curtailment", curtailed=5.0, n1=[a])])
    assert worse.change == "worse" and worse.n1_cleared == [c]


def test_diff_results_carries_years_and_works():
    base, head = _synthetic_pair()
    yb = _yr(2030, {10: 80.0}, {1: 50.0}, studies=[_study("w", 2030, "feasible")])
    yh = _yr(2030, {10: 85.0}, {1: 52.0}, studies=[_study("w", 2030, "curtailment", curtailed=5.0)])
    d = diff_results(base.model_copy(update={"years": {"2030": yb}}), head.model_copy(update={"years": {"2030": yh}}))
    assert d.years["2030"].top_line_deltas[0].delta == 5.0
    assert [x.change for x in d.works] == ["worse"] and d.headline["n_works_worse"] == 1
    # the caller's studies on base's plan take precedence over base's own windows
    d2 = diff_results(base, head.model_copy(update={"years": {"2030": yh}}),
                      works_on_base=[_study("w", 2030, "curtailment", curtailed=5.0)])
    assert d2.years == {} and d2.works[0].change == "unchanged"
    # results without years still diff (backward compatible)
    assert diff_results(base, head).years == {} and diff_results(base, head).works == []


def test_a_real_year_and_window_diff_on_the_live_grid():
    """Same year, same window; base without and head with a project energised (grid-agnostic)."""
    net = base_net()
    sb = stiff_bus(net)
    lid = max(net.line.index, key=lambda i: (net.bus.at[net.line.at[i, "from_bus"], "vn_kv"], -i))
    window = Outage(outage_id="w", element_kind="line", element_id=str(lid), season="Summer", year=2030)
    cand = Candidate(request_id="PV", bus_id=sb, technology="solar", rating_mw=20.0)
    params = OptimizeParams()
    b = evaluate_year(2030, [cand], params, {}, outages=[window], n1=False)
    h = evaluate_year(2030, [cand], params, {"PV": 2030}, outages=[window], n1=False)
    y = diff_year(b, h)
    assert y.energised_only_head == ["PV"] and y.gsp_export_delta > 0
    assert not (set(y.newly_overloaded_line_ids) & set(y.cleared_line_ids))
    [w] = diff_works(b.outage_studies, h.outage_studies)
    assert w.verdict_on_main == b.outage_studies[0].verdict and w.verdict_on_branch == h.outage_studies[0].verdict
    assert w.change in ("worse", "better", "unchanged") and w.consequence
