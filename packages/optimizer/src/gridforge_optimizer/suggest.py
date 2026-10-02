"""'What would it take' suggestions: turn a deferral's binding constraint into a concrete,
quantified unblock recommendation.

Deterministic and grounded. For each project the optimizer DEFERRED — each carrying a binding
`Reason` naming the limiting element — we work out what it would actually take to connect it and
MEASURE the result with pandapower. A single reinforcement rarely suffices: relieving the worst
line just exposes the next, so for a thermal binding we ITERATE, chaining parallel circuits until
the project connects (or we hit a voltage wall). For a voltage binding the lever is the new DER
absorbing reactive power, else one upstream reinforcement. No LLM arithmetic — llm.py only phrases
the numbers this module computes.

`freed_mw_*` is first-order: it does not model the knock-on where a freed project then blocks a
later one. The accurate mode is `optimize(..., reinforcements=[...])` + `diff_results`.
"""

from __future__ import annotations

from typing import Callable, NamedTuple

from .config import MAX_REINFORCE_STEPS, MAX_SUGGESTIONS, VOLTAGE_ABSORB_PF_STEPS
from .greedy import _grow, optimize
from .network import (
    apply_reinforcement,
    build_base_net,
    drop_sgen,
    feasibility,
    inject_sgen,
    upstream_path_lines,
)
from .types import Candidate, OptimizeParams, OptimizeResult, Reason, Reinforcement, Suggestion

_THERMAL_TYPES = ("line", "trafo")  # reasons fixed by adding a parallel circuit to the binding element
_HARDEST_PHASE = "2035"  # max demand growth -> the binding set that gates the whole horizon


def _cand_index(candidates: list[Candidate]) -> dict[str, Candidate]:
    """Index connectable candidates by request id (needs a bus and a rating to inject)."""
    return {c.request_id: c for c in candidates if c.bus_id is not None and c.rating_mw is not None}


def _phase_net(cand_by_id, params, base, phase_key, reinf):
    """A phase net grown + reinforced, with everything the base run already connected replayed in."""
    net = build_base_net()
    _grow(net, getattr(params, f"growth_{phase_key}"), params.scenario, int(phase_key))
    for r in reinf:
        apply_reinforcement(net, r)
    for rid in base.phases[phase_key].accepted:
        c = cand_by_id.get(rid)
        if c is not None:
            inject_sgen(net, c.bus_id, c.rating_mw, c.request_id, c.technology, import_mw=c.import_mw)
    return net


def _trial_phase(cand_by_id, deferred_ids, params, base, phase_key, reinf=None, q_factor=0.0):
    """Re-trial every deferred project for one phase; return (freed_mw, newly_ids, solves)."""
    net = _phase_net(cand_by_id, params, base, phase_key, reinf or [])
    freed, newly, solves = 0.0, [], 0
    for rid in deferred_ids:  # deferred projects in the base run's rank order
        c = cand_by_id.get(rid)
        if c is None:
            continue
        idx = inject_sgen(
            net, c.bus_id, c.rating_mw, c.request_id, c.technology, q_mvar=-q_factor * c.rating_mw, import_mw=c.import_mw
        )
        ok, _, _ = feasibility(net)
        solves += 1
        if ok:
            newly.append(rid)
            freed += c.rating_mw
        else:
            drop_sgen(net, idx)
    return round(freed, 1), newly, solves


def _discover_chain(cand_by_id, params, base, target_rid):
    """Chain parallel circuits until `target_rid` connects (hardest phase) or a wall is hit.

    Returns (reinforcements, connected, last_reason, solves). The reinforcement set is grown one
    binding line/trafo at a time; a repeated or voltage/non-convergent binding stops the search.
    """
    reinf: list[Reinforcement] = []
    solves = 0
    last_reason: Reason | None = None
    target = cand_by_id.get(target_rid)
    if target is None:
        return reinf, False, None, solves
    for _ in range(MAX_REINFORCE_STEPS + 1):
        net = _phase_net(cand_by_id, params, base, _HARDEST_PHASE, reinf)
        inject_sgen(net, target.bus_id, target.rating_mw, target.request_id, target.technology, import_mw=target.import_mw)
        ok, reason, _ = feasibility(net)
        solves += 1
        last_reason = reason
        if ok:
            return reinf, True, None, solves
        if reason is None or reason.type not in _THERMAL_TYPES or reason.element_id is None:
            break  # voltage / non-convergent: not fixable by adding parallels here
        key = (reason.type, int(reason.element_id))
        if any((r.kind, r.element_id) == key for r in reinf):
            break  # already reinforced this element and it still binds -> give up
        reinf.append(Reinforcement(kind=reason.type, element_id=int(reason.element_id)))
    return reinf, False, last_reason, solves


