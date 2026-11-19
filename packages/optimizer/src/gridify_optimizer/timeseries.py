"""The measured year (step 1): a year of measured half-hours through the same AC power flow as the plan years, so each
line's and transformer's loading, each busbar's voltage and the GSP's flow are known half-hour by half-hour.

`run_year` takes the grid's measured year (`GridSource.measured_year`), solves every half-hour IN TIME ORDER with
`network.solve_snapshot` (tap positions carry from one half-hour to the next, as a real tap changer's do, so the
result depends on the order: never split a year across workers), and saves the arrays to one `.npz` file that the
report reads. Lines are judged against the rating of NGED's season for the month (`config.RATING_SEASON_BY_MONTH`),
transformers against their single rating; what counts as a breach is the engine's own limits, applied by the report.

    python -m gridify_optimizer.timeseries <flows folder> <out.npz> [published|screened|unity] [first row] [last row]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pandapower as pp

from .config import BATTERY_YEAR_RULE, RATING_SEASON_BY_MONTH, SEASON_RATIO_COLUMN, WIND_OFFSHORE_MIN_KV
from .network import inject_connection, solve_snapshot
from .sources import default_source


def season_of(times: pd.DatetimeIndex) -> np.ndarray:
    """NGED's rating season of each half-hour (labelled by its end, so its month is the month it starts in)."""
    return np.array([RATING_SEASON_BY_MONTH[m] for m in (times - pd.Timedelta(minutes=30)).month])


def _import(c) -> float:
    return float(c.import_mw if c.import_mw is not None else c.rating_mw or 0.0)


def _in(hours: np.ndarray, window: tuple[float, float]) -> np.ndarray:
    return (hours >= window[0]) & (hours < window[1])


def _battery(c, shapes, hours, kv) -> np.ndarray:
    """The placeholder day (config.BATTERY_YEAR_RULE): charging, then exporting, idle otherwise."""
    return np.where(_in(hours, BATTERY_YEAR_RULE["charge"]), -_import(c),
                    np.where(_in(hours, BATTERY_YEAR_RULE["export"]), float(c.rating_mw), 0.0))


def _shape(kind: str):
    return lambda c, shapes, hours, kv: float(c.rating_mw) * shapes[kind].to_numpy(float)


# a new connection's MW every half-hour (export positive), per technology (README register: "Year shape"); a technology
# not named runs firm at its rating
YEAR_DISPATCH = {
    "solar": _shape("solar"),
    "wind": lambda c, shapes, hours, kv: _shape("wind_offshore" if kv >= WIND_OFFSHORE_MIN_KV else "wind_onshore")(c, shapes, hours, kv),
    "battery": _battery,
    "hybrid": lambda c, shapes, hours, kv: np.clip(_shape("solar")(c, shapes, hours, kv) + _battery(c, shapes, hours, kv),
                                                   -_import(c), float(c.rating_mw)),
    "demand": lambda c, shapes, hours, kv: np.full(len(hours), -_import(c)),
    "electrolyser": lambda c, shapes, hours, kv: np.full(len(hours), -_import(c)),
}


def _firm(c, shapes, hours, kv) -> np.ndarray:
    return np.full(len(hours), float(c.rating_mw))


