"""Pydantic models exchanged across the optimizer: inputs (Candidate, OptimizeParams) and
outputs (QueueItem, PhaseResult, OptimizeResult, Reason)."""

from __future__ import annotations

import math
from typing import Literal, NamedTuple

from pydantic import Field, BaseModel, model_validator

from .config import (
    DEFAULT_SCENARIO,
    FORECASTS,
    GROWTH_2030,
    GROWTH_2035,
    IMPORT_FORECAST_FACTOR_MAX,
    IMPORT_PATHWAYS,
    PLAN_END_YEAR,
    PLAN_START_YEAR,
    W_NEED,
    W_READINESS,
    W_STRATEGIC,
)


class Control(BaseModel):
    """How a project runs on the grid, as its connection offer sets it (the DNO's choice, not the engine's): `pf`, a
    fixed power factor, its reactive power following its active power (absorbing counters the voltage rise its export
    causes); or `voltage`, holding a voltage setpoint at its terminals within a reactive range (a large connection's
    voltage support). A project that does not state one (`Candidate.control` None) is modelled at unity power factor."""

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


class Candidate(BaseModel):
    """A proposed connection project fed into the optimizer (pre-scored by the pipeline)."""

    request_id: str
    bus_id: int | None = None
    technology: str | None = None
    rating_mw: float | None = None
    readiness_score: float = 0.5
    strategic_fit: float = 0.5
    readiness_rationale: str = ""
    status: str = "auto_accept"  # "auto_accept" | "needs_review"
    review_reasons: str = ""
    commissioning_year: int | None = None  # developer's requested energisation year (the timeline axis)
    import_mw: float | None = None  # charging capacity (batteries); None = same as the rating
    control: Control | None = None  # how its connection offer runs it; None: not stated, modelled at unity power factor

    def import_at(self, rating_mw: float) -> float | None:
        """The import this project keeps at another export size: it scales with the rating (a battery
        resized from 248 to 60 MW charges at 60 MW, not 248). None while it has no import of its own
        (it then follows the rating) or no rating to scale from."""
        if self.import_mw is None or not self.rating_mw:
            return None
        return float(self.import_mw) * rating_mw / float(self.rating_mw)

    def signature(self) -> tuple:
        """What a power flow with this project in service depends on (`network.inject_project`): the one key both the
        greedy trial cache and the plan-year signature use, so neither can miss a field the physics reads."""
        return (self.request_id, self.bus_id, self.rating_mw, self.import_mw, self.technology,
                self.control.model_dump_json() if self.control else None)


class Reason(BaseModel):
    """Why a project was deferred or rejected, with the binding element where applicable."""

    type: str  # a REASON_SPECS key ("voltage" | "line" | "trafo" | "gsp" | "non_convergent" | "islanded"; "collapse" in N-1 records only), or "rejected"
    element_id: int | None = None
    value: float | None = None
    limit: float | None = None  # the limit breached (pu for voltage, % for thermal, MW for the GSP)
    message: str
    case: str | None = None  # the study case it fails in: "winter_peak" | "summer_min" (None = n/a)


class ReasonSpec(NamedTuple):
    """What the planning layer knows about one kind of breach (the engine's `network.LIMIT_CHECKS` and its boundary and
    convergence reasons): a new kind is one entry here, beside its check (AGENTS.md rule 6)."""

    unit: str  # its figure's unit
    grid: bool = True  # the GRID held a project back (not intake or policy): findings, the gate, the agents' grid levers
    thermal: bool = False  # a parallel circuit on the binding element relieves it (suggest's chain)
    n1_order: int = 4  # worst first among N-1 findings during a works window (maintenance)


REASON_SPECS: dict[str, ReasonSpec] = {
    "non_convergent": ReasonSpec("", n1_order=0),
    "collapse": ReasonSpec("pu", n1_order=0),  # the N-1 screen's "no credible post-fault state" (network.N1_COLLAPSE_VM_PU)
    "islanded": ReasonSpec("MW", n1_order=1),
    "line": ReasonSpec("%", thermal=True, n1_order=2),
    "trafo": ReasonSpec("%", thermal=True, n1_order=2),
    "voltage": ReasonSpec("pu", n1_order=3),
    "gsp": ReasonSpec("MW"),
}


