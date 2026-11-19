"""The geolocated model of a network for the map and the API (`GridModel`), shaped from a pandapower net the same way
for every source. Pure."""

from __future__ import annotations

import math

from .naming import name_model
from .network import voltage_limits
from .types import GridModel, ModelBus, ModelGenerator, ModelLine, ModelLoad, ModelTransformer


def _name(v, fallback: str) -> str:
    return fallback if v is None or (isinstance(v, float) and math.isnan(v)) or str(v).strip() in ("", "nan", "None") else str(v)


def model_from_net(net, xy: dict[int, tuple[float, float]], existing: list[dict], crs: str = "wgs84") -> GridModel:
    """Buses, lines, transformers, loads and the existing fleet with their positions. `existing` is the fleet as the
    source describes it (NGED's builder keeps its own list)."""
    vmin, vmax = voltage_limits(net)
    buses = [ModelBus(bus_id=int(i), name=_name(net.bus.at[i, "name"], f"bus {i}"), vn_kv=float(net.bus.at[i, "vn_kv"]),
                      lon=xy[int(i)][0], lat=xy[int(i)][1], vmin_pu=float(vmin[i]), vmax_pu=float(vmax[i])) for i in net.bus.index]
    lines = []
    for i in net.line.index:
        f, t = int(net.line.at[i, "from_bus"]), int(net.line.at[i, "to_bus"])
        imax = float(net.line.at[i, "max_i_ka"])
        lines.append(ModelLine(line_id=int(i), line_name=_name(net.line.at[i, "name"], f"L{i}"),
                               rating_a=round(imax * 1000, 0),  # an unrated line is refused at import, NGED's are all rated
                               voltage_kv=float(net.bus.at[f, "vn_kv"]), from_bus=f, to_bus=t,
                               length_km=round(float(net.line.at[i, "length_km"]), 3),
                               from_lon=xy[f][0], from_lat=xy[f][1], to_lon=xy[t][0], to_lat=xy[t][1],
                               # a connector (out of service, joined by a closed switch) is joined, not an open point
                               in_service=bool(net.line.at[i, "in_service"]) or bool(net.line.get("connector", {}).get(i, False))))
    transformers = []
    for i in net.trafo.index:
        hv, lv = int(net.trafo.at[i, "hv_bus"]), int(net.trafo.at[i, "lv_bus"])
        transformers.append(ModelTransformer(trafo_id=int(i), name=_name(net.trafo.at[i, "name"], f"T{i}"),
                                             sn_mva=float(net.trafo.at[i, "sn_mva"]), hv_bus=hv, lv_bus=lv,
                                             hv_kv=float(net.bus.at[hv, "vn_kv"]), lv_kv=float(net.bus.at[lv, "vn_kv"]),
                                             hv_name=_name(net.bus.at[hv, "name"], f"bus {hv}"),
                                             hv_lon=xy[hv][0], hv_lat=xy[hv][1], lv_lon=xy[lv][0], lv_lat=xy[lv][1]))
    has_regions = "region_id" in net.load.columns
    loads = []
    for n, i in enumerate(net.load.index):
        b = int(net.load.at[i, "bus"])
        rid = net.load.at[i, "region_id"] if has_regions else None
        loads.append(ModelLoad(load_id=n, bus_id=b, p_mw=round(float(net.load.at[i, "p_mw"]), 3),
                               region_id=None if rid is None or (isinstance(rid, float) and math.isnan(rid)) else str(rid),
                               lon=xy[b][0], lat=xy[b][1]))
    generators = []
    for g in existing:
        b = int(g["bus_id"])
        generators.append(ModelGenerator(request_id=g["request_id"], bus_id=b, rating_mw=float(g["rating_mw"]),
                                         technology=g["technology"], applicant=g["applicant"], lon=xy[b][0], lat=xy[b][1]))
    model = GridModel(buses=buses, lines=lines, transformers=transformers, loads=loads, generators=generators, crs=crs)
    name_model(model)  # every element by the name people use for it
    return model
