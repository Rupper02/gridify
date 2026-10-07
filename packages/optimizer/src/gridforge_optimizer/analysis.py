"""The analytics layer: a run's outputs reduced to what a planning engineer asks, with no model and no solve.

A run is thousands of figures (an envelope per element per plan year, an N-1 row per breached element per outage
per case, a works verdict per window). An engineer asks three things of them: what **binds** (which elements, from
which year, in which case, by how many MW, holding back which projects, breached by which outages), why each deferral
happened and what it would take (its **chain**), and which rows are one cause (**clusters**: the outages that strand
the same buses, the weak link several outages overload, the outages that collapse the voltage). `limits` answers
them as data for the planner and the answerer; `run_digest` folds them into about 2 kB for the note writer, which
only phrases it.

Every figure here is the engine's own, rounded as the engine rounds it. Headroom in MW is first-order: a loading
percentage is current-based, so (limit − loading) × rating is within a couple of points of the real MVA margin.
"""

from __future__ import annotations

import math
from collections import defaultdict

from pydantic import BaseModel

from .config import GSP_NEAR_LIMIT_FRACTION, LINE_LOADING_MAX_PCT, N1_COLLAPSE_VM_PU, OLTC_DEADBAND_PU, PLAN_YEARS, TRAFO_LOADING_MAX_PCT
from .naming import Names, element_names
from .types import VERDICT_SEVERITY, GridModel, MergeVerdict, OptimizeResult, YearResult

NEAR_FRACTION = GSP_NEAR_LIMIT_FRACTION  # an element within this fraction of its limit is "near" (the GSP's own threshold, reused)
TOP_BINDING = 8  # what the planner's Limits view and the digest lead with
TOP_DIGEST = 4


# --- the shapes -------------------------------------------------------------------------------------------------------
class Point(BaseModel):
    year: int
    value: float
    case: str | None = None  # the study case that set the envelope figure that year


class ElementBinding(BaseModel):
    """One element and how it binds over the plan years: the envelope figure per year with its case, the first year it
    comes within reach of its limit, the worst year, the headroom left there, the projects deferred on it and the N-1
    outages that breach it."""

    kind: str  # line | trafo | bus
    element_id: int
    name: str
    unit: str  # % for loadings, pu for voltages
    limit: float  # the limit the figure is judged against (% or the band edge crossed)
    trajectory: list[Point]
    first_near_year: int | None = None  # first plan year at or beyond NEAR_FRACTION of the limit (voltage: within the deadband of the band)
    first_breach_year: int | None = None
    worst: Point
    headroom_mw: float | None = None  # at the worst year, first-order; None for a bus
    rating_mva: float | None = None
    holds_back: list[str] = []  # request ids deferred with this element as their reason
    n1_outages: int = 0  # distinct (outage, case) pairs whose post-fault state breaches this element
    severity: str  # breach | near | ok

    @property
    def binds(self) -> bool:
        return self.severity != "ok"


class Chain(BaseModel):
    """Why a project was deferred and what it would take, as far as the engine has measured it."""

    request_id: str
    technology: str | None = None
    rating_mw: float | None = None
    bus_id: int | None = None
    reason_type: str
    element_kind: str | None = None
    element_id: int | None = None
    element_name: str = ""
    value: float | None = None
    limit: float | None = None
    case: str | None = None
    phase: str = "2035"  # the queue trial the reason comes from: demand grown to the plan's end, every higher-ranked project in
    first_near_year: int | None = None  # when that element starts binding on its own, from the binding set
    message: str
    fits_mw: float | None = None  # a firm size at its own busbar, from a cached connection_options study
    chain_connects: bool | None = None  # whether parallel circuits get it to full MW (cached study)
    best_move: dict | None = None  # {"bus_id", "name", "mw", "case"} the higher-voltage busbar taking the most (cached study)
    studied: bool = False  # whether connection_options has been run for it


class Cluster(BaseModel):
    """Several N-1 rows that are one cause."""

    kind: str  # weak_link | island | collapse
    key: str
    label: str
    n_rows: int
    outages: list[str]  # outage names (distinct)
    cases: list[str]
    years: list[int]
    worst: float | None = None  # the worst figure among the rows (% / MW / pu by kind)
    unit: str = ""


