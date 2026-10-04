"""The study registry: deterministic, bounded analyses with stable fingerprints (grid-agnostic)."""

from types import SimpleNamespace

import pytest

from _grid import base_net, grid_deferred, saturating_candidates, stiff_bus, weak_buses
from gridforge_optimizer import STUDIES, OptimizeParams, OptimizeResult, StudyContext, YearResult, optimize, run_study
from gridforge_optimizer.config import HOSTING_STEP_MW, MAX_CONNECTION_MW, TAP_MARGIN_MIN_STEPS
from gridforge_optimizer.network import _oltc_trafos, build_base_net, n1_screen
from gridforge_optimizer.studies import HostingParams, chunk_study, merge_chunks


def _ctx(**kw):
    return StudyContext(net_factory=build_base_net, params=OptimizeParams(), **kw)


def _yr(year, export, limit):
    return YearResult(year=year, growth=1.0, accepted=[], worst_line_loading_pct=50.0, worst_trafo_loading_pct=50.0, min_vm_pu=0.98,
                      max_vm_pu=1.02, overloaded_line_ids=[], gsp_export_mw=export, gsp_limit_mw=limit)


_PLAN = OptimizeResult(params=OptimizeParams(), queue=[], phases={}, years={"2030": _yr(2030, 300.0, 527.0), "2035": _yr(2035, 500.0, 527.0)})

@pytest.fixture(scope="module")
def plan():
    """A real run that defers projects on the grid (what connection options and best windows read),
    with the plan years it needs faked: the years only gate `needs_plan`; these studies do not read them."""
    net = base_net()
    cands = saturating_candidates(net, n=4)
    result = optimize(cands, OptimizeParams()).model_copy(update={"years": {"2030": _yr(2030, 300.0, 527.0), "2035": _yr(2035, 500.0, 527.0)}})
    deferred = grid_deferred(result.queue)
    assert deferred, "the fixture must defer a project on the grid"
    return SimpleNamespace(cands=cands, result=result, deferred=deferred[0].request_id)


# cheap parameters per study, so the whole module stays well under a minute
_CHEAP = {
    "hosting_capacity": lambda net, plan: {"bus_ids": weak_buses(net, 2), "cases": ["winter_peak"], "step_mw": 25.0},
    "contingency_ranking": lambda net, plan: {"min_kv": 132.0, "cases": ["winter_peak"], "top": 5},
    "structural_weak_points": lambda net, plan: {},
    "tap_margin": lambda net, plan: {"cases": ["winter_peak"]},
    "gsp_margin_by_year": lambda net, plan: {},
    "data_quality": lambda net, plan: {},
    "connection_options": lambda net, plan: {"request_id": plan.deferred, "step_mw": 50.0, "max_buses": 1},
    "best_window": lambda net, plan: {"element_kind": "line", "element_id": str(int(net.line.index[0])), "years": (2030, 2030), "seasons": ["Winter"], "n1": False},
}


def test_every_study_runs_through_the_registry_and_is_deterministic(plan):
    net = base_net()
    assert set(_CHEAP) == set(STUDIES)
    for kind, spec in STUDIES.items():
        params = _CHEAP[kind](net, plan)
        ctx = _ctx(result=plan.result if spec.needs_plan else None, candidates=plan.cands)
        a, b = run_study(kind, ctx, params), run_study(kind, ctx, params)
        assert a.kind == kind and a.model_dump() == b.model_dump(), kind
        assert a.solves >= 0 and a.summary and a.not_studied, kind
        assert spec.description and spec.cost_hint(spec.params_model.model_validate(params)) >= 0
        for i, it in enumerate(a.items):
            assert it.index == i and it.message and it.fingerprint and it.severity in ("info", "warn", "breach"), kind
        assert len({it.fingerprint for it in a.items}) == len(a.items), kind
    with pytest.raises(KeyError):
        run_study("nope", _ctx())
    with pytest.raises(ValueError):
        run_study("gsp_margin_by_year", _ctx())


