"""Rebase: move a branch onto its parent's current state, git-style.

A branch records its parent's state when it is opened (the fork point, `branches.fork_json`). Three
states then tell everything apart: the fork, the parent now and the branch now. The parent's changes
since the fork are what a squash-merge would undo (`behind`, a merge blocker); a rebase replays the
branch's own changes on the parent's current state. Where both sides changed the same thing (fields of
one project, a project removed on one side and changed on the other, works or reinforcements added on
the same element, the demand profile) it is a conflict, shown to the operator and never picked here.

The fork point is `recorded`, `rebuilt` from the merge history for a branch older than fork points (its
demand profile unknown, None: a difference in it is a conflict), or `none` (no common ancestor): then
every difference between the parent and the branch is a conflict, as in git without a merge base.

A state is a plain dict (`repository.branch_state`): {"projects": {request_id: row}, "works": {outage_id:
row}, "reinforcements": {reinforcement_id: row}, "profile": {...} | None}. Pure functions; no SQL, no HTTP.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from gridforge_optimizer.gate import ParentMove

# what a project is: the fields compared and merged (status and review_reasons follow from them)
PROJECT_FIELDS = ("applicant", "bus_id", "technology", "rating_mw", "import_mw", "commissioning_year", "scheduled_year",
                  "control_json", "readiness_score", "strategic_fit", "readiness_rationale")
_LABEL = {"applicant": "applicant", "bus_id": "point of connection", "technology": "technology", "rating_mw": "export rating",
          "import_mw": "import capacity", "commissioning_year": "requested year", "scheduled_year": "energisation year",
          "control_json": "control mode", "readiness_score": "readiness score", "strategic_fit": "strategic fit",
          "readiness_rationale": "readiness rationale"}
# the things a works window or a reinforcement is on: two added on the same element by both sides conflict
_ELEMENT = {"works": ("element_kind", "element_id"), "reinforcements": ("kind", "element_id")}
_KIND = {"works": "outage", "reinforcements": "reinforcement"}
_EMPTY = {"projects": {}, "works": {}, "reinforcements": {}, "profile": None}


@dataclass
class Change:
    """One difference between two states of a branch. `point` is what it is about ("project:ECR-1:rating_mw",
    "project:ECR-1", "works:mw-1", "reinforcements:rf-1", "profile")."""

    point: str
    element_kind: str | None
    element_id: str | None
    text: str

    @property
    def item(self) -> str:
        """The thing it is about: a project, a works window, a reinforcement or the profile ("project:ECR-1")."""
        return ":".join(self.point.split(":")[:2])

    def move(self) -> ParentMove:
        return ParentMove(self.element_kind, self.element_id, self.text)


@dataclass
class Conflict:
    """Both sides changed the same thing: the operator picks `parent` or `branch` (or `both` for works and
    reinforcements added on the same element). A project's conflicting `fields` are picked together, so a
    resize and the import that follows it never come from different sides."""

    id: str
    element_kind: str | None
    element_id: str | None
    text: str
    parent: str
    branch: str
    options: list[str]
    fields: list[str] = field(default_factory=list)


@dataclass
class Plan:
    """What a rebase would do: the state it writes before any pick, the conflicts to pick, and both sides' changes."""

    fork: dict
    parent: dict
    head: dict
    state: dict
    fork_kind: str = "recorded"
    conflicts: list[Conflict] = field(default_factory=list)
    parent_changes: list[Change] = field(default_factory=list)
    own_changes: list[Change] = field(default_factory=list)
    behind: list[Change] = field(default_factory=list)


def items(changes: list[Change]) -> set[str]:
    """The distinct things a list of changes is about (one resize that also scales the import is one project)."""
    return {c.item for c in changes}


