import type { PlannerSlice } from "../hooks/planner/slice";

import { byStatus, sumMw } from "../lib/derive";
import { ST, fmtMw, techLabel } from "../theme";
import type { QueueItem, Status } from "../types";
import { TechIcon } from "./TechIcon";

export type RoadmapPlanner = PlannerSlice<"result" | "sel", "selectProject", "q">;

function Card({ x, selected, onClick, deferred }: { x: QueueItem; selected: boolean; onClick: () => void; deferred?: boolean }) {
  const st = ST[x.status];
  const sub = `${techLabel(x.technology) ?? "—"} · ${fmtMw(x.rating_mw)} MW`;
  if (deferred)
    return (
      <div className="rm-card" title={x.reason ? x.reason.why || x.reason.message : ""} onClick={onClick} style={{ background: "#fffbeb", borderStyle: "dashed", borderColor: selected ? st.c : st.bd, maxWidth: "100%" }}>
        <div className="row id" style={{ gap: 5, color: "#92400e", whiteSpace: "nowrap" }}>
          {x.request_id} <TechIcon tech={x.technology} /><span style={{ fontFamily: "var(--sans)", fontWeight: 400, color: "var(--ink3)", fontSize: 10.5 }}>{sub}</span>
        </div>
        <div className="ellipsis" style={{ fontSize: 10.5, color: "#b45309", maxWidth: 190 }}>{x.reason ? x.reason.short || x.reason.message : ""}</div>
      </div>
    );
  return (
    <div className="rm-card" onClick={onClick} style={{ background: st.soft, borderColor: selected ? st.c : st.bd }}>
      <div className="id" style={{ color: st.fg }}>{x.request_id}</div>
      <div className="sub"><TechIcon tech={x.technology} /><span>{sub}</span></div>
    </div>
  );
}

export function Roadmap({ planner }: { planner: RoadmapPlanner }) {
  const { s, actions, derived } = planner;
  const { q } = derived;
  const r = s.result;
  const p1 = byStatus(q, "Phase1");
  const p2 = byStatus(q, "Phase2");
  const def = byStatus(q, "Deferred");
  const valid = q.filter((x) => x.status !== "Rejected");
  const summary = r
    ? `${fmtMw(sumMw(p1))} MW by 2030 · ${fmtMw(sumMw(p1) + sumMw(p2))} MW cumulative by 2035 · ${def.length} deferred (${fmtMw(sumMw(def))} MW waiting on grid or readiness)`
    : "Run the simulation to build the roadmap.";
  const isSel = (x: QueueItem) => s.sel?.kind === "project" && s.sel.id === x.request_id;
  const col = (st: Status) => ST[st].c;
  return (
    <div className="roadmap">
      <div className="row" style={{ alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Connection roadmap</span>
        <span style={{ fontSize: 11.5, color: "var(--mute)" }}>{summary}</span>
      </div>
      <div className="roadmap-grid">
        <div>
          <div className="rm-track" style={{ borderColor: "#d1d5db" }}><span className="knob" style={{ background: "#fff", border: "2px solid #6b7280" }} /></div>
          <div style={{ marginTop: 12, fontSize: 12, fontWeight: 600 }}>Now · Sep 2026</div>
          <div style={{ fontSize: 11.5, color: "var(--mute)", marginTop: 3, lineHeight: 1.45 }}>
            {r ? `${valid.length} valid applications, ${fmtMw(sumMw(valid))} MW requested. ${byStatus(q, "Rejected").length} rejected at intake.` : "—"}
          </div>
        </div>
        <div>
          <div className="rm-track" style={{ borderColor: col("Phase1") }}><span className="knob" style={{ background: col("Phase1"), border: "2px solid #fff", boxShadow: `0 0 0 1px ${col("Phase1")}` }} /></div>
          <div className="rm-head"><span style={{ fontWeight: 600, color: ST.Phase1.fg }}>By 2030 · Phase 1</span><span className="mono muted">{fmtMw(sumMw(p1))} MW</span></div>
          <div className="rm-cards">{p1.map((x) => <Card key={x.request_id} x={x} selected={isSel(x)} onClick={() => actions.selectProject(x.request_id)} />)}</div>
        </div>
        <div>
          <div className="rm-track" style={{ borderColor: col("Phase2") }}><span className="knob" style={{ background: col("Phase2"), border: "2px solid #fff", boxShadow: `0 0 0 1px ${col("Phase2")}` }} /></div>
          <div className="rm-head"><span style={{ fontWeight: 600, color: ST.Phase2.fg }}>By 2035 · Phase 2</span><span className="mono muted">+{fmtMw(sumMw(p2))} MW</span></div>
          <div className="rm-cards">
            {p2.map((x) => <Card key={x.request_id} x={x} selected={isSel(x)} onClick={() => actions.selectProject(x.request_id)} />)}
            {r && p2.length === 0 && <span style={{ fontSize: 11.5, color: "var(--mute2)" }}>No projects in Phase 2</span>}
          </div>
        </div>
        <div style={{ paddingRight: 0 }}>
          <div className="rm-track" style={{ borderColor: col("Deferred"), borderTopStyle: "dashed" }}><span className="knob" style={{ background: "#fef3c7", border: `2px solid ${col("Deferred")}` }} /></div>
          <div className="rm-head"><span style={{ fontWeight: 600, color: ST.Deferred.fg }}>Deferred · not scheduled</span><span className="mono muted">{fmtMw(sumMw(def))} MW</span></div>
          <div className="rm-cards">{def.map((x) => <Card key={x.request_id} x={x} deferred selected={isSel(x)} onClick={() => actions.selectProject(x.request_id)} />)}</div>
        </div>
      </div>
    </div>
  );
}
