"""Export the network as CIM / CGMES (IEC 61970 CIM16, ENTSO-E CGMES 2.4.15 profiles).

CIM is the common model standard GB networks exchange planning models in (Squid sits on the GB CIM
Advisory Group; Squid's canonical model is CIM/CGMES). This module serialises a pandapower network
plus the geolocated model into four RDF/XML profile files:

  EQ   equipment: regions, base voltages, substations, voltage levels, connectivity nodes,
       AC line segments (+ current limits), power transformers (+ ends, ratio tap changers),
       energy consumers, synchronous machines (+ generating units), the external network injection
  TP   topology: one topological node per bus, terminals mapped to it
  SSH  steady-state hypothesis: load p/q, machine p/q, tap steps, terminal connected flags
  GL   geographical location: a WGS84 position per substation

Identifiers are deterministic (uuid5 of stable keys), so exporting the same network twice gives the
same bytes: the files are diffable, and `network@<snapshot_id>` is written into each model header.
Pure: no I/O except through `write_cgmes_zip`. Verified by re-importing with pandapower's own CGMES
importer (tests/test_cim.py).
"""

from __future__ import annotations

import io
import math
import uuid
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from .nged import _substation

CIM = "http://iec.ch/TC57/2013/CIM-schema-cim16#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
MD = "http://iec.ch/TC57/61970-552/ModelDescription/1#"
ENTSOE = "http://entsoe.eu/CIM/SchemaExtension/3/1#"
PROFILES = {
    "EQ": ["http://entsoe.eu/CIM/EquipmentCore/3/1", "http://entsoe.eu/CIM/EquipmentOperation/3/1"],
    "TP": ["http://entsoe.eu/CIM/Topology/4/1"],
    "SSH": ["http://entsoe.eu/CIM/SteadyStateHypothesis/1/1"],
    "GL": ["http://entsoe.eu/CIM/GeographicalLocation/2/1"],
}
_NS = uuid.UUID("6f1c8d2e-4a5b-4c6d-8e9f-0a1b2c3d4e5f")  # namespace for the deterministic ids
_UNIT_KINDS = {"solar": "SolarGeneratingUnit", "wind": "WindGeneratingUnit", "battery": "ThermalGeneratingUnit",
               "other": "ThermalGeneratingUnit"}


def _id(*parts) -> str:
    """A stable mRID-style id for an object, from the parts that identify it."""
    return "_" + str(uuid.uuid5(_NS, "|".join(str(p) for p in parts)))


class _Doc:
    """One profile document: an rdf:RDF root with a FullModel header, and helpers to add objects."""

    def __init__(self, profile: str, model_id: str, description: str, created: str, deps: list[str]):
        ET.register_namespace("cim", CIM)
        ET.register_namespace("rdf", RDF)
        ET.register_namespace("md", MD)
        ET.register_namespace("entsoe", ENTSOE)
        self.root = ET.Element(f"{{{RDF}}}RDF")
        fm = ET.SubElement(self.root, f"{{{MD}}}FullModel", {f"{{{RDF}}}about": f"urn:uuid:{model_id}"})
        ET.SubElement(fm, f"{{{MD}}}Model.scenarioTime").text = created
        ET.SubElement(fm, f"{{{MD}}}Model.created").text = created
        ET.SubElement(fm, f"{{{MD}}}Model.description").text = description
        ET.SubElement(fm, f"{{{MD}}}Model.version").text = "1"
        for p in PROFILES[profile]:
            ET.SubElement(fm, f"{{{MD}}}Model.profile").text = p
        for d in deps:
            ET.SubElement(fm, f"{{{MD}}}Model.DependentOn", {f"{{{RDF}}}resource": f"urn:uuid:{d}"})
        ET.SubElement(fm, f"{{{MD}}}Model.modelingAuthoritySet").text = "http://gridforge.example/ngedd-bickerfen"

    def obj(self, cls: str, oid: str, *, about: bool = False, name: str | None = None) -> ET.Element:
        key = f"{{{RDF}}}about" if about else f"{{{RDF}}}ID"
        e = ET.SubElement(self.root, f"{{{CIM}}}{cls}", {key: (f"#{oid}" if about else oid)})
        if name is not None:
            ET.SubElement(e, f"{{{CIM}}}IdentifiedObject.name").text = str(name)
        return e

    @staticmethod
    def attr(e: ET.Element, prop: str, value) -> None:
        ET.SubElement(e, f"{{{CIM}}}{prop}").text = _fmt(value)

    @staticmethod
    def ref(e: ET.Element, prop: str, oid: str) -> None:
        ET.SubElement(e, f"{{{CIM}}}{prop}", {f"{{{RDF}}}resource": f"#{oid}"})

    @staticmethod
    def enum(e: ET.Element, prop: str, value: str) -> None:
        ET.SubElement(e, f"{{{CIM}}}{prop}", {f"{{{RDF}}}resource": f"{CIM}{value}"})

    def bytes(self) -> bytes:
        ET.indent(self.root, space="  ")
        return ET.tostring(self.root, encoding="utf-8", xml_declaration=True)


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:.10g}"
    return str(v)


