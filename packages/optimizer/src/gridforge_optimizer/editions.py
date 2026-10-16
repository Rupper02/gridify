"""Editions and change detection: "what changed between network@v41 and network@v42?"

Two sources of change, both deterministic and pure (no I/O here):

* **LTDS edition change-set.** NGED flags every LTDS row New / Updated / Unchanged / Removed
  against its previous publication. That lets us reconstruct the previous edition (drop the New
  rows, keep the Removed ones) and diff it against the current one (drop the Removed rows) at
  three levels: the raw rows, the built model (buses / circuits / transformers / demand), and the
  physics (today's power flow on each edition: loadings, voltages, GSP export).
  Caveat, stated in the output: Updated rows carry their *current* values in both editions, because
  NGED does not publish the old ones, so an Updated rating/demand change shows as a flag, not a delta.

* **ECR edition diff.** NGED republishes the Embedded Capacity Register monthly without a stable
  reference per site. `diff_ecr_editions` keys sites on their published identity (site name,
  location, energy source, connection voltage) and reports what was added, withdrawn, connected,
  or changed in capacity or target date between two fetches.
"""

from __future__ import annotations

from collections import Counter

from .nged import EDITION_CURRENT, EDITION_PREVIOUS, LtdsTables, _ctx, _num, _substation

# which column carries NGED's change flag, per table
STATUS_COLUMN = {"circuit": "Circuit Status", "t2a": "Status", "demand": "Status", "node": "Status"}
CHANGE_KINDS = ("new", "removed", "updated")


def status_counts(tables: LtdsTables) -> dict[str, dict[str, int]]:
    """Per table, how many rows NGED marked New / Updated / Unchanged / Removed."""
    out: dict[str, dict[str, int]] = {}
    for table, col in STATUS_COLUMN.items():
        c = Counter(str(r.get(col) or "unknown").strip().lower() for r in tables.get(table, []))
        out[table] = dict(sorted(c.items()))
    return out


def _row_change(table: str, r: dict) -> dict | None:
    """One human-readable change row for a New / Updated / Removed LTDS row, or None if unchanged."""
    st = str(r.get(STATUS_COLUMN[table]) or "").strip().lower()
    if st not in CHANGE_KINDS:
        return None
    if table == "circuit":
        rating = _num(r.get("Winter"))
        return {
            "table": table, "change": st, "key": f"{r.get('Node 1')} — {r.get('Node 2')} ({r.get('Circuit Code')})",
            "description": f"{r.get('Equipment') or 'Circuit'} at {r.get('Operating Voltage (kV)')} kV"
                           + (f", {rating:.0f} A winter rating" if rating else ""),
            "value": rating,
        }
    if table == "t2a":
        sn = _num(r.get("Nominal Rating"))
        return {
            "table": table, "change": st, "key": f"{r.get('Node 1')} — {r.get('Node 2')}",
            "description": f"{r.get('Operating Voltage 1')}/{r.get('Operating Voltage 2')} kV transformer"
                           + (f", {sn:g} MVA" if sn else ""),
            "value": sn,
        }
    if table == "demand":
        mw = _num(r.get("Current Year Max Demand"))
        site = (r.get("Primary Substation") or "").strip()
        return {
            "table": table, "change": st, "key": f"{site or '-'} @ {r.get('Node')}",
            "description": f"demand point{' at ' + site if site and site != '-' else ''}"
                           + (f", {mw:g} MW maximum demand" if mw is not None else ""),
            "value": mw,
        }
    if table == "node":
        return {"table": table, "change": st, "key": str(r.get("Code")), "description": f"busbar {r.get('Name')}", "value": None}
    return None


def change_rows(tables: LtdsTables) -> list[dict]:
    """Every New / Updated / Removed row across the LTDS tables, described."""
    rows: list[dict] = []
    for table in STATUS_COLUMN:
        for r in tables.get(table, []):
            c = _row_change(table, r)
            if c:
                rows.append(c)
    order = {"removed": 0, "new": 1, "updated": 2}
    rows.sort(key=lambda c: (c["table"], order[c["change"]], c["key"]))
    return rows


def _model_summary(ctx: dict) -> dict:
    """Element counts, demand and transformer capacity of a built edition."""
    net = ctx["net"]
    by_sub: dict[str, float] = {}
    for _, ld in net.load.iterrows():
        sub = _substation(str(ld["name"] or "")) or str(ld["name"] or "-")
        by_sub[sub] = by_sub.get(sub, 0.0) + float(ld["p_mw"])
    return {
        "buses": int(len(net.bus)), "lines": int(len(net.line)), "transformers": int(len(net.trafo)),
        "loads": int(len(net.load)), "demand_mw": round(float(net.load["p_mw"].sum()), 2),
        "transformer_mva": round(float(net.trafo["sn_mva"].sum()), 1),
        "demand_by_substation_mw": {k: round(v, 3) for k, v in sorted(by_sub.items())},
    }


def _physics(ctx: dict) -> dict:
    """Today's power flow on an edition (existing fleet, today's demand, both study cases)."""
    import copy

    from .network import feasibility

    net = copy.deepcopy(ctx["net"])
    ok, breaches, m = feasibility(net)
    return {
        "feasible": bool(ok),
        "binding": breaches[0].message if breaches else None,
        "worst_line_pct": round(float(m.get("max_line_pct", 0.0)), 1) if m else None,
        "worst_trafo_pct": round(float(m.get("max_trafo_pct", 0.0)), 1) if m else None,
        "min_vm_pu": round(float(m.get("min_vm", 0.0)), 4) if m else None,
        "max_vm_pu": round(float(m.get("max_vm", 0.0)), 4) if m else None,
        "gsp_export_mw": m.get("gsp_export_mw") if m else None,
    }


