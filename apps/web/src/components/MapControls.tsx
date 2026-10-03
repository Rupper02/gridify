// Over the map: the layer toggle (Flow / Loading / Voltage) with the Deferred switch, the legend and
// zoom (+ / − / FIT), and the diff-mode banner.

import { ArrowRight, Gauge, GitDiff, HourglassMedium, Lightning, Minus, Plus, WaveSine, Wrench, X } from "@phosphor-icons/react";

import type { PlannerSlice } from "../hooks/planner/slice";
import type { Layout } from "../lib/layout";
import { C } from "../theme";
import type { MapLayer, Tech } from "../types";
import { Switch, TechIcon } from "./ui";

export type LayerTogglePlanner = PlannerSlice<"layer" | "showDeferred" | "sideOpen", "setLayer" | "toggleDeferred">;

const LAYERS: [MapLayer, string, typeof WaveSine][] = [
  ["flow", "Flow", WaveSine],
  ["loading", "Loading", Gauge],
  ["voltage", "Voltage", Lightning],
];

export function LayerToggle({ planner, layout }: { planner: LayerTogglePlanner; layout: Layout }) {
  const { s, actions } = planner;
  return (
    <div className="layers glass" style={{ top: s.sideOpen ? 68 : 114, right: layout.sideW + (s.sideOpen ? 20 : 10) }}>
      {LAYERS.map(([k, label, I]) => (
        <button key={k} className={s.layer === k ? "on" : ""} onClick={() => actions.setLayer(k)} aria-pressed={s.layer === k}>
          <I size={14} />
          {label}
        </button>
      ))}
      <div className="sep" />
      <button className={`def${s.showDeferred ? " on" : ""}`} role="switch" aria-checked={s.showDeferred} onClick={actions.toggleDeferred} title="Show deferred projects on the map">
        <HourglassMedium size={14} />
        Deferred
        <span style={{ marginLeft: "auto", display: "flex" }}>
          <Switch on={s.showDeferred} />
        </span>
      </button>
    </div>
  );
}

export type MapCornerPlanner = PlannerSlice<"legendOpen", "toggleLegend" | "zoomFit" | "zoomIn" | "zoomOut", "hue">;

const LEGEND_TECH: [Tech, string][] = [
  ["solar", "Solar PV"], ["wind", "Wind"], ["battery", "Battery"], ["hybrid", "Solar + battery"],
  ["gas", "Gas (CCGT, OCGT, engines)"], ["biomass", "Biomass / EfW"], ["electrolyser", "Hydrogen electrolyser"], ["demand", "Demand connection"],
];