def _describe(reinf: list[Reinforcement], connected: bool, last_reason: Reason | None = None) -> str:
    if not reinf:
        return "No single-element reinforcement found"
    label = {"line": "line", "trafo": "transformer"}
    parts = ", ".join(f"{label[r.kind]} {r.element_id}" for r in reinf)
    verb = "Add a parallel circuit to" if len(reinf) == 1 else "Add parallel circuits to"
    if connected:
        tail = ""
    elif last_reason is not None and last_reason.type == "gsp":
        tail = " — clears the local limit, but the project then hits the GSP export limit (see the supergrid-transformer lever)"
    else:
        tail = " (still constrained — would need further reinforcement)"
    return f"{verb} {parts}{tail}"


def _reinforcement_suggestion(cand_by_id, deferred_ids, params, base, target_rid, blocked):
    """Thermal binding: discover the reinforcement chain, then measure the MW it frees."""
    reinf, connected, last_reason, s0 = _discover_chain(cand_by_id, params, base, target_rid)
    # the chain ran into a voltage wall -> hand off to the voltage lever
    if not connected and last_reason is not None and last_reason.type == "voltage" and last_reason.element_id is not None:
        sug = _voltage_suggestion(cand_by_id, deferred_ids, params, base, int(last_reason.element_id), blocked)
        sug.extra_solves += s0
        return sug
    f30, n30, s30 = _trial_phase(cand_by_id, deferred_ids, params, base, "2030", reinf=reinf)
    f35, n35, s35 = _trial_phase(cand_by_id, deferred_ids, params, base, "2035", reinf=reinf)
    first = reinf[0] if reinf else None
    return Suggestion(
        target_type=first.kind if first else "line",
        target_element_id=first.element_id if first else -1,
        action=_describe(reinf, connected, last_reason),
        reinforcements=reinf,
        connects_target=connected,
        freed_mw_2030=f30,
        freed_mw_2035=f35,
        newly_connected_project_ids=sorted(set(n30) | set(n35)),
        blocked_project_ids=blocked,
        extra_solves=s0 + s30 + s35,
        caveat=(
            "Each added parallel circuit halves its element's series impedance and doubles its "
            "rating, relieving thermal and voltage limits. A feasible lever, not a least-cost study."
        ),
    )


def _voltage_suggestion(cand_by_id, deferred_ids, params, base, bus_id, blocked):
    """Voltage binding: try reactive absorption first (cheapest), else one upstream reinforcement."""
    solves = 0
    for pf, k in VOLTAGE_ABSORB_PF_STEPS:
        f30, n30, s30 = _trial_phase(cand_by_id, deferred_ids, params, base, "2030", q_factor=k)
        f35, n35, s35 = _trial_phase(cand_by_id, deferred_ids, params, base, "2035", q_factor=k)
        solves += s30 + s35
        if n30 or n35:
            return Suggestion(
                target_type="voltage",
                target_element_id=bus_id,
                action=f"Connect new DER at bus {bus_id} absorbing reactive power (~{pf:.2f} pf)",
                connects_target=True,
                freed_mw_2030=f30,
                freed_mw_2035=f35,
                newly_connected_project_ids=sorted(set(n30) | set(n35)),
                blocked_project_ids=blocked,
                extra_solves=solves,
                caveat=(
                    "Voltage binding is voltage rise from unity-power-factor export; quantified by "
                    f"re-running power flow with the new DER absorbing reactive power (to ~{pf:.2f} "
                    "pf). A feasible operating lever, not the minimum-cost or only fix."
                ),
            )
    # fall back to one upstream reinforcement on the weakest line of the feeder path
    probe = build_base_net()
    path = upstream_path_lines(probe, int(bus_id))
    if path:
        lid = max(
            path,
            key=lambda i: float(probe.line.at[i, "x_ohm_per_km"]) * float(probe.line.at[i, "length_km"]),
        )
        r = Reinforcement(kind="line", element_id=lid, action="add_parallel")
        f30, n30, s30 = _trial_phase(cand_by_id, deferred_ids, params, base, "2030", reinf=[r])
        f35, n35, s35 = _trial_phase(cand_by_id, deferred_ids, params, base, "2035", reinf=[r])
        solves += s30 + s35
        return Suggestion(
            target_type="voltage",
            target_element_id=bus_id,
            action=f"Add a parallel circuit to line {lid} feeding bus {bus_id}",
            reinforcements=[r],
            connects_target=bool(n30 or n35),
            freed_mw_2030=f30,
            freed_mw_2035=f35,
            newly_connected_project_ids=sorted(set(n30) | set(n35)),
            blocked_project_ids=blocked,
            extra_solves=solves,
            caveat=(
                f"Voltage-bound at bus {bus_id}; modelled by reinforcing the highest-impedance line "
                f"({lid}) on its feeder path. A feasible lever, not a least-cost study."
            ),
        )
    return Suggestion(
        target_type="voltage",
        target_element_id=bus_id,
        action=f"Reinforce the feeder supplying bus {bus_id}",
        connects_target=False,
        blocked_project_ids=blocked,
        extra_solves=solves,
        caveat="Voltage-bound with no low-cost reactive or single-circuit lever identified here.",
    )