class WorkVerdict(BaseModel):
    outage_id: str
    element: str
    year: int
    verdict: str
    curtailed_mw: float = 0.0
    demand_at_risk_mw: float = 0.0
    n1_findings: int | None = None


class Limits(BaseModel):
    """What limits a run: the binding set, the deferrals' chains, the clusters and the works, for the planner's Limits
    view and the answerer's `limits` tool."""

    years: list[int]
    binding: list[ElementBinding]
    chains: list[Chain]
    clusters: list[Cluster]
    works: list[WorkVerdict]
    n1_rows: int
    n1_pairs: int  # distinct (outage, case) pairs with any finding


class Headline(BaseModel):
    mw_2030: float
    mw_2035: float
    n_connected: int
    n_deferred: int
    n_rejected: int
    worst_line_pct: float
    worst_trafo_pct: float
    min_vm_pu: float
    max_vm_pu: float
    worst_year: int
    gsp_export_max_mw: float
    gsp_limit_mw: float | None = None
    gsp_case: str | None = None
    years_converged: int
    n1_rows: int
    n1_pairs: int
    n1_collapses: int


class Delta(BaseModel):
    vs: str
    mw_2035_delta: float
    n_added: int
    n_dropped: int
    n_accelerated: int
    n_slipped: int
    new_overloads: int
    new_voltage: int
    n1_new: int
    n1_collapse_new: int
    works_worse: int
    gate_ok: bool | None = None
    blockers: list[str] = []  # the gate's blocker kinds, distinct, worst first


class RunDigest(BaseModel):
    """What the note writer reads: about 2 kB, every figure the engine's."""

    branch: str
    years: list[int]
    headline: Headline
    queue: dict  # {"connected": n, "deferred": n, "rejected": n}
    binding: list[ElementBinding]
    chains: list[Chain]
    clusters: list[Cluster]
    works: list[WorkVerdict]
    delta: Delta | None = None
    assumptions: int = 0
    not_studied: list[str]


# --- ratings: what a loading percentage is a percentage of ------------------------------------------------------------
def element_ratings(net) -> dict[str, dict[int, float]]:
    """MVA ratings per element from the (reinforced) network: lines √3·kV·I·parallel, transformers sn·parallel; and the
    summer ratio per line (`summer_ratio`, 1 when the file carries none). Read from the net, not the model, because a
    parallel-circuit reinforcement lives only on the net."""
    lines: dict[int, float] = {}
    summer: dict[int, float] = {}
    for lid in net.line.index:
        kv = float(net.bus.at[int(net.line.at[lid, "from_bus"]), "vn_kv"])
        i_ka = net.line.at[lid, "max_i_ka"]
        if i_ka == i_ka and i_ka is not None:
            lines[int(lid)] = math.sqrt(3) * kv * float(i_ka) * float(net.line.at[lid, "parallel"] if "parallel" in net.line.columns else 1.0)
        ratio = net.line.at[lid, "summer_ratio"] if "summer_ratio" in net.line.columns else 1.0
        summer[int(lid)] = float(ratio) if ratio == ratio and ratio is not None else 1.0
    trafos = {int(t): float(net.trafo.at[t, "sn_mva"]) * float(net.trafo.at[t, "parallel"] if "parallel" in net.trafo.columns else 1.0)
              for t in net.trafo.index}
    return {"line": lines, "trafo": trafos, "summer_ratio": summer}


# --- the binding set --------------------------------------------------------------------------------------------------
def _case_of(year: YearResult, kind: str, eid: int) -> str | None:
    """The study case that set this element's envelope figure in this year (`PhaseResult.envelope_case`)."""
    table = {"line": "lines", "trafo": "trafos", "bus": "buses"}[kind]
    for case, ids in (year.envelope_case or {}).items():
        if eid in (ids.get(table) or []):
            return case
    return None


def _trajectory(years: dict[str, YearResult], kind: str, eid: int) -> list[Point]:
    out = []
    for key in sorted(years, key=int):
        y = years[key]
        table = y.line_loading if kind == "line" else y.trafo_loading if kind == "trafo" else y.bus_vm
        v = table.get(eid)
        if v is None:
            continue
        out.append(Point(year=y.year, value=float(v), case=_case_of(y, kind, eid)))
    return out