export function MapCorner({ planner, layout }: { planner: MapCornerPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  return (
    <div className="map-ctrl" style={{ right: layout.sideW + 20, bottom: layout.showDock ? layout.dockPx + 20 : 14 }}>
      {s.legendOpen ? (
        <div className="legend">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontWeight: 600, color: C.ink }}>Legend</span>
            <button className="icon-btn sm" onClick={actions.toggleLegend} aria-label="Close legend">
              <X size={12} />
            </button>
          </div>
          <div className="grid">
            {LEGEND_TECH.map(([t, l]) => (
              <span key={t}>
                <TechIcon tech={t} size={13} color={C.phase1} />
                {l}
              </span>
            ))}
            <span><span style={{ width: 0, height: 0, margin: "0 2px", borderLeft: "5px solid transparent", borderRight: "5px solid transparent", borderTop: "8px solid #8b98a9" }} />Load (sized by MW)</span>
            <span><span style={{ position: "relative", width: 12, height: 14 }}><span style={{ position: "absolute", left: 1, top: 0, width: 10, height: 10, borderRadius: "50%", border: `1.5px solid ${C.ink}` }} /><span style={{ position: "absolute", left: 1, top: 4, width: 10, height: 10, borderRadius: "50%", border: `1.5px solid ${C.ink}` }} /></span>Transformer</span>
            <span><span style={{ width: 14, height: 3, borderRadius: 2, background: C.line132 }} />132 kV · <span style={{ width: 14, height: 2, borderRadius: 2, background: C.line33 }} />33 kV</span>
            <span><span style={{ width: 10, height: 10, borderRadius: "50%", background: C.existing, border: `1.5px solid ${C.ink}` }} />Existing generation</span>
            <span><span style={{ width: 14, height: 3, borderRadius: 2, background: C.red }} />Overloaded line</span>
            <span><span style={{ width: 8, height: 8, border: `1.5px solid ${C.mute}`, background: C.substation }} />Open point</span>
            <span><span style={{ width: 14, height: 3, background: `repeating-linear-gradient(90deg,${C.amber} 0 4px,transparent 4px 7px)` }} />Binding constraint</span>
            <span><Wrench size={12} color={C.line132} />Planned outage</span>
            <span><span style={{ width: 12, height: 12, borderRadius: "50%", border: `1.5px solid ${C.red}`, background: "rgba(255,107,107,0.15)" }} />Voltage breach</span>
            <span><span style={{ width: 12, height: 12, borderRadius: "50%", border: `1.5px solid ${derived.hue}` }} />Only on this branch</span>
          </div>
          <div className="foot">
            <span><span style={{ width: 9, height: 9, borderRadius: 2, background: C.phase1 }} />Phase 1</span>
            <span><span style={{ width: 9, height: 9, borderRadius: 2, background: C.phase2 }} />Phase 2</span>
            <span><span style={{ width: 9, height: 9, borderRadius: 2, border: `1px dashed ${C.amber}` }} />Deferred</span>
            <span><span style={{ width: 9, height: 9, borderRadius: 2, border: `1px dashed ${C.accent}` }} />Preliminary</span>
          </div>
        </div>
      ) : (
        <button className="legend-btn" onClick={actions.toggleLegend}>
          Legend
        </button>
      )}
      <div className="zoom">
        <button onClick={actions.zoomIn} aria-label="Zoom in"><Plus size={14} /></button>
        <button onClick={actions.zoomOut} aria-label="Zoom out"><Minus size={14} /></button>
        <button onClick={actions.zoomFit} aria-label="Fit the network">FIT</button>
      </div>
    </div>
  );
}

export type DiffBannerPlanner = PlannerSlice<"diff" | "sideOpen", "toggleDiff", "branch" | "branchOnly" | "diffPhase" | "hue">;

export function DiffBanner({ planner, layout }: { planner: DiffBannerPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const nAdded = (s.diff?.projects ?? []).filter((p) => p.change === "added").length || derived.branchOnly.size;
  return (
    <div className="diff-banner" style={{ top: layout.narrow ? 110 : 68, left: layout.narrow ? 10 : 270, right: s.sideOpen ? layout.sideW + 130 : 222 }}>
      <div className="glass" style={{ borderColor: "var(--hue-bd)" }}>
        <span className="mono" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, whiteSpace: "nowrap" }}>
          <GitDiff size={14} color={derived.hue} />
          <span style={{ color: C.mute }}>main</span>
          <ArrowRight size={11} color={C.mute2} />
          <b style={{ color: derived.hue, fontWeight: 600 }}>{derived.branch?.name}</b>
        </span>
        <span className="key">
          <span style={{ width: 14, height: 14, borderRadius: 4, display: "grid", placeItems: "center", background: derived.hue, color: "#08131c", fontSize: 11, fontWeight: 700, lineHeight: 1 }}>+</span>
          {nAdded} added on branch
        </span>
        <span className="key">
          <span className="mono" style={{ fontSize: 10, fontWeight: 600, padding: "0 5px", borderRadius: 999, border: `1px solid ${C.amber}`, color: C.amber }}>+N%</span>
          loading change at {derived.diffPhase}
        </span>
        <span className="key">
          <span style={{ width: 14, height: 3, borderRadius: 2, background: C.red }} />
          newly over 100%
        </span>
        <span style={{ whiteSpace: "nowrap", color: C.mute2 }}>{s.diff ? "Unchanged is dimmed" : "Loading the diff…"}</span>
        <button className="icon-btn" style={{ width: 24, height: 24 }} onClick={actions.toggleDiff} aria-label="Close diff">
          <X size={12} />
        </button>
      </div>
    </div>
  );
}