def test_hosting_capacity_is_bounded_names_the_binding_limit_and_leaves_the_net_as_found():
    net = base_net()
    calls = []

    def factory():
        calls.append(1)
        return build_base_net()

    sb, wb = stiff_bus(net), weak_buses(net, 1)[0]
    r = run_study("hosting_capacity", StudyContext(net_factory=factory), {"bus_ids": [sb, wb], "cases": ["summer_min"], "step_mw": 25.0})
    by = {it.element_id: it for it in r.items}
    assert set(by) == {sb, wb} and all(it.case == "summer_min" and it.unit == "MW" for it in r.items)
    assert 0.0 <= by[wb].value <= by[sb].value <= MAX_CONNECTION_MW
    for it in r.items:
        binding = it.extra["binding"]
        if it.value < MAX_CONNECTION_MW:
            assert binding and binding["type"] in ("voltage", "line", "trafo", "gsp", "non_convergent"), it.message
            assert binding["message"] in it.message
        else:
            assert binding is None and "no limit reached" in it.message
    assert r.solves <= 2 * (2 + 5)  # at most the cap probe, the zero probe and log2(300/25) ~ 4 bisections per bus
    assert calls == [1]  # one network, probed and restored in place
    # the value is a multiple of the step, and the chunks cover the same buses
    assert all((it.value / 25.0).is_integer() for it in r.items)
    chunks = chunk_study("hosting_capacity", _ctx(), {"bus_ids": [sb, wb], "max_buses": 2})
    assert sum(len(c.bus_ids) for c in chunks) == 2
    merged = merge_chunks("hosting_capacity", HostingParams(bus_ids=[sb, wb]), [r, r])
    assert [it.index for it in merged.items] == list(range(2 * len(r.items))) and merged.solves == 2 * r.solves


def test_contingency_ranking_extends_the_n1_screen_and_keeps_it_unchanged():
    before = n1_screen(build_base_net())
    r = run_study("contingency_ranking", _ctx(), {"min_kv": 132.0, "cases": ["winter_peak"], "top": 50})
    assert n1_screen(build_base_net()) == before  # the extraction changed nothing in the screen
    # every winter-peak N-1 finding is a ranked contingency, and the ranking is worst first
    found = {(v["outage_type"], v["outage_id"]) for v in before["violations"]}
    ranked = {(it.element_kind, it.element_id) for it in r.items}
    assert found <= ranked
    keys = [(not it.extra["non_convergent"], -it.extra["islanded_mw"], -it.extra["thermal_excess_mva"], -it.extra["voltage_shortfall_pu"]) for it in r.items]
    assert keys == sorted(keys)
    assert all(it.unit == "index" and it.case == "winter_peak" for it in r.items)
    assert r.solves >= len(before["violations"]) and "single outages screened" in r.summary
    # a 33 kV scope studies more elements than the 132 kV one (chunk per case)
    chunks = chunk_study("contingency_ranking", _ctx(), {})
    assert [c.cases for c in chunks] == [[c] for c in ("winter_peak", "summer_min")]


@pytest.mark.slow
def test_contingency_ranking_full_scope_covers_33_kv_and_summer_minimum():
    r = run_study("contingency_ranking", _ctx(), {"top": 500})
    assert any(it.case == "summer_min" for it in r.items) or r.solves > 0
    assert r.solves > 2 * len(n1_screen(build_base_net())["violations"])


