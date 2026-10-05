"""The GridSource seam: NGED behind it unchanged, and any grid through it. The NGED CGMES export
re-imports as a project with the same elements and a converging base case; a pandapower JSON with no
coordinates gets a synthetic layout and keeps its voltage-controlled generators; a file that lacks what a
real simulation needs is refused with the list, never filled."""

import math

import pandapower as pp
import pandapower.networks as pn
import pytest

from gridforge_optimizer import GridModel, ImportMeta, ModelAssumption
from gridforge_optimizer.cim import cgmes_zip_bytes, export_cgmes
from gridforge_optimizer.network import build_base_net, feasibility
from gridforge_optimizer.nged import NGED_CGMES_META, nged_model
from gridforge_optimizer.sources import (
    SOURCES,
    GridSource,
    NgedSource,
    cgmes_source,
    default_source,
    pandapower_json_source,
    source_from_file,
    source_kind_for,
    validate_net,
)


def _keys(assumptions: list[ModelAssumption]) -> set[str]:
    return {a.key for a in assumptions}


# --- the registry and NGED behind the seam -----------------------------------------------------------------------
def test_the_registry_names_every_kind_and_nged_is_a_source():
    assert set(SOURCES) >= {"nged", "cgmes", "pandapower_json", "matpower"}
    assert source_kind_for("grid.zip") == "cgmes" and source_kind_for("net.JSON") == "pandapower_json" and source_kind_for("case9.mat") == "matpower"
    with pytest.raises(ValueError):
        source_kind_for("grid.csv")
    src = default_source()
    assert isinstance(src, GridSource) and src.kind == "nged" and src.capabilities()["boundary"]
    assert src.fingerprint() and src.fingerprint() == NgedSource().fingerprint()


def test_nged_through_the_seam_is_the_same_network():
    a, b = build_base_net(), NgedSource().build_net()
    assert (len(a.bus), len(a.line), len(a.trafo), len(a.load), len(a.sgen)) == (len(b.bus), len(b.line), len(b.trafo), len(b.load), len(b.sgen))
    _, _, ma = feasibility(a)
    _, _, mb = feasibility(b)
    assert ma == mb  # the same solves, the same figures
    m = NgedSource().model()
    assert isinstance(m, GridModel) and m.crs == "wgs84" and m.model_dump() == nged_model()
    assert len(m.buses) == len(a.bus) and len(m.regions) > 0 and all(ln.rating_a for ln in m.lines)
    keys = _keys(NgedSource().assumptions())
    assert "rating_fallback" in keys and "tap_target" in keys  # the builder's records and the planning assumptions


# --- the NGED export, re-imported as a project ------------------------------------------------------------------------
@pytest.fixture(scope="module")
def nged_zip():
    net = build_base_net()
    feasibility(net)
    return cgmes_zip_bytes(export_cgmes(net, nged_model(), "rt", meta=NGED_CGMES_META))


def test_the_nged_cgmes_export_imports_as_a_grid_with_the_same_elements(nged_zip):
    base = build_base_net()
    src = cgmes_source(nged_zip, id="imp-nged", name="NGED re-imported")
    net = src.build_net()
    assert (len(net.bus), len(net.line), len(net.trafo), len(net.load), len(net.sgen), len(net.ext_grid)) == (
        len(base.bus), len(base.line), len(base.trafo), len(base.load), len(base.sgen), len(base.ext_grid))
    report = src.validate()
    assert report.ok and report.converged and report.cases == ["winter_peak"], report
    keys = _keys(src.assumptions())
    assert {"no_seasonal_ratings", "no_min_demand", "no_gsp_limit", "gb_voltage_bands", "n1_scope"} <= keys
    assert "unrated_lines" not in keys and src.candidates() == [] and src.boundary() is None
    caps = src.capabilities()
    assert caps["summer_case"] is False and caps["boundary"] is False and caps["registry"] is False and caps["crs"] == "wgs84"
    # the technology tag round-trips through our own export
    assert sorted(set(net.sgen["type"])) == sorted(set(base.sgen["type"]))
    # positions come from the GL profile: the model sits where NGED's does
    m = src.model()
    assert m.crs == "wgs84" and len(m.buses) == len(NgedSource().model().buses)
    lons = [b.lon for b in m.buses]
    assert min(lons) > -1.0 and max(lons) < 0.5  # Lincolnshire, not a synthetic box


