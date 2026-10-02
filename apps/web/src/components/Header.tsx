import type { PlannerSlice, WithPatch } from "../hooks/planner/slice";

import { isStale } from "../lib/derive";

export type HeaderPlanner = PlannerSlice<
  "activeBranch" | "branches" | "cands" | "forecastId" | "forecasts" | "lastParams" | "model" | "running",
  "newBranchQuick" | "onForecast" | "run" | "selectBranch",
  "onMainView" | "activeB" | "eg30" | "eg35" | "fcEff" | "reviewB"
> &
  WithPatch;

export function Header({ planner }: { planner: HeaderPlanner }) {
  const { s, actions, derived, patch } = planner;
  const { onMainView, activeB, eg30, eg35, fcEff, reviewB } = derived;
  const stale = isStale(s.lastParams, s.activeBranch, eg30, eg35, s.cands.length);
  const openBranches = s.branches.filter((b) => b.branch_id !== "main" && (b.status === "open" || b.branch_id === s.activeBranch));
  const forecastId = activeB ? activeB.scenario : s.forecastId;
  const netMeta = s.model
    ? `LTDS · ${s.model.buses.length} buses · ${s.model.lines.length} lines · ${s.model.transformers.length} transformers`
    : "loading model…";

  return (
    <header className="hdr">
      <div className="row" style={{ gap: 10 }}>
        <div className="hdr-logo">GF</div>
        <div className="col" style={{ lineHeight: 1.15 }}>
          <span className="hdr-title">GridForge</span>
          <span className="hdr-sub">Connection queue planner</span>
        </div>
      </div>
      <div className="hdr-sep" />
      <div className="col" style={{ lineHeight: 1.3 }}>
        <span style={{ fontSize: 12, fontWeight: 500, color: "var(--ink2)" }}>NGED · Bicker Fen 132 kV GSP</span>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--mute2)" }}>{netMeta}</span>
      </div>
      <div className="grow" />

      {/* branch picker: the view (map · Queue · tiles · roadmap) follows the active branch */}
      <div className="pill" style={{ borderColor: onMainView ? "var(--bd)" : "#c7d2fe", background: onMainView ? "#f9fafb" : "#eef2ff" }}>
        <div className="col" style={{ gap: 2, minWidth: 0 }}>
          <span className="caps">Branch</span>
          <div className="row" style={{ gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: onMainView ? "#9ca3af" : "#4f46e5", flex: "none" }} />
            <select value={s.activeBranch || "main"} onChange={(e) => actions.selectBranch(e.target.value)} style={{ maxWidth: 200 }}>
              <option value="main">main · plan of record</option>
              {openBranches.map((b) => (
                <option key={b.branch_id} value={b.branch_id}>{b.name}</option>
              ))}
            </select>
          </div>
          <span className="hint">{onMainView ? "plan of record · existing fleet" : `${reviewB?.n_added ?? 0} added · proposal vs main`}</span>
        </div>
        <button className="btn" title="Start a new branch off main" onClick={actions.newBranchQuick}>＋ New branch</button>
      </div>

      {/* demand forecast: on a branch it is the branch's own (fixed); on main the dropdown drives it */}
      <div className="pill" style={{ gap: 14 }}>
        <div className="col" style={{ gap: 2 }}>
          <span className="caps">{onMainView ? "Demand forecast" : "Demand forecast · branch"}</span>
          {s.forecasts.length > 0 && (
            <select value={forecastId} disabled={!onMainView} onChange={(e) => actions.onForecast(e.target.value)}>
              {s.forecasts.map((x) => (
                <option key={x.id} value={x.id}>FES 2025 · {x.label}</option>
              ))}
            </select>
          )}
          <span className="hint">
            {fcEff ? `${fcEff.source || "NESO FES 2025"} · peak demand${fcEff.cited === false ? " (spread indicative)" : ""}` : "NESO FES 2025 · peak demand"}
          </span>
        </div>
        <button className="btn primary" disabled={s.running} onClick={() => void actions.run()} style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {stale && !s.running && <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#fbbf24" }} />}
          {s.running ? "Computing power flow…" : stale ? "Re-run simulation" : "Run simulation"}
        </button>
      </div>
      <button className="btn" onClick={() => patch({ drawer: true })}>+ Add project</button>
    </header>
  );
}
