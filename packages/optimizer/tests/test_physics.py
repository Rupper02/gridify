"""Physics of the study cases: statutory voltage bands by level, regulated tap changers,
technology-specific dispatch per case."""

import pandas as pd
import pytest

from _grid import stiff_bus
from gridify_optimizer.config import GENERATION_FACTORS, OLTC_DEADBAND_PU, OLTC_SETPOINT_PU
from gridify_optimizer.network import (
    case_breaches,
    _oltc_trafos,
    _run_case,
    _study_cases,
    build_base_net,
    dispatch_for_case,
    feasibility,
    inject_sgen,
    voltage_band,
    voltage_limits,
)


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


def test_case_breaches_apply_the_band_of_the_bus():
    net = build_base_net()
    vm = pd.Series(1.0, index=net.bus.index)
    lines = pd.Series(10.0, index=net.line.index)
    trafos = pd.Series(10.0, index=net.trafo.index)
    hv = int(net.bus.index[net.bus["vn_kv"] >= 132][0])
    mv = int(net.bus.index[net.bus["vn_kv"] < 132][0])
    vm[hv] = 1.08  # fine at 132 kV (±10 %)
    assert case_breaches(net, "winter_peak", vm, lines, trafos) == []
    vm[mv] = 1.08  # a breach below 132 kV (±6 %)
    [r] = case_breaches(net, "winter_peak", vm, lines, trafos)
    assert r.type == "voltage" and r.element_id == mv and r.limit == 1.06
    assert "outside [0.94, 1.06]" in r.message


def test_tap_changers_hold_their_lv_busbars_near_the_setpoint():
    net = build_base_net()
    oltc = _oltc_trafos(net)
    assert len(oltc) > 0  # LTDS gives every transformer a tap range
    ok, breaches, _ = feasibility(net)
    assert ok, breaches
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
