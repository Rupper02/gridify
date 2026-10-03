// The composition root: the one place that sees the whole planner. It lays the floating panels over
// the full-bleed map for the viewport (lib/layout.ts) and hands each component its slice.

import { useEffect, useMemo, useState } from "react";

import { DetailCards } from "./components/DetailCards";
import { Header } from "./components/Header";
import { LeftCards } from "./components/LeftCards";
import { DiffBanner, LayerToggle, MapCorner } from "./components/MapControls";
import { MapView } from "./components/MapView";
import { Roadmap } from "./components/Roadmap";
import { RunOverlay } from "./components/RunOverlay";
import { SidePanel } from "./components/SidePanel";
import { hueVars } from "./components/ui";
import { usePlanner } from "./hooks/usePlanner";
import { buildGeo } from "./lib/geo";
import { layoutFor } from "./lib/layout";

function useViewport() {
  const [vp, setVp] = useState({ w: window.innerWidth, h: window.innerHeight });
  useEffect(() => {
    let t = 0;
    const on = () => {
      window.clearTimeout(t);
      t = window.setTimeout(() => setVp({ w: window.innerWidth, h: window.innerHeight }), 80);
    };
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return vp;
}

function useReducedMotion() {
  const q = "(prefers-reduced-motion: reduce)";
  const [reduce, setReduce] = useState(() => window.matchMedia?.(q).matches ?? false);
  useEffect(() => {
    const m = window.matchMedia?.(q);
    if (!m) return;
    const on = () => setReduce(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return reduce;
}

export function App() {
  const planner = usePlanner();
  const { s, derived, actions } = planner;
  const vp = useViewport();
  const reducedMotion = useReducedMotion();
  const layout = useMemo(() => layoutFor(vp.w, vp.h, s.sideOpen), [vp.w, vp.h, s.sideOpen]);

  // `]` toggles the side panel (not while typing)
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName ?? "";
      if (e.key === "]" && !/input|textarea|select/i.test(tag)) actions.toggleSide();
      if (e.key === "Escape") actions.select(null);
    };
    window.addEventListener("keyup", on);
    return () => window.removeEventListener("keyup", on);
  }, [actions]);

  // GeoJSON for the map layers, rebuilt only when something it depends on changes
  const geo = useMemo(
    () =>
      s.model
        ? buildGeo({
            model: s.model,
            yr: derived.yr,
            layer: s.layer,
            sel: s.sel,
            bindLines: derived.bindLines,
            outLines: derived.outLines,
            diffDeltas: derived.diffDeltas,
          })
        : null,
    [s.model, derived.yr, s.layer, s.sel, derived.bindLines, derived.outLines, derived.diffDeltas],
  );

  const showFrame = !derived.onMain;
  return (
    <div className={`stage${layout.narrow ? " narrow" : ""}`} style={hueVars(derived.hue, derived.onMain)}>
      <MapView planner={planner} geo={geo} layout={layout} reducedMotion={reducedMotion} />
      {showFrame && <div className="branch-frame" />}
      <Header planner={planner} layout={layout} />
      <LeftCards planner={planner} layout={layout} />
      {s.diffMode && !derived.onMain && <DiffBanner planner={planner} layout={layout} />}
      <LayerToggle planner={planner} layout={layout} />
      <MapCorner planner={planner} layout={layout} />
      <DetailCards planner={planner} layout={layout} />
      {layout.showDock && <Roadmap planner={planner} layout={layout} />}
      <SidePanel planner={planner} layout={layout} />
      {s.running && <RunOverlay planner={planner} layout={layout} />}
    </div>
  );
}
