// The planner controller: one state object (mirroring the API + UI), the actions that drive it, and
// a handle to the map. Components are pure functions of what this returns.
//
// This file only composes. The state and shared core live in planner/core.ts; each concern is its
// own hook under planner/ (run + boot, branch list, branch flows, registry, selection, project
// edits, maintenance, the agents, ask, projects, derived values), taking the core plus only the other hooks' actions
// it needs.

import { useCallback, useMemo, useRef } from "react";

import { clampYear } from "../lib/plan";
import type { ElementSel, Tab } from "../types";
import { useCore } from "./planner/core";
import { useAgents } from "./planner/useAgents";
import { useAsk } from "./planner/useAsk";
import { useBranchFlows } from "./planner/useBranchFlows";
import { useBranchList } from "./planner/useBranchList";
import { useDerived } from "./planner/useDerived";
import { useFindings } from "./planner/useFindings";
import { useAutoRefresh } from "./planner/useAutoRefresh";
import { useMaintenance } from "./planner/useMaintenance";
import { useMapFeatures } from "./planner/useMapFeatures";
import { useProjects } from "./planner/useProjects";
import { useProjectEdits } from "./planner/useProjectEdits";
import { useRegistry } from "./planner/useRegistry";
import { useRun } from "./planner/useRun";
import { useSelection } from "./planner/useSelection";

export type { MapApi, PlannerState } from "./planner/core";

export function usePlanner() {
  const { s, core } = useCore();
  const { patch, ref, mapApi } = core;

  // the run and the branch flows need each other (a run refreshes the diff; a branch switch runs):
  // the run reaches the flows through this ref, filled once they exist
  const afterRunRef = useRef<(bid: string) => void>(() => {});
  const afterRun = useCallback((bid: string) => afterRunRef.current(bid), []);

  const { refreshBranches } = useBranchList(core);
  const run = useRun(core, afterRun);
  const projects = useProjects(core, run);
  const edited = useAutoRefresh(core, run);
  const maint = useMaintenance(core, edited);
  const flows = useBranchFlows(core, run, refreshBranches, maint.loadExtras, edited);
  const findings = useFindings(core);
  const agents = useAgents(core, s.projectId);
  const ask = useAsk(core, run, refreshBranches, maint.loadExtras, edited);
  afterRunRef.current = (bid: string) => {
    void refreshBranches();
    void findings.loadFindings(bid);
    void agents.loadReviews(bid); // the reviewer comments a few seconds later; the status poll refreshes it
    void (async () => {
      await flows.refreshDiff(bid); // the diff solves main's years if need be; the gate then finds them cached
      await flows.refreshMergeCheck(bid);
    })();
  };
  const { loadRegistry, addRegistryProject } = useRegistry(core, flows.ensureEditableBranch, refreshBranches);
  const { select, selectProject, focusSel } = useSelection(core);
  const { setSchedule, setControl } = useProjectEdits(core, edited);
  const mapView = useMapFeatures(core, s.visible);
  const derived = useDerived(s);

  const actions = useMemo(
    () => ({
      run, toastMsg: core.toastMsg, select, selectProject, focusSel, setSchedule, setControl, loadRegistry, addRegistryProject,
      ...flows,
      ...maint,
      ...mapView,
      ...findings,
      ...agents,
      ...ask,
      ...projects,
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
      /** Schedule maintenance on the selected element; on main this opens a branch for it first. */
      scheduleOutage: async (sel: ElementSel) => {
        const bid = await flows.ensureEditableBranch();
        if (!bid) return;
        await maint.addOutage(sel, bid);
        await maint.loadExtras(bid); // a new branch loads its (empty) list too: settle on the API's view
      },
      /** Review the branch: open the Review tab (Merge lives there). A run still solving asks for both itself
       * when it is done, so nothing is asked of a result that is not there yet. */
      goReview: () => {
        patch({ tab: "review", sideOpen: true });
        if (ref.current.solving) return;
        if (!ref.current.diff) void flows.refreshDiff(ref.current.activeBranch);
        if (!ref.current.mergeCheck) void flows.refreshMergeCheck(ref.current.activeBranch);
      },
    }),
    // each hook's callbacks are stable; the objects holding them are not, so depend on the callbacks
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [addRegistryProject, core.toastMsg, focusSel, loadRegistry, mapApi, patch, ref, run, select, selectProject, setSchedule, setControl,
      ...Object.values(flows), ...Object.values(maint), ...Object.values(mapView), ...Object.values(findings), ...Object.values(agents), ...Object.values(ask), ...Object.values(projects)],
  );

  return { s, patch, actions, derived, mapApi };
}

export type Planner = ReturnType<typeof usePlanner>;
