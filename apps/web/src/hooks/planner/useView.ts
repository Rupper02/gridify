// The view: which tab and year are shown, the panels and toggles, and the map's zoom buttons. Nothing here loads or runs.

import { useMemo } from "react";

import { clampYear } from "../../lib/plan";
import type { Tab } from "../../types";
import type { Core } from "./core";

export function useView({ patch, mapApi }: Core) {
  return useMemo(
    () => ({
      setTab: (tab: Tab) => patch({ tab, sideOpen: true }),
      setYear: (year: number) => patch((st) => (st.plan ? { year: clampYear(st.plan, year) } : {})),
      toggleSide: () => patch((st) => ({ sideOpen: !st.sideOpen })),
      toggleMenu: () => patch((st) => ({ menuOpen: !st.menuOpen })),
      toggleDeferred: () => patch((st) => ({ showDeferred: !st.showDeferred })),
      toggleLegend: () => patch((st) => ({ legendOpen: !st.legendOpen })),
      toggleBoundary: () => patch((st) => ({ showBoundary: !st.showBoundary })),
      zoomIn: () => mapApi.current?.zoomBy(1),
      zoomOut: () => mapApi.current?.zoomBy(-1),
      zoomFit: () => mapApi.current?.fit(true),
    }),
    [mapApi, patch],
  );
}