class QueueItem(BaseModel):
    """One project's place in the ordered queue: its rank, phase, scores, and reason."""

    rank: int | None
    request_id: str
    bus_id: int | None
    technology: str | None
    rating_mw: float | None
    readiness_score: float
    strategic_fit: float
    grid_need: float
    rank_score: float | None
    status: str  # "Phase1" | "Phase2" | "Deferred" | "Rejected"
    reason: Reason | None = None
    commissioning_year: int | None = None  # developer's requested energisation year
    recommended_year: int | None = None  # the year the optimizer suggests it energise (None if it can't)
    worst_line_loading_pct: float | None = None
    readiness_rationale: str = ""


class OptimizeParams(BaseModel):
    """Tunable inputs to a run: demand growth per phase, the DFES pathway, and ranking weights."""

    growth_2030: float = GROWTH_2030
    growth_2035: float = GROWTH_2035
    # DFES pathway id driving the per-bus growth shape; "custom" = uniform scalar growth.
    scenario: str = DEFAULT_SCENARIO
    # an imported grid's forecast, entered at import: the peak-demand multiplier for every plan year after the first,
    # spread uniformly over its loads (network.demand_multiplier, grow_for); None: the pathway's two anchors above
    curve: dict[int, float] | None = None
    w_readiness: float = W_READINESS
    w_need: float = W_NEED
    w_strategic: float = W_STRATEGIC


class PhaseResult(BaseModel):
    """The solved network state at the end of a phase: who connected and the loading/voltage limits."""

    accepted: list[str]
    worst_line_loading_pct: float
    worst_trafo_loading_pct: float
    min_vm_pu: float
    max_vm_pu: float
    overloaded_line_ids: list[int]
    line_loading: dict[int, float] = {}  # line_id -> loading_percent, for the map heat overlay
    bus_vm: dict[int, float] = {}  # bus_id -> voltage pu, for the map voltage overlay
    voltage_violation_bus_ids: list[int] = []  # buses outside the voltage band
    gsp_export_mw: float = 0.0  # peak power pushed UP through the GSP to transmission (worst case)
    gsp_import_mw: float = 0.0  # peak power drawn DOWN from transmission (worst case)
    gsp_limit_mw: float | None = None  # the GSP's export limit to transmission; None = unlimited
    n1_cases: list[str] = []  # the study cases the N-1 screen ran in (config.N1_CASES, those the net supports)
    n1_screened: int = 0  # EHV elements outaged one at a time in the N-1 screen (per case)
    n1_violations: list[dict] = []  # {outage_type, outage_id, outage_name, case, type, element_id, value, message}; islands on the first case only
    # every figure above is the worst of the study cases: which case set each element's, case -> {lines, trafos, buses}
    # (ids), and the export's (`gsp_case`), so a reading says "93% at summer minimum", never just "worst case"
    envelope_case: dict[str, dict[str, list[int]]] = {}
    gsp_case: str | None = None


class Outage(BaseModel):
    """A planned maintenance window on a branch: an element out of service (or derated) for some weeks
    of one season of one year. Studied in that season's case(s); reported, never a connection gate."""

    outage_id: str
    element_kind: str  # "line" | "trafo" | "gen" (an existing generator, by its model id EX-…)
    element_id: str  # line/trafo index as text, or the generator's request id
    season: str  # "Winter" | "Spring" | "Summer" | "Autumn" (config.SEASON_STUDY)
    year: int
    weeks: int = 4
    kind: str = "outage"  # "outage" | "derate" (maintenance only; the other works take the element fully out)
    # what the window is for (maintenance.WORKS): "maintenance" | "repowering" | "replacement".
    # Maintenance and replacement (like-for-like) return the element as it was; repowering returns it
    # with a new capability from the FOLLOWING year on (years.evaluate_year applies it, the queue run does not)
    work: str = "maintenance"
    repower: str | None = None  # repowering only: "uprate" | "add_parallel"
    factor: float | None = None  # repowering "uprate" only: the rating multiplier (1 < factor <= 4)


class Curtailment(BaseModel):
    """Generation constrained to hold the limits during a window (a first-order planning estimate)."""

    id: str  # the generator's model id (EX-… for the existing fleet) or the project's request id
    name: str  # its technology (the UI resolves the display name by id)
    mw: float  # output constrained in that case
    case: str  # the study case it is needed in


