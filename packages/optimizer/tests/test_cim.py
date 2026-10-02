"""The CGMES export is well-formed, fully linked, deterministic, and round-trips through
pandapower's own CGMES importer to the same network and the same power-flow solution."""

import tempfile
from pathlib import Path

import pandapower as pp
import pytest
from lxml import etree

from gridforge_optimizer.cim import PROFILES, cgmes_zip_bytes, export_cgmes
from gridforge_optimizer.network import build_base_net, feasibility
from gridforge_optimizer.nged import nged_model


@pytest.fixture(scope="module")
def exported():
    net = build_base_net()
    feasibility(net)  # settle the tap changers so the SSH carries the regulated steps
    return net, export_cgmes(net, nged_model(), "t1")


def _parse(files):
    return {name: etree.fromstring(data) for name, data in files.items()}


def test_profiles_are_well_formed_and_fully_linked(exported):
    _, files = exported
    docs = _parse(files)
    assert sorted(n.rsplit("_", 1)[1] for n in docs) == ["EQ.xml", "GL.xml", "SSH.xml", "TP.xml"]
    ids, refs = set(), []
    for root in docs.values():
        for el in root.iter():
            for k, v in el.attrib.items():
                if k.endswith("}ID"):
                    ids.add(v)
                elif k.endswith("}resource") and v.startswith("#"):
                    refs.append(v[1:])
    assert ids and refs
    assert not [r for r in refs if r not in ids]  # every rdf:resource="#..." points at a defined object
    for name, root in docs.items():
        profile = name.rsplit("_", 1)[1][:-4]
        declared = [e.text for e in root.iter() if e.tag.endswith("Model.profile")]
        assert declared == PROFILES[profile]


def test_export_counts_match_the_network(exported):
    net, files = exported
    eq = _parse(files)[next(n for n in files if n.endswith("_EQ.xml"))]
    count = lambda cls: sum(1 for e in eq if e.tag.endswith("}" + cls))
    assert count("ConnectivityNode") == len(net.bus)
    assert count("ACLineSegment") == len(net.line) == count("CurrentLimit")
    assert count("PowerTransformer") == len(net.trafo) and count("PowerTransformerEnd") == 2 * len(net.trafo)
    assert count("RatioTapChanger") == int((net.trafo.tap_step_percent > 0).sum())
    assert count("EnergyConsumer") == len(net.load)
    assert count("SynchronousMachine") == len(net.sgen)
    assert count("ExternalNetworkInjection") == len(net.ext_grid)


def test_export_is_deterministic(exported):
    net, files = exported
    again = export_cgmes(net, nged_model(), "t1")
    strip = lambda b: b"\n".join(l for l in b.splitlines() if b"Model.created" not in l and b"scenarioTime" not in l)
    assert {k: strip(v) for k, v in files.items()} == {k: strip(v) for k, v in again.items()}
    assert len(cgmes_zip_bytes(files)) > 10_000


def test_round_trips_through_pandapowers_cgmes_importer(exported):
    from pandapower.converter.cim.cim2pp.from_cim import from_cim

    net, files = exported
    d = Path(tempfile.mkdtemp())
    paths = []
    for name, data in files.items():
        (d / name).write_bytes(data)
        paths.append(str(d / name))
    back = from_cim(file_list=paths, cgmes_version="2.4.15", run_powerflow=False, ignore_errors=False)
    assert (len(back.bus), len(back.line), len(back.trafo), len(back.load), len(back.sgen), len(back.ext_grid)) == (
        len(net.bus), len(net.line), len(net.trafo), len(net.load), len(net.sgen), len(net.ext_grid))
    assert float(back.line.length_km.sum()) == pytest.approx(float(net.line.length_km.sum()), rel=1e-6)
    assert float(back.line.max_i_ka.sum()) == pytest.approx(float(net.line.max_i_ka.sum()), rel=1e-6)
    assert sorted(back.trafo.sn_mva.round(3)) == sorted(net.trafo.sn_mva.round(3))
    assert sorted(back.trafo.vk_percent) == pytest.approx(sorted(net.trafo.vk_percent), abs=2e-3)  # r/x -> vk round-trip
    assert sorted(back.trafo.tap_pos.astype(int)) == sorted(net.trafo.tap_pos.astype(int))
    assert float(back.load.p_mw.sum()) == pytest.approx(float((net.load.p_mw * net.load.scaling).sum()), rel=1e-6)
    assert float(back.sgen.p_mw.sum()) == pytest.approx(float(net.sgen.p_mw.sum()), rel=1e-6)
    # the physics agrees: same voltage envelope, same exchange with transmission
    pp.runpp(back)
    pp.runpp(net)
    assert float(back.res_bus.vm_pu.min()) == pytest.approx(float(net.res_bus.vm_pu.min()), abs=1e-4)
    assert float(back.res_bus.vm_pu.max()) == pytest.approx(float(net.res_bus.vm_pu.max()), abs=1e-4)
    assert float(back.res_ext_grid.p_mw.sum()) == pytest.approx(float(net.res_ext_grid.p_mw.sum()), abs=0.05)
