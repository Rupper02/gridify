// The collapsible side panel (keyboard `]`): Copilot / Queue / Outages / Review as a pill segmented
// control, the active tab's body, and the toast.

import { ChatCircleDots, CheckCircle, GitDiff, ListNumbers, SidebarSimple, Warning, Wrench } from "@phosphor-icons/react";

import type { PlannerSlice } from "../hooks/planner/slice";
import type { Layout } from "../lib/layout";
import { C } from "../theme";
import type { Tab } from "../types";
import { CopilotTab, type CopilotTabPlanner } from "./CopilotTab";
import { OutagesTab, type OutagesTabPlanner } from "./OutagesTab";
import { QueueTab, type QueueTabPlanner } from "./QueueTab";
import { ReviewTab, type ReviewTabPlanner } from "./ReviewTab";

export type SidePanelPlanner = PlannerSlice<"outages" | "sideOpen" | "tab" | "toast", "setTab" | "toggleSide", "prelim" | "q"> &
  CopilotTabPlanner &
  QueueTabPlanner &
  OutagesTabPlanner &
  ReviewTabPlanner;

const TABS: [Tab, string, typeof ChatCircleDots][] = [
  ["copilot", "Copilot", ChatCircleDots],
  ["queue", "Queue", ListNumbers],
  ["outages", "Outages", Wrench],
  ["review", "Review", GitDiff],
];

export function SidePanel({ planner, layout }: { planner: SidePanelPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const badge: Record<Tab, string> = {
    copilot: "",
    queue: String(derived.q.length + derived.prelim.length || ""),
    outages: s.outages.length ? String(s.outages.length) : "",
    review: "",
  };
  return (
    <>
      {!s.sideOpen && (
        <button className="reopen glass" onClick={actions.toggleSide} title="Show panel (])">
          <SidebarSimple size={15} style={{ transform: "scaleX(-1)" }} />
          Copilot, queue and review
        </button>
      )}
      <aside className={`side${s.sideOpen ? "" : " closed"}`} aria-hidden={!s.sideOpen}>
        <div className="tabs" role="tablist">
          <button className="hide" onClick={actions.toggleSide} title="Hide panel (])" aria-label="Hide panel">
            <SidebarSimple size={15} style={{ transform: "scaleX(-1)" }} />
          </button>
          {TABS.map(([k, label, I]) => {
            const on = s.tab === k;
            return (
              <button key={k} role="tab" aria-selected={on} className={on ? "on" : ""} onClick={() => actions.setTab(k)} title={label}>
                <I size={14} />
                {(layout.wide || on) && label}
                {badge[k] && <span className="badge">{badge[k]}</span>}
              </button>
            );
          })}
        </div>
        <div className="tab-body">
          {s.tab === "copilot" && <CopilotTab planner={planner} layout={layout} />}
          {s.tab === "queue" && <QueueTab planner={planner} />}
          {s.tab === "outages" && <OutagesTab planner={planner} />}
          {s.tab === "review" && <ReviewTab planner={planner} />}
        </div>
        {s.toast && s.sideOpen && <Toast toast={s.toast} />}
      </aside>
      {s.toast && !s.sideOpen && <Toast toast={s.toast} floating />}
    </>
  );
}

function Toast({ toast, floating }: { toast: { text: string; tone: "ok" | "warn" }; floating?: boolean }) {
  return (
    <div className={`toast${toast.tone === "warn" ? " warn" : ""}${floating ? " floating" : ""}`} role="status">
      {toast.tone === "warn" ? <Warning size={15} color={C.amber} weight="fill" /> : <CheckCircle size={15} color={C.phase1} weight="fill" />}
      {toast.text}
    </div>
  );
}