# --- words ---------------------------------------------------------------------------------------------
def _num(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def _control(raw) -> str:
    if not raw:
        return "not stated"
    c = json.loads(raw) if isinstance(raw, str) else raw
    if c.get("mode") == "pf":
        return f"power factor {_num(c.get('pf'))} {'absorbing' if c.get('absorbing', True) else 'injecting'}"
    return f"voltage control at {_num(c.get('vm_pu'))} pu within ±{_num(c.get('q_range_pf'))} pf"


def _value(f: str, v) -> str:
    if f == "control_json":
        return _control(v)
    if v is None:
        return "none"
    if f == "bus_id":
        return f"bus {v}"
    if f in ("rating_mw", "import_mw"):
        return f"{_num(v)} MW"
    if f == "readiness_rationale":
        return "its own wording"
    return _num(v)


def _field_text(rid: str, f: str, a, b) -> str:
    if f == "readiness_rationale":
        return f"{rid}: readiness rationale rewritten"
    return f"{rid}: {_LABEL[f]} {_value(f, a)} → {_value(f, b)}"


def _project_text(rid: str, row: dict) -> str:
    size = (f"{_num(row['rating_mw'])} MW" if row.get("rating_mw") else f"{_num(row['import_mw'])} MW import" if row.get("import_mw")
            else "size not stated")
    return f"{rid} ({row.get('technology') or 'technology not stated'}, {size} at bus {row.get('bus_id')})"


def _item_text(area: str, row: dict) -> str:
    if area == "works":
        what = row.get("work") or "maintenance"
        return (f"a {what} window on {row.get('element_kind')} {row.get('element_id')} "
                f"({row.get('season')} {row.get('year')}, {row.get('weeks')} weeks)")
    how = "uprate ×" + _num(row.get("factor")) if row.get("action") == "uprate" else "a parallel circuit"
    return f"a reinforcement of {row.get('kind')} {row.get('element_id')} ({how})"


def _profile_text(p: dict | None) -> str:
    if not p:
        return "not recorded"
    s = p.get("scenario") or "custom"
    return s if s != "custom" else f"custom (×{_num(p.get('growth_2030'))} by 2030, ×{_num(p.get('growth_2035'))} by 2035)"


# --- differences -----------------------------------------------------------------------------------------
def _fields(row: dict | None) -> dict:
    return {f: (row or {}).get(f) for f in PROJECT_FIELDS}


def changes(a: dict, b: dict) -> list[Change]:
    """What changed from state `a` to state `b`, in words."""
    out: list[Change] = []
    pa, pb = a.get("projects", {}), b.get("projects", {})
    for rid in sorted(pa.keys() | pb.keys()):
        if rid not in pa:
            out.append(Change(f"project:{rid}", "project", rid, f"added {_project_text(rid, pb[rid])}"))
        elif rid not in pb:
            out.append(Change(f"project:{rid}", "project", rid, f"removed {rid}"))
        else:
            fa, fb = _fields(pa[rid]), _fields(pb[rid])
            out += [Change(f"project:{rid}:{f}", "project", rid, _field_text(rid, f, fa[f], fb[f])) for f in PROJECT_FIELDS if fa[f] != fb[f]]
    for area in ("works", "reinforcements"):
        ia, ib = a.get(area, {}), b.get(area, {})
        out += [Change(f"{area}:{i}", _KIND[area], i, f"added {_item_text(area, ib[i])}") for i in sorted(ib.keys() - ia.keys())]
        out += [Change(f"{area}:{i}", _KIND[area], i, f"removed {_item_text(area, ia[i])}") for i in sorted(ia.keys() - ib.keys())]
    if a.get("profile") is not None and a.get("profile") != b.get("profile"):  # an unrecorded profile tells no change (see plan)
        out.append(Change("profile", None, None, f"demand profile {_profile_text(a.get('profile'))} → {_profile_text(b.get('profile'))}"))
    return out


_ABSENT = object()


def _at(state: dict, point: str):
    """A state's value at a change's point (what the branch has there), to tell whether it already has a change."""
    area, _, rest = point.partition(":")
    if area == "profile":
        return state.get("profile")
    if area == "project":
        rid, _, f = rest.partition(":")
        row = state.get("projects", {}).get(rid)
        if not f:
            return row is not None
        return _ABSENT if row is None else row.get(f)
    return rest in state.get(area, {})


# --- the three-way plan --------------------------------------------------------------------------------
def plan(fork: dict | None, parent: dict, head: dict, *, fork_kind: str = "recorded") -> Plan:
    """The rebase of `head` onto `parent` as it is now, from `fork` (None: no common ancestor): the state before any
    pick, the conflicts, the changes on each side, and `behind` (the parent's changes the branch does not have, what a
    merge would undo; not known without a fork point)."""
    known = fork is not None
    p = Plan(fork if known else _EMPTY, parent, head, {"projects": {}, "works": {}, "reinforcements": {}, "profile": None}, fork_kind=fork_kind)
    if known:
        p.parent_changes = changes(fork, parent)
        p.own_changes = changes(fork, head)
        p.behind = [c for c in p.parent_changes if _at(parent, c.point) != _at(head, c.point)]
        if fork.get("profile") is None and parent.get("profile") != head.get("profile"):  # rebuilt fork: whose change is not known
            p.behind.append(Change("profile", None, None, f"demand profile {_profile_text(parent.get('profile'))} here, "
                                                          f"{_profile_text(head.get('profile'))} on the branch (which one changed is not recorded)"))
    _projects(p, known)
    for area in ("works", "reinforcements"):
        _items(p, area, known)
    _profile(p)
    return p


def _projects(p: Plan, known: bool) -> None:
    fk, pa, hd = p.fork["projects"], p.parent["projects"], p.head["projects"]
    for rid in sorted(fk.keys() | pa.keys() | hd.keys()):
        f, a, h = fk.get(rid), pa.get(rid), hd.get(rid)
        if a is None and h is None:
            continue
        if a is None or h is None:  # on one side only
            other = h if a is None else a
            if f is None and known:  # added on that side after the fork: kept
                p.state["projects"][rid] = dict(other)
                continue
            if f is not None and _fields(other) == _fields(f):  # removed on the other side, left as it was here: removed
                continue
            side, where = ("the parent", "this branch") if a is not None else ("this branch", "the parent")
            why = (f"{rid} is on {side} but not on {where}" if not known
                   else f"{rid} was removed on {where} and changed on {side}")
            p.conflicts.append(Conflict(f"project:{rid}", "project", rid, why,
                                        "removed" if a is None else f"kept, as {_project_text(rid, a)}",
                                        "removed" if h is None else f"kept, as {_project_text(rid, h)}", ["parent", "branch"]))
            continue
        row, clash = dict(a), []
        base = _fields(f)
        for k in PROJECT_FIELDS:
            fv, av, hv = base[k], a.get(k), h.get(k)
            if av == hv or (known and hv == fv):
                row[k] = av
            elif known and av == fv:
                row[k] = hv
            else:
                clash.append(k)
        if clash:  # one conflict for the project: its clashing fields are picked together
            p.conflicts.append(Conflict(f"project:{rid}", "project", rid, f"{rid}: {', '.join(_LABEL[k] for k in clash)} "
                                        + ("changed on both sides" if known else "differ"),
                                        "; ".join(f"{_LABEL[k]} {_value(k, a.get(k))}" for k in clash),
                                        "; ".join(f"{_LABEL[k]} {_value(k, h.get(k))}" for k in clash), ["parent", "branch"], clash))
        p.state["projects"][rid] = row


def _items(p: Plan, area: str, known: bool) -> None:
    fk, pa, hd = p.fork.get(area, {}), p.parent.get(area, {}), p.head.get(area, {})
    for i in pa.keys() & hd.keys():  # on both sides (works and reinforcements are never edited, only added or removed)
        p.state[area][i] = pa[i]
    if not known:  # no common ancestor: each one on one side only is the operator's call
        for i, r in sorted({**{i: pa[i] for i in pa.keys() - hd.keys()}, **{i: hd[i] for i in hd.keys() - pa.keys()}}.items()):
            on = "the parent" if i in pa else "this branch"
            p.conflicts.append(Conflict(f"{area}:{i}", _KIND[area], i, f"{_item_text(area, r)} is on {on} only",
                                        "kept" if i in pa else "not there", "kept" if i in hd else "not there", ["parent", "branch"]))
        return
    ek = _ELEMENT[area]
    key = lambda row: tuple(str(row.get(k)) for k in ek)  # noqa: E731
    added_p = {i: pa[i] for i in pa.keys() - fk.keys() - hd.keys()}
    added_h = {i: hd[i] for i in hd.keys() - fk.keys() - pa.keys()}
    on_both = {key(r) for r in added_p.values()} & {key(r) for r in added_h.values()}
    for i, r in {**added_p, **added_h}.items():
        if key(r) not in on_both:
            p.state[area][i] = r
    for k in sorted(on_both):
        mine = "; ".join(_item_text(area, r) for r in added_h.values() if key(r) == k)
        theirs = "; ".join(_item_text(area, r) for r in added_p.values() if key(r) == k)
        p.conflicts.append(Conflict(f"{area}:{':'.join(k)}", k[0], k[1],
                                    f"{'works windows' if area == 'works' else 'reinforcements'} added on {k[0]} {k[1]} on both sides",
                                    theirs, mine, ["parent", "branch", "both"]))


def _profile(p: Plan) -> None:
    f, a, h = p.fork.get("profile"), p.parent.get("profile"), p.head.get("profile")
    if a == h or (f is not None and h == f):
        p.state["profile"] = a
    elif f is not None and a == f:
        p.state["profile"] = h
    else:  # changed on both sides, or not recorded at the fork: the operator's call
        p.state["profile"] = a
        p.conflicts.append(Conflict("profile", None, None, "the demand profile differs" + (" on both sides" if f is not None else
                                    " and the parent's at the time this branch was opened is not recorded"),
                                    _profile_text(a), _profile_text(h), ["parent", "branch"]))


# --- the operator's picks ------------------------------------------------------------------------------
class PicksError(ValueError):
    """The picks do not answer the plan's conflicts (missing, unknown, or an option a conflict does not offer)."""


def resolve(p: Plan, picks: dict[str, str]) -> dict:
    """The state the rebase writes: the plan's, with every conflict answered by the operator's pick. Each project's
    `status` / `review_reasons` follow the side its fields came from; a row mixed from both sides is marked
    `_retriage` for the caller to triage again."""
    by_id = {c.id: c for c in p.conflicts}
    missing = [c.id for c in p.conflicts if c.id not in picks]
    unknown = [k for k in picks if k not in by_id]
    bad = [k for k, v in picks.items() if k in by_id and v not in by_id[k].options]
    if missing or unknown or bad:
        raise PicksError({"missing": missing, "unknown": unknown, "invalid": bad})
    state = json.loads(json.dumps(p.state))
    side = {"parent": p.parent, "branch": p.head}
    for c in p.conflicts:
        pick = picks[c.id]
        area, _, rest = c.id.partition(":")
        if area == "project":
            src = side[pick]["projects"].get(rest)
            if not c.fields:  # on one side only
                if src is None:
                    state["projects"].pop(rest, None)
                else:
                    state["projects"][rest] = dict(src)
            else:
                for f in c.fields:
                    state["projects"][rest][f] = src.get(f)
        elif area == "profile":
            state["profile"] = side[pick]["profile"]
        elif c.element_kind in _KIND.values() and rest in {**p.parent.get(area, {}), **p.head.get(area, {})}:  # one item (no ancestor)
            src = side[pick][area].get(rest)
            if src is not None:
                state[area][rest] = src
        else:  # added on the same element on both sides
            ek, k = _ELEMENT[area], tuple(rest.split(":", 1))
            for s in (("parent", "branch") if pick == "both" else (pick,)):
                for i, r in side[s][area].items():
                    if i not in p.fork.get(area, {}) and tuple(str(r.get(x)) for x in ek) == k:
                        state[area][i] = r
    for rid, row in state["projects"].items():
        for s in (p.parent, p.head):
            src = s["projects"].get(rid)
            if src is not None and _fields(src) == _fields(row):
                row["status"], row["review_reasons"] = src.get("status"), src.get("review_reasons")
                break
        else:
            row["_retriage"] = True
    return state


def taken(p: Plan, state: dict, picks: dict[str, str]) -> int:
    """How many of the parent's changes (by thing changed) the rebased branch now has. Without a fork point, the
    conflicts answered with the parent's side."""
    if p.fork_kind == "none":
        return sum(1 for v in picks.values() if v in ("parent", "both"))
    return len(items([c for c in p.behind if _at(state, c.point) == _at(p.parent, c.point)]))


def preview(p: Plan, *, onto: str) -> dict:
    """The plan as the planner shows it before the operator confirms."""
    as_dict = lambda c: {"point": c.point, "element_kind": c.element_kind, "element_id": c.element_id, "text": c.text}  # noqa: E731
    return {
        "onto": onto, "fork": p.fork_kind, "up_to_date": not p.behind and not p.conflicts,
        "parent_changes": [as_dict(c) for c in p.parent_changes],
        "own_changes": [as_dict(c) for c in p.own_changes],
        "behind": [as_dict(c) for c in p.behind],
        "n_behind": len(items(p.behind)),
        "conflicts": [c.__dict__ for c in p.conflicts],
    }
