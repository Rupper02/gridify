// The region card (Demand layer): one demand group in the viewed year. Its P2/8 class in plain
// English, demand against firm capacity, the demand one 132 kV outage would cut off, its buses
// outside the voltage band, the ≈ room for new demand and its alerts. Every figure is the engine's
// (demand.py); this is a simplified P2/8-style check and the card says so.

import { Users, X } from "@phosphor-icons/react";
import type { CSSProperties } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { LEVEL_LINE, P2_CLASS, REGION_STATE, alertTitle, alertsFor, classMeaning, firmFill, outagePhrase, regionRows } from "../lib/demand";
import { busLabel, nameElements } from "../lib/derive";
import { cardSlot, type Layout } from "../lib/layout";
import { C, fmtMw, tint } from "../theme";

export type RegionCardPlanner = PlannerSlice<"diffMode" | "model" | "sel" | "sideOpen" | "year", "select", "exact" | "ix" | "yr">;

const cardPos = (planner: RegionCardPlanner, layout: Layout): CSSProperties => cardSlot(layout, planner.s.sideOpen, planner.s.diffMode);

export function RegionCard({ planner, layout }: { planner: RegionCardPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const { yr, ix, exact } = derived;
  const sel = s.sel;
  if (sel?.kind !== "region") return null;
  const row = regionRows(s.model, yr).find((r) => r.region_id === sel.id);
  if (!row) return null;
  const st = REGION_STATE[row.state];
  const y = row.year;
  const fill = firmFill(row.demand_mw, row.firm_mw);
  // above firm is a breach or a warning by class (the engine's alert decides), so it takes the state's colour
  const overC = row.state === "breach" || row.state === "warn" ? st.c : C.red;
  const alerts = alertsFor(yr, row.region_id);
  const when = yr ? `in ${yr.year}` : "today";
  const cls = P2_CLASS[row.p2_class];
  return (
    <div className="detail glass region-card" style={{ ...cardPos(planner, layout), width: 304, borderColor: row.state === "breach" || row.state === "warn" ? tint(st.c, "80") : undefined }}>
      <div className="head">
        <span className="ic" style={{ background: tint(st.c, "22") }}>
          <Users size={18} color={st.c} />
        </span>
        <div style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1, lineHeight: 1.3 }}>
          <span style={{ fontSize: 13.5, fontWeight: 600, textWrap: "pretty" }}>{row.name}</span>
          <span className="ellipsis mono" style={{ fontSize: 11, color: C.mute }}>{LEVEL_LINE[row.level](row)}</span>
        </div>
        <button className="icon-btn" onClick={() => actions.select(null)} aria-label="Close">
          <X size={12} />
        </button>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        <span className="chip" style={{ background: tint(st.c, "22"), color: st.c }}>{st.label}</span>
        <span className="chip" style={{ background: "rgba(255,255,255,0.08)", color: C.ink2 }}>
          Class {row.p2_class}{cls ? ` · ${cls.range}` : ""}
        </span>
      </div>
      <span style={{ fontSize: 11.5, color: C.ink2, lineHeight: 1.45 }}>{classMeaning(row.p2_class)}</span>

      <div className="firm">
        <div className="firm-head">
          <span>Peak demand {when}</span>
          <span className="mono" style={{ color: fill.over ? overC : C.ink }}>
            {fmtMw(row.demand_mw)} / {row.firm_mw > 0 ? `${fmtMw(row.firm_mw)} MW firm` : "no firm figure"}
          </span>
        </div>
        <div className="firm-bar" role="img" aria-label={`Demand ${fmtMw(row.demand_mw)} MW against ${fmtMw(row.firm_mw)} MW firm capacity`}>
          <span style={{ width: `${fill.frac * 100}%`, background: fill.over ? overC : fill.c }} />
        </div>
        {!exact && yr && <span style={{ fontSize: 10.5, color: C.mute2 }}>Showing {yr.year} until {s.year} is solved.</span>}
      </div>

      {y ? (
        <div className="kv">
          <span>Firm headroom</span>
          <span className="mono" style={{ color: y.headroom_mw < 0 ? overC : C.ink }}>{row.firm_mw > 0 ? `${fmtMw(y.headroom_mw)} MW` : "–"}</span>
          <span>Carried in the power flow</span>
          <span className="mono">{fmtMw(y.modelled_mw)} MW</span>
          <span>N-1 demand at risk</span>
          <span style={{ color: y.n1_at_risk_mw > 0 ? C.amber : C.ink }}>
            {y.n1_at_risk_mw > 0 ? (
              <>
                <span className="mono">{fmtMw(y.n1_at_risk_mw)} MW</span> if {nameElements(outagePhrase(y.n1_outage), ix)} is lost
              </>
            ) : (
              "none from one 132 kV outage"
            )}
          </span>
          <span>Outside the voltage band</span>
          <span style={{ color: y.voltage_violation_bus_ids.length ? C.red : C.ink }}>
            {y.voltage_violation_bus_ids.length
              ? y.voltage_violation_bus_ids.map((b) => (ix ? busLabel(ix, b) : `Bus ${b}`)).join(", ")
              : "no load buses"}
          </span>
          <span>Room for new demand</span>
          <span className="mono">{y.demand_room_mw != null ? `≈ ${fmtMw(y.demand_room_mw)} MW` : "–"}</span>
        </div>
      ) : (
        <div className="box dark">
          <span style={{ fontSize: 12, color: C.ink2, lineHeight: 1.45 }}>Today's peak and firm capacity from the LTDS. Run the branch to judge this group year by year.</span>
        </div>
      )}

      {alerts.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 600 }}>Alerts {when}</span>
          {alerts.map((a, i) => {
            const c = REGION_STATE[a.level].c;
            return (
              <div key={`${a.kind}${i}`} className="region-alert" style={{ borderColor: tint(c, "66"), background: tint(c, "14") }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: c }}>{alertTitle(a.kind)}</span>
                <span style={{ fontSize: 11.5, color: C.ink2, lineHeight: 1.45 }}>{nameElements(a.message, ix)}</span>
              </div>
            );
          })}
        </div>
      )}
      {y && alerts.length === 0 && <span style={{ fontSize: 11.5, color: C.greenInk }}>No alerts for this group {when}.</span>}

      <span style={{ fontSize: 10.5, color: C.mute2, lineHeight: 1.45 }}>
        A simplified P2/8-style check (ENA EREC P2/8 demand classes), in MW of demand: the open data has no customer counts. Restoration
        times, switching, transfers and second outages are not modelled; room for new demand is first-order.
      </span>
    </div>
  );
}