class N1During(BaseModel):
    """An N-1 screen of the 132 kV backbone with the window in place (informational, never a gate)."""

    cases: list[str] = []
    screened: int = 0  # second faults studied, summed over the cases
    findings: int = 0  # second faults (outage and case) that breach a limit or strand demand; `violations` lists each breach
    violations: list[dict] = []  # those findings, worst first: network.n1_screen dicts (outage, case, type, element, value, message)
    second_fault_at_risk_mw: float = 0.0  # demand stranded by the worst second fault, beyond what the window strands
    worst: str = ""  # the worst finding in words ("" when there is none)


# how bad a window's verdict is, worst last: the one order maintenance folds cases by, diff and the gate compare by and
# the best-window search ranks by (demand at risk is the worst: customers lose supply). `unstudied` (the element is not
# in the network model) is no verdict on the grid, so it ranks with nothing and says so in its own words.
VERDICT_SEVERITY = {"unstudied": 0, "feasible": 0, "curtailment": 1, "not_feasible": 2, "demand_at_risk": 3}


class OutageStudy(BaseModel):
    """What one planned window does to its year's network, in each case its season stresses, studied
    together with the other windows of the same season and year (`with_ids`)."""

    outage_id: str
    year: int
    cases: list[str]
    ok: bool  # True when no limit is breached with the element(s) out, before any curtailment
    violations: list[Reason] = []  # the first limit each case breaches
    worst_line_loading_pct: float = 0.0
    worst_trafo_loading_pct: float = 0.0
    gsp_export_mw: float = 0.0
    message: str
    work: str = "maintenance"
    with_ids: list[str] = []  # the other windows studied at the same time
    verdict: str = "feasible"  # "feasible" | "curtailment" | "demand_at_risk" | "not_feasible"
    demand_at_risk_mw: float = 0.0  # stranded, or at load buses left outside the voltage band
    curtailment: list[Curtailment] = []  # what constraining generation clears the limits ("curtailment" only)
    curtailed_mw: float = 0.0  # the most constrained in any one case
    n1_during: N1During | None = None  # None when the year was solved without the N-1 screen
    after: str = ""  # what the work leaves behind once the window is over


class RegionYear(BaseModel):
    """One demand group (an LTDS Table 3 primary or BSP group) in one year of the plan, judged by a
    simplified P2/8-style check (demand.py). Figures in MW; there are no customer counts in the data."""

    region_id: str
    name: str
    bsp: str = ""
    demand_mw: float  # the group's own peak this year (LTDS max demand grown, + projects drawing at winter peak)
    modelled_mw: float  # what the power flow carries for it (its share of the GSP's coincident peak)
    firm_mw: float  # LTDS firm capacity (read as MVA, x the row's power factor); 0 = none published
    headroom_mw: float  # firm_mw - demand_mw (negative = demand above firm capacity)
    p2_class: str  # P2/8 demand class by group demand: A..F
    n1_at_risk_mw: float = 0.0  # worst own-peak demand cut off by one 132 kV backbone outage (N-1 screen)
    n1_outage: str | None = None  # the outage that strands it, e.g. "line 13"
    voltage_violation_bus_ids: list[int] = []  # the group's load buses outside the statutory band (intact envelope)
    worst_vm_pu: float | None = None  # the group's load-bus voltage furthest from 1.0 pu (intact envelope)
    worst_vm_limit_pu: float | None = None  # that bus's statutory band edge on the same side
    demand_room_mw: float | None = None  # first-order room for new demand (≈): min(firm headroom, winter transformer spare)


class Alert(BaseModel):
    """A demand-side warning for one group in one year, from one check in demand.ALERT_CHECKS.
    `value` and `limit` are engine figures; `message` restates them in plain English."""

    kind: str  # "firm_capacity" | "n1_stranded" | "voltage" | "headroom"
    level: str  # "warn" | "breach"
    region_id: str
    year: int
    value: float | None = None
    limit: float | None = None
    message: str


# how bad a finding is, worst first: the order findings and the merge gate sort by
SEVERITY_ORDER = {"breach": 0, "warn": 1, "info": 2}


