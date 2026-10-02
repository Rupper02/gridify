import type { Planner } from "../hooks/usePlanner";

export function RunOverlay({ planner }: { planner: Planner }) {
  const { s, derived } = planner;
  const { eg30, eg35, fcEff } = derived;
  const labels = [
    "Ranking: readiness · grid need · strategic fit",
    `Power flow · 2030 demand ×${eg30.toFixed(2)} · two study cases`,
    `Power flow · 2035 demand ×${eg35.toFixed(2)} · two study cases`,
    "N-1 screen of the 132 kV backbone",
    "Drafting committee briefing",
  ];
  const pct = Math.min(100, Math.max(4, s.step * 20));
  return (
    <div className="run-overlay">
      <div className="run-card">
        <div style={{ fontSize: 14, fontWeight: 600 }}>Computing power flow</div>
        <div style={{ fontSize: 12, color: "var(--mute)", marginTop: 2 }}>
          {fcEff ? `DFES · ${fcEff.label}` : "Custom scenario"} · {s.cands.length} applications
        </div>
        {s.stage && <div className="mono" style={{ fontSize: 11, color: "var(--ink2)", marginTop: 6 }}>{s.stage}</div>}
        <div className="run-bar"><div style={{ width: `${pct}%` }} /></div>
        <div className="run-steps">
          {labels.map((label, i) => {
            const done = i < s.step;
            const cur = i === s.step;
            return (
              <div key={i} style={{ color: done ? "var(--ink2)" : cur ? "var(--ink)" : "var(--mute2)" }}>
                <span className="mark" style={{ background: done ? "var(--ink)" : "#fff", borderColor: done || cur ? "var(--ink)" : "var(--bd2)" }}>{done ? "✓" : ""}</span>
                {label}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
