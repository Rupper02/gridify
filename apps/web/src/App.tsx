// The composition root: the one place that sees the whole planner. It lays the floating panels over
// the full-bleed map for the viewport (lib/layout.ts) and hands each component its slice.

import { useEffect, useMemo } from "react";

import { DetailCards } from "./components/DetailCards";
import { Header } from "./components/Header";
import { LeftCards } from "./components/LeftCards";
import { DiffBanner, LayerToggle, MapCorner } from "./components/MapControls";
import { MapView } from "./components/MapView";
import { ProjectsScreen } from "./components/ProjectsScreen";
import { RegionCard } from "./components/RegionCard";
import { Roadmap } from "./components/Roadmap";
import { RunOverlay } from "./components/RunOverlay";
import { SidePanel } from "./components/SidePanel";
import { StudyDrawer } from "./components/StudyDrawer";
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

  // `]` toggles the side panel (not while typing); Escape closes the projects screen, else clears the selection
  const projectsOpen = s.projectsOpen;
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName ?? "";
      if (e.key === "]" && !/input|textarea|select/i.test(tag)) actions.toggleSide();
      if (e.key === "Escape") {
        if (projectsOpen) actions.closeProjects();
        else actions.select(null);
      }
    };
    window.addEventListener("keyup", on);
    return () => window.removeEventListener("keyup", on);
  }, [actions, projectsOpen]);

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
            visible: s.visible,
            tiers: derived.tiers,
          })
        : null,
    [s.model, derived.yr, s.layer, s.sel, derived.bindLines, derived.outLines, derived.diffDeltas, s.visible, derived.tiers],
  );

  const showFrame = !derived.onMain;
  return (
    <div className={`stage${layout.narrow ? " narrow" : ""}`} style={hueVars(derived.hue, derived.onMain)}>
      <MapView key={s.model?.crs ?? "wgs84"} planner={planner} geo={geo} layout={layout} reducedMotion={reducedMotion} />
      {showFrame && <div className="branch-frame" />}
      <Header planner={planner} layout={layout} />
      <LeftCards planner={planner} layout={layout} />
      {s.diffMode && !derived.onMain && <DiffBanner planner={planner} layout={layout} />}
      <LayerToggle planner={planner} layout={layout} />
      <MapCorner planner={planner} layout={layout} />
      <DetailCards planner={planner} layout={layout} />
      {s.sel?.kind === "region" && <RegionCard planner={planner} layout={layout} />}
      {s.study && <StudyDrawer planner={planner} />}
      {s.projectsOpen && <ProjectsScreen planner={planner} />}
      {layout.showDock && <Roadmap planner={planner} layout={layout} />}
      <SidePanel planner={planner} layout={layout} />
      {derived.run.overlay && <RunOverlay planner={planner} layout={layout} />}
    </div>
  );
}
