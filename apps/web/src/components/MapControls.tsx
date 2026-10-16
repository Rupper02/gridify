// Zoom, fit and the legend, bottom right of the map above the timeline; and the toasts.

import { ArrowsOut, Minus, Plus } from "@phosphor-icons/react";
import { useState } from "react";

import type { Planner } from "../hooks/usePlanner";
import type { Layout } from "../lib/layout";
import { C } from "../theme";

export function MapControls({ planner, layout }: { planner: Planner; layout: Layout }) {
  const { s, mapApi, derived } = planner;
  const [legend, setLegend] = useState(false);
  return (
    <div className="map-ctrl" style={{ right: layout.sideW ? layout.sideW + 20 : 10, bottom: (layout.showDock ? layout.dockPx : 0) + 20 }}>
      {legend && (
        <div className="legend">
          <div className="grid">
            {derived.compare ? (
              <>
                <span><i style={{ width: 16, height: 3, background: C.amber }} /> loads more</span>
                <span><i style={{ width: 16, height: 3, background: C.phase1 }} /> loads less</span>
                <span><i style={{ width: 16, height: 3, background: C.red }} /> over 100%</span>
                <span><i style={{ width: 16, height: 3, background: C.dimmed }} /> unchanged</span>
              </>
            ) : s.layer === "voltage" ? (
              <>
                <span><i style={{ width: 9, height: 9, borderRadius: 5, background: C.ink2 }} /> in band</span>
                <span><i style={{ width: 9, height: 9, borderRadius: 5, background: C.amber }} /> near the top</span>
                <span><i style={{ width: 9, height: 9, borderRadius: 5, background: C.phase2 }} /> near the bottom</span>
                <span><i style={{ width: 9, height: 9, borderRadius: 5, background: C.red }} /> out of band</span>
              </>
            ) : (
              <>
                <span><i style={{ width: 16, height: 3, background: "#9fb3c9" }} /> under 70%</span>
                <span><i style={{ width: 16, height: 3, background: "#e6d7a8" }} /> 70-90%</span>
                <span><i style={{ width: 16, height: 3, background: C.amber }} /> 90-100%</span>
                <span><i style={{ width: 16, height: 3, background: C.red }} /> overloaded</span>
              </>
            )}
          </div>
          <div className="foot">
            <span><i style={{ width: 10, height: 10, borderRadius: 5, background: C.existing }} /> generation today</span>
            <span><i style={{ width: 10, height: 10, borderRadius: 3, background: derived.hue }} /> connection on the branch</span>
          </div>
        </div>
      )}
      <button className="legend-btn" onClick={() => setLegend((x) => !x)}>Legend</button>
      <div className="zoom">
        <button onClick={() => mapApi.current?.zoomBy(0.8)} aria-label="Zoom in"><Plus size={14} /></button>
        <button onClick={() => mapApi.current?.zoomBy(-0.8)} aria-label="Zoom out"><Minus size={14} /></button>
        <button onClick={() => mapApi.current?.fit(true)} aria-label="Fit the network"><ArrowsOut size={13} /></button>
      </div>
    </div>
  );
}

export function Toasts({ planner }: { planner: Planner }) {
  const { s } = planner;
  if (!s.toasts.length) return null;
  return (
    <div className="toasts floating">
      {s.toasts.map((t) => (
        <div key={t.id} className={`toast${t.tone === "warn" ? " warn" : ""}`}>{t.text}</div>
      ))}
    </div>
  );
}