def _bus_limits(model: GridModel) -> dict[int, tuple[float, float]]:
    return {b.bus_id: (b.vmin_pu, b.vmax_pu) for b in model.buses}


def _bind_thermal(kind: str, eid: int, traj: list[Point], limit: float, rating: float | None, ratio: float, names: Names) -> ElementBinding:
    worst = max(traj, key=lambda p: p.value)
    near = next((p.year for p in traj if p.value >= NEAR_FRACTION * limit), None)
    breach = next((p.year for p in traj if p.value > limit), None)
    headroom = None
    if rating is not None:
        case_rating = rating * (ratio if worst.case == "summer_min" else 1.0)
        headroom = round((limit - worst.value) / 100.0 * case_rating, 1)
    return ElementBinding(kind=kind, element_id=eid, name=names.of("line" if kind == "line" else "transformer", eid) or f"{kind} {eid}", unit="%",
                          limit=limit, trajectory=traj, first_near_year=near, first_breach_year=breach, worst=worst, headroom_mw=headroom,
                          rating_mva=None if rating is None else round(rating, 1), severity="breach" if breach else "near" if near else "ok")


def _bind_voltage(bid: int, traj: list[Point], band: tuple[float, float], names: Names) -> ElementBinding:
    vmin, vmax = band
    dist = lambda v: max(vmin - v, v - vmax)  # noqa: E731  # positive outside the band, negative inside
    worst = max(traj, key=lambda p: dist(p.value))
    near = next((p.year for p in traj if dist(p.value) >= -OLTC_DEADBAND_PU), None)
    breach = next((p.year for p in traj if dist(p.value) > 0), None)
    edge = vmin if worst.value < 1.0 else vmax
    return ElementBinding(kind="bus", element_id=bid, name=names.of("bus", bid) or f"bus {bid}", unit="pu", limit=edge, trajectory=traj,
                          first_near_year=near, first_breach_year=breach, worst=worst, severity="breach" if breach else "near" if near else "ok")


def binding_set(result: OptimizeResult, years: dict[str, YearResult], model: GridModel, ratings: dict[str, dict[int, float]] | None = None) -> list[ElementBinding]:
    """Every element that binds or comes near its limit in any plan year, worst first, with the projects deferred on it
    and the N-1 (outage, case) pairs that breach it. Elements comfortably within their limits are left out: the view
    is what limits the plan, not the whole network."""
    if not years:
        return []
    names = element_names(model.buses, model.lines, model.transformers)
    ratings = ratings or {"line": {}, "trafo": {}, "summer_ratio": {}}
    out: list[ElementBinding] = []
    first = years[sorted(years, key=int)[0]]
    for lid in first.line_loading:
        traj = _trajectory(years, "line", lid)
        if traj:
            out.append(_bind_thermal("line", lid, traj, LINE_LOADING_MAX_PCT, ratings["line"].get(lid), ratings["summer_ratio"].get(lid, 1.0), names))
    for tid in first.trafo_loading:
        traj = _trajectory(years, "trafo", tid)
        if traj:
            out.append(_bind_thermal("trafo", tid, traj, TRAFO_LOADING_MAX_PCT, ratings["trafo"].get(tid), 1.0, names))
    bands = _bus_limits(model)
    for bid in first.bus_vm:
        traj = _trajectory(years, "bus", bid)
        if traj and bid in bands:
            out.append(_bind_voltage(bid, traj, bands[bid], names))
    # what each element holds back (the queue's deferral reasons) and which outages breach it (the N-1 rows)
    holds: dict[tuple[str, int], list[str]] = defaultdict(list)
    for q in result.queue:
        r = q.reason
        if q.status == "Deferred" and r is not None and r.element_id is not None and r.type in ("line", "trafo", "voltage"):
            holds[("bus" if r.type == "voltage" else r.type, int(r.element_id))].append(q.request_id)
    pairs: dict[tuple[str, int], set[tuple]] = defaultdict(set)
    for y in years.values():
        for v in y.n1_violations:
            if v.get("type") in ("line", "trafo", "voltage") and v.get("element_id") is not None:
                pairs[("bus" if v["type"] == "voltage" else v["type"], int(v["element_id"]))].add((v.get("outage_type"), v.get("outage_id"), v.get("case")))
    for b in out:
        b.holds_back = sorted(set(holds.get((b.kind, b.element_id), [])))
        b.n1_outages = len(pairs.get((b.kind, b.element_id), ()))
    kept = [b for b in out if b.binds or b.holds_back or b.n1_outages]
    rank = {"breach": 0, "near": 1, "ok": 2}
    kept.sort(key=lambda b: (rank[b.severity], -len(b.holds_back), -b.n1_outages, -_badness(b)))
    return kept


