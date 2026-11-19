"""NGED's half-hourly flows for the GSP group (its curtailment-analysis data) mapped onto the built network: the inputs
of the measured year, half-hour by half-hour, and NGED's own branch flows to compare against. NGED-specific; reached
through `NgedSource.measured_year`. Reads local files only (the pipeline's `nged_flows` asset fetches them).

Supported by NGED Open Data (NGED Open Data Licence, December 2020).

What the files hold (checked on the 2024 edition, see docs/reports/timeseries-step1-spec-2026-11-12.md):
- substation loading: per NGED bus number, the net MW and MVAr at the node, demand positive, metered and cleansed by
  NGED (gaps imputed, unflagged); a substation on two nodes publishes a share on each;
- branch loading: per `from_to_circuit_kind` column, the MW of NGED's own load flow (PSS/E) on those nodes, + = from -> to.

How the inputs are made (README register, "The measured year"):
- the engine buses joined only by branches NGED's file does not carry are one node in NGED's model: they form a
  cluster, and each cluster's injection sits on one bus of it (the anchor);
- each cluster's injection is NGED's own balance there over the branches the engine models (what they deliver to it:
  Kirchhoff's current law); a branch with one end outside the engine (Middlemarsh's 33 kV) is part of the injection; where a node series of NGED's sums to that balance (within NODE_MATCH_MW on 99% of half-hours), the metered
  series is used instead, with its MVAr; elsewhere reactive power is 0;
- a cluster that is not a leaf and has no load, generator or node series of its own carries nothing: what NGED's balance shows there is line
  loss or a difference between NGED's topology and ours, recorded in `notes["unplaced"]`, not injected;
  clusters held at 0 (the supply point's `held_at_zero`) carry nothing by decision;
- the slack's cluster (the GSP) carries nothing: the external grid balances the rest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import IMPUTATION_RUN_HALF_HOURS

SUBSTATION_FILE = "substation_load.csv"
BRANCH_FILE = "branch_load.csv"
BUS_MAP_FILE = "bus_mapping.json"
REACTIVE_MODES = ("published", "screened", "unity")  # the published MVAr; the screen below; every node at unity power factor
IMPLAUSIBLE_S_PER_CAPACITY = 1.5  # apparent power above this multiple of the substation's installed transformer capacity
SUSPECT_Q_PER_P, SUSPECT_Q_MVAR = 2.0, 2.0  # |Q| above twice |P| and above 2 MVAr
SUSPECT_GUARD_SHARE = 0.01  # a node whose suspect flags exceed this share of the year, with no implausible half-hour, is listed, not substituted
NODE_MATCH_MW = 0.5  # a node series is an injection where it equals NGED's balance at its cluster within this, 99% of the time
@dataclass
class MeasuredYear:
    """A year of half-hours mapped onto one built network (bus and element ids are that network's)."""

    times: pd.DatetimeIndex  # as published: each half-hour labelled by its end
    bus_p: pd.DataFrame  # half-hour x anchor bus: MW drawn at the bus (generation negative)
    bus_q: pd.DataFrame  # half-hour x anchor bus: MVAr
    branch_mw: pd.DataFrame  # NGED's branch flows, as published (+ = from -> to)
    branch_map: dict[str, dict]  # column -> {"kind": "line"|"trafo", "ids": [...], "sign": +1|-1} (sign: engine end vs NGED's)
    node_flags: pd.DataFrame  # half-hour x node column: True inside a run of identical values (IMPUTATION_RUN_HALF_HOURS)
    node_bus: dict[str, int]  # node column -> engine bus
    q_flags: pd.DataFrame  # half-hour x anchor bus: 2 implausible, 1 suspect, 0 neither (the reactive-power screen)
    unplaced_p: pd.DataFrame  # half-hour x cluster: NGED's balance where nothing is injected (held at 0 by decision, or unplaced)
    notes: dict = field(default_factory=dict)  # counts and what was held at 0, for the report
    shapes: pd.DataFrame = field(default_factory=pd.DataFrame)  # half-hour x kind: a new connection's output per unit (the supply point's `year_shapes`), 0..1


def _read(folder: Path):
    sub = pd.read_csv(folder / SUBSTATION_FILE)
    br = pd.read_csv(folder / BRANCH_FILE)
    if not sub.iloc[:, 0].equals(br.iloc[:, 0]):
        raise ValueError("the substation and branch files do not share their half-hours")
    raw = json.loads((folder / BUS_MAP_FILE).read_text(encoding="utf-8"))
    recs = raw["result"]["records"] if isinstance(raw, dict) else raw
    names = {int(r["bus_number"]): str(r["bus_name"]) for r in recs}
    return sub, br, names


def _run_flags(s: pd.Series, n: int) -> pd.Series:
    run = (s.diff() != 0).cumsum()
    return s.groupby(run).transform("size") >= n


def _screen_reactive(net, cl_of, p: pd.DataFrame, q: pd.DataFrame, mode: str, notes: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The reactive-power screen (README register, "Reactive-power screen"). A node's half-hour is flagged implausible when
    its apparent power exceeds IMPLAUSIBLE_S_PER_CAPACITY x the installed transformer capacity at its substation, and
    suspect when |Q| > SUSPECT_Q_PER_P x |P| and > SUSPECT_Q_MVAR. In "screened" mode a flagged half-hour's Q is replaced
    by P x tan(the LTDS power-factor angle of the substation's demand); P is never touched. A node with suspect flags on
    more than SUSPECT_GUARD_SHARE of the year and no implausible half-hour is not substituted (net P can be small at a
    node with embedded generation while its Q is real): it is listed instead. "unity" sets every Q to 0 (a diagnostic)."""
    flags = pd.DataFrame(0, index=p.index, columns=p.columns, dtype=np.int8)
    rep = notes.setdefault("reactive", {"mode": mode, "implausible": {}, "suspect": {}, "guarded": [], "no_capacity": []})
    for a in p.columns:
        members = [b for b, c in cl_of.items() if c == cl_of[int(a)]]
        cap = float(net.trafo.loc[net.trafo.lv_bus.isin(members), "sn_mva"].sum())
        S = np.hypot(p[a], q[a])
        imp = (S > IMPLAUSIBLE_S_PER_CAPACITY * cap) if cap > 0 else pd.Series(False, index=p.index)
        sus = (q[a].abs() > SUSPECT_Q_PER_P * p[a].abs()) & (q[a].abs() > SUSPECT_Q_MVAR) & ~imp
        if cap <= 0:
            rep["no_capacity"].append(int(a))
        if sus.mean() > SUSPECT_GUARD_SHARE and not imp.any():
            rep["guarded"].append(int(a))
            sus = pd.Series(False, index=p.index)
        flags.loc[imp, a] = 2
        flags.loc[sus, a] = 1
        if imp.any():
            rep["implausible"][int(a)] = int(imp.sum())
        if sus.any():
            rep["suspect"][int(a)] = int(sus.sum())
    if mode == "unity":
        return pd.DataFrame(0.0, index=q.index, columns=q.columns), flags
    if mode == "screened":
        q = q.copy()
        for a in p.columns:
            hit = flags[a] > 0
            if hit.any():
                ld = net.load[net.load.bus.isin([b for b, c in cl_of.items() if c == cl_of[int(a)]])]
                tan = float(ld.q_mvar.sum() / ld.p_mw.sum()) if len(ld) and float(ld.p_mw.sum()) > 0 else 0.0
                q.loc[hit, a] = p.loc[hit, a] * tan
                rep.setdefault("tan_phi", {})[int(a)] = round(tan, 4)
    return q, flags


def map_year(net, bus_of_code, folder, reactive: str = "published", *, held_at_zero: dict, year_shapes: dict) -> MeasuredYear:
    """Map NGED's files in `folder` onto `net`. `bus_of_code(code) -> engine bus | None` resolves an LTDS node code;
    `reactive` is one of REACTIVE_MODES; `held_at_zero` and `year_shapes` are the supply point's (`nged_points`)."""
    if reactive not in REACTIVE_MODES:
        raise ValueError(f"reactive must be one of {REACTIVE_MODES}")
    folder = Path(folder)
    sub, br, names = _read(folder)
    times = pd.DatetimeIndex(pd.to_datetime(sub.iloc[:, 0]))
    def bus(num) -> int | None:
        b = bus_of_code(names.get(int(num), ""))
        return int(b) if b is not None and int(b) in net.bus.index else None

    # NGED branch -> engine element(s), and the engine buses at its ends
    ends: dict[str, tuple[int | None, int | None]] = {}
    branch_map: dict[str, dict] = {}
    mapped: set[tuple[str, int]] = set()
    for col in br.columns[1:]:
        f, t = col.split("_")[:2]
        fb, tb = bus(f), bus(t)
        ends[col] = (fb, tb)
        if fb is None or tb is None or fb == tb:
            continue
        ln = net.line[((net.line.from_bus == fb) & (net.line.to_bus == tb)) | ((net.line.from_bus == tb) & (net.line.to_bus == fb))]
        if "connector" in net.line.columns:  # a connector (a closed switch; its row out of service) is not compared: its
            ln = ln[~ln["connector"].astype(bool)]  # buses join one cluster, as two joined by an unmapped branch do
        tr = net.trafo[((net.trafo.hv_bus == fb) & (net.trafo.lv_bus == tb)) | ((net.trafo.hv_bus == tb) & (net.trafo.lv_bus == fb))]
        if len(ln):
            branch_map[col] = {"kind": "line", "ids": [int(i) for i in ln.index], "sign": 1 if int(ln.from_bus.iloc[0]) == fb else -1}
            mapped |= {("line", int(i)) for i in ln.index}
        elif len(tr):
            branch_map[col] = {"kind": "trafo", "ids": [int(i) for i in tr.index], "sign": 1 if int(tr.hv_bus.iloc[0]) == fb else -1}
            mapped |= {("trafo", int(i)) for i in tr.index}

    # clusters: engine buses joined by branches NGED's file does not carry
    parent = {int(b): int(b) for b in net.bus.index}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for kind, tab, a, b in (("line", net.line, "from_bus", "to_bus"), ("trafo", net.trafo, "hv_bus", "lv_bus")):
        for i, r in tab.iterrows():
            if (kind, int(i)) not in mapped:
                parent[find(int(r[a]))] = find(int(r[b]))
    clusters: dict[int, list[int]] = {}
    for b in parent:
        clusters.setdefault(find(b), []).append(b)
    cl_of = {b: find(b) for b in parent}

    # NGED's balance per cluster: demand = what flows in - what flows out
    kcl: dict[int, pd.Series] = {}
    n_ends: dict[int, int] = {}  # how many of NGED's branches reach each cluster: one means a leaf (a customer site)
    for col, (fb, tb) in ends.items():
        if fb is None or tb is None:
            continue  # one end outside the engine (Middlemarsh's 33 kV, the supergrid side): its flow is an injection
        cf, ct = cl_of[fb], cl_of[tb]
        if cf == ct:
            continue
        for c in (cf, ct):
            n_ends[c] = n_ends.get(c, 0) + 1
        s = br[col].astype(float)
        kcl[cf] = kcl.get(cf, 0.0) - s
        kcl[ct] = kcl.get(ct, 0.0) + s

    # node series per cluster (a substation's columns are shares: summed)
    node_bus: dict[str, int] = {}
    node_cols: dict[int, list[str]] = {}
    for c in [c for c in sub.columns if c.startswith("MW_")]:
        b = bus(c[3:])
        if b is None:
            continue
        node_bus[c] = int(b)
        node_cols.setdefault(cl_of[int(b)], []).append(c)

    slack_cl = {cl_of[int(b)] for b in net.ext_grid.bus}
    held = {cl_of[int(b)] for code in held_at_zero if (b := bus_of_code(code)) is not None and int(b) in cl_of}
    load_bus = net.load.groupby("bus")["p_mw"].sum() if len(net.load) else pd.Series(dtype=float)
    sgen_bus = net.sgen.groupby("bus")["p_mw"].sum() if len(net.sgen) else pd.Series(dtype=float)
    p_cols: dict[int, pd.Series] = {}
    q_cols: dict[int, pd.Series] = {}
    notes = {"clusters": len(clusters), "multi_bus_clusters": {int(k): sorted(v) for k, v in clusters.items() if len(v) > 1},
             "metered": [], "derived": [], "unplaced": {}, "held_at_zero": {}, "group_totals": []}
    zero = pd.Series(0.0, index=sub.index)
    unplaced: dict[str, pd.Series] = {}
    for cl, members in clusters.items():
        if cl in slack_cl:
            continue
        balance = kcl.get(cl)
        cols = node_cols.get(cl, [])
        metered = None
        if cols:
            m = sub[cols].sum(axis=1)
            if balance is not None and float(((m - balance).abs() <= NODE_MATCH_MW).mean()) >= 0.99:
                metered = m
            elif balance is not None:
                notes["group_totals"] += cols  # a node series that is not this cluster's injection (a BSP's group total)
        has_own = (any(b in load_bus.index or b in sgen_bus.index for b in members) or metered is not None
                   or n_ends.get(cl, 0) == 1)  # a leaf passes nothing on: what reaches it is its own
        if cl in held:
            if balance is not None:
                notes["held_at_zero"][int(cl)] = round(float(balance.abs().max()), 2)
                unplaced[f"held@{int(cl)}"] = balance
            continue
        if metered is None and (balance is None or not has_own):
            if balance is not None and float(balance.abs().max()) > 0:
                notes["unplaced"][int(cl)] = round(float(balance.abs().max()), 2)
                unplaced[f"unplaced@{int(cl)}"] = balance
            continue
        anchor = (node_bus[cols[0]] if metered is not None else
                  max(members, key=lambda b: (float(load_bus.get(b, 0.0)), float(sgen_bus.get(b, 0.0)), -b)))
        if metered is not None:
            p_cols[anchor] = metered
            q_cols[anchor] = sub[["MVAr_" + c[3:] for c in cols]].sum(axis=1)
            notes["metered"].append(int(anchor))
        else:
            p_cols[anchor] = balance
            q_cols[anchor] = zero
            notes["derived"].append(int(anchor))
    flags = pd.DataFrame({c: _run_flags(sub[c], IMPUTATION_RUN_HALF_HOURS) for c in node_bus}, index=sub.index)
    idx = pd.RangeIndex(len(times))
    bus_p = pd.DataFrame(p_cols).set_index(idx)
    bus_q, q_flags = _screen_reactive(net, cl_of, bus_p, pd.DataFrame(q_cols).set_index(idx), reactive, notes)
    return MeasuredYear(
        times=times,
        bus_p=bus_p,
        bus_q=bus_q,
        q_flags=q_flags,
        branch_mw=br.iloc[:, 1:].set_index(idx),
        branch_map=branch_map,
        node_flags=flags.set_index(idx),
        node_bus=node_bus,
        unplaced_p=pd.DataFrame(unplaced).set_index(idx),
        notes=notes,
        # empty for a year whose branch list lacks the reference columns (2025 lists them the other way round): only the
        # grown and branch years, built on 2024, use the shapes
        shapes=pd.DataFrame({k: (br[list(cols)].sum(axis=1) * sign / mw).clip(0.0, 1.0).to_numpy() for k, (cols, sign, mw)
                             in year_shapes.items() if all(c in br.columns for c in cols)}, index=idx),
    )