def _connections(net, year, connections, plan_year: int) -> tuple[list[int], np.ndarray, np.ndarray, dict]:
    """Inject the connections in service by `plan_year` (`years.in_service`, the plan years' rule) as `sgen`s and give
    each its MW and MVAr every half-hour. A voltage-controlled connection runs at unity: the half-hourly solve takes
    fixed P and Q (`solve_snapshot`). A fixed power factor gives Q = |P| x `q_per_p`, the same sign exporting or
    importing: the plan-year cases' convention (`network._follow_power_factor`), one definition for both. Hours are the
    run file's own clock, a fixed one (no clock change in the 2024 series; most likely UTC)."""
    from .years import in_service
    hours = np.asarray((year.times - pd.Timedelta(minutes=30)).hour + (year.times - pd.Timedelta(minutes=30)).minute / 60.0)
    ids, ps, qs, unity = [], [], [], []
    for c in in_service(connections, plan_year):
        if c.control is not None and c.control.mode == "voltage":
            unity.append(c.request_id)
            c = c.model_copy(update={"control": None})
        _, idx = inject_connection(net, c)
        kv = float(net.bus.at[int(c.bus_id), "vn_kv"])
        p = YEAR_DISPATCH.get((c.technology or "").lower(), _firm)(c, year.shapes, hours, kv)
        k = float(net.sgen.at[idx, "q_per_p"]) if "q_per_p" in net.sgen.columns and pd.notna(net.sgen.at[idx, "q_per_p"]) else 0.0
        ids.append(int(idx)); ps.append(p); qs.append(np.abs(p) * k)
    shape = (len(year.times), len(ids))
    P = np.column_stack(ps) if ids else np.zeros(shape)
    Q = np.column_stack(qs) if ids else np.zeros(shape)
    return ids, P, Q, {"in_service": [c.request_id for c in in_service(connections, plan_year)], "voltage_control_at_unity": unity}


PROGRESS_EVERY = 50  # half-hours between progress reports: also how soon a job's stop is noticed (a few seconds)


def growth_scale(folder, year: int, pathway: str, *, source=None, net_factory=None, reactive: str = "screened") -> dict[int, float]:
    """A grown year's multipliers: per metered anchor bus, the engine's growth multiplier for `year` on `pathway`
    (`network.per_load_growth`) over the loads its cluster holds, weighted by each load's own LTDS maximum."""
    from .network import per_load_growth
    source = source or default_source()
    net = (net_factory or source.build_net)()
    y = source.measured_year(folder, net, reactive)
    cl = {int(b): int(b) for b in net.bus.index}
    for k, m in y.notes["multi_bus_clusters"].items():
        for b in m:
            cl[int(b)] = int(k)
    g = per_load_growth(net, pathway, year)
    out = {}
    for a in y.notes["metered"]:
        members = [b for b in net.bus.index if cl.get(int(b), int(b)) == cl.get(int(a), int(a))]
        ld = net.load[net.load.bus.isin(members)]
        w = ld["peak_mw"].astype(float)
        out[int(a)] = float((g[ld.index] * w).sum() / w.sum()) if len(ld) and w.sum() > 0 else 1.0
    return out