def _badness(b: ElementBinding) -> float:
    return b.worst.value / b.limit if b.unit == "%" else abs(b.worst.value - 1.0)


# --- the chains ---------------------------------------------------------------------------------------------------------
def _option_fields(study) -> dict:
    """What a cached connection_options study says a deferred project could do: the firm size at its own busbar, whether
    parallel circuits get it to full MW, the best higher-voltage busbar. `study` is a StudyResult (or None)."""
    if study is None:
        return {"studied": False}
    sizes = [it for it in study.items if (it.extra or {}).get("option") == "size" and (it.extra or {}).get("fits") is not None]
    fits = min((float(it.value) for it in sizes if it.value is not None), default=None)
    chain = next((it for it in study.items if (it.extra or {}).get("option") == "reinforce"), None)
    moves = [it for it in study.items if (it.extra or {}).get("option") == "move" and it.value is not None]
    best = max(moves, key=lambda it: float(it.value), default=None)
    return {"studied": True, "fits_mw": fits, "chain_connects": None if chain is None else bool((chain.extra or {}).get("connects")),
            "best_move": None if best is None else {"bus_id": best.element_id, "name": best.element_name, "mw": float(best.value), "case": best.case}}


def chains(result: OptimizeResult, binding: list[ElementBinding], names: Names, options: dict[str, object] | None = None) -> list[Chain]:
    """One chain per deferred project, in queue order: its reason (the element, the case, the figure against the limit),
    when that element starts binding on its own, and what a cached connection_options study measured for it."""
    near = {(b.kind, b.element_id): b.first_near_year for b in binding}
    out = []
    for q in result.queue:
        if q.status != "Deferred" or q.reason is None:
            continue
        r = q.reason
        kind = None if r.element_id is None else "bus" if r.type == "voltage" else r.type if r.type in ("line", "trafo") else None
        name = ""
        if kind and r.element_id is not None:
            name = names.of("transformer" if kind == "trafo" else kind, int(r.element_id)) or f"{kind} {r.element_id}"
        out.append(Chain(request_id=q.request_id, technology=q.technology, rating_mw=q.rating_mw, bus_id=q.bus_id, reason_type=r.type,
                         element_kind=kind, element_id=None if r.element_id is None else int(r.element_id), element_name=name,
                         value=r.value, limit=r.limit, case=r.case, first_near_year=near.get((kind, int(r.element_id))) if kind and r.element_id is not None else None,
                         message=r.message, **_option_fields((options or {}).get(q.request_id))))
    return out