def _delta(a: dict, b: dict, keys: tuple[str, ...]) -> dict:
    out = {}
    for k in keys:
        if a.get(k) is None or b.get(k) is None:
            out[k] = None
        else:
            out[k] = round(float(b[k]) - float(a[k]), 4)
    return out


def edition_changeset(tables: LtdsTables) -> dict:
    """The full change-set between NGED's previous LTDS edition and the current one.

    Returns {"status_counts", "rows", "model": {previous, current, delta, demand_changes},
    "physics": {previous, current, delta}, "caveats"}.
    """
    prev = _ctx(tables, EDITION_PREVIOUS)
    cur = _ctx(tables, EDITION_CURRENT)
    mp, mc = _model_summary(prev), _model_summary(cur)
    subs = set(mp["demand_by_substation_mw"]) | set(mc["demand_by_substation_mw"])
    demand_changes = []
    for sub in sorted(subs):
        a = mp["demand_by_substation_mw"].get(sub, 0.0)
        b = mc["demand_by_substation_mw"].get(sub, 0.0)
        if abs(b - a) > 1e-6:
            demand_changes.append({"substation": sub, "previous_mw": round(a, 3), "current_mw": round(b, 3), "delta_mw": round(b - a, 3)})
    demand_changes.sort(key=lambda d: -abs(d["delta_mw"]))
    pp, pc = _physics(prev), _physics(cur)
    counts = status_counts(tables)
    rows = change_rows(tables)
    return {
        "status_counts": counts,
        "n_changes": {k: sum(1 for r in rows if r["change"] == k) for k in CHANGE_KINDS},
        "rows": rows,
        "model": {
            "previous": {k: v for k, v in mp.items() if k != "demand_by_substation_mw"},
            "current": {k: v for k, v in mc.items() if k != "demand_by_substation_mw"},
            "delta": _delta(mp, mc, ("buses", "lines", "transformers", "loads", "demand_mw", "transformer_mva")),
            "demand_changes": demand_changes,
        },
        "physics": {
            "previous": pp, "current": pc,
            "delta": _delta(pp, pc, ("worst_line_pct", "worst_trafo_pct", "min_vm_pu", "max_vm_pu", "gsp_export_mw")),
        },
        "caveats": [
            "Updated rows carry their current values in both editions (NGED does not publish the previous values), so an updated rating or demand shows as a flag, not a delta.",
            "The existing fleet is placed by a siting heuristic in both editions; physics deltas reflect network changes plus any re-siting that follows from them.",
        ],
    }


# ---- ECR editions --------------------------------------------------------------------------------

ECR_SITE_KEY = ("customer_site", "lat", "lon", "energy_source_1", "point_of_connection(poc)_voltage(kv)")
_ECR_MW = "accepted_change_to_maximum_export_capacity(mw)"
_ECR_CONNECTED_MW = "connected_maximum_export_capacity(mw)"


def ecr_site_key(row: dict) -> str:
    """A site's published identity (the ECR has no stable reference column)."""
    return "|".join(str(row.get(k) if row.get(k) is not None else "").strip().lower() for k in ECR_SITE_KEY)


def diff_ecr_editions(previous: list[dict], current: list[dict]) -> list[dict]:
    """Site-level changes between two ECR fetches: added / withdrawn / connected / capacity_changed /
    date_changed / status_changed. Unchanged sites are not listed."""
    prev = {ecr_site_key(r): r for r in previous}
    cur = {ecr_site_key(r): r for r in current}
    out: list[dict] = []

    def mw(r: dict) -> float | None:
        return _num(r.get(_ECR_MW)) if _num(r.get(_ECR_MW)) is not None else _num(r.get(_ECR_CONNECTED_MW))

    def base(key: str, r: dict, change: str, detail: str) -> dict:
        return {
            "site_key": key, "change": change, "detail": detail,
            "site": (r.get("customer_site") or "").strip() or "Unnamed site",
            "energy_source": r.get("energy_source_1"), "status": r.get("connection_status"),
            "export_mw": mw(r), "target_energisation_date": r.get("target_energisation_date"),
        }

    for key, r in cur.items():
        if key not in prev:
            out.append(base(key, r, "added", f"new in the register as '{r.get('connection_status')}'"))
            continue
        p = prev[key]
        ps, cs = p.get("connection_status"), r.get("connection_status")
        pm, cm = mw(p), mw(r)
        pd, cd = p.get("target_energisation_date"), r.get("target_energisation_date")
        if ps != cs:
            kind = "connected" if cs == "Connected" else "status_changed"
            out.append(base(key, r, kind, f"{ps} → {cs}"))
        if pm is not None and cm is not None and abs(pm - cm) > 1e-6:
            out.append(base(key, r, "capacity_changed", f"{pm:g} → {cm:g} MW"))
        if pd != cd and (pd or cd):
            out.append(base(key, r, "date_changed", f"{pd or '—'} → {cd or '—'}"))
    for key, p in prev.items():
        if key not in cur:
            out.append(base(key, p, "withdrawn", f"no longer in the register (was '{p.get('connection_status')}')"))
    order = {"connected": 0, "added": 1, "withdrawn": 2, "capacity_changed": 3, "date_changed": 4, "status_changed": 5}
    out.sort(key=lambda c: (order[c["change"]], c["site"]))
    return out
