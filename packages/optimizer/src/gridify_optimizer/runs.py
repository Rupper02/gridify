"""Measured and grown years as the planner's year view reads them: a summary of one run file (every line and
transformer's peak and hours over rating, busbars out of band, substations above firm capacity, each element's agreement
with the source's own model), one element's month-by-hour grid, and a branch's year against its "before".

A run file is what `timeseries.run_year` writes. Which runs a grid has, and their limits in plain words, are the grid's
(`RunCatalogue`, from `GridSource.run_catalogue()`; NGED's is `nged_runs.CATALOGUE`); this module is the general
machinery. Reads local files only; nothing here solves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import pandapower.topology as top

from .config import LINE_LOADING_MAX_PCT, TRAFO_LOADING_MAX_PCT
from .network import build_base_net, voltage_limits
from .types import RunBus, RunChange, RunComparison, RunElement, RunGrid, RunInfo, RunSubstation, RunSummary, RunWorst

BRANCH_PREFIX = "branch-"
UNRELIABLE_SHARE = 0.01  # a node whose reactive input the screen flags on more than this share of the year is unreliable


@dataclass(frozen=True)
class RunCatalogue:
    """A grid's year runs: what each is, which grown years a branch's year can be run on, and the limits in plain words."""

    runs: dict[str, tuple]  # run id -> (file, label, kind, year, pathway, how to make it)
    bases: tuple[str, ...]  # the grown years a branch's year can be run on, each its "before"
    measured_flows: str  # the measured flows' folder, inside the run folder
    reference: str  # the run every element's agreement with the source's model is judged on (the best-closing year)
    source: str  # the source's name, as the labels say it ("flow agrees with NGED's model")
    measured_limits: str
    grown_limits: str
    branch_year_limits: str  # added to a grown year's limits for a branch's year
    notes: dict[str, str] = field(default_factory=dict)  # a run's own caveat, added to its kind's limits
    screen_from: dict[str, str] = field(default_factory=dict)  # a run whose file carries no screen flags -> the run whose flags stand for it


def branch_run_id(key: str) -> str:
    """The run id of a branch's year, from its cache key (what it was solved for)."""
    return BRANCH_PREFIX + key[:20]


def _clusters(meta) -> dict[int, int]:
    cl: dict[int, int] = {}
    for k, m in meta["notes"]["multi_bus_clusters"].items():
        for b in m:
            cl[int(b)] = int(k)
    return cl


def _rating_mva(z, net, kind: str, i: int) -> np.ndarray:
    """An element's rating in force each half-hour (MVA): a line's winter rating x its season's ratio, a transformer's."""
    if kind == "trafo":
        return np.full(len(z["times"]), float(net.trafo.at[i, "sn_mva"]))
    j = list(z["line_ids"]).index(i)
    ln = net.line.loc[i]
    base = float(ln.max_i_ka) * float(net.bus.at[int(ln.from_bus), "vn_kv"]) * np.sqrt(3) * float(ln.get("parallel", 1) or 1)
    return base * np.array([z[f"line_ratio_{s}"][j] for s in z["season"].astype(str)])


