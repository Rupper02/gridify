"""Work 8.2, the gate (spec.md): rebuild each of Bicker Fen's 21 ESAs' 2035 (and 2030) Holistic Transition peak day
from NGED's DFES pieces on its measured 2025 base, and compare with NGED's own Power Projections. Writes `gate.json`.
Supported by NGED Open Data.

    cd packages/optimizer && uv run python ../../docs/reports/dfes-shape-2026-11-13/gate.py
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from gridify_optimizer import nged
from gridify_optimizer.sources import NgedSource

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
D = ROOT / "apps" / "pipeline" / "warehouse" / "nged-flows" / "dfes-2025"
FLOWS = ROOT / "apps" / "pipeline" / "warehouse" / "nged-flows" / "bicker-fen-2025"
SCEN = "Holistic Transition"
DEMAND = ["Domestic", "Non domestic", "Heat pumps", "EV Charge Point", "Resistive electric heating", "Air conditioning",
          "Hydrogen electrolysis", "Agriculture", "Rail"]
TOTALS = {"All", "Total non domestic metres squared", "All domestic heat pumps", "Total non domestic heated floorspace"}
DAY = {"Winter": "Winter peak demand", "Intermediate Cool": "Intermediate cool peak demand",
       "Intermediate Warm": "Intermediate warm peak demand", "Summer": "Summer peak demand"}
SEASON_MONTHS = {"Winter": (12, 1, 2), "Intermediate Cool": (3, 4, 11), "Intermediate Warm": (5, 9, 10), "Summer": (6, 7, 8)}
MIDS = [f"{(15 + 30 * k) // 60:02d}:{(15 + 30 * k) % 60:02d}" for k in range(48)]  # half-hour mid-points, row order


def part(hhmm: str) -> str:
    h = int(hhmm[:2]) + int(hhmm[3:5]) / 60
    return "night" if h < 5 or h >= 23 else "morning" if h < 11 else "midday" if h < 16 else "evening"


# --- the pieces --------------------------------------------------------------------------------------------------
prof = pd.read_csv(D / "dfes_profiles.csv", encoding="utf-8-sig")
prof["k"] = prof.groupby(["profile_type", "region", "technology", "subtechnology", "representative_day"]).cumcount()
splits = pd.read_csv(D / "dfes_profile_splits.csv", encoding="utf-8-sig")
scal = pd.read_csv(D / "dfes_annual_scaling.csv", encoding="utf-8-sig")
vol = pd.read_csv(D / "dfes_volumes_bicker_fen.csv", dtype=str)
vol = vol[(vol.scenario == SCEN) & vol.technology.isin(DEMAND) & ~vol.subtechnology.isin(TOTALS)]
pp_ = pd.read_csv(D / "dfes_power_projections.csv")


def profile(tech, sub, ptype, day):
    """48 values; East Midlands where the technology has its own rows, else All. A volume's ASHP takes the mean of
    the A2A and A2W profiles (the volumes do not split them)."""
    subs = [f"{sub} (A2A)", f"{sub} (A2W)"] if sub == "Domestic - Non-hybrid ASHP" else [sub]
    out = []
    for s in subs:
        m = prof[(prof.technology == tech) & (prof.subtechnology == s) & (prof.profile_type == ptype) & (prof.representative_day == day)]
        r = m[m.region == "East Midlands"] if (m.region == "East Midlands").any() else m[m.region == "All"]
        if len(r) == 48:
            out.append(r.sort_values("k").output.to_numpy(float))
    return np.mean(out, axis=0) if out else None


def lookup(df, tech, sub, year, col, extra=None):
    m = df[(df.technology == tech) & (df.subtechnology == sub) & (df.scenario == SCEN)]
    if extra is not None:
        m = m[extra(m)]
    if not len(m):
        return None
    ys = m.year.astype(int)
    pick = m[ys == year] if (ys == year).any() else m[ys == ys[ys <= year].max()] if (ys <= year).any() else m
    return float(pick[col].iloc[0])


def increments(esa: str, year: int, day: str):
    """Σ_i ΔV_i · s_i · (u·p_unabated + f·p_flexed) on `day`, MW per half-hour, and the per-piece breakdown."""
    v = vol[vol.ESA == esa]
    tot, parts, unknown, unmatched = np.zeros(48), {}, 0, []
    for (tech, sub), g in v.groupby(["technology", "subtechnology"]):
        val = dict(zip(g.year.astype(int), g.value))
        a, b = val.get(year), val.get(2025)
        if a in (None, "[c]") or b in (None, "[c]"):
            unknown += 1
            continue
        dv = float(a) - float(b)
        if dv == 0:
            continue
        u = lookup(splits, tech, sub, year, "proportion_customers_unabated")
        f = lookup(splits, tech, sub, year, "proportion_customers_flexed")
        u, f = (1.0, 0.0) if u is None else (u, f or 0.0)
        shape = np.zeros(48)
        for ptype, share in (("Unabated", u), ("Flexed", f)):
            if share <= 0:
                continue
            p = profile(tech, sub, ptype, day)
            if p is None:
                unmatched.append(f"{tech} / {sub} / {ptype}")
                continue
            s = lookup(scal, tech, sub, year, "scaling_factor",
                       extra=lambda m, pt=ptype: (m.profile_type == pt) & (m.locations_covered == "All"))
            shape += share * (1.0 if s is None else s) * p
        inc = dv * shape
        tot += inc
        parts[f"{tech} / {sub}"] = round(float(inc.max()), 3)
    return tot, parts, unknown, unmatched


if __name__ == "__main__":
    # --- the measured base: each ESA's primary's anchor series in 2025 ---------------------------------------------------
    src = NgedSource()
    net = src.build_net()
    y = src.measured_year(FLOWS, net, "screened")
    cl = {int(b): int(b) for b in net.bus.index}
    for k, m in y.notes["multi_bus_clusters"].items():
        for b in m:
            cl[int(b)] = int(k)
    metered = {cl.get(int(a), int(a)): int(a) for a in y.notes["metered"]}
    esas = sorted({r["ESA"] for r in json.loads((ROOT / "packages/optimizer/src/gridify_optimizer/data/nged/dfes.json").read_text())})
    anchor_of = {}
    for i, ld in net.load.iterrows():
        e = nged.dfes_esa(str(ld["primary"] or ""), esas)
        a = metered.get(cl.get(int(ld.bus), int(ld.bus)))
        if e and a is not None:
            anchor_of.setdefault(e, set()).add(a)
    times = pd.DatetimeIndex(y.times)
    mid = (times - pd.Timedelta(minutes=15))  # NGED stamps the end of each half-hour
    shared = {a for e, s in anchor_of.items() for a in s if sum(a in t for t in anchor_of.values()) > 1}

    out, passes = {}, 0
    for esa in esas:
        rec = {"anchors": sorted(anchor_of.get(esa, []))}
        for year in (2030, 2035):
            row = pp_[(pp_.ESA == esa) & (pp_.scenario == SCEN) & (pp_.year == year)]
            base_row = pp_[(pp_.ESA == esa) & (pp_.scenario == SCEN) & (pp_.year == 2025)]
            season, t_star, mw = row.season.iloc[0], row.mid_point_of_HH_period.iloc[0][:5], float(row.MW_total.iloc[0])
            r = {"projection": {"season": season, "time": t_star, "mw": mw}, "projection_2025_mw": float(base_row.MW_total.iloc[0])}
            anchors = anchor_of.get(esa, set())
            if not anchors or anchors & shared:
                r["tested"] = False
                r["why"] = "no metered 2025 series of its own" if not anchors else "its anchor carries another ESA too"
            else:
                s = y.bus_p[sorted(anchors)].sum(axis=1).to_numpy(float)
                in_season = np.isin(mid.month, SEASON_MONTHS[season])
                zero_share = float((np.abs(s) < 1e-6).mean())
                day0 = mid[in_season][int(np.argmax(s[in_season]))].normalize()
                dayv = s[(mid.normalize() == day0)]
                if zero_share > 0.5 or len(dayv) != 48:
                    r["tested"] = False
                    r["why"] = f"series zero on {zero_share:.0%} of 2025" if zero_share > 0.5 else "base day incomplete"
                else:
                    base = dayv / dayv.max() * r["projection_2025_mw"]
                    inc, parts, unknown, unmatched = increments(esa, year, DAY[season])
                    P = base + inc
                    k_star = MIDS.index(t_star)
                    at = float(P[k_star])
                    kmax = int(np.argmax(P))
                    size_ok = abs(at - mw) <= max(1.0, 0.1 * mw)
                    time_ok = part(MIDS[kmax]) == part(t_star)
                    r.update({"tested": True, "base_day": str(day0.date()), "base_peak_time": MIDS[int(np.argmax(base))],
                              "rebuilt_at_projection_time": round(at, 2), "rebuilt_peak": round(float(P.max()), 2),
                              "rebuilt_peak_time": MIDS[kmax], "error_pct": round(100 * (at - mw) / mw, 1),
                              "size_ok": size_ok, "time_ok": time_ok, "pass": size_ok and time_ok,
                              "increment_at_projection_time": round(float(inc[k_star]), 2), "pieces_peak_mw": parts,
                              "suppressed_values": unknown, "unmatched_profiles": unmatched})
            rec[str(year)] = r
        passes += bool(rec["2035"].get("pass"))
        out[esa] = rec
    result = {"passes_2035": passes, "of": len(esas), "gate": "pass" if passes >= 15 else "fail", "esas": out}
    (HERE / "gate.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"GATE {result['gate']}: {passes} of {len(esas)} ESAs (2035 HT)")
    for esa, rec in out.items():
        for yr in ("2030", "2035"):
            r = rec[yr]
            p = r["projection"]
            if not r["tested"]:
                print(f"{esa[:28]:28s} {yr}: proj {p['mw']:.2f}@{p['time']} ({p['season'][:5]}) NOT TESTED: {r['why']}")
            else:
                print(f"{esa[:28]:28s} {yr}: proj {p['mw']:6.2f}@{p['time']} rebuilt {r['rebuilt_at_projection_time']:6.2f} ({r['error_pct']:+.1f}%) "
                      f"peak {r['rebuilt_peak']:6.2f}@{r['rebuilt_peak_time']} base@{r['base_peak_time']} inc {r['increment_at_projection_time']:.2f} "
                      f"{'PASS' if r['pass'] else 'fail'}{'' if r['size_ok'] else ' size'}{'' if r['time_ok'] else ' time'}")
