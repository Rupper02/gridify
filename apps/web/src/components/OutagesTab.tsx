// Outages: the planned works windows on the branch (maintenance, repowering, replacement), grouped by
// year, each with its studied verdict. Read-only on main. New windows are added from the element card
// (click a line, transformer or generator).

import { Trash, Wrench } from "@phosphor-icons/react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { elementInfo, outageSel } from "../lib/derive";
import { outageLine, verdictColor, windowSummary, windowView, windowsByYear } from "../lib/maintenance";
import { C, tint } from "../theme";
import { VerdictChip, WindowDetail } from "./WindowVerdict";

export type OutagesTabPlanner = PlannerSlice<"outages" | "result", "removeOutage" | "select" | "setYear", "branch" | "ix" | "onMain" | "q">;

export function OutagesTab({ planner }: { planner: OutagesTabPlanner }) {
  const { s, actions, derived } = planner;
  const { ix } = derived;
  const ctx = { result: s.result, ix, outages: s.outages, queue: derived.q };
  const groups = windowsByYear(s.outages);
  return (
    <div className="scroll" style={{ padding: "4px 14px 16px", gap: 10 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Planned works on {derived.onMain ? "main" : derived.branch?.name}</span>
        <span style={{ fontSize: 12, color: C.mute, lineHeight: 1.45 }}>
          Each window is studied in its season: summer at summer minimum, winter at winter peak, spring and autumn in both. Windows in the
          same season and year are studied together. Reported, not a connection gate. Click a line, transformer or generator on the map to
          add one.
        </span>
        {s.outages.length > 0 && <span className="out-sum">{windowSummary(s.outages, s.result)}</span>}
      </div>
      {!groups.length && (
        <div className="empty">
          <Wrench size={20} color={C.mute} />
          <b>No works planned</b>
          <span>{derived.onMain ? "main is read-only. Open a branch to plan works." : "Click a line, transformer or generator on the map to schedule maintenance, repowering or a replacement."}</span>
        </div>
      )}
      {groups.map((g) => (
        <div key={g.year} className="ygroup">
          <span className="ygroup-head mono">{g.year}</span>
          {g.rows.map((o) => {
            const info = ix ? elementInfo(outageSel(o), ix, null, o.year) : null;
            const view = windowView(o, ctx);
            const vc = verdictColor(view.verdict);
            return (
              <div key={o.outage_id} className="wrow">
                <span className="tech-tile" style={{ background: vc ? tint(vc, "22") : "rgba(255,255,255,0.08)" }}>
                  <Wrench size={14} color={vc ?? C.lineHigh} />
                </span>
                <button
                  className="wrow-main"
                  onClick={() => {
                    actions.setYear(o.year);
                    actions.select(outageSel(o));
                  }}
                  title="Show on map"
                >
                  <span className="ellipsis" style={{ maxWidth: "100%", fontSize: 12.5, fontWeight: 600 }}>{info?.name ?? `${o.element_kind} ${o.element_id}`}</span>
                  <span style={{ fontSize: 11, color: C.mute }}>{outageLine(o)}</span>
                </button>
                {!derived.onMain ? (
                  <button className="icon-btn sm" style={{ width: 24, height: 24 }} onClick={() => void actions.removeOutage(o.outage_id)} title="Remove" aria-label="Remove window">
                    <Trash size={12} />
                  </button>
                ) : (
                  <span />
                )}
                <span className="wrow-detail">
                  <VerdictChip view={view} />
                  <WindowDetail view={view} />
                </span>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
