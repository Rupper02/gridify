import type { Planner } from "../hooks/usePlanner";

export function RunOverlay({ planner }: { planner: Planner }) {
  const { s, derived } = planner;
  const { eg30, eg35, fcEff } = derived;
  const labels = [
    `Validating ${s.cands.length} applications`,
    "Ranking: readiness · grid need · strategic fit",
    `Power flow · 2030 demand ×${eg30.toFixed(2)}`,
    `Power flow · 2035 demand ×${eg35.toFixed(2)}`,
    "Drafting committee briefing",
  ];
  const pct = Math.min(100, (s.step + 0.5) * 20);
  return (
    <div className="run-overlay">
      <div className="run-card">
        <div style={{ fontSize: 14, fontWeight: 600 }}>Computing power flow</div>
        <div style={{ fontSize: 12, color: "var(--mute)", marginTop: 2 }}>
          {fcEff ? `DFES · ${fcEff.label}` : "Custom scenario"} · {s.cands.length} applications
        </div>
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
