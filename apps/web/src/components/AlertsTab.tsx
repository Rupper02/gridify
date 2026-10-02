import type { Planner } from "../hooks/usePlanner";
import type { AlertGroup, AlertItem } from "../lib/derive";

export function AlertsTab({ planner, groups }: { planner: Planner; groups: AlertGroup[] }) {
  const { s, actions } = planner;
  const sel = s.sel;
  const isSel = (a: AlertItem) =>
    !!sel && ((!!a.project && sel.kind === "project" && sel.id === a.project) || (!!a.target && sel.kind === a.target.kind && sel.id === a.target.id));
  const open = (a: AlertItem) => {
    if (a.project) return actions.selectProject(a.project, true);
    if (a.target) actions.focusSel(a.target, 2.8);
  };
  return (
    <div style={{ padding: "6px 0 14px" }}>
      {groups.map((g) => (
        <div key={g.key}>
          <div className="group-head" style={{ padding: "12px 14px 6px", color: g.fg }}>
            <span className="dot" style={{ background: g.color }} />
            {g.label}
            <span style={{ color: "var(--mute2)", fontWeight: 500, letterSpacing: 0 }}>{g.items.length}</span>
          </div>
          {g.items.map((a) => (
            <div key={a.key} className="alert-row" style={{ background: isSel(a) ? "#f3f4f6" : "transparent" }} onClick={() => open(a)}>
              <span style={{ fontSize: 12.5, fontWeight: 600, color: a.fg }}>{a.title}</span>
              <span className="tag">{a.tag}</span>
              <span style={{ gridColumn: "1 / -1", fontSize: 11.5, color: "var(--mute)" }}>{a.meta}</span>
            </div>
          ))}
        </div>
      ))}
      {s.result && groups.length === 0 && <div className="empty">No violations in this plan.</div>}
    </div>
  );
}