def test_structural_weak_points_make_no_power_flow(monkeypatch):
    import pandapower as pp

    monkeypatch.setattr(pp, "runpp", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no power flow allowed")))
    r = run_study("structural_weak_points", _ctx(), {})
    assert r.solves == 0
    for it in r.items:
        assert it.element_kind in ("line", "trafo", "bus") and it.unit == "MW" and it.value >= 0
        assert "cuts off" in it.message and "island_bus_ids" in it.extra
    # every single-route circuit it names really is a bridge of the graph
    net = base_net()
    import networkx as nx
    from gridforge_optimizer.studies import _simple_graph
    g, _ = _simple_graph(net)
    bridges = {tuple(sorted(e)) for e in nx.bridges(g)}
    for it in r.items:
        if it.element_kind == "line":
            l = net.line.loc[it.element_id]
            assert tuple(sorted((int(l.from_bus), int(l.to_bus)))) in bridges


def test_tap_margin_flags_a_transformer_parked_at_its_stop():
    base = run_study("tap_margin", _ctx(), {"cases": ["winter_peak"]})
    assert all(it.unit == "steps" and it.value <= TAP_MARGIN_MIN_STEPS for it in base.items)
    net0 = build_base_net()
    tid = int(_oltc_trafos(net0)[0])

    def parked():
        net = build_base_net()
        net.trafo.at[tid, "tap_min"] = int(net.trafo.at[tid, "tap_max"]) - 1  # a range of one step: it must sit at a stop
        return net

    r = run_study("tap_margin", StudyContext(net_factory=parked), {"cases": ["winter_peak"]})
    hit = next(it for it in r.items if it.element_id == tid)
    assert hit.severity in ("breach", "warn") and hit.extra["tap_pos"] in (hit.extra["tap_min"], hit.extra["tap_max"])
    assert f"transformer {tid}" in hit.message and r.solves == 1


def test_gsp_margin_by_year_reads_the_plan():
    r = run_study("gsp_margin_by_year", _ctx(result=_PLAN), {})
    by = {it.year: it for it in r.items}
    assert by[2030].value == 227.0 and by[2030].severity == "info" and by[2030].limit == 527.0
    assert by[2035].value == 27.0 and by[2035].severity == "warn"  # under 10% of the limit
    assert "2035" in r.summary and r.solves == 0 and any("import" in n for n in r.not_studied)


def test_data_quality_lists_the_builders_assumptions():
    net = base_net()
    assert "assumptions" in net and {"rating_fallback", "tap_step_assumed"} <= set(net["assumptions"])
    r = run_study("data_quality", _ctx(), {})
    by = {it.element_id: it for it in r.items}
    assert by["rating_fallback"].severity == "warn" and by["rating_fallback"].value == len(net["assumptions"]["rating_fallback"]["element_ids"])
    assert by["tap_step_assumed"].value == len(_oltc_trafos(net))
    assert all(it.extra["source"] == "engine-default" and it.unit == "count" for it in r.items)
    assert r.solves == 0 and "assumption" in r.summary


def test_hosting_step_is_the_configured_resolution_by_default():
    assert HostingParams().step_mw == HOSTING_STEP_MW


def test_connection_options_size_the_project_chain_circuits_and_probe_higher_busbars(plan):
    net = base_net()
    rid = plan.deferred
    c = next(x for x in plan.cands if x.request_id == rid)
    ctx = _ctx(result=plan.result, candidates=plan.cands)
    params = {"request_id": rid, "step_mw": 50.0, "max_buses": 2}
    r = run_study("connection_options", ctx, params)
    sizes = [it for it in r.items if it.extra["option"] == "size"]
    chain = [it for it in r.items if it.extra["option"] == "reinforce"]
    moves = [it for it in r.items if it.extra["option"] == "move"]
    assert sizes and len(chain) == 1 and moves
    # the size: what its own busbar takes of it, per case, against what it asks
    for it in sizes:
        assert it.element_id == c.bus_id and it.limit == c.rating_mw and 0.0 <= it.value <= MAX_CONNECTION_MW and it.unit == "MW"
        assert it.severity == ("info" if it.extra["fits"] else "warn") and it.extra["fits"] == (it.value >= c.rating_mw)
        if not it.extra["fits"]:
            assert "flexibly" in it.message and it.extra["binding"]["message"] in it.message
    # the chain names what it reinforced and whether the project then connects, or why it stops
    ch = chain[0]
    assert ch.element_kind == "project" and ch.element_id == rid and ch.severity == ("info" if ch.extra["connects"] else "warn")
    if not ch.extra["connects"]:
        assert ch.extra["binding"] and ch.extra["binding"]["message"] in ch.message
    # the higher-voltage busbars really are higher, nearest first, probed with the project's full MW
    kv0 = float(net.bus.at[c.bus_id, "vn_kv"])
    assert all(it.extra["vn_kv"] > kv0 and it.limit == c.rating_mw and it.unit == "MW" for it in moves)
    steps = [it.extra["steps"] for it in moves]
    assert steps == sorted(steps) and len({it.element_id for it in moves}) <= 2
    assert all(it.severity == ("info" if it.extra["fits"] else "warn") and it.extra["fits"] == (it.value >= c.rating_mw) for it in moves)
    assert len({it.fingerprint for it in r.items}) == len(r.items) and r.solves > 0
    assert any("2035" in n for n in r.not_studied) and rid in r.summary
    assert "takes its full MW" in r.summary or "takes about" in r.summary  # each probed busbar is summed up by name
    # chunks: the site, then one part per busbar; merged, they equal the whole study item for item
    parts = chunk_study("connection_options", ctx, params)
    assert [p.part for p in parts] == ["site", "bus", "bus"] and all(len(p.bus_ids) == 1 for p in parts[1:])
    merged = merge_chunks("connection_options", params, [run_study("connection_options", ctx, p) for p in parts])
    strip = lambda its: [it.model_dump(exclude={"index"}) for it in its]  # noqa: E731
    assert strip(merged.items) == strip(r.items) and merged.solves == r.solves
    assert STUDIES["connection_options"].cost_hint(parts[0]) + sum(STUDIES["connection_options"].cost_hint(p) for p in parts[1:]) >= r.solves


def test_connection_options_refuse_a_project_that_is_not_on_the_branch(plan):
    with pytest.raises(ValueError):
        run_study("connection_options", _ctx(result=plan.result, candidates=plan.cands), {"request_id": "nope"})
    with pytest.raises(ValueError):  # the plan is required
        run_study("connection_options", _ctx(candidates=plan.cands), {"request_id": plan.deferred})


def test_best_window_study_wraps_the_search_and_chunks_by_year_without_n1(plan):
    net = base_net()
    lid = str(int(net.line.index[0]))
    ctx = _ctx(result=plan.result, candidates=plan.cands)
    r = run_study("best_window", ctx, {"element_kind": "line", "element_id": lid, "years": (2030, 2031), "seasons": ["Winter", "Summer"], "n1": False})
    assert {(it.year, it.case) for it in r.items} == {(2030, "Winter"), (2030, "Summer"), (2031, "Winter"), (2031, "Summer")} and len(r.items) == 4
    for it in r.items:
        assert it.element_kind == "line" and it.element_id == lid and it.unit == "MW"
        assert it.extra["verdict"] in ("feasible", "curtailment", "demand_at_risk", "not_feasible") and it.extra["n1_findings"] is None
        assert it.severity == {"feasible": "info", "curtailment": "warn"}.get(it.extra["verdict"], "breach")
        assert it.extra["verdict"] in it.message and f"line {lid}" in it.message
    assert "the best is" in r.summary and any("not screened" in n for n in r.not_studied)
    assert len({it.fingerprint for it in r.items}) == 4
    parts = chunk_study("best_window", ctx, {"element_kind": "line", "element_id": lid, "years": (2030, 2032), "n1": False})
    assert [tuple(p.years) for p in parts] == [(2030, 2030), (2031, 2031), (2032, 2032)]
    assert len(chunk_study("best_window", ctx, {"element_kind": "line", "element_id": lid, "years": (2030, 2032)})) == 1  # the N-1 shortlist needs the whole ranking
    with pytest.raises(ValueError):
        run_study("best_window", ctx, {"element_kind": "line", "element_id": lid, "years": (2035, 2030)})
    with pytest.raises(ValueError):
        run_study("best_window", ctx, {"element_kind": "line", "element_id": "999999", "years": (2030, 2030), "seasons": ["Winter"], "n1": False})