# --- the clusters ---------------------------------------------------------------------------------------------------------
def clusters(years: dict[str, YearResult], names: Names) -> list[Cluster]:
    """The N-1 rows folded by cause: the element several outages overload or push out of band (a weak link), the set of
    buses several outages strand (an island), the outages whose post-fault state has no credible steady state (a
    collapse). Most rows first."""
    weak: dict[tuple, list[dict]] = defaultdict(list)
    island: dict[tuple, list[dict]] = defaultdict(list)
    collapse: dict[tuple, list[dict]] = defaultdict(list)
    for y in years.values():
        for v in y.n1_violations:
            row = {**v, "year": y.year}
            t = v.get("type")
            if t in ("line", "trafo", "voltage") and v.get("element_id") is not None:
                weak[(t, int(v["element_id"]))].append(row)
            elif t == "islanded":
                island[tuple(sorted(int(b) for b in (v.get("islanded_bus_ids") or [])))].append(row)
            elif t == "collapse":
                collapse[(v.get("outage_type"), v.get("outage_id"))].append(row)
    out: list[Cluster] = []

    def fold(kind: str, key: str, label: str, rows: list[dict], unit: str, worst) -> None:
        out.append(Cluster(kind=kind, key=key, label=label, n_rows=len(rows), outages=sorted({r.get("outage_name") or str(r.get("outage_id")) for r in rows}),
                           cases=sorted({r.get("case") for r in rows if r.get("case")}), years=sorted({r["year"] for r in rows}), worst=worst, unit=unit))
    for (t, eid), rows in weak.items():
        kind = "bus" if t == "voltage" else t
        name = names.of("transformer" if kind == "trafo" else kind, eid) or f"{kind} {eid}"
        vals = [float(r["value"]) for r in rows if r.get("value") is not None]
        worst = (max(vals) if t != "voltage" else max(vals, key=lambda v: abs(v - 1.0))) if vals else None
        fold("weak_link", f"{t}:{eid}", f"{len({(r.get('outage_type'), r.get('outage_id')) for r in rows})} outages {'overload' if t != 'voltage' else 'push out of band'} {name}",
             rows, "%" if t != "voltage" else "pu", None if worst is None else round(worst, 3 if t == "voltage" else 1))
    for buses, rows in island.items():
        mw = [float(r["value"]) for r in rows if r.get("value") is not None]
        where = ", ".join(filter(None, (names.of("bus", b) for b in buses[:3]))) or f"{len(buses)} buses"
        fold("island", "island:" + ",".join(map(str, buses)), f"{len({(r.get('outage_type'), r.get('outage_id')) for r in rows})} outages strand {where}",
             rows, "MW", round(max(mw), 1) if mw else None)
    for (ot, oid), rows in collapse.items():
        name = rows[0].get("outage_name") or f"{ot} {oid}"
        low = [float(r["value"]) for r in rows if r.get("value") is not None]
        fold("collapse", f"collapse:{ot}:{oid}", f"{name} out: no credible post-fault steady state (below {N1_COLLAPSE_VM_PU:g} pu)", rows, "pu",
             round(min(low), 3) if low else None)
    out.sort(key=lambda c: (-c.n_rows, c.key))
    return out


# --- the works and the headline ---------------------------------------------------------------------------------------------
def works(years: dict[str, YearResult], names: Names) -> list[WorkVerdict]:
    out = []
    for y in years.values():
        for s in y.outage_studies:
            out.append(WorkVerdict(outage_id=s.outage_id, element=s.message.split(":")[0][:80] if s.message else s.outage_id, year=s.year, verdict=s.verdict,
                                   curtailed_mw=round(s.curtailed_mw, 1), demand_at_risk_mw=round(s.demand_at_risk_mw, 1),
                                   n1_findings=None if s.n1_during is None else int(getattr(s.n1_during, "findings", 0) or 0)))
    out.sort(key=lambda w: (-VERDICT_SEVERITY.get(w.verdict, 0), -(w.n1_findings or 0), w.year))
    return out


def headline(result: OptimizeResult, years: dict[str, YearResult]) -> Headline:
    ys = [years[k] for k in sorted(years, key=int)]
    by_status = defaultdict(int)
    for q in result.queue:
        by_status[q.status] += 1
    worst = max(ys, key=lambda y: max(y.worst_line_loading_pct, y.worst_trafo_loading_pct)) if ys else None
    rows = sum(len(y.n1_violations) for y in ys)
    pairs = {(v.get("outage_type"), v.get("outage_id"), v.get("case")) for y in ys for v in y.n1_violations}
    collapses = {(v.get("outage_type"), v.get("outage_id"), v.get("case")) for y in ys for v in y.n1_violations if v.get("type") == "collapse"}
    p1, p2 = result.phases.get("phase1"), result.phases.get("phase2")
    mw = lambda ph: round(sum(q.rating_mw or 0.0 for q in result.queue if ph and q.request_id in ph.accepted), 1)  # noqa: E731
    gsp = max(ys, key=lambda y: y.gsp_export_mw) if ys else None
    return Headline(mw_2030=mw(p1), mw_2035=mw(p2), n_connected=by_status["Phase1"] + by_status["Phase2"], n_deferred=by_status["Deferred"],
                    n_rejected=by_status["Rejected"], worst_line_pct=round(worst.worst_line_loading_pct, 1) if worst else 0.0,
                    worst_trafo_pct=round(worst.worst_trafo_loading_pct, 1) if worst else 0.0,
                    min_vm_pu=round(min((y.min_vm_pu for y in ys), default=1.0), 3), max_vm_pu=round(max((y.max_vm_pu for y in ys), default=1.0), 3),
                    worst_year=worst.year if worst else PLAN_YEARS[0], gsp_export_max_mw=round(gsp.gsp_export_mw, 1) if gsp else 0.0,
                    gsp_limit_mw=gsp.gsp_limit_mw if gsp else None, gsp_case=gsp.gsp_case if gsp else None,
                    years_converged=sum(1 for y in ys if y.converged), n1_rows=rows, n1_pairs=len(pairs), n1_collapses=len(collapses))