def run_year(folder, out, *, source=None, net_factory=None, rows: slice | None = None, progress=None,
             reactive: str = "published", scale: dict[int, float] | None = None, connections=None,
             plan_year: int | None = None, about: dict | None = None) -> Path:
    """`scale`: a multiplier per anchor bus on its MW and MVAr (a grown year: the same 2024 shape at a future year's
    demand); buses not named keep 1. `connections` (a branch's, `types.Connection`) with `plan_year`: those in service by
    that year are added, each on its technology's 2024 shape (`YEAR_DISPATCH`). The default reproduces the measured year
    exactly. `about` is stored in the file's meta as it is (what the run is, for the year view)."""
    source = source or default_source()
    net = (net_factory or source.build_net)()
    year = source.measured_year(folder, net, reactive)
    # every load and generator the network carries is already inside the measured figures: they are left at 0, and each
    # cluster's measured injection sits on one load added at its anchor bus
    cols = list(year.bus_p.columns)
    added = [int(pp.create_load(net, int(b), p_mw=0.0, name=f"measured@{int(b)}")) for b in cols]
    no_sgen = pd.Series(dtype=float)
    if connections and plan_year is None:
        raise ValueError("connections need the plan year they are judged in")
    sg_ids, sg_p, sg_q, sg_meta = _connections(net, year, connections or [], plan_year or 0)
    ratio = {s: (None if c is None else net.line[c].astype(float)) for s, c in SEASON_RATIO_COLUMN.items()}
    rows = rows or slice(0, len(year.times))
    ks = range(*rows.indices(len(year.times)))
    seasons = season_of(year.times)
    n, nl, nt, nb = len(ks), len(net.line), len(net.trafo), len(net.bus)
    arr = {"line_pct": np.full((n, nl), np.nan, np.float32), "trafo_pct": np.full((n, nt), np.nan, np.float32),
           "vm": np.full((n, nb), np.nan, np.float32), "line_p_mw": np.full((n, nl), np.nan, np.float32),
           "trafo_p_mw": np.full((n, nt), np.nan, np.float32), "p_ext_mw": np.full(n, np.nan, np.float64),
           "converged": np.zeros(n, bool), "collapsed": np.zeros(n, bool)}
    p_all, q_all = year.bus_p.to_numpy(float), year.bus_q.to_numpy(float)
    if scale:
        f = np.array([float(scale.get(int(b), 1.0)) for b in cols])
        p_all, q_all = p_all * f, q_all * f
    t0 = time.perf_counter()
    for j, k in enumerate(ks):  # time order: the taps carry over
        r = solve_snapshot(net, pd.Series(p_all[k], index=added), pd.Series(q_all[k], index=added),
                           pd.Series(sg_p[k], index=sg_ids) if sg_ids else no_sgen, pd.Series(sg_q[k], index=sg_ids) if sg_ids else no_sgen,
                           rating_ratio=ratio[seasons[k]])
        if r is not None and "collapse" in r:  # a voltage collapse: not solved, counted apart from non-convergence
            arr["collapsed"][j] = True
        elif r is not None:
            arr["converged"][j] = True
            arr["line_pct"][j], arr["trafo_pct"][j], arr["vm"][j] = r["line_pct"], r["trafo_pct"], r["vm"]
            arr["line_p_mw"][j], arr["trafo_p_mw"][j], arr["p_ext_mw"][j] = r["line_p_mw"], r["trafo_p_mw"], r["p_ext_mw"]
        if progress and (j + 1) % PROGRESS_EVERY == 0:
            progress(j + 1, n, time.perf_counter() - t0)
    meta = {"about": about or {}, "reactive": reactive, "scale": {int(k): float(v) for k, v in (scale or {}).items()}, "plan_year": plan_year,
            "connections": [c.model_dump(mode="json") for c in (connections or [])], **sg_meta, "source": source.id, "fingerprint": source.fingerprint(), "rows": [ks.start, ks.stop], "seconds": round(time.perf_counter() - t0, 1),
            "inputs_per_half_hour": len(cols), "anchor_buses": [int(b) for b in cols], "branch_map": year.branch_map,
            "node_bus": year.node_bus, "notes": year.notes, "solved_in": "time order (tap positions carry over)"}
    out = Path(out)
    np.savez_compressed(out, times=np.array(year.times[ks.start:ks.stop].astype(str), dtype=str), season=seasons[ks.start:ks.stop].astype(str),
                        line_ids=net.line.index.to_numpy(), trafo_ids=net.trafo.index.to_numpy(), bus_ids=net.bus.index.to_numpy(),
                        **{f"line_ratio_{s}": (np.ones(nl) if c is None else net.line[c].to_numpy(float)) for s, c in SEASON_RATIO_COLUMN.items()},
                        bus_p=p_all[ks.start:ks.stop], branch_mw=year.branch_mw.iloc[ks.start:ks.stop].to_numpy(np.float32),
                        branch_cols=np.array(year.branch_mw.columns, dtype=str), node_flags=year.node_flags.iloc[ks.start:ks.stop].to_numpy(),
                        node_cols=np.array(year.node_flags.columns, dtype=str),
                        bus_q=q_all[ks.start:ks.stop], q_flags=year.q_flags.iloc[ks.start:ks.stop].to_numpy(),
                        unplaced_p=year.unplaced_p.iloc[ks.start:ks.stop].to_numpy(float),
                        unplaced_cols=np.array(year.unplaced_p.columns, dtype=str), conn_p_mw=sg_p[ks.start:ks.stop],
                        meta=json.dumps(meta), **arr)
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    mode = a[2] if len(a) >= 3 else "published"
    sl = slice(int(a[3]), int(a[4])) if len(a) >= 5 else None
    p = run_year(a[0], a[1], rows=sl, reactive=mode, progress=lambda j, n, s: print(f"{j}/{n} half-hours, {s:.0f} s", flush=True))
    print("saved", p)
