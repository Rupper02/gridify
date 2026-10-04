"""Physics of the study cases: statutory voltage bands by level, regulated tap changers,
technology-specific dispatch per case, siting of the existing fleet, and the N-1 screen."""

import pandas as pd
import pytest

from _grid import stiff_bus
from gridforge_optimizer.config import GENERATION_FACTORS, OLTC_DEADBAND_PU, OLTC_SETPOINT_PU
from gridforge_optimizer.network import (
    _case_reason,
    _oltc_trafos,
    _run_case,
    _study_cases,
    build_base_net,
    dispatch_for_case,
    feasibility,
    inject_sgen,
    n1_screen,
    voltage_band,
    voltage_limits,
)
from gridforge_optimizer.nged import _ctx, _substation


def test_voltage_band_is_statutory_by_level():
    assert voltage_band(132) == (0.9, 1.1)
    assert voltage_band(400) == (0.9, 1.1)
    assert voltage_band(33) == (0.94, 1.06)
    assert voltage_band(11) == (0.94, 1.06)
    net = build_base_net()
    vmin, vmax = voltage_limits(net)
    kv = net.bus["vn_kv"]
    assert (vmax[kv >= 132] == 1.1).all() and (vmax[kv < 132] == 1.06).all()
    assert (vmin[kv >= 132] == 0.9).all() and (vmin[kv < 132] == 0.94).all()


def test_case_reason_applies_the_band_of_the_bus():
    net = build_base_net()
    vm = pd.Series(1.0, index=net.bus.index)
    lines = pd.Series(10.0, index=net.line.index)
    trafos = pd.Series(10.0, index=net.trafo.index)
    hv = int(net.bus.index[net.bus["vn_kv"] >= 132][0])
    mv = int(net.bus.index[net.bus["vn_kv"] < 132][0])
    vm[hv] = 1.08  # fine at 132 kV (±10 %)
    assert _case_reason(net, "winter_peak", vm, lines, trafos) is None
    vm[mv] = 1.08  # a breach below 132 kV (±6 %)
    r = _case_reason(net, "winter_peak", vm, lines, trafos)
    assert r is not None and r.type == "voltage" and r.element_id == mv and r.limit == 1.06
    assert "outside [0.94, 1.06]" in r.message


def test_tap_changers_hold_their_lv_busbars_near_the_setpoint():
    net = build_base_net()
    oltc = _oltc_trafos(net)
    assert len(oltc) > 0  # LTDS gives every transformer a tap range
    ok, reason, _ = feasibility(net)
    assert ok, reason
    # after the solve the winter case's taps have settled: every regulated LV busbar sits inside the
    # deadband, unless the changer is at an end stop
    case, ls, rr = _study_cases(net)[0]
    res = _run_case(net, case, ls, rr)
    for tid in oltc:
        lv = int(net.trafo.at[tid, "lv_bus"])
        v = float(res["vm"].loc[lv])
        pos = int(net.trafo.at[tid, "tap_pos"])
        at_stop = pos in (int(net.trafo.at[tid, "tap_min"]), int(net.trafo.at[tid, "tap_max"]))
        assert at_stop or abs(v - OLTC_SETPOINT_PU) <= OLTC_DEADBAND_PU + 0.0125, (tid, v, pos)
    assert (net.trafo.loc[oltc, "tap_pos"] != 0).any()  # the regulation actually moved something


def test_dispatch_by_case_pv_nil_in_winter_batteries_charge():
    net = build_base_net()
    b = stiff_bus(net)
    pv = inject_sgen(net, b, 10.0, "pv", "solar")
    bat = inject_sgen(net, b, 20.0, "bat", "battery", import_mw=15.0)
    firm = inject_sgen(net, b, 5.0, "chp", "other")
    w = dispatch_for_case(net, "winter_peak")
    s = dispatch_for_case(net, "summer_min")
    assert w[pv] == 0.0 and s[pv] == 10.0
    assert w[bat] == -15.0 and s[bat] == 20.0  # charging at its import capacity vs full export
    assert w[firm] == 5.0 and s[firm] == 5.0
    assert GENERATION_FACTORS["winter_peak"]["solar"] == 0.0