def delta(diff, gate: MergeVerdict | None) -> Delta | None:
    """What changed against the parent plan, from the consequence diff and the gate; None when there is no parent."""
    if diff is None:
        return None
    h = diff.headline or {}
    yd = list(diff.years.values())
    kinds: list[str] = []
    for b in (gate.blockers if gate else []):
        if b.kind not in kinds:
            kinds.append(b.kind)
    return Delta(vs=diff.base_label, mw_2035_delta=round(float(h.get("mw_2035_delta", 0.0)), 1), n_added=int(h.get("n_added", 0)), n_dropped=int(h.get("n_dropped", 0)),
                 n_accelerated=int(h.get("n_accelerated", 0)), n_slipped=int(h.get("n_slipped", 0)),
                 new_overloads=sum(len(y.newly_overloaded_line_ids) + len(y.newly_overloaded_trafo_ids) for y in yd),
                 new_voltage=sum(1 for y in yd if y.min_vm_delta < -OLTC_DEADBAND_PU or y.max_vm_delta > OLTC_DEADBAND_PU),
                 n1_new=sum(len(y.n1_new) for y in yd), n1_collapse_new=sum(max(0, y.n1_collapse_head - y.n1_collapse_base) for y in yd),
                 works_worse=sum(1 for w in diff.works if w.change == "worse"), gate_ok=None if gate is None else gate.ok, blockers=kinds)


# --- the two products -----------------------------------------------------------------------------------------------------
def limits(result: OptimizeResult, years: dict[str, YearResult], model: GridModel, ratings: dict[str, dict[int, float]] | None = None,
           options: dict[str, object] | None = None) -> Limits:
    names = element_names(model.buses, model.lines, model.transformers)
    binding = binding_set(result, years, model, ratings)
    ys = list(years.values())
    return Limits(years=sorted(y.year for y in ys), binding=binding, chains=chains(result, binding, names, options), clusters=clusters(years, names),
                  works=works(years, names), n1_rows=sum(len(y.n1_violations) for y in ys),
                  n1_pairs=len({(v.get("outage_type"), v.get("outage_id"), v.get("case")) for y in ys for v in y.n1_violations}))


NOT_STUDIED = ("fault levels", "the 400 kV network beyond the GSP (context only)", "N-1 is reported, never a connection gate",
               "planned works are studied in their season, their weeks are not placed")


def run_digest(branch: str, lim: Limits, result: OptimizeResult, years: dict[str, YearResult], *, diff=None, gate: MergeVerdict | None = None,
               assumptions: int = 0) -> RunDigest:
    """The note writer's input: the headline, the top of the binding set, the deferrals' chains, the biggest clusters, the
    worst works and what changed against the parent. About 2 kB; nothing a model could add to."""
    h = headline(result, years)
    return RunDigest(branch=branch, years=lim.years, headline=h, queue={"connected": h.n_connected, "deferred": h.n_deferred, "rejected": h.n_rejected},
                     binding=[b.model_copy(update={"trajectory": [b.worst]}) for b in lim.binding[:TOP_DIGEST]],
                     chains=lim.chains[:TOP_DIGEST], clusters=lim.clusters[:TOP_DIGEST], works=lim.works[:TOP_DIGEST], delta=delta(diff, gate),
                     assumptions=assumptions, not_studied=list(NOT_STUDIED))
