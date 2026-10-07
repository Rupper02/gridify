// Over the map: the layer toggle (Flow / Loading / Voltage / Demand) with the Deferred switch and the
// Show menu (which kinds of element the map draws, lib/mapFeatures.ts), the legend and
// zoom (+ / − / FIT), and the diff-mode banner.

import { ArrowRight, CaretDown, CaretUp, Crosshair, Eye, Gauge, GitDiff, Lightning, Minus, Plus, Users, WaveSine, Wrench, X } from "@phosphor-icons/react";

import { useEffect, useRef } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import type { Layout } from "../lib/layout";
import { REGION_STATE } from "../lib/demand";
import { DEFAULT_VISIBLE, FEATURE_GROUPS, FEATURE_KEYS, MAP_FEATURES, featureLabel, shows } from "../lib/mapFeatures";
import { C, tint } from "../theme";
import type { MapLayer, Tech } from "../types";
import { Switch, TechIcon } from "./ui";

export type LayerTogglePlanner = PlannerSlice<
  "layer" | "showDeferred" | "showMenuOpen" | "visible",
  "setLayer" | "showAll" | "showOnly" | "toggleDeferred" | "toggleFeatureShown" | "toggleShowMenu",
  "caps" | "tiers"
>;

const LAYERS: [MapLayer, string, typeof WaveSine][] = [
  ["flow", "Flow", WaveSine],
  ["loading", "Loading", Gauge],
  ["voltage", "Voltage", Lightning],
  ["demand", "Demand", Users],
];

/** The map's layers, in the header: the layer in view and the Show menu (which also holds the Deferred switch). */
export function MapLayers({ planner, wide }: { planner: LayerTogglePlanner; wide: boolean }) {
  const { s, actions, derived } = planner;
  const layers = LAYERS.filter(([k]) => k !== "demand" || derived.caps.regions); // no demand groups, no Demand layer
  return (
    <div className="map-layers">
      <div className="seg" role="radiogroup" aria-label="Map layer">
        {layers.map(([k, label, I]) => (
          <button key={k} role="radio" aria-checked={s.layer === k} className={s.layer === k ? "on" : ""} onClick={() => actions.setLayer(k)} data-tip={label} aria-label={label} style={{ padding: wide ? "0 11px" : "0 9px" }}>
            <I size={14} />
            {wide && label}
          </button>
        ))}
      </div>
      <ShowMenu planner={planner} wide={wide} />
    </div>
  );
}

/** Which kinds of element the map draws: a switch each, "only" to focus on one, and Show all. Line features are named
 * by the grid's own voltages, and a kind the grid does not have is left out. */