def test_summer_minimum_is_the_generation_case():
    # a PV project changes nothing at winter peak and raises export at summer minimum
    base = build_base_net()
    cases = {c: (ls, rr) for c, ls, rr in _study_cases(base)}
    w0 = _run_case(base, "winter_peak", *cases["winter_peak"])["p_ext_mw"]
    s0 = _run_case(base, "summer_min", *cases["summer_min"])["p_ext_mw"]
    inject_sgen(base, stiff_bus(base), 20.0, "pv", "solar")
    w1 = _run_case(base, "winter_peak", *cases["winter_peak"])["p_ext_mw"]
    s1 = _run_case(base, "summer_min", *cases["summer_min"])["p_ext_mw"]
    assert w1 == pytest.approx(w0, abs=0.5)
    assert s1 < s0 - 15  # ~20 MW more pushed up to transmission (ext_grid p is negative when exporting)


def test_existing_fleet_is_sited_at_its_named_substation():
    ctx = _ctx()
    net = ctx["net"]
    placed = 0
    for g in ctx["existing"]:
        where = g["placement"]
        if "site not matched" in where:
            continue
        placed += 1
        site_tok = _substation(where.split(" at ")[0].split(" (")[0]).lower()
        bus_tok = _substation(net.bus.at[g["bus_id"], "name"]).lower()
        assert site_tok.startswith(bus_tok) or bus_tok.startswith(site_tok), (g["request_id"], where, bus_tok)
    assert placed >= len(ctx["existing"]) - 1  # at most one unmatched site
    # the fleet's total rating is preserved even where a site is shared across busbars
    assert float(net.sgen["p_mw"].sum()) == pytest.approx(sum(g["rating_mw"] for g in ctx["existing"]), rel=1e-6)


@pytest.mark.n1
def test_n1_screen_reports_backbone_outages_without_gating():
    net = build_base_net()
    out = n1_screen(net)
    assert out["case"] == "winter_peak" and out["screened"] > 0
    for v in out["violations"]:
        assert v["outage_type"] in ("line", "trafo") and v["type"] in ("line", "trafo", "voltage", "islanded", "non_convergent")
        assert v["message"]
    # the screen restores every element to service
    assert net.line["in_service"].all() and net.trafo["in_service"].all()
    # an islanded generator spur with no demand is not a violation
    assert all(v["type"] != "islanded" or (v["value"] or 0) >= 1.0 for v in out["violations"])


@pytest.mark.n1
def test_n1_screen_cases_covers_every_case_and_reports_islands_once():
    from gridforge_optimizer.config import N1_CASES
    from gridforge_optimizer.network import n1_screen_cases

    net = build_base_net()
    out = n1_screen_cases(net)
    assert out["cases"] == list(N1_CASES) and out["screened"] > 0
    by_case = {c: [v for v in out["violations"] if v["case"] == c] for c in out["cases"]}
    assert set(by_case) == set(N1_CASES)
    # every finding names its case; islanded demand is reported on the first case only
    assert all(v["case"] in N1_CASES for v in out["violations"])
    assert all(v["type"] != "islanded" for c in out["cases"][1:] for v in by_case[c])
    islands = [v for v in by_case[out["cases"][0]] if v["type"] == "islanded"]
    assert islands == [v for v in n1_screen(net, out["cases"][0])["violations"] if v["type"] == "islanded"]
    # the summer case is where a net-exporting GSP is thermally bound: its findings are the screen's, with their case
    summer = n1_screen(net, "summer_min")["violations"]
    assert [v for v in summer if v["type"] != "islanded"] == by_case["summer_min"]
    assert net.line["in_service"].all() and net.trafo["in_service"].all()
