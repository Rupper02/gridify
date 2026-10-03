// Outages: the planned maintenance windows on the branch, each with its studied impact. Read-only on
// main. New windows are added from the element card (click a line, transformer or generator).

import { Trash, Wrench } from "@phosphor-icons/react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { elementInfo, outageImpact, outageSel } from "../lib/derive";
import { C } from "../theme";

export type OutagesTabPlanner = PlannerSlice<"outages" | "result", "removeOutage" | "select" | "setYear", "branch" | "ix" | "onMain">;

export function OutagesTab({ planner }: { planner: OutagesTabPlanner }) {
  const { s, actions, derived } = planner;
  const { ix } = derived;
  const rows = [...s.outages].sort((a, b) => a.year - b.year);
  return (
    <div className="scroll" style={{ padding: "4px 14px 16px", gap: 10 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Planned maintenance on {derived.onMain ? "main" : derived.branch?.name}</span>
        <span style={{ fontSize: 12, color: C.mute, lineHeight: 1.45 }}>
          Each window is studied in its season: summer at summer minimum, winter at winter peak, spring and autumn in both. Reported, not a
          connection gate. Click a line, transformer or generator on the map to add one.
        </span>
      </div>
      {!rows.length && (
        <div className="empty">
          <Wrench size={20} color={C.mute} />
          <b>No outages planned</b>
          <span>{derived.onMain ? "main is read-only. Open a branch to plan maintenance." : "Click a line, transformer or generator on the map to schedule an outage or a derate."}</span>
        </div>
      )}
      {rows.map((o) => {
        const info = ix ? elementInfo(outageSel(o), ix, null, o.year) : null;
        const imp = outageImpact(o, s.result, ix);
        return (
          <div key={o.outage_id} style={{ display: "grid", gridTemplateColumns: "28px minmax(0,1fr) auto", gap: "3px 10px", alignItems: "center", padding: 10, borderRadius: 12, background: "var(--well)", border: "var(--well-bd)" }}>
            <span className="tech-tile" style={{ background: "rgba(255,255,255,0.08)" }}>
              <Wrench size={14} color={C.line132} />
            </span>
            <button
              onClick={() => {
                actions.setYear(o.year);
                actions.select(outageSel(o));
              }}
              title="Show on map"
              style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", minWidth: 0, lineHeight: 1.35, padding: 0, border: "none", background: "transparent", textAlign: "left" }}
            >
              <span className="ellipsis" style={{ maxWidth: "100%", fontSize: 12.5, fontWeight: 600 }}>{info?.name ?? `${o.element_kind} ${o.element_id}`}</span>
              <span style={{ fontSize: 11, color: C.mute }}>
                {o.season} {o.year} · {o.weeks} weeks · {o.kind === "outage" ? "full outage" : "derate to 50%"}
              </span>
            </button>
            {!derived.onMain ? (
              <button className="icon-btn sm" style={{ width: 24, height: 24 }} onClick={() => void actions.removeOutage(o.outage_id)} title="Remove" aria-label="Remove outage">
                <Trash size={12} />
              </button>
            ) : (
              <span />
            )}
            <span style={{ gridColumn: "2 / -1", fontSize: 11.5, lineHeight: 1.4, color: imp.c }}>{imp.text}</span>
          </div>
        );
      })}
    </div>
  );
}
