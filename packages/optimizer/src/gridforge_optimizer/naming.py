"""What people call a network's elements: a bus by its place, a line by the places it joins (parallel circuits
numbered), a transformer by its substation and ratio. The engine reports elements by index ("line 1",
"transformer 29", "bus 19"); this is the one place those become names, for the map (`GridModel`) and for every
text an agent reads. Grid-agnostic and pure.

The rules: a busbar's place is its name without the voltage and bay suffix ("BOSTON 33kV MAIN1" -> "Boston"),
its abbreviations spelled out ("Slr Pk" -> "Solar Park") and its acronyms kept ("RAF", "PV"); a coded busbar
("BOST1_MAIN1": no spaces, digits or underscores) borrows the place of a transformer on it, else of a named
neighbour on a line. A pole or tower on an overhead line ("Pole 90ZTADA3", an asset code, not a place) is a point
on a circuit: it is "the pole near Woodhall Spa", and a line section through poles is named by the substations
at the ends of its circuit, found by walking through the poles ("Tattershall to Woodhall Spa 33 kV, section 2").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SUFFIX = re.compile(r"\s*\d+(\.\d+)?\s*kV.*$", re.IGNORECASE)


# the LTDS's abbreviations, spelled out (a whole word, any case), and the acronyms title-case would flatten
ABBREVIATIONS = {"slr": "Solar", "pk": "Park", "fm": "Farm", "nth": "North", "sth": "South", "stn": "Station",
                 "la": "Lane", "rd": "Road", "gt": "Great", "wd": "Wood"}
ACRONYMS = {"raf": "RAF", "pv": "PV", "bess": "BESS", "gsp": "GSP", "sgt": "SGT", "nged": "NGED"}
_SMALL = {"of", "on", "and", "the", "in", "by", "at", "upon"}
# a pole or tower named by its asset code ("Pole 90ZTADA3", "Tower 91ZB9F10"): a point on a circuit, not a place
_JUNCTION = re.compile(r"^\s*(pole|tower)\s+\S*\d", re.IGNORECASE)


def _word(w: str) -> str:
    k = w.lower()
    return ACRONYMS.get(k) or ABBREVIATIONS.get(k) or w


def place_name(bus_name: str | None) -> str:
    """A substation's name from a busbar name ("BOSTON 33kV MAIN1" -> "Boston", "Burton Pedwardine Slr Pk 1" ->
    "Burton Pedwardine Solar Park 1"); "" when nothing is left."""
    s = re.sub(r"[_-]+", " ", _SUFFIX.sub("", str(bus_name or ""))).strip()
    if not s:
        return ""
    # each word capitalised at its start only ("Pedw'dine", not "Pedw'Dine"); small words lower inside a name
    words = [w[:1].upper() + w[1:].lower() for w in s.split()]
    return " ".join(w.lower() if k and w.lower() in _SMALL else _word(w) for k, w in enumerate(words))


def junction_kind(name: str | None) -> str:
    """"pole" or "tower" for an overhead-line point named by its asset code, else ""."""
    m = _JUNCTION.match(name or "")
    return m.group(1).lower() if m else ""


def is_code(name: str | None) -> bool:
    """A busbar code rather than a name: no spaces, and digits or underscores in it."""
    s = (name or "").strip()
    return bool(s) and not re.search(r"\s", s) and bool(re.search(r"[\d_]", s))


def _kv(v: float) -> str:
    return f"{float(v):g}"


@dataclass
class Names:
    """Every element's name by its engine index (what `GridModel` carries and `name_text` uses)."""

    place: dict[int, str] = field(default_factory=dict)  # bus -> its place ("" when nothing near it is named)
    bus_kv: dict[int, float] = field(default_factory=dict)
    line: dict[int, str] = field(default_factory=dict)
    trafo: dict[int, str] = field(default_factory=dict)
    junction: dict[int, str] = field(default_factory=dict)  # bus -> "pole" / "tower" (a point on a circuit, near its place)

    def bus(self, i: int) -> str:
        p = self.place.get(i, "")
        if not p or i not in self.bus_kv:
            return ""
        if i in self.junction:
            return f"{self.junction[i]} near {p} ({_kv(self.bus_kv[i])} kV)"
        return f"{p} {_kv(self.bus_kv[i])} kV busbar"

    def of(self, kind: str, i: int) -> str:
        return {"line": self.line, "transformer": self.trafo, "trafo": self.trafo}.get(kind, {}).get(i, "") or (self.bus(i) if kind == "bus" else "")