def test_operator_entered_limits_enable_the_summer_case_and_the_boundary(nged_zip):
    meta = ImportMeta(gsp_export_limit_mw=527.0, gsp_name="Bicker Fen", min_demand_factor=0.5, summer_rating_ratio=0.9)
    src = cgmes_source(nged_zip, id="imp-nged-meta", name="NGED with limits", meta=meta)
    report = src.validate()
    assert report.ok and report.cases == ["winter_peak", "summer_min"]
    entered = {a.key: a for a in src.assumptions() if a.source == "operator-entered"}
    assert {"gsp_limit_entered", "min_demand_entered", "summer_ratio_entered"} <= set(entered)
    assert "no_gsp_limit" not in _keys(src.assumptions()) and "no_min_demand" not in _keys(src.assumptions())
    b = src.boundary()
    assert b and b["export_limit_mw"] == 527.0 and b["export_today_mw"] > 0
    assert src.capabilities()["summer_case"] and src.capabilities()["boundary"]
    assert src.fingerprint() != cgmes_source(nged_zip, id="x", name="x").fingerprint()  # the limits are part of the identity


# --- a plain pandapower network with no coordinates -----------------------------------------------------------------------
def test_a_pandapower_json_with_no_coordinates_gets_a_synthetic_layout_and_keeps_its_generators():
    c9 = pn.case9()
    c9.bus["geo"] = None
    c9.gen["type"] = "thermal"
    src = pandapower_json_source(pp.to_json(c9).encode(), id="imp-c9", name="case9")
    report = src.validate()
    assert report.ok and report.converged and report.counts["slacks"] == 1 and report.counts["generators"] == 2, report
    assert len(src.build_net().gen) == 2  # still voltage-controlled, never turned into fixed injections
    keys = _keys(src.assumptions())
    assert "merit_order_dispatch" in keys and "no_gsp_limit" in keys and "no_demand_groups" in keys
    m = src.model()
    assert m.crs == "synthetic" and len(m.buses) == 9 and m.regions == [] and src.capabilities()["crs"] == "synthetic"
    again = pandapower_json_source(pp.to_json(c9).encode(), id="imp-c9", name="case9").model()
    assert [(b.lon, b.lat) for b in m.buses] == [(b.lon, b.lat) for b in again.buses]  # deterministic
    assert len({(b.lon, b.lat) for b in m.buses}) == 9  # no two buses on the same spot
    assert src.fingerprint() == pandapower_json_source(pp.to_json(c9).encode(), id="imp-c9", name="case9").fingerprint()
    assert source_from_file("case9.json", pp.to_json(c9).encode(), id="imp-c9", name="case9").kind == "pandapower_json"


def test_a_file_missing_what_a_real_simulation_needs_is_refused_with_the_list():
    c9 = pn.case9()
    c9.line.at[0, "max_i_ka"] = float("nan")  # an unrated line
    c9.gen.at[0, "max_q_mvar"] = float("nan")  # a power station without its reactive limit
    report = pandapower_json_source(pp.to_json(c9).encode(), id="imp-c9u", name="case9 gaps").validate()
    errors = " | ".join(report.errors)
    assert not report.ok and report.converged is False
    assert "technology" in errors and "thermal rating" in errors and "reactive limits" in errors and "line 0" in errors


def test_validation_reports_a_network_nobody_can_feed():
    net = pp.create_empty_network()
    b1, b2 = pp.create_bus(net, 33.0), pp.create_bus(net, 33.0)
    pp.create_line_from_parameters(net, b1, b2, 1.0, 0.1, 0.1, 0.0, 0.4)
    pp.create_load(net, b2, 5.0)
    report = validate_net(net)  # not normalised: no slack was placed
    assert not report.ok and any("slack" in e for e in report.errors) and report.converged is False


def test_matpower_case_imports_when_scipy_is_available():
    pytest.importorskip("scipy")
    import tempfile
    from pathlib import Path

    from pandapower.converter.matpower import to_mpc

    from gridforge_optimizer.sources import matpower_source
    c9 = pn.case9()
    pp.runpp(c9)
    p = Path(tempfile.mkdtemp()) / "case9.mat"
    to_mpc(c9, str(p))
    src = matpower_source(p.read_bytes(), id="imp-mat", name="case9 mat")
    assert len(src.build_net().bus) == 9 and src.kind == "matpower"
    assert not math.isnan(src.model().buses[0].lon)
    # a MATPOWER case carries no generator technology: refused until it says what each unit is
    assert any("technology" in e for e in src.validate().errors)
