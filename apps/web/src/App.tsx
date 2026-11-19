// The composition root: the one place that sees the whole planner. It lays the floating panels over the full-bleed map
// for the viewport (lib/layout.ts).

import { CaretLeft } from "@phosphor-icons/react";
import { useEffect, useMemo } from "react";

import { DetailCard } from "./components/DetailCard";
import { Header } from "./components/Header";
import { LeftCards } from "./components/LeftCards";
import { MapControls, Toasts } from "./components/MapControls";
import { MapView } from "./components/MapView";
import { SidePanel } from "./components/SidePanel";
import { Timeline } from "./components/Timeline";
import { hueVars } from "./components/ui";
import { usePlanner } from "./hooks/usePlanner";
import { useReducedMotion, useViewport } from "./hooks/useViewport";
import { buildGeo } from "./lib/geo";
import { layoutFor } from "./lib/layout";

export function App() {
  const planner = usePlanner();
  const { s, derived, actions } = planner;
  const vp = useViewport();
  const reducedMotion = useReducedMotion();
  const layout = useMemo(() => layoutFor(vp.w, vp.h, s.sideOpen), [vp.w, vp.h, s.sideOpen]);

  // `]` toggles the side panel (not while typing); Escape clears the selection
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName ?? "";
      if (e.key === "]" && !/input|textarea|select/i.test(tag)) actions.toggleSide();
      if (e.key === "Escape") {
        actions.select(null);
        actions.toggleMenu(false);
      }
    };
    window.addEventListener("keyup", on);
    return () => window.removeEventListener("keyup", on);
  }, [actions]);

  const geo = useMemo(
    () => (s.model ? buildGeo({ model: s.model, yr: derived.yr, layer: s.layer, sel: s.sel, diff: derived.diffMap, visible: s.visible, tiers: derived.tiers, run: derived.runView }) : null),
    [s.model, derived.yr, s.layer, s.sel, derived.diffMap, s.visible, derived.tiers, derived.runView],
  );

  return (
    <div className={`stage${layout.narrow ? " narrow" : ""}`} style={hueVars(derived.hue, derived.onMain)}>
      <MapView planner={planner} geo={geo} layout={layout} reducedMotion={reducedMotion} />
      {!derived.onMain && <div className="branch-frame" />}
      <Header planner={planner} wide={layout.wide} />
      {s.sel ? <DetailCard planner={planner} layout={layout} /> : <LeftCards planner={planner} compact={layout.compactReadings} />}
      <MapControls planner={planner} layout={layout} />
      {layout.showDock && <Timeline planner={planner} layout={layout} />}
      <SidePanel planner={planner} />
      {!s.sideOpen && (
        <button className="reopen glass" onClick={actions.toggleSide}>
          <CaretLeft size={13} /> Panel
        </button>
      )}
      <Toasts planner={planner} />
    </div>
  );
}