def element_names(buses: list, lines: list, transformers: list) -> Names:
    """Names for a model's elements (`ModelBus` / `ModelLine` / `ModelTransformer`, or anything with their fields)."""
    n = Names(bus_kv={b.bus_id: b.vn_kv for b in buses})
    n.junction = {b.bus_id: junction_kind(b.name) for b in buses if junction_kind(b.name)}
    for b in buses:
        if b.bus_id not in n.junction and not is_code(b.name) and place_name(b.name):
            n.place[b.bus_id] = place_name(b.name)

    def borrow(i: int, other: int) -> None:
        if i not in n.place and other in n.place:
            n.place[i] = n.place[other]

    for t in transformers:
        borrow(t.hv_bus, t.lv_bus)
        borrow(t.lv_bus, t.hv_bus)
    for ln in lines:
        if ln.from_bus not in n.junction and ln.to_bus not in n.junction:
            borrow(ln.from_bus, ln.to_bus)
            borrow(ln.to_bus, ln.from_bus)

    # the circuit a pole sits on: from a point, walk through poles and towers to the substations at the ends
    adj: dict[int, list[tuple[int, int]]] = {}
    for ln in lines:
        adj.setdefault(ln.from_bus, []).append((ln.to_bus, ln.line_id))
        adj.setdefault(ln.to_bus, []).append((ln.from_bus, ln.line_id))

    def circuit_ends(start: int, via: int) -> list[str]:
        """The places reached from `start` (a pole) without crossing line `via`, walking only through poles."""
        seen, todo, ends = {start}, [start], []
        while todo:
            u = todo.pop()
            for v, lid in adj.get(u, []):
                if lid == via or v in seen:
                    continue
                seen.add(v)
                if v in n.junction:
                    todo.append(v)
                elif n.place.get(v):
                    ends.append(n.place[v])
        return sorted(set(ends))

    for j in n.junction:  # a pole is near the first place along its circuit
        ends = circuit_ends(j, -1)
        if ends:
            n.place[j] = ends[0]

    def side(bus: int, via: int) -> list[str]:
        if bus in n.junction:
            return circuit_ends(bus, via)
        return [n.place[bus]] if n.place.get(bus) else []

    def base_line(ln) -> tuple[str, bool]:
        """The line's name before numbering, and whether it is a section of a circuit through poles."""
        kv = _kv(ln.voltage_kv)
        if ln.from_bus in n.junction or ln.to_bus in n.junction:
            a_side, b_side = side(ln.from_bus, ln.line_id), side(ln.to_bus, ln.line_id)
            a = a_side[0] if a_side else ""
            b = next((x for x in b_side if x != a), b_side[0] if b_side else "")
            if a and b and a != b:
                return f"{min(a, b)} to {max(a, b)} {kv} kV", True
            if a or b:
                return f"{a or b} {kv} kV spur", True
        a, b = n.place.get(ln.from_bus, ""), n.place.get(ln.to_bus, "")
        if a and b and a != b:
            return f"{a} to {b} {kv} kV", False
        return f"{a or ln.line_name or f'Line {ln.line_id}'} {kv} kV".strip(), False

    # parallel circuits are numbered "circuit k"; the sections of one circuit through poles, "section k"
    by_name: dict[tuple[str, bool], list[int]] = {}
    for ln in sorted(lines, key=lambda x: x.line_id):
        by_name.setdefault(base_line(ln), []).append(ln.line_id)
    for (name, section), ids in by_name.items():
        for k, i in enumerate(ids):
            n.line[i] = f"{name}, {'section' if section else 'circuit'} {k + 1}" if len(ids) > 1 else name
    # parallel transformers (the same substation and ratio) are numbered, like parallel circuits
    by_trafo: dict[str, list[int]] = {}
    for t in sorted(transformers, key=lambda x: x.trafo_id):
        sub = place_name(t.hv_name or t.name) or f"T{t.trafo_id}"
        ratio = f"{_kv(t.hv_kv)}/{_kv(t.lv_kv)} kV" if t.hv_kv and t.lv_kv else "–"
        by_trafo.setdefault(f"{sub} {ratio} transformer", []).append(t.trafo_id)
    for name, ids in by_trafo.items():
        for k, i in enumerate(ids):
            n.trafo[i] = f"{name} {k + 1}" if len(ids) > 1 else name
    return n


