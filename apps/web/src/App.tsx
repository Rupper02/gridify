import { useMemo } from "react";

import { Header } from "./components/Header";
import { MapView } from "./components/MapView";
import { Roadmap } from "./components/Roadmap";
import { SidePanel } from "./components/SidePanel";
import { usePlanner } from "./hooks/usePlanner";
import { bindingSets, buildProjList, busProjectsOf, selectedElement } from "./lib/derive";
import { buildGeo } from "./lib/geo";

export function App() {
  const planner = usePlanner();
  const { s, derived } = planner;
  const { q, qById, ph } = derived;

  const projList = useMemo(() => buildProjList(q, s.timelineYear), [q, s.timelineYear]);
  const { bindLines, bindBuses } = useMemo(() => bindingSets(q), [q]);
  const busProjects = useMemo(() => busProjectsOf(q), [q]);
  const { selQ, selEl } = useMemo(() => selectedElement(s.sel, qById), [s.sel, qById]);
  const over = useMemo(() => new Set(ph?.overloaded_line_ids ?? []), [ph]);
  const vv = useMemo(() => new Set(ph?.voltage_violation_bus_ids ?? []), [ph]);

  // GeoJSON for the map layers, rebuilt only when something it depends on changes
  const geo = useMemo(
    () =>
      s.model
        ? buildGeo({
            model: s.model,
            projList,
            sel: s.sel,
            hov: s.hover,
            selEl,
            bindLines,
            bindBuses,
            over,
            lineLoading: ph?.line_loading ?? {},
            busVm: ph?.bus_vm ?? {},
            voltageViolations: vv,
            pickMode: s.pickMode,
            loadingMode: s.loadingMode,
            voltageMode: s.voltageMode,
            drawerBus: s.drawer ? s.form.bus : "",
            weightByRating: true,
          })
        : null,
    [s.model, projList, s.sel, s.hover, selEl, bindLines, bindBuses, over, ph, vv, s.pickMode, s.loadingMode, s.voltageMode, s.drawer, s.form.bus],
  );

  return (
    <div className="app">
      <Header planner={planner} />
      <div className="main">
        <div className="left">
          <MapView planner={planner} geo={geo} projList={projList} selQ={selQ} selEl={selEl} bindLines={bindLines} busProjects={busProjects} over={over} vv={vv} />
          <Roadmap planner={planner} />
        </div>
        <SidePanel planner={planner} />
      </div>
    </div>
  );
}
