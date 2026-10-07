// The run card, docked bottom-centre over the map above the roadmap: what is being solved, a progress rail with a
// travelling pulse, the five stages bound to the job's real stage, and the engine's own readout. No backdrop: the map
// and its substations stay clickable while the engine works. It shows for a loud run from its start to its end (the
// years land on the map as they are solved, the viewed one first); a quiet refresh never shows it.

import { Check } from "@phosphor-icons/react";

import type { PlannerSlice } from "../hooks/planner/slice";
import type { Layout } from "../lib/layout";
import { firstYear, lastYear } from "../lib/plan";
import { runStages, stageIndex, stageReadout } from "../lib/runStages";
import { C } from "../theme";

export type RunOverlayPlanner = PlannerSlice<"outages" | "plan" | "run", never, "branch" | "hue" | "onMain" | "prelim" | "profile" | "q">;

export function RunOverlay({ planner, layout }: { planner: RunOverlayPlanner; layout: Layout }) {
  const { s, derived } = planner;
  const { plan, run } = s;
  if (!plan || run.kind !== "running") return null;
  const profile = derived.profile?.label ?? "";
  const stages = runStages(plan, profile, s.outages.length);
  const cur = stageIndex(run.stage, plan);
  const n = derived.q.length + derived.prelim.length;
  return (
    <div className="run-overlay" style={{ right: layout.sideW + 10, bottom: layout.showDock ? layout.dockPx + 20 : 20 }} role="status" aria-live="polite">
      <div className="run-card">
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <span style={{ fontSize: 15, fontWeight: 600 }}>Solving AC power flow</span>
            <span style={{ fontSize: 12, color: C.mute }}>
              {profile ? `${profile} demand · ` : ""}every year {firstYear(plan)} to {lastYear(plan)} · {n} project{n === 1 ? "" : "s"}
            </span>
          </div>
          <span className="mono" style={{ display: "flex", alignItems: "center", height: 26, padding: "0 10px", borderRadius: 999, border: `1px solid ${derived.onMain ? "rgba(255,255,255,0.16)" : derived.hue + "80"}`, fontSize: 11, color: derived.hue, whiteSpace: "nowrap" }}>
            {derived.onMain ? "main" : derived.branch?.name}
          </span>
        </div>
        <div className="rail">
          <div className="wire" />
          <div className="done" style={{ width: `${Math.max(4, Math.min(100, run.fraction * 100))}%` }} />
          <div className="pulse" />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {stages.map((st, i) => {
            const done = i < cur;
            const now = i === cur;
            return (
              <div key={st.label} className="stage-row" style={{ color: done ? C.ink2 : now ? C.ink : C.mute2 }}>
                <span className="dot" style={{ borderColor: done || now ? C.accent : "rgba(255,255,255,0.2)", background: done ? C.accent : "transparent" }}>
                  {done && <Check size={10} weight="bold" />}
                </span>
                <span className="grow">{st.label}</span>
                <span className="mono" style={{ fontSize: 10.5, color: C.mute }}>{st.note}</span>
              </div>
            );
          })}
        </div>
        <div className="readout">{stageReadout(run.stage, plan)}</div>
      </div>
    </div>
  );
}