def name_model(model) -> Names:
    """Fill a `GridModel`'s names in place (a bus's `place`, a line's and a transformer's `display_name`) and return
    them: what `gridmodel.model_from_net` does to every model, and what a reader of a stored model (the warehouse's,
    made before the names existed) does to have them."""
    names = element_names(model.buses, model.lines, model.transformers)
    for b in model.buses:
        b.place = names.place.get(b.bus_id, "")
    for ln in model.lines:
        ln.display_name = names.line[ln.line_id]
    for t in model.transformers:
        t.display_name = names.trafo[t.trafo_id]
    return names


# "line 12", "Lines 0 and 1", "transformers 29, 30 and 31", "bus 19": not one already named "(line 12)", and not a
# figure written after the word ("worst line 93%", "a line 4 km long", "line 4.5 MW"): a number followed by a percent
# sign, a decimal or a unit is a value, not an element
_REF = re.compile(r"(?<!\()\b(line|transformer|trafo|bus)(?:s|es)? (\d+(?:(?:,? and |, )\d+)*)\b"
                  r"(?![.,]\d)(?!\s*%)(?!\s*(?:km|MW|MVAr|MVA|kV|kA|pu)\b)", re.IGNORECASE)


def name_text(text: str, names: Names) -> str:
    """Element references in a text named by place, the id kept in brackets for whoever acts on it:
    "lines 0 and 1" -> "Bicker Fen to Boston 132 kV, circuit 1 (line 0) and ... (line 1)". A reference with an
    id the model does not know is left as it was; a text already named is not named again."""

    def one(m: re.Match) -> str:
        kind = m.group(1).lower()
        kind = "transformer" if kind == "trafo" else kind
        ids = [int(x) for x in re.findall(r"\d+", m.group(2))]
        named = [names.of(kind, i) for i in ids]
        if not all(named):
            return m.group(0)
        parts = [f"{nm} ({kind} {i})" for nm, i in zip(named, ids)]
        return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]

    return _REF.sub(one, text)


def name_payload(value, names: Names):
    """`name_text` through a tool's payload (dicts, lists, strings). An N-1 record's `outage_name` (the net's own,
    often a code such as "L1") is replaced by the name of its `outage_type` / `outage_id`."""
    if isinstance(value, str):
        return name_text(value, names)
    if isinstance(value, list):
        return [name_payload(v, names) for v in value]
    if not isinstance(value, dict):
        return value
    out = {k: name_payload(v, names) for k, v in value.items()}
    kind, eid = value.get("outage_type"), value.get("outage_id")
    if "outage_name" in value and isinstance(kind, str) and isinstance(eid, int) and names.of(kind, eid):
        out["outage_name"] = f"{names.of(kind, eid)} ({'transformer' if kind == 'trafo' else kind} {eid})"
    return out
