"""Pydantic models exchanged across the engine: inputs (Connection, PlanParams) and outputs (YearResult, PlanResult,
Reason), plus the geolocated model of a network (GridModel)."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, BaseModel, model_validator

from .config import DEFAULT_SCENARIO, GROWTH_2030, GROWTH_2035


class Control(BaseModel):
    """How a connection runs on the grid, as its connection offer sets it: `pf`, a fixed power factor, its reactive
    power following its active power (absorbing counters the voltage rise its export causes); or `voltage`, holding a
    voltage setpoint at its terminals within a reactive range. A connection that states none (`Connection.control`
    None) is modelled at unity power factor."""

    mode: Literal["pf", "voltage"]
    pf: float | None = Field(default=None, ge=0.5, le=1.0)  # pf: the power factor it holds
    absorbing: bool = True  # pf: absorbing reactive power (counters voltage rise) or injecting it
    vm_pu: float | None = Field(default=None, ge=0.9, le=1.1)  # voltage: the setpoint at its terminals
    q_range_pf: float | None = Field(default=None, ge=0.5, lt=1.0)  # voltage: its reactive range at full output, as a power factor

    @model_validator(mode="after")
    def _complete(self) -> Control:
        if self.mode == "pf" and self.pf is None:
            raise ValueError("a power-factor connection needs its power factor (pf)")
        if self.mode == "voltage" and (self.vm_pu is None or self.q_range_pf is None):
            raise ValueError("a voltage-controlled connection needs its setpoint (vm_pu) and its reactive range (q_range_pf)")
        return self

    def q_per_p(self) -> float:
        """A power-factor connection's reactive power per MW of active power (negative when absorbing)."""
        k = math.tan(math.acos(self.pf or 1.0))
        return -k if self.absorbing else k

    def q_limit(self, rating_mw: float) -> float:
        """A voltage-controlled connection's reactive limit either way (MVAr) at its rating."""
        return rating_mw * math.tan(math.acos(self.q_range_pf or 1.0))

    def label(self) -> str:
        if self.mode == "voltage":
            return f"voltage control at {self.vm_pu:g} pu (±{self.q_range_pf:g} pf range)"
        return "unity power factor" if (self.pf or 1.0) >= 1.0 else f"{self.pf:g} power factor {'absorbing' if self.absorbing else 'injecting'}"


class Connection(BaseModel):
    """A generation, storage or demand connection placed on a branch: where it connects, what it is, how big, and the
    plan year it energises in (it is in service from that year on)."""

    request_id: str
    bus_id: int
    technology: str | None = None
    rating_mw: float
    import_mw: float | None = None  # charging or demand capacity (batteries, demand); None = same as the rating
    control: Control | None = None  # how its connection offer runs it; None: unity power factor
    year: int  # the plan year it energises in

    def signature(self) -> tuple:
        """What a power flow with this connection in service depends on (`network.inject_connection`): the key the
        plan-year cache uses, so it can never miss a field the physics reads."""
        return (self.request_id, self.bus_id, self.rating_mw, self.import_mw, self.technology,
                self.control.model_dump_json() if self.control else None)


class Reason(BaseModel):
    """One limit breached in a solve: the element, its figure, the limit and the study case."""

    type: str  # "voltage" | "line" | "trafo" | "gsp" | "non_convergent"
    element_id: int | None = None
    value: float | None = None
    limit: float | None = None  # the limit breached (pu for voltage, % for thermal, MW for the GSP)
    message: str
    case: str | None = None  # the study case it is breached in: "winter_peak" | "summer_min"


class PlanParams(BaseModel):
    """What a run's demand is grown on: the demand pathway (a DFES scenario per primary on the built-in grid), or
    `custom` with its two anchors."""

    growth_2030: float = GROWTH_2030
    growth_2035: float = GROWTH_2035
    scenario: str = DEFAULT_SCENARIO


