// The collapsible side panel (keyboard `]`): Ask / Queue / Outages / Findings / Review as a pill
// segmented control, the active tab's body, and the toast. The tabs are a registry: adding one is one
// entry here (its label, icon, badge and body) plus its key in the `Tab` union.

import { CheckCircle, ChatCircleDots, GitDiff, type Icon, ListNumbers, SidebarSimple, Warning, Wrench } from "@phosphor-icons/react";
import type { ReactNode } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import type { Layout } from "../lib/layout";
import { C } from "../theme";
import type { Tab } from "../types";
import { AskTab, type AskTabPlanner } from "./AskTab";
import { FindingsTab, type FindingsTabPlanner } from "./FindingsTab";
import { OutagesTab, type OutagesTabPlanner } from "./OutagesTab";
import { QueueTab, type QueueTabPlanner } from "./QueueTab";
import { ReviewTab, type ReviewTabPlanner } from "./ReviewTab";

export type SidePanelPlanner = PlannerSlice<"outages" | "sideOpen" | "tab" | "toast", "setTab" | "toggleSide", "openFindings" | "prelim" | "q"> &
  AskTabPlanner &
  QueueTabPlanner &
  OutagesTabPlanner &
  FindingsTabPlanner &
  ReviewTabPlanner;

interface TabSpec {
  label: string;
  icon: Icon;
  /** The small count next to the label ("" for none). */
  badge: (p: SidePanelPlanner) => string;
  render: (p: SidePanelPlanner, layout: Layout) => ReactNode;
}

const TABS: Record<Tab, TabSpec> = {
  ask: {
    label: "Ask",
    icon: ChatCircleDots,
    badge: (p) => (p.derived.pendingApprovals ? String(p.derived.pendingApprovals) : ""),
    render: (p, layout) => <AskTab planner={p} layout={layout} />,
  },
  queue: { label: "Queue", icon: ListNumbers, badge: (p) => String(p.derived.q.length + p.derived.prelim.length || ""), render: (p) => <QueueTab planner={p} /> },
  outages: { label: "Outages", icon: Wrench, badge: (p) => (p.s.outages.length ? String(p.s.outages.length) : ""), render: (p) => <OutagesTab planner={p} /> },
  findings: {
    label: "Findings",
    icon: Warning,
    badge: (p) => String(p.derived.openFindings.breach || p.derived.openFindings.open || ""),
    render: (p) => <FindingsTab planner={p} />,
  },
  review: { label: "Review", icon: GitDiff, badge: () => "", render: (p) => <ReviewTab planner={p} /> },
};

export function SidePanel({ planner, layout }: { planner: SidePanelPlanner; layout: Layout }) {
  const { s, actions } = planner;
  return (
    <>
      {!s.sideOpen && (
        <button className="reopen glass" onClick={actions.toggleSide} title="Show panel (])">
          <SidebarSimple size={15} style={{ transform: "scaleX(-1)" }} />
          Ask, queue, findings and review
        </button>
      )}
      <aside className={`side${s.sideOpen ? "" : " closed"}`} aria-hidden={!s.sideOpen}>
        <div className="tabs" role="tablist">
          <button className="hide" onClick={actions.toggleSide} title="Hide panel (])" aria-label="Hide panel">
            <SidebarSimple size={15} style={{ transform: "scaleX(-1)" }} />
          </button>
          {(Object.entries(TABS) as [Tab, TabSpec][]).map(([k, t]) => {
            const on = s.tab === k;
            const badge = t.badge(planner);
            return (
              <button key={k} role="tab" aria-selected={on} className={on ? "on" : ""} onClick={() => actions.setTab(k)} title={t.label}>
                <t.icon size={14} />
                {(layout.wide || on) && t.label}
                {badge && <span className="badge">{badge}</span>}
              </button>
            );
          })}
        </div>
        <div className="tab-body">{TABS[s.tab].render(planner, layout)}</div>
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