def _gsp_suggestion(cand_by_id, deferred_ids, params, base, blocked):
    """GSP-boundary binding: no distribution-side reinforcement helps — the export limit is the
    supergrid transformers above the GSP. Model one more SGT and measure what it frees."""
    sgt_mw = float(build_base_net().get("gsp_sgt_mw") or 0.0)
    reinf = [Reinforcement(kind="gsp", element_id=0)]
    f30, n30, s30 = _trial_phase(cand_by_id, deferred_ids, params, base, "2030", reinf=reinf)
    f35, n35, s35 = _trial_phase(cand_by_id, deferred_ids, params, base, "2035", reinf=reinf)
    newly = sorted(set(n30) | set(n35))
    return Suggestion(
        target_type="gsp",
        target_element_id=-1,
        action=f"Add a supergrid transformer at the GSP (+{sgt_mw:.0f} MW of export to transmission)",
        reinforcements=reinf,
        connects_target=bool(set(blocked) & set(newly)),
        freed_mw_2030=f30,
        freed_mw_2035=f35,
        newly_connected_project_ids=newly,
        blocked_project_ids=blocked,
        extra_solves=s30 + s35,
        caveat=(
            "Transmission works by National Grid Electricity Transmission, coordinated by NESO — "
            "outside the DNO's control and typically years away; wider transmission reinforcement "
            "out of the area may also be needed. Nearer-term levers: flexible (curtailable) "
            "connections or co-located storage that shifts export away from the peak."
        ),
    )


class Lever(NamedTuple):
    """What to do about one kind of binding constraint. `suggest(cand_by_id, deferred_ids, params,
    base, blocked_ids, element_id)` returns a Suggestion; a `wide` lever acts on the whole network
    (element_id is None) and covers every project bound by that reason type with one suggestion."""

    suggest: Callable[..., Suggestion]
    wide: bool = False


def _lever_thermal(cand_by_id, deferred_ids, params, base, blocked, element_id):
    return _reinforcement_suggestion(cand_by_id, deferred_ids, params, base, blocked[0], blocked)


def _lever_voltage(cand_by_id, deferred_ids, params, base, blocked, element_id):
    return _voltage_suggestion(cand_by_id, deferred_ids, params, base, element_id, blocked)


def _lever_gsp(cand_by_id, deferred_ids, params, base, blocked, element_id):
    return _gsp_suggestion(cand_by_id, deferred_ids, params, base, blocked)


# Reason.type -> its lever. A new kind of binding constraint is a reason in network.py plus one entry here.
LEVERS: dict[str, Lever] = {
    **{t: Lever(_lever_thermal) for t in _THERMAL_TYPES},
    "voltage": Lever(_lever_voltage),
    "gsp": Lever(_lever_gsp, wide=True),
}


def _dedupe(suggestions: list[Suggestion]) -> list[Suggestion]:
    """Merge suggestions that model the same action (two projects needing the same upgrade)."""
    out: dict[tuple, Suggestion] = {}
    for s in suggestions:
        key = (s.target_type, tuple(sorted((r.kind, r.element_id) for r in s.reinforcements)), s.action)
        if key in out:
            prev = out[key]
            prev.blocked_project_ids = sorted(set(prev.blocked_project_ids) | set(s.blocked_project_ids))
        else:
            out[key] = s
    return list(out.values())


def suggest_unblock(
    candidates: list[Candidate],
    params: OptimizeParams | None = None,
    base: OptimizeResult | None = None,
    max_suggestions: int = MAX_SUGGESTIONS,
) -> list[Suggestion]:
    """Propose concrete unblocks for the highest-ranked projects the optimizer deferred on the grid.

    For each (up to `max_suggestions`), returns what it would take to connect it — a reinforcement
    chain or a reactive-power lever — plus the MW that action frees by 2030/2035 and the projects it
    connects. Deterministic; reuses the cached `base` run when provided.
    """
    params = params or OptimizeParams()
    if base is None:
        base = optimize(candidates, params)

    cand_by_id = _cand_index(candidates)
    deferred_ids = [q.request_id for q in base.queue if q.status == "Deferred"]
    bound = [  # already in rank order
        q for q in base.queue
        if q.status == "Deferred" and q.reason is not None and q.reason.type in LEVERS
    ]

    out: list[Suggestion] = []
    # a wide lever covers every project bound by its reason type with ONE suggestion, which leads the list
    for reason_type, lever in LEVERS.items():
        if not lever.wide:
            continue
        blocked = [q.request_id for q in bound if q.reason.type == reason_type]
        if blocked:
            out.append(lever.suggest(cand_by_id, deferred_ids, params, base, blocked, None))
            max_suggestions -= 1
    per_project = [q for q in bound if not LEVERS[q.reason.type].wide and q.reason.element_id is not None]
    for q in per_project[:max(max_suggestions, 0)]:
        out.append(LEVERS[q.reason.type].suggest(
            cand_by_id, deferred_ids, params, base, [q.request_id], int(q.reason.element_id)))
    return _dedupe(out)