class Finding(BaseModel):
    """One thing wrong (or worth knowing) in a plan: extracted deterministically from a result by
    `findings.EXTRACTORS`, or filed by an agent against a recorded study step. Its fingerprint is
    stable across runs (kind + element + year + case, never the value), so a ledger upserts the same
    finding instead of duplicating it. `value` and `limit` are engine figures; `message` restates them."""

    fingerprint: str
    kind: str  # overload | voltage | gsp_over_limit | gsp_near_limit | n1 | alert | work | deferred | rejected | against_recommendation | non_convergent
    severity: str  # "breach" | "warn" | "info" (SEVERITY_ORDER)
    source: str = "engine"  # "engine" | "agent" | "operator"
    year: int | None = None
    case: str | None = None
    element_kind: str | None = None  # line | trafo | bus | gsp | region | project | outage
    element_id: str | None = None  # text: project and region ids are strings, line/bus ids are indices
    value: float | None = None
    limit: float | None = None
    message: str
    context: dict = {}  # identity extras: the N-1 breach, the alert kind, the works verdict, the binding reason


class GateFinding(BaseModel):
    """One reason the merge gate (gate.MERGE_CHECKS) blocks, warns or merely notes. Its level comes
    from `config.MERGE_GATE_LEVELS`, never from the check itself."""

    kind: str
    level: str  # "blocker" | "warning" | "info"
    year: int | None = None
    case: str | None = None
    element_kind: str | None = None
    element_id: str | None = None
    value: float | None = None  # on the branch
    base_value: float | None = None  # on the parent, where there is one
    limit: float | None = None
    message: str
    finding_fingerprint: str | None = None  # the ledger finding on the branch this refers to (findings.fingerprint)


class MergeVerdict(BaseModel):
    """May this branch become the plan of record? `ok` means no blockers; warnings may still need
    acknowledging (an API policy). `context` is what the parent already carries: never a reason to block."""

    ok: bool
    blockers: list[GateFinding] = []
    warnings: list[GateFinding] = []
    context: list[GateFinding] = []
    years_compared: list[int] = []
    summary: str = ""


class ModelAssumption(BaseModel):
    """Something the model had to assume or could not provide, stated rather than hidden: a builder
    fallback (a blank rating filled, a tap step assumed), an operator-entered limit, or data a file
    did not carry. `studies.data_quality` reports them; an imported grid lists its own."""

    key: str
    message: str
    source: str = "engine-default"  # "engine-default" | "operator-entered" | "file"
    element_kind: str | None = None
    count: int | None = None
    element_ids: list = []


class StudyItem(BaseModel):
    """One row of a study (studies.STUDIES): an element and a figure, with a stable fingerprint so a
    finding filed against it keeps its identity across runs. Every figure is the engine's."""

    index: int
    element_kind: str | None = None  # "bus" | "line" | "trafo" | "gsp" | "assumption" | None
    element_id: int | str | None = None
    element_name: str = ""
    case: str | None = None
    year: int | None = None
    value: float | None = None
    limit: float | None = None
    unit: str = ""  # "MW" | "pu" | "steps" | "index" | "count"
    severity: str = "info"  # "info" | "warn" | "breach"
    message: str
    fingerprint: str
    extra: dict = {}


class StudyResult(BaseModel):
    """A study's answer: its items, what it cost, and what it deliberately did NOT study (prompted
    into every agent answer, so the limits of the evidence travel with it)."""

    kind: str
    params: dict = {}
    items: list[StudyItem] = []
    solves: int = 0
    not_studied: list[str] = []
    summary: str = ""


class WindowOption(BaseModel):
    """One candidate window for a planned work (windows.best_windows): the element studied out in
    one season of one year against the plan as it stands then, ranked against the others."""

    rank: int  # 1 = the best window
    year: int
    season: str
    verdict: str  # as OutageStudy.verdict
    curtailed_mw: float = 0.0
    demand_at_risk_mw: float = 0.0
    n1_findings: int | None = None  # second faults adding a problem during the window; None = not screened (outside the shortlist)
    worst_line_loading_pct: float = 0.0
    worst_trafo_loading_pct: float = 0.0
    message: str  # the engine's plain-English study summary
    study: OutageStudy


class FaultLevel(BaseModel):
    """One switchgear busbar's fault level in a year (faults.py): the source's published three-phase break current and
    rating, the modelled Ik'' today and this year, the published figure scaled by the modelled change, and how much of
    the rating that takes. Figures in kA; `utilisation_pct` is None without a published rating."""

    bus: int
    name: str
    kv: float
    published_ka: float | None = None  # the DNO's own break current at the busbar today (LTDS Table 4)
    rating_ka: float | None = None  # the published break rating of the switchgear (the weakest published row)
    modelled_ka: float  # IEC 60909 Ik'' with this year's network
    today_ka: float | None = None  # the same on today's network: the anchor
    projected_ka: float | None = None  # published × modelled / today
    utilisation_pct: float | None = None  # (projected, else modelled) / rating
    published_over_rating: bool = False  # the DNO's own published current already exceeds the published rating
    year: int | None = None  # set when the row stands for an element's worst plan year (analysis.Limits)


