import type { Planner } from "../hooks/usePlanner";
import { alertGroupsFor, byStatus, sumMw, violationCount } from "../lib/derive";
import { ST, fmtMw } from "../theme";
import type { Status, Tab } from "../types";
import { AddProjectDrawer } from "./AddProjectDrawer";
import { AlertsTab } from "./AlertsTab";
import { QueueTab } from "./QueueTab";
import { ReviewTab } from "./ReviewTab";

const TILES: ["All" | Status, string, string][] = [
  ["All", "All", "#111827"],
  ["Phase1", "Phase 1", ST.Phase1.c],
  ["Phase2", "Phase 2", ST.Phase2.c],
  ["Deferred", "Deferred", ST.Deferred.c],
  ["Rejected", "Rejected", ST.Rejected.c],
];

export function SidePanel({ planner }: { planner: Planner }) {
  const { s, patch, actions, derived } = planner;
  const { q, eg30, eg35 } = derived;
  const r = s.result;
  const alertGroups = alertGroupsFor(r, eg30, eg35);
  const viol = violationCount(alertGroups);
  const tabs: [Tab, string, number, string][] = [
    ["queue", "Queue", q.length, "#6b7280"],
    ["alerts", "Alerts", viol, viol ? "#dc2626" : "#9ca3af"],
    ["compare", "Review", 0, ""],
  ];
  return (
    <div className="side">
      <div className="tiles">
        {TILES.map(([key, label, color]) => {
          const xs = key === "All" ? q : byStatus(q, key);
          const act = s.filter === key;
          return (
            <button key={key} className="tile" style={{ borderColor: act ? color : "var(--bd)", background: act ? (key === "All" ? "#f3f4f6" : ST[key].soft) : "#fff" }} onClick={() => patch({ filter: key, tab: "queue" })}>
              <span className="lab"><span className="dot" style={{ background: color }} />{label}</span>
              <span className="n">{r ? xs.length : "—"}</span>
              <span className="mw">{r ? `${fmtMw(sumMw(xs))} MW` : ""}</span>
            </button>
          );
        })}
      </div>
      <div className="tabs">
        {tabs.map(([key, label, badge, badgeBg]) => (
          <button key={key} className={`tab${s.tab === key ? " on" : ""}`} onClick={() => actions.setTab(key)}>
            {label}
            {(key === "queue" || key === "alerts") && r && <span className="badge" style={{ background: badgeBg }}>{badge}</span>}
          </button>
        ))}
      </div>
      <div className="panel">
        {s.tab === "queue" && <QueueTab planner={planner} />}
        {s.tab === "alerts" && <AlertsTab planner={planner} groups={alertGroups} />}
        {s.tab === "compare" && <ReviewTab planner={planner} />}
      </div>
      {s.drawer && <AddProjectDrawer planner={planner} />}
      {s.toast && <div className="toast">{s.toast}</div>}
    </div>
  );
}