def export_cgmes(net, model: dict | None = None, snapshot_id: str = "network") -> dict[str, bytes]:
    """Serialise `net` (a pandapower network) to CGMES. `model` (the geolocated model from
    `nged_model`) supplies substation coordinates for the GL profile; without it GL has no points.

    Returns {file name: xml bytes} for the EQ, TP, SSH and GL profiles.
    """
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    tag = f"GridForge network@{snapshot_id}"
    mids = {p: str(uuid.uuid5(_NS, f"{snapshot_id}|{p}")) for p in PROFILES}
    eq = _Doc("EQ", mids["EQ"], f"{tag} · equipment", created, [])
    tp = _Doc("TP", mids["TP"], f"{tag} · topology", created, [mids["EQ"]])
    ssh = _Doc("SSH", mids["SSH"], f"{tag} · steady state hypothesis", created, [mids["EQ"]])
    gl = _Doc("GL", mids["GL"], f"{tag} · geographical location", created, [mids["EQ"]])

    # regions
    region = _id("region", "GB")
    e = eq.obj("GeographicalRegion", region, name="Great Britain")
    subregion = _id("subregion", "NGED")
    e = eq.obj("SubGeographicalRegion", subregion, name="NGED East Midlands licence area")
    eq.ref(e, "SubGeographicalRegion.Region", region)

    # base voltages
    base_voltage: dict[float, str] = {}
    for kv in sorted({round(float(v), 3) for v in net.bus["vn_kv"]}):
        bid = _id("basevoltage", kv)
        base_voltage[kv] = bid
        e = eq.obj("BaseVoltage", bid, name=f"{kv:g} kV")
        eq.attr(e, "BaseVoltage.nominalVoltage", float(kv))

    # substations, voltage levels, nodes
    sub_ids: dict[str, str] = {}
    vl_ids: dict[tuple[str, float], str] = {}
    node_of_bus: dict[int, str] = {}
    vl_of_bus: dict[int, str] = {}
    for b in net.bus.index:
        bus_name = str(net.bus.at[b, "name"] or f"bus {b}")
        sub = _substation(bus_name) or bus_name
        kv = round(float(net.bus.at[b, "vn_kv"]), 3)
        if sub not in sub_ids:
            sid = _id("substation", sub)
            sub_ids[sub] = sid
            e = eq.obj("Substation", sid, name=sub)
            eq.ref(e, "Substation.Region", subregion)
        if (sub, kv) not in vl_ids:
            vid = _id("voltagelevel", sub, kv)
            vl_ids[(sub, kv)] = vid
            e = eq.obj("VoltageLevel", vid, name=f"{sub} {kv:g} kV")
            eq.ref(e, "VoltageLevel.Substation", sub_ids[sub])
            eq.ref(e, "VoltageLevel.BaseVoltage", base_voltage[kv])
        nid = _id("connectivitynode", int(b))
        node_of_bus[int(b)] = nid
        vl_of_bus[int(b)] = vl_ids[(sub, kv)]
        e = eq.obj("ConnectivityNode", nid, name=bus_name)
        eq.ref(e, "ConnectivityNode.ConnectivityNodeContainer", vl_ids[(sub, kv)])
        # topology: one topological node per connectivity node
        tnid = _id("topologicalnode", int(b))
        e = tp.obj("TopologicalNode", tnid, name=bus_name)
        tp.ref(e, "TopologicalNode.ConnectivityNodeContainer", vl_ids[(sub, kv)])
        tp.ref(e, "TopologicalNode.BaseVoltage", base_voltage[kv])
        e = tp.obj("ConnectivityNode", nid, about=True)
        tp.ref(e, "ConnectivityNode.TopologicalNode", tnid)

    def terminal(owner_id: str, bus: int, seq: int, key: str) -> str:
        tid = _id("terminal", key, seq)
        e = eq.obj("Terminal", tid, name=f"{key} T{seq}")
        eq.ref(e, "Terminal.ConductingEquipment", owner_id)
        eq.ref(e, "Terminal.ConnectivityNode", node_of_bus[bus])
        eq.attr(e, "ACDCTerminal.sequenceNumber", seq)
        eq.enum(e, "Terminal.phases", "PhaseCode.ABC")
        e = tp.obj("Terminal", tid, about=True)
        tp.ref(e, "Terminal.TopologicalNode", _id("topologicalnode", bus))
        e = ssh.obj("Terminal", tid, about=True)
        ssh.attr(e, "ACDCTerminal.connected", True)
        return tid

    # one PATL limit type for every current limit
    patl = _id("limittype", "PATL")
    e = eq.obj("OperationalLimitType", patl, name="PATL")
    eq.attr(e, "OperationalLimitType.acceptableDuration", 1e9)
    eq.enum(e, "OperationalLimitType.direction", "OperationalLimitDirectionKind.absoluteValue")
    ET.SubElement(e, f"{{{ENTSOE}}}OperationalLimitType.limitType", {f"{{{RDF}}}resource": f"{ENTSOE}LimitTypeKind.patl"})

    # lines
    for i in net.line.index:
        f, t = int(net.line.at[i, "from_bus"]), int(net.line.at[i, "to_bus"])
        lid = _id("acline", int(i))
        name = str(net.line.at[i, "name"] or f"line {i}")
        length_km = float(net.line.at[i, "length_km"])
        par = int(net.line.at[i, "parallel"]) if "parallel" in net.line.columns else 1
        e = eq.obj("ACLineSegment", lid, name=f"{name} ({i})")
        eq.ref(e, "Equipment.EquipmentContainer", vl_of_bus[f])
        eq.ref(e, "ConductingEquipment.BaseVoltage", base_voltage[round(float(net.bus.at[f, "vn_kv"]), 3)])
        eq.attr(e, "Conductor.length", length_km)
        eq.attr(e, "ACLineSegment.r", float(net.line.at[i, "r_ohm_per_km"]) * length_km / par)
        eq.attr(e, "ACLineSegment.x", float(net.line.at[i, "x_ohm_per_km"]) * length_km / par)
        eq.attr(e, "ACLineSegment.bch", 2 * math.pi * 50 * float(net.line.at[i, "c_nf_per_km"]) * 1e-9 * length_km * par)
        eq.attr(e, "ACLineSegment.gch", 0.0)
        eq.attr(e, "ACLineSegment.r0", float(net.line.at[i, "r_ohm_per_km"]) * length_km / par * 3)
        eq.attr(e, "ACLineSegment.x0", float(net.line.at[i, "x_ohm_per_km"]) * length_km / par * 3)
        eq.attr(e, "ACLineSegment.b0ch", 0.0)
        eq.attr(e, "ACLineSegment.g0ch", 0.0)
        eq.attr(e, "ACLineSegment.shortCircuitEndTemperature", 90.0)
        t1 = terminal(lid, f, 1, f"acline{i}")
        terminal(lid, t, 2, f"acline{i}")
        # thermal rating as a current limit on terminal 1
        amps = float(net.line.at[i, "max_i_ka"]) * 1000.0 * par
        sid = _id("limitset", "acline", int(i))
        e = eq.obj("OperationalLimitSet", sid, name=f"{name} rating")
        eq.ref(e, "OperationalLimitSet.Terminal", t1)
        e = eq.obj("CurrentLimit", _id("currentlimit", "acline", int(i)), name="PATL")
        eq.attr(e, "CurrentLimit.value", amps)
        eq.ref(e, "OperationalLimit.OperationalLimitSet", sid)
        eq.ref(e, "OperationalLimit.OperationalLimitType", patl)

    # transformers (two-winding), impedance referred to the HV end, ratio tap changer on the HV end
    for i in net.trafo.index:
        hv, lv = int(net.trafo.at[i, "hv_bus"]), int(net.trafo.at[i, "lv_bus"])
        tid = _id("trafo", int(i))
        name = str(net.trafo.at[i, "name"] or f"transformer {i}")
        sn = float(net.trafo.at[i, "sn_mva"])
        u_hv, u_lv = float(net.trafo.at[i, "vn_hv_kv"]), float(net.trafo.at[i, "vn_lv_kv"])
        vk, vkr = float(net.trafo.at[i, "vk_percent"]), float(net.trafo.at[i, "vkr_percent"])
        z_base = u_hv ** 2 / sn
        r = vkr / 100.0 * z_base
        x = math.sqrt(max(vk ** 2 - vkr ** 2, 0.0)) / 100.0 * z_base
        sub_name = _substation(str(net.bus.at[hv, "name"] or "")) or str(net.bus.at[hv, "name"])
        e = eq.obj("PowerTransformer", tid, name=f"{sub_name} {name} ({i})")
        eq.ref(e, "Equipment.EquipmentContainer", sub_ids[sub_name])
        ends = []
        for end_no, (bus, u, rr, xx) in enumerate(((hv, u_hv, r, x), (lv, u_lv, 0.0, 0.0)), start=1):
            term = terminal(tid, bus, end_no, f"trafo{i}")
            eid = _id("trafoend", int(i), end_no)
            ends.append(eid)
            e = eq.obj("PowerTransformerEnd", eid, name=f"{name} end {end_no}")
            eq.ref(e, "PowerTransformerEnd.PowerTransformer", tid)
            eq.ref(e, "TransformerEnd.Terminal", term)
            eq.ref(e, "TransformerEnd.BaseVoltage", base_voltage[round(float(net.bus.at[bus, "vn_kv"]), 3)])
            eq.attr(e, "TransformerEnd.endNumber", end_no)
            eq.attr(e, "TransformerEnd.grounded", end_no == 1)
            eq.attr(e, "PowerTransformerEnd.ratedS", sn)
            eq.attr(e, "PowerTransformerEnd.ratedU", u)
            eq.attr(e, "PowerTransformerEnd.r", rr)
            eq.attr(e, "PowerTransformerEnd.x", xx)
            eq.attr(e, "PowerTransformerEnd.b", 0.0)
            eq.attr(e, "PowerTransformerEnd.g", 0.0)
            eq.attr(e, "PowerTransformerEnd.r0", rr)
            eq.attr(e, "PowerTransformerEnd.x0", xx)
            eq.attr(e, "PowerTransformerEnd.b0", 0.0)
            eq.attr(e, "PowerTransformerEnd.g0", 0.0)
            eq.attr(e, "PowerTransformerEnd.phaseAngleClock", 0 if end_no == 1 else 11)
            eq.enum(e, "PowerTransformerEnd.connectionKind", "WindingConnection.Y" if end_no == 1 else "WindingConnection.D")
        step = float(net.trafo.at[i, "tap_step_percent"]) if "tap_step_percent" in net.trafo.columns else 0.0
        if step and step > 0:
            tc = _id("tapchanger", int(i))
            e = eq.obj("RatioTapChanger", tc, name=f"{name} OLTC")
            eq.ref(e, "RatioTapChanger.TransformerEnd", ends[0])
            eq.attr(e, "TapChanger.lowStep", int(net.trafo.at[i, "tap_min"]))
            eq.attr(e, "TapChanger.highStep", int(net.trafo.at[i, "tap_max"]))
            eq.attr(e, "TapChanger.neutralStep", int(net.trafo.at[i, "tap_neutral"]))
            eq.attr(e, "TapChanger.normalStep", int(net.trafo.at[i, "tap_neutral"]))
            eq.attr(e, "TapChanger.neutralU", u_hv)
            eq.attr(e, "TapChanger.ltcFlag", True)
            eq.attr(e, "RatioTapChanger.stepVoltageIncrement", step)
            eq.enum(e, "RatioTapChanger.tculControlMode", "TransformerControlMode.volt")
            e = ssh.obj("RatioTapChanger", tc, about=True)
            ssh.attr(e, "TapChanger.step", int(net.trafo.at[i, "tap_pos"]))
            ssh.attr(e, "TapChanger.controlEnabled", False)

    # loads
    for i in net.load.index:
        b = int(net.load.at[i, "bus"])
        lid = _id("load", int(i))
        name = str(net.load.at[i, "name"] or f"load {i}")
        e = eq.obj("EnergyConsumer", lid, name=f"{name} ({i})")
        eq.ref(e, "Equipment.EquipmentContainer", vl_of_bus[b])
        eq.ref(e, "ConductingEquipment.BaseVoltage", base_voltage[round(float(net.bus.at[b, "vn_kv"]), 3)])
        terminal(lid, b, 1, f"load{i}")
        e = ssh.obj("EnergyConsumer", lid, about=True)
        scale = float(net.load.at[i, "scaling"]) if "scaling" in net.load.columns else 1.0
        ssh.attr(e, "EnergyConsumer.p", float(net.load.at[i, "p_mw"]) * scale)
        ssh.attr(e, "EnergyConsumer.q", float(net.load.at[i, "q_mvar"]) * scale)

    # generation: synchronous machines (PQ, not regulating) with a generating unit per technology
    for i in net.sgen.index:
        b = int(net.sgen.at[i, "bus"])
        mid = _id("machine", int(i))
        name = str(net.sgen.at[i, "name"] or f"generator {i}")
        tech = str(net.sgen.at[i, "type"] or "other").lower()
        p_rated = float(net.sgen.at[i, "p_rated_mw"]) if "p_rated_mw" in net.sgen.columns and net.sgen.at[i, "p_rated_mw"] == net.sgen.at[i, "p_rated_mw"] else float(net.sgen.at[i, "p_mw"])
        uid = _id("genunit", int(i))
        e = eq.obj(_UNIT_KINDS.get(tech, "ThermalGeneratingUnit"), uid, name=f"{name} unit")
        eq.ref(e, "Equipment.EquipmentContainer", sub_ids[_substation(str(net.bus.at[b, "name"] or "")) or str(net.bus.at[b, "name"])])
        eq.attr(e, "GeneratingUnit.initialP", float(net.sgen.at[i, "p_mw"]))
        eq.attr(e, "GeneratingUnit.maxOperatingP", p_rated)
        eq.attr(e, "GeneratingUnit.minOperatingP", 0.0)
        eq.attr(e, "GeneratingUnit.nominalP", p_rated)
        e = eq.obj("SynchronousMachine", mid, name=f"{name} ({i})")
        eq.ref(e, "Equipment.EquipmentContainer", vl_of_bus[b])
        eq.ref(e, "ConductingEquipment.BaseVoltage", base_voltage[round(float(net.bus.at[b, "vn_kv"]), 3)])
        eq.ref(e, "RotatingMachine.GeneratingUnit", uid)
        eq.attr(e, "RotatingMachine.ratedS", max(p_rated, 0.01))
        eq.attr(e, "RotatingMachine.ratedU", float(net.bus.at[b, "vn_kv"]))
        eq.attr(e, "SynchronousMachine.maxQ", p_rated * 0.33)
        eq.attr(e, "SynchronousMachine.minQ", -p_rated * 0.33)
        eq.enum(e, "SynchronousMachine.type", "SynchronousMachineKind.generator")
        terminal(mid, b, 1, f"machine{i}")
        e = ssh.obj("SynchronousMachine", mid, about=True)
        ssh.attr(e, "RotatingMachine.p", -float(net.sgen.at[i, "p_mw"]))  # CIM load convention: generation is negative
        ssh.attr(e, "RotatingMachine.q", -float(net.sgen.at[i, "q_mvar"]))
        ssh.attr(e, "RegulatingCondEq.controlEnabled", False)
        ssh.attr(e, "SynchronousMachine.referencePriority", 0)
        ssh.enum(e, "SynchronousMachine.operatingMode", "SynchronousMachineOperatingMode.generator")

    # the transmission infeed (slack) as an external network injection with a voltage target
    for i in net.ext_grid.index:
        b = int(net.ext_grid.at[i, "bus"])
        xid = _id("extgrid", int(i))
        name = str(net.ext_grid.at[i, "name"] or "external grid")
        e = eq.obj("ExternalNetworkInjection", xid, name=name)
        eq.ref(e, "Equipment.EquipmentContainer", vl_of_bus[b])
        eq.ref(e, "ConductingEquipment.BaseVoltage", base_voltage[round(float(net.bus.at[b, "vn_kv"]), 3)])
        eq.attr(e, "ExternalNetworkInjection.maxP", 1e4)
        eq.attr(e, "ExternalNetworkInjection.minP", -1e4)
        eq.attr(e, "ExternalNetworkInjection.maxQ", 1e4)
        eq.attr(e, "ExternalNetworkInjection.minQ", -1e4)
        term = terminal(xid, b, 1, f"extgrid{i}")
        rc = _id("regcontrol", int(i))
        eq.ref(e, "RegulatingCondEq.RegulatingControl", rc)
        e = eq.obj("RegulatingControl", rc, name=f"{name} voltage control")
        eq.ref(e, "RegulatingControl.Terminal", term)
        eq.enum(e, "RegulatingControl.mode", "RegulatingControlModeKind.voltage")
        e = ssh.obj("RegulatingControl", rc, about=True)
        ssh.attr(e, "RegulatingControl.discrete", False)
        ssh.attr(e, "RegulatingControl.enabled", True)
        ssh.attr(e, "RegulatingControl.targetDeadband", 0.0)
        ssh.attr(e, "RegulatingControl.targetValue", float(net.ext_grid.at[i, "vm_pu"]) * float(net.bus.at[b, "vn_kv"]))
        ssh.enum(e, "RegulatingControl.targetValueUnitMultiplier", "UnitMultiplier.k")
        e = ssh.obj("ExternalNetworkInjection", xid, about=True)
        ssh.attr(e, "ExternalNetworkInjection.p", 0.0)
        ssh.attr(e, "ExternalNetworkInjection.q", 0.0)
        ssh.attr(e, "RegulatingCondEq.controlEnabled", True)
        ssh.attr(e, "ExternalNetworkInjection.referencePriority", 1)

    # geography: one WGS84 point per substation (from the geolocated model), ODbL-credited upstream
    crs = _id("crs", "WGS84")
    e = gl.obj("CoordinateSystem", crs, name="WGS 84")
    gl.attr(e, "CoordinateSystem.crsUrn", "urn:ogc:def:crs:EPSG::4326")
    if model:
        pos: dict[str, tuple[float, float]] = {}
        for bus in model.get("buses", []):
            sub = _substation(str(bus.get("name") or "")) or str(bus.get("name"))
            if sub in sub_ids and sub not in pos and bus.get("lon") is not None:
                pos[sub] = (float(bus["lon"]), float(bus["lat"]))
        for sub, (lon, lat) in pos.items():
            loc = _id("location", sub)
            e = gl.obj("Location", loc, name=f"{sub} location")
            gl.ref(e, "Location.CoordinateSystem", crs)
            gl.ref(e, "Location.PowerSystemResources", sub_ids[sub])
            e = gl.obj("PositionPoint", _id("position", sub))
            gl.ref(e, "PositionPoint.Location", loc)
            gl.attr(e, "PositionPoint.sequenceNumber", 1)
            gl.attr(e, "PositionPoint.xPosition", lon)
            gl.attr(e, "PositionPoint.yPosition", lat)

    stem = f"GridForge_{snapshot_id}"
    return {f"{stem}_EQ.xml": eq.bytes(), f"{stem}_TP.xml": tp.bytes(), f"{stem}_SSH.xml": ssh.bytes(), f"{stem}_GL.xml": gl.bytes()}


def cgmes_zip_bytes(files: dict[str, bytes]) -> bytes:
    """The four profile files as one zip archive (the usual CGMES exchange unit)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def write_cgmes_zip(path, net, model: dict | None = None, snapshot_id: str = "network") -> dict[str, int]:
    """Export to a zip at `path`; returns {file name: bytes}."""
    files = export_cgmes(net, model, snapshot_id)
    with open(path, "wb") as f:
        f.write(cgmes_zip_bytes(files))
    return {k: len(v) for k, v in files.items()}