class YearResult(PhaseResult):
    """The plan as it stands in one year: the projects energised by then (their scheduled or
    recommended year), demand interpolated to the year, solved in both cases, plus that year's
    planned outages."""

    year: int
    growth: float  # the demand multiplier this year was solved at
    energised: list[str] = []  # projects in service this year
    trafo_loading: dict[int, float] = {}  # trafo_id -> loading_percent (worst case), for the element card
    outage_studies: list[OutageStudy] = []
    regions: list[RegionYear] = []  # the demand side: every demand group this year (demand.py)
    alerts: list[Alert] = []  # demand-side warnings this year (demand.ALERT_CHECKS)
    fault_levels: list[FaultLevel] = []  # every switchgear busbar's fault level this year (faults.py); [] when not studied
    converged: bool = True  # False when a study case did not converge this year (the figures are then the last solve's)


class OptimizeResult(BaseModel):
    """The full optimizer output: the parameters used, the ordered queue, per-phase results, per-year
    results (filled by years.evaluate_years)."""

    params: OptimizeParams
    queue: list[QueueItem]
    phases: dict[str, PhaseResult]
    years: dict[str, YearResult] = {}


class Reinforcement(BaseModel):
    """A simulated network reinforcement for a 'what would it take' trial.

    `add_parallel` bumps the element's parallel count (halves series impedance AND doubles its
    rating -> relieves thermal AND voltage). `uprate` raises only the thermal rating by `factor`
    (impedance unchanged -> voltage unmoved).
    """

    kind: str  # "line" | "trafo" | "gsp" (one more supergrid transformer at the GSP)
    element_id: int
    action: str = "add_parallel"  # "add_parallel" | "uprate"
    factor: float = 2.0  # uprate multiplier on the rating (ignored for add_parallel)


class Suggestion(BaseModel):
    """A concrete, quantified unblock recommendation for one binding constraint.

    Every number here is measured by re-running the power flow (suggest.py); the LLM only phrases
    them. `freed_mw_*` is first-order (second-order knock-on is not modelled) -> report it as ≈.
    """

    target_type: str  # "line" | "trafo" | "voltage" | "gsp"
    target_element_id: int
    action: str
    reinforcements: list[Reinforcement] = []  # the full chain of upgrades this suggestion models
    connects_target: bool = True  # did the modelled action actually connect the blocked project(s)?
    freed_mw_2030: float = 0.0
    freed_mw_2035: float = 0.0
    newly_connected_project_ids: list[str] = []
    blocked_project_ids: list[str] = []  # deferred projects this suggestion is for (the motivation)
    extra_solves: int = 0  # power-flow solves this suggestion cost (observability)
    caveat: str = ""


# --- the geolocated model of a network (any source), and what an import is judged on -------------------------------
class ModelBus(BaseModel):
    bus_id: int
    name: str
    vn_kv: float
    lon: float
    lat: float
    place: str = ""  # where it is, by name (`naming`): its own name, or a neighbour's for a coded busbar; "" when nothing near is named
    # the voltage band this bus is judged against (`network.voltage_limits`: the grid's own limits at its level)
    vmin_pu: float
    vmax_pu: float


class ModelLine(BaseModel):
    line_id: int
    line_name: str
    display_name: str = ""  # what people call it (`naming`): the places it joins, parallel circuits numbered
    rating_a: float | None  # None: the file left it unrated (its loading is not checked)
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
    """The map's view of a network: every source shapes one (`gridmodel.model_from_net`). `crs` is
    `wgs84` when the positions are real and `synthetic` when the file carried none (a layout)."""

    buses: list[ModelBus]
    lines: list[ModelLine]
    transformers: list[ModelTransformer]
    loads: list[ModelLoad]
    generators: list[ModelGenerator]
    regions: list[dict] = []  # the demand groups (demand.regions_of), when the net carries them
    crs: Literal["wgs84", "synthetic"] = "wgs84"


