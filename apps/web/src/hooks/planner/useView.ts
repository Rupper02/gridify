// The view: which tab and year are shown, the panels and toggles, and the map's zoom buttons. Nothing here loads or runs.

import { useMemo } from "react";

import { clampYear } from "../../lib/plan";
import type { Tab } from "../../types";
import type { Core, FindingsFocus } from "./core";

export function useView({ patch, mapApi }: Core) {
  return useMemo(
    () => ({
      /** Open a tab; the Capacity tab brings the map's Headroom layer with it (its figures are that layer's). */
      setTab: (tab: Tab) => patch({ tab, sideOpen: true, ...(tab === "capacity" ? { layer: "headroom" as const } : {}) }),
      /** Open the Limits tab with its findings ledger unfolded on a group (the tab expands it once, then clears the focus). */
      showLimits: (focus: FindingsFocus | null = null) => patch({ tab: "limits", sideOpen: true, findingsFocus: focus }),  // no focus: the tab as it stands, binding set first
      clearFindingsFocus: () => patch({ findingsFocus: null }),
      setYear: (year: number) => patch((st) => (st.plan ? { year: clampYear(st.plan, year) } : {})),
      toggleLeft: () => patch((st) => ({ leftFolded: !st.leftFolded })),
      toggleDock: () => patch((st) => ({ dockFolded: !st.dockFolded })),
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