class RunFiles:
    """The run files in one folder, read for the year view, under a grid's catalogue and network (`net_factory`)."""

    def __init__(self, folder, catalogue: RunCatalogue, net_factory=build_base_net):
        self.folder = Path(folder)
        self.cat = catalogue
        self.net_factory = net_factory
        self._agreement: tuple | None = None  # (reference file's mtime, labels): recomputed when the file changes

    # ---- what a run is ------------------------------------------------------------------------------------
    def file_of(self, run_id: str) -> str:
        """A run's file name: the catalogue's, or a branch's year's own; KeyError for neither."""
        if run_id in self.cat.runs:
            return self.cat.runs[run_id][0]
        if run_id.startswith(BRANCH_PREFIX) and run_id[len(BRANCH_PREFIX):].isalnum():
            return f"{run_id}.npz"
        raise KeyError(run_id)

    def path(self, run_id: str) -> Path:
        return self.folder / self.file_of(run_id)

    def known(self, run_id: str) -> bool:
        """A catalogued run, or a branch's year whose file exists."""
        try:
            f = self.path(run_id)
        except KeyError:
            return False
        return run_id in self.cat.runs or f.exists()

    def info(self, run_id: str) -> RunInfo:
        cat = self.cat
        if run_id not in cat.runs:  # a branch's year: what it is lives in its file
            with np.load(self.path(run_id)) as z:
                a = json.loads(str(z["meta"])).get("about", {})
            return RunInfo(run_id=run_id, label=a.get("label", run_id), kind="grown", year=int(a.get("year", 0)), pathway=a.get("pathway"),
                           available=True, make="run it from the planner (Year runs tab)", limits=cat.grown_limits + cat.branch_year_limits,
                           before=a.get("before"), branch_id=a.get("branch_id"))
        f, label, kind, year, pathway, make = cat.runs[run_id]
        return RunInfo(run_id=run_id, label=label, kind=kind, year=year, pathway=pathway, available=(self.folder / f).exists(),
                       make=make, limits=(cat.grown_limits if kind == "grown" else cat.measured_limits) + cat.notes.get(run_id, ""),
                       base=run_id in cat.bases)

    def catalogue(self) -> list[RunInfo]:
        return [self.info(r) for r in self.cat.runs]

    def _load(self, run_id: str):
        z = np.load(self.path(run_id))
        return z, json.loads(str(z["meta"]))

    # ---- agreement with the source's own model: a property of the network ----------------------------------
    def compare_with_source(self) -> dict[tuple[str, int], tuple[str, float | None, float | None, int]]:
        """Each line and transformer's agreement with the source's own model, by the measured year's rules, on the
        catalogue's reference run (the best-closing year). A meshed or backbone element agrees when its
        flow is within 5 % of its rating on 95 % of solved half-hours with the same direction on 95 % (where either side
        carries over 1 MW); a radial one when every solved half-hour is within 0.5 MW + 2 %. A radial element whose far side
        holds only injections taken from the source's own flows carries them by construction ("input"); beyond a cluster
        held at 0, or whose flow in the source's model tracks that held injection (|correlation| >= 0.9), it is not
        compared. Returns (kind, id) -> (label, offset MW, offset %, the year the label comes from). Input reliability is
        a separate matter (`unreliable_buses`). Kept until a reference file changes."""
        ref = self.cat.reference
        mtime = self.path(ref).stat().st_mtime
        if self._agreement is None or self._agreement[0] != mtime:
            year = int(self.cat.runs[ref][3])
            self._agreement = (mtime, {k: (*v, year) for k, v in self._compare_on(ref).items()})
        return self._agreement[1]

    def _compare_on(self, ref: str) -> dict:
        src = self.cat.source
        z, meta = self._load(ref)
        net = self.net_factory()
        conv = z["converged"]
        lp = pd.DataFrame(z["line_p_mw"], columns=z["line_ids"])[conv]
        tp = pd.DataFrame(z["trafo_p_mw"], columns=z["trafo_ids"])[conv]
        bmw = pd.DataFrame(z["branch_mw"], columns=list(z["branch_cols"]))[conv]
        season = z["season"][conv]
        seasons = ("winter", "intermediate_cool", "intermediate_warm", "summer")
        # each line's rating in force, per solved half-hour (MVA): its winter rating x its season's ratio
        ratio = np.array([z[f"line_ratio_{s}"] for s in seasons])  # season x line
        s_idx = np.array([seasons.index(str(s)) for s in season])
        vn = net.bus.vn_kv
        winter_mva = np.sqrt(3) * vn[net.line.from_bus].to_numpy() * net.line.max_i_ka.to_numpy()
        line_rating = pd.DataFrame(ratio[s_idx] * winter_mva, columns=z["line_ids"], index=lp.index)
        cl = _clusters(meta)
        c_of = lambda b: cl.get(int(b), int(b))  # noqa: E731
        notes = meta["notes"]
        metered = {c_of(b) for b in notes["metered"]}
        derived = {c_of(b) for b in notes["derived"]}
        held = {int(k) for k in notes["held_at_zero"]}
        slack = {int(b) for b in net.ext_grid.bus}
        g = top.create_nxgraph(net, multi=True, include_switches=True)  # a closed bus-bus switch (a connector) joins its buses
        G = nx.Graph()
        for u, v, _k in g.edges(keys=True):
            G.add_edge(u, v, n=G[u][v]["n"] + 1 if G.has_edge(u, v) else 1)

        def far_side(a: int, b: int) -> set[int] | None:
            """The buses beyond a radial (bridge) element, away from the slack; None when it is meshed."""
            if G[a][b]["n"] > 1:
                return None
            H = G.copy()
            H.remove_edge(a, b)
            if nx.has_path(H, a, b):
                return None
            side = nx.node_connected_component(H, b)
            return set(nx.node_connected_component(H, a)) if side & slack else set(side)

        # an element whose flow in the source's model tracks a cluster held at 0 here carries that input (meshed or not)
        up = pd.DataFrame(z["unplaced_p"], columns=list(z["unplaced_cols"]))[conv]
        held_series = [up[c] for c in up.columns if c.startswith("held@") and float(up[c].std()) > 0]
        out: dict = {}
        groups: dict[tuple, list[str]] = {}
        for c, m in meta["branch_map"].items():
            groups.setdefault((m["kind"], tuple(m["ids"])), []).append(c)
        for (kind, ids), cols in groups.items():
            tab = net.line if kind == "line" else net.trafo
            if kind == "line" and not bool(tab.loc[list(ids), "in_service"].all()):
                continue  # a connector or an open point: out of service, carries nothing, not shown as an element
            a, b = (int(tab.at[ids[0], "from_bus"]), int(tab.at[ids[0], "to_bus"])) if kind == "line" else (int(tab.at[ids[0], "hv_bus"]), int(tab.at[ids[0], "lv_bus"]))
            side = far_side(a, b)
            s0 = meta["branch_map"][cols[0]]["sign"]
            eng = (lp if kind == "line" else tp)[list(ids)].sum(axis=1) * s0
            ng = sum(bmw[c] * (meta["branch_map"][c]["sign"] * s0) for c in cols)
            if kind == "line":
                rating = line_rating[list(ids)].sum(axis=1)
            else:
                rating = pd.Series(float(net.trafo.loc[list(ids), "sn_mva"].sum()), index=eng.index)
            d = eng - ng
            clusters = {c_of(x) for x in side} if side is not None else set()
            held_corr = max((abs(float(np.corrcoef(ng, h)[0, 1])) for h in held_series if float(ng.std()) > 0), default=0.0)
            if (side is not None and clusters & held) or held_corr >= 0.9:
                lab, ok = "not compared (input held at 0)", None
            elif side is not None and not (clusters & metered) and clusters & derived:
                lab, ok = f"input: carries {src}'s own flow by construction", None
            elif side is not None:
                ok = bool((d.abs() <= 0.5 + 0.02 * ng.abs()).all())
                lab = None
            else:
                big = (eng.abs() > 1) | (ng.abs() > 1)
                same = float((np.sign(eng[big]) == np.sign(ng[big])).mean()) if big.any() else 1.0
                ok = float((d.abs() <= 0.05 * rating).mean()) >= 0.95 and same >= 0.95
                lab = None
            if lab is None:
                lab = f"flow agrees with {src}'s model" if ok else "flow differs"
            off_mw = round(float(d.median() * s0), 2) if lab == "flow differs" else None
            off_pct = round(float((d / rating * 100).median() * s0), 1) if lab == "flow differs" else None
            for i in ids:
                out[(kind, int(i))] = (lab, off_mw, off_pct)
        return out

    # ---- input reliability: a property of the flows a run is built from ----------------------------------
    def unreliable_buses(self, run_id: str) -> set[int]:
        """The busbars whose reactive input the screen flags on more than UNRELIABLE_SHARE of the year, in the flows this
        run is built from. Every run file carries the screen's flags for its own source flows (set when they are mapped,
        before any growth); a file made before the screen existed takes them from `screen_from`."""
        z, meta = self._load(self.cat.screen_from.get(run_id, run_id))
        if "q_flags" not in z.files:
            return set()
        cl = _clusters(meta)
        qf = pd.DataFrame(z["q_flags"], columns=meta["anchor_buses"])
        bad = {cl.get(int(a), int(a)) for a in qf.columns if float((qf[a] > 0).mean()) > UNRELIABLE_SHARE}
        return {b for b, c in cl.items() if c in bad} | {b for b in bad}

    # ---- a run --------------------------------------------------------------------------------------------
    def summarise(self, run_id: str) -> RunSummary:
        """A run's summary for the year view."""
        z, meta = self._load(run_id)
        net = self.net_factory()
        T = pd.DatetimeIndex(pd.to_datetime(z["times"]))
        labels = self.compare_with_source()
        bad_buses = self.unreliable_buses(run_id)
        not_in = f"not compared (not in {self.cat.source}'s file)"
        elements = []
        for kind, key, limit in (("line", "line_pct", LINE_LOADING_MAX_PCT), ("trafo", "trafo_pct", TRAFO_LOADING_MAX_PCT)):
            pct = pd.DataFrame(z[key], columns=z[f"{kind}_ids"])
            for i in pct.columns:
                x = pct[i]
                if x.isna().all() or (kind == "line" and not bool(net.line.at[int(i), "in_service"])):
                    continue  # no figure, or a line out of service (an open point, a connector): it carries nothing
                lab, om, op, year = labels.get((kind, int(i)), (not_in, None, None, None))
                finding = True
                # a transformer feeding a node whose reactive input is unreliable in this run's flows: shown, not a finding
                if kind == "trafo" and int(net.trafo.at[int(i), "lv_bus"]) in bad_buses:
                    lab, om, op, finding = "reactive input unreliable: not a finding", None, None, False
                elements.append(RunElement(kind=kind, element_id=int(i), peak_pct=round(float(x.max()), 1), peak_at=str(T[int(x.idxmax())]),
                                           h80=float((x >= 80).sum() / 2), h90=float((x >= 90).sum() / 2), h100=float((x > limit).sum() / 2),
                                           label=lab, offset_mw=om, offset_pct=op, finding=finding, label_year=year))
        vm = pd.DataFrame(z["vm"], columns=z["bus_ids"])
        vmin, vmax = voltage_limits(net)
        buses = []
        for b in vm.columns:
            v = vm[b]
            out = (v < float(vmin[b])) | (v > float(vmax[b]))
            if out.any():
                buses.append(RunBus(bus_id=int(b), hours_outside=float(out.sum() / 2), vmin_pu=round(float(v.min()), 4),
                                    vmax_pu=round(float(v.max()), 4), finding=int(b) not in bad_buses))
        # primary substations (below 132 kV): each published firm capacity against the MVA through its transformers
        tpct = pd.DataFrame(z["trafo_pct"], columns=z["trafo_ids"])
        cl = _clusters(meta)
        subs = []
        for (region, firm), grp in net.load[net.load.firm_mva.fillna(0) > 0].groupby(["region", "firm_mva"]):
            bs = {cl.get(int(b), int(b)) for b in grp.bus}
            site = [int(x) for x in net.bus.index if cl.get(int(x), int(x)) in bs]
            tr = [int(i) for i in net.trafo.index if int(net.trafo.at[i, "lv_bus"]) in site and float(net.bus.at[int(net.trafo.at[i, "hv_bus"]), "vn_kv"]) < 132]
            if not tr or set(site) & bad_buses:
                continue
            mva = (tpct[tr] / 100 * net.trafo.loc[tr, "sn_mva"].to_numpy()).sum(axis=1)
            hours = float((mva > firm).sum() / 2)
            if hours > 0:
                subs.append(RunSubstation(name=str(region), bus_id=int(grp.bus.iloc[0]), firm_mva=float(firm), peak_mva=round(float(mva.max()), 2),
                                          peak_at=str(T[int(mva.idxmax())]), hours_above_firm=hours))
        elements.sort(key=lambda e: (-e.h100, -e.peak_pct))
        return RunSummary(info=self.info(run_id), half_hours=int(len(T)), solved=int(z["converged"].sum()), collapsed=int(z["collapsed"].sum()) if "collapsed" in z else 0, fingerprint=str(meta.get("fingerprint", "")),
                          elements=elements, buses=sorted(buses, key=lambda b: -b.hours_outside),
                          substations=sorted(subs, key=lambda s: -s.hours_above_firm), check=self.cat.measured_limits)

    def month_hour_grid(self, run_id: str, kind: str, element_id: int) -> RunGrid:
        """When one element is over in a run: hours above its rating (a line or transformer) or outside its band (a
        busbar) per month and hour of day, each half-hour counted at its own start."""
        z, _meta = self._load(run_id)
        start = pd.DatetimeIndex(pd.to_datetime(z["times"])) - pd.Timedelta(minutes=30)
        if kind == "bus":
            vmin, vmax = voltage_limits(self.net_factory())
            v = pd.DataFrame(z["vm"], columns=z["bus_ids"])[element_id]
            over = (v < float(vmin[element_id])) | (v > float(vmax[element_id]))
        else:
            x = pd.DataFrame(z[f"{kind}_pct"], columns=z[f"{kind}_ids"])[element_id]
            over = x > (LINE_LOADING_MAX_PCT if kind == "line" else TRAFO_LOADING_MAX_PCT)
        grid = np.zeros((12, 24))
        np.add.at(grid, (start.month.to_numpy() - 1, start.hour.to_numpy()), over.to_numpy().astype(float) / 2)
        return RunGrid(run_id=run_id, kind=kind, element_id=element_id, hours=grid.round(1).tolist())

    # ---- a branch's year against its "before" -------------------------------------------------------------
    def compare(self, run_id: str, before: RunSummary, after: RunSummary) -> RunComparison:
        """A branch's year against its "before" (both summaries as `summarise` gives them): every line and transformer
        whose hours above rating change or whose peak moves by more than 5 points, longest increase first; the MVAh above
        rating on the first of them; busbars and substations whose hours change; the boundary exchange; what the branch
        put in."""
        z, meta = self._load(run_id)
        zb, _ = self._load(before.info.run_id)
        net = self.net_factory()
        b = {(e.kind, e.element_id): e for e in before.elements}
        changed = []
        for e in after.elements:
            o = b.get((e.kind, e.element_id))
            if o is None or (e.h100 == o.h100 and abs(e.peak_pct - o.peak_pct) <= 5):
                continue
            changed.append(RunChange(kind=e.kind, element_id=e.element_id, peak_before=o.peak_pct, peak_after=e.peak_pct,
                                     h90_before=o.h90, h90_after=e.h90, h100_before=o.h100, h100_after=e.h100))
        changed.sort(key=lambda c: (-(c.h100_after - c.h100_before), -c.peak_after))
        worst = None
        first = next((c for c in changed if c.h100_after > c.h100_before), None)
        if first is not None:
            pct = z[f"{first.kind}_pct"][:, list(z[f"{first.kind}_ids"]).index(first.element_id)]
            limit = LINE_LOADING_MAX_PCT if first.kind == "line" else TRAFO_LOADING_MAX_PCT
            over = np.clip(np.nan_to_num(pct) - limit, 0, None) / 100.0 * _rating_mva(z, net, first.kind, first.element_id)
            worst = RunWorst(kind=first.kind, element_id=first.element_id, hours_above=float((over > 0).sum() / 2),
                             mvah_above=round(float(over.sum() / 2), 0), largest_mva_above=round(float(over.max()), 1))
        vb = {x.bus_id: x.hours_outside for x in before.buses}
        va = {x.bus_id: x.hours_outside for x in after.buses}
        buses = [[k, vb.get(k, 0.0), va.get(k, 0.0)] for k in sorted(set(vb) | set(va)) if vb.get(k, 0.0) != va.get(k, 0.0)]
        fb = {x.name: x.hours_above_firm for x in before.substations}
        fa = {x.name: x.hours_above_firm for x in after.substations}
        subs = [[k, fb.get(k, 0.0), fa.get(k, 0.0)] for k in sorted(set(fb) | set(fa)) if fb.get(k, 0.0) != fa.get(k, 0.0)]
        slack = {int(x) for x in net.ext_grid.bus}
        conns = meta.get("connections", [])
        ins = set(meta.get("in_service", []))
        cp = np.asarray(z["conn_p_mw"], float)
        out = cp.sum(axis=1) if cp.ndim == 2 and cp.shape[1] else np.zeros(1)
        ex_b, ex_a = -np.asarray(zb["p_ext_mw"], float), -np.asarray(z["p_ext_mw"], float)
        return RunComparison(
            run_id=run_id, before=before.info.run_id, year=after.info.year, in_service=sorted(ins),
            voltage_control_at_unity=meta.get("voltage_control_at_unity", []),
            on_slack=[c["request_id"] for c in conns if c["request_id"] in ins and int(c["bus_id"]) in slack],
            storage=[c["request_id"] for c in conns if c["request_id"] in ins and (c.get("technology") or "").lower() in ("battery", "hybrid")],
            output_peak_mw=round(float(out.max()), 1), output_energy_gwh=round(float(out[out > 0].sum() / 2 / 1000), 1),
            changed=changed[:40], worst=worst, buses=buses, substations=subs,
            export_peak_mw=[round(float(np.nanmax(ex_b)), 1), round(float(np.nanmax(ex_a)), 1)],
            import_peak_mw=[round(float(np.nanmax(-ex_b)), 1), round(float(np.nanmax(-ex_a)), 1)])