class VoltageBand(BaseModel):
    """The voltage limits at one level of an imported grid, as the operator states them (pu, after the tap changers settle)."""

    kv: float = Field(gt=0)
    vmin_pu: float = Field(gt=0, lt=1)
    vmax_pu: float = Field(gt=1, lt=2)


class ImportMeta(BaseModel):
    """What the operator knows about an imported grid that its file does not carry. Each is applied
    uniformly and recorded as an operator-entered assumption. The study basis below is required, and so is the summer
    data (minimum demand, summer ratings) unless the file carries it: a missing part is a gap."""

    gsp_export_limit_mw: float | None = Field(default=None, gt=0)
    gsp_name: str | None = None
    gsp_sgt_mw: float | None = Field(default=None, gt=0)  # one supergrid transformer's rating: the "add an SGT" lever's size
    min_demand_factor: float | None = Field(default=None, gt=0, le=1)  # minimum demand as a share of maximum
    summer_rating_ratio: float | None = Field(default=None, gt=0, le=1.5)  # summer / winter line rating
    intermediate_rating_ratio: float | None = Field(default=None, gt=0, le=1.5)
    # the study basis, which a grid file does not carry and an import must state (sources.apply_import_meta):
    # peak demand's year-on-year growth factor (1.02 = +2 % on the year before), every plan year after the first, by
    # pathway (IMPORT_PATHWAYS: Low, Standard, High; Standard required), where it comes from, the lowest level the
    # N-1 screen covers, and the voltage limits at every level
    forecasts: dict[str, dict[int, float]] | None = None
    forecast_source: str | None = None
    n1_min_kv: float | None = Field(default=None, gt=0)
    voltage_bands: list[VoltageBand] | None = None

    def cumulative(self) -> dict[str, dict[int, float]]:
        """Each pathway's multiplier on today's peak by year: the year-on-year factors multiplied up (2026 = 1.0)."""
        out: dict[str, dict[int, float]] = {}
        for p, rates in (self.forecasts or {}).items():
            m, curve = 1.0, {}
            for y in sorted(rates):
                m *= rates[y]
                curve[y] = round(m, 6)
            out[p] = curve
        return out

    @model_validator(mode="after")
    def _forecast_shape(self) -> ImportMeta:
        """Every pathway known and complete, each year's factor positive, Low <= Standard <= High in what they add up
        to (a year's own factor may cross); kept in that order."""
        if self.forecasts is None:
            return self
        years = set(range(PLAN_START_YEAR + 1, PLAN_END_YEAR + 1))
        unknown = sorted(set(self.forecasts) - set(IMPORT_PATHWAYS))
        if unknown:
            raise ValueError(f"unknown forecast pathways {unknown}: use {', '.join(IMPORT_PATHWAYS)} (Low, Standard, High)")
        name = lambda p: FORECASTS[p]["short"]  # noqa: E731
        for p, curve in self.forecasts.items():
            if set(curve) != years:
                raise ValueError(f"the {name(p)} forecast must give every plan year from {min(years)} to {max(years)}")
            if any(not (0 < v <= IMPORT_FORECAST_FACTOR_MAX) for v in curve.values()):
                raise ValueError(f"the {name(p)} forecast's year-on-year factors must be above 0 and at most {IMPORT_FORECAST_FACTOR_MAX:g} (1.02 is +2 %)")
        order = [p for p in IMPORT_PATHWAYS if p in self.forecasts]
        self.forecasts = {p: dict(sorted(self.forecasts[p].items())) for p in order}
        total = self.cumulative()
        for lo, hi in zip(order, order[1:]):
            for y in sorted(years):
                if total[lo][y] > total[hi][y] + 1e-9:
                    raise ValueError(f"by {y} the {name(lo)} forecast (x{total[lo][y]:.3f} of today) is above the {name(hi)} one (x{total[hi][y]:.3f})")
        return self


class ValidationReport(BaseModel):
    """Can the engine plan on an imported grid? Errors stop the import; warnings and assumptions are shown."""

    ok: bool
    errors: list[str] = []
    warnings: list[str] = []
    counts: dict[str, int] = {}
    islands: int = 0
    converged: bool = False
    feasible: bool | None = None  # the base case against the limits (None when it did not solve)
    reason: str | None = None  # the first limit the base case breaks, if any
    cases: list[str] = []  # the study cases this grid can be studied in
    assumptions: list[ModelAssumption] = []