class YearResult(BaseModel):
    """The plan as it stands in one year: demand grown to the year and the connections energised by then, solved in
    both study cases. Every figure is the worst of the cases (the envelope); `envelope_case` says which case set each
    element's figure, `violations` lists every breach in every case."""

    year: int
    growth: float  # the network-wide demand multiplier this year was solved at
    energised: list[str] = []  # connections in service this year
    converged: bool = True  # False when a study case did not converge (the figures are then empty)
    worst_line_loading_pct: float = 0.0
    worst_trafo_loading_pct: float = 0.0
    min_vm_pu: float = 0.0
    max_vm_pu: float = 0.0
    overloaded_line_ids: list[int] = []
    line_loading: dict[int, float] = {}  # line_id -> loading_percent (worst case)
    trafo_loading: dict[int, float] = {}  # trafo_id -> loading_percent (worst case)
    bus_vm: dict[int, float] = {}  # bus_id -> voltage pu (furthest from 1.0 pu across the cases)
    voltage_violation_bus_ids: list[int] = []  # buses outside their statutory band
    gsp_export_mw: float = 0.0  # peak power pushed UP through the GSP to transmission (worst case)
    gsp_import_mw: float = 0.0  # peak power drawn DOWN from transmission (worst case)
    gsp_limit_mw: float | None = None  # the GSP's export limit to transmission; None = unlimited
    gsp_case: str | None = None  # the case that set the export figure
    envelope_case: dict[str, dict[str, list[int]]] = {}  # case -> {lines, trafos, buses}: the elements whose figure it set
    violations: list[Reason] = []  # every limit breached, per case (voltage, lines, transformers), then the GSP


class PlanResult(BaseModel):
    """A run of a branch: the parameters it was grown on and every plan year."""

    params: PlanParams
    years: dict[str, YearResult] = {}


class ModelAssumption(BaseModel):
    """Something the model had to assume, stated rather than hidden: a builder fallback (a blank rating filled, a tap
    step assumed) or a planning assumption of the study basis."""

    key: str
    message: str
    source: str = "engine-default"
    element_kind: str | None = None
    count: int | None = None
    element_ids: list = []


# --- the geolocated model of a network ---------------------------------------------------------------------------
class ModelBus(BaseModel):
    bus_id: int
    name: str
    vn_kv: float
    lon: float
    lat: float
    place: str = ""  # where it is, by name (`naming`): its own name, or a neighbour's for a coded busbar
    # the voltage band this bus is judged against (`network.voltage_limits`)
    vmin_pu: float
    vmax_pu: float


class ModelLine(BaseModel):
    line_id: int
    line_name: str
    display_name: str = ""  # what people call it (`naming`): the places it joins, parallel circuits numbered
    rating_a: float | None
    voltage_kv: float
    from_bus: int
    to_bus: int
    length_km: float
    from_lon: float
    from_lat: float
    to_lon: float
    to_lat: float
    in_service: bool = True  # False: an open point (the line is in the model but carries nothing)


class ModelTransformer(BaseModel):
    trafo_id: int
    name: str
    display_name: str = ""  # what people call it (`naming`): its substation and ratio
    sn_mva: float
    hv_bus: int
    lv_bus: int
    hv_kv: float
    lv_kv: float
    hv_name: str
    hv_lon: float
    hv_lat: float
    lv_lon: float
    lv_lat: float


class ModelLoad(BaseModel):
    load_id: int
    bus_id: int
    p_mw: float
    region_id: str | None = None
    lon: float
    lat: float


class ModelGenerator(BaseModel):
    """An existing (connected) generator: part of the base network, shown on the map."""

    request_id: str
    bus_id: int
    rating_mw: float
    technology: str
    applicant: str
    lon: float
    lat: float


class GridModel(BaseModel):
    """The map's view of a network (`gridmodel.model_from_net`)."""

    buses: list[ModelBus]
    lines: list[ModelLine]
    transformers: list[ModelTransformer]
    loads: list[ModelLoad]
    generators: list[ModelGenerator]
    regions: list[dict] = []  # kept for the pipeline's warehouse table; the engine no longer fills it
    crs: Literal["wgs84", "synthetic"] = "wgs84"