function ShowMenu({ planner, wide }: { planner: LayerTogglePlanner; wide: boolean }) {
  const { s, actions, derived } = planner;
  const box = useRef<HTMLDivElement>(null);
  const { showMenuOpen, toggleShowMenu } = { showMenuOpen: s.showMenuOpen, toggleShowMenu: actions.toggleShowMenu };
  // a click anywhere else closes the menu
  useEffect(() => {
    if (!showMenuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) toggleShowMenu();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [showMenuOpen, toggleShowMenu]);
  const keys = FEATURE_KEYS.filter((k) => featureLabel(k, derived.tiers) != null);
  const n = keys.filter((k) => shows(s.visible, k)).length;
  const defaults = DEFAULT_VISIBLE.filter((k) => keys.includes(k));
  const isDefault = n === defaults.length && defaults.every((k) => s.visible.includes(k));
  return (
    <div style={{ position: "relative" }} ref={box}>
      <button className="btn" onClick={actions.toggleShowMenu} aria-expanded={s.showMenuOpen} data-tip={s.showMenuOpen ? undefined : "Choose what the map shows"} aria-label="Choose what the map shows">
        <Eye size={14} />
        {wide && "Show"}
        <span className="mono show-count">{n}/{keys.length}</span>
        {s.showMenuOpen ? <CaretUp size={12} /> : <CaretDown size={12} />}
      </button>
      {s.showMenuOpen && (
        <div className="show-menu glass" role="group" aria-label="Elements on the map">
          {FEATURE_GROUPS.map((g) => (
            <div key={g} className="show-group">
              <span className="show-head">{g}</span>
              {keys.filter((k) => MAP_FEATURES[k].group === g).map((k) => {
                const label = featureLabel(k, derived.tiers)!;
                const on = shows(s.visible, k);
                const alone = n === 1 && on;
                return (
                  <div key={k} className="show-row">
                    <button className="show-label" role="switch" aria-checked={on} onClick={() => actions.toggleFeatureShown(k)}>
                      <span className="ellipsis" style={{ color: on ? C.ink : C.mute2 }}>{label}</span>
                      <Switch on={on} />
                    </button>
                    <button
                      className={`show-only${alone ? " on" : ""}`}
                      onClick={() => actions.showOnly(k)}
                      title={alone ? "Show the usual elements again" : `Show only ${label.toLowerCase()}`}
                      aria-label={alone ? "Show the usual elements again" : `Only ${label}`}
                    >
                      <Crosshair size={12} />
                    </button>
                  </div>
                );
              })}
            </div>
          ))}
          <div className="show-group">
            <span className="show-head">Projects not connecting</span>
            <div className="show-row">
              <button className="show-label" role="switch" aria-checked={s.showDeferred} onClick={actions.toggleDeferred} title="Draw the projects the plan defers, dashed, where they would connect">
                <span className="ellipsis" style={{ color: s.showDeferred ? C.ink : C.mute2 }}>Deferred projects</span>
                <Switch on={s.showDeferred} />
              </button>
            </div>
          </div>
          <button className="show-all" onClick={actions.showAll} disabled={isDefault}>
            Show all
          </button>
        </div>
      )}
    </div>
  );
}

export type MapCornerPlanner = PlannerSlice<"legendOpen", "toggleLegend" | "zoomFit" | "zoomIn" | "zoomOut", "hue" | "tiers">;

const LEGEND_TECH: [Tech, string][] = [
  ["solar", "Solar PV"], ["wind", "Wind"], ["battery", "Battery"], ["hybrid", "Solar + battery"],
  ["gas", "Gas (CCGT, OCGT, engines)"], ["biomass", "Biomass / EfW"], ["electrolyser", "Hydrogen electrolyser"], ["demand", "Demand connection"],
];

const DEMAND_KEY = [REGION_STATE.breach.c, REGION_STATE.warn.c, REGION_STATE.ok.c];

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
            {derived.tiers.high != null && (
              <span>
                <span style={{ width: 14, height: 3, borderRadius: 2, background: C.lineHigh }} />
                {+derived.tiers.high} kV
                {derived.tiers.mid != null && <> · <span style={{ width: 14, height: 2, borderRadius: 2, background: C.lineMid }} />{+derived.tiers.mid} kV</>}
              </span>
            )}
            <span><span style={{ width: 10, height: 10, borderRadius: "50%", background: C.existing, border: `1.5px solid ${C.ink}` }} />Existing generation</span>
            <span><span style={{ width: 14, height: 3, borderRadius: 2, background: C.red }} />Overloaded line</span>
            <span><span style={{ width: 8, height: 8, border: `1.5px solid ${C.mute}`, background: C.substation }} />Open point</span>
            <span><span style={{ width: 14, height: 3, background: `repeating-linear-gradient(90deg,${C.amber} 0 4px,transparent 4px 7px)` }} />Binding constraint</span>
            <span><Wrench size={12} color={C.lineHigh} />Planned works</span>
            <span><span style={{ width: 12, height: 12, borderRadius: "50%", border: `1.5px solid ${C.red}`, background: "rgba(255,107,107,0.15)" }} />Voltage breach</span>
            <span><span style={{ width: 12, height: 12, borderRadius: "50%", border: `1.5px solid ${derived.hue}` }} />Only on this branch</span>
            <span className="legend-demand">
              {DEMAND_KEY.map((c) => <span key={c} style={{ borderColor: c, background: tint(c, "29") }} />)}
              Demand region: breach · warn · ok
            </span>
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

export type DiffBannerPlanner = PlannerSlice<"diff" | "year", "toggleDiff", "branch" | "branchOnly" | "hue" | "parent">;

export function DiffBanner({ planner, layout }: { planner: DiffBannerPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const nAdded = s.diff ? s.diff.projects.filter((p) => p.change === "added").length : derived.branchOnly.size; // the diff's count once it is in, even 0
  return (
    <div className="diff-banner" style={{ top: layout.narrow ? 110 : 68, left: layout.narrow ? 10 : 280, right: layout.cardRight }}>
      <div className="glass" style={{ borderColor: "var(--hue-bd)" }}>
        <span className="mono" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, whiteSpace: "nowrap" }}>
          <GitDiff size={14} color={derived.hue} />
          <span style={{ color: C.mute }}>{derived.parent}</span>
          <ArrowRight size={11} color={C.mute2} />
          <b style={{ color: derived.hue, fontWeight: 600 }}>{derived.branch?.name}</b>
        </span>
        <span className="key">
          <span style={{ width: 14, height: 14, borderRadius: 4, display: "grid", placeItems: "center", background: derived.hue, color: "#08131c", fontSize: 11, fontWeight: 700, lineHeight: 1 }}>+</span>
          {nAdded} added on branch
        </span>
        <span className="key">
          <span className="mono" style={{ fontSize: 10, fontWeight: 600, padding: "0 5px", borderRadius: 999, border: `1px solid ${C.amber}`, color: C.amber }}>+N%</span>
          line and transformer loading change in {s.year}
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
