// The planner controller: one state object (mirroring the API + UI), the actions that drive it, and
// a handle to the map. Components are pure functions of what this returns.
//
// This file only composes. The state and shared core live in planner/core.ts; each concern is its
// own hook under planner/ (run + boot, branch list, branch flows, registry, selection, project
// edits, derived values), taking the core plus only the other hooks' actions it needs.

import { useMemo } from "react";

import type { Tab } from "../types";
import { useCore } from "./planner/core";
import { useBranchFlows } from "./planner/useBranchFlows";
import { useBranchList } from "./planner/useBranchList";
import { useDerived } from "./planner/useDerived";
import { useProjectEdits } from "./planner/useProjectEdits";
import { useRegistry } from "./planner/useRegistry";
import { useRun } from "./planner/useRun";
import { useSelection } from "./planner/useSelection";

export type { MapApi, PlannerState } from "./planner/core";

export function usePlanner() {
  const { s, core } = useCore();
  const { patch, ref, mapApi } = core;

  const { refreshBranches, ensureBranches } = useBranchList(core);
  const run = useRun(core, refreshBranches);
  const { selectProject, setForm, pick, focusSel } = useSelection(core);
  const {
    selectBranch, ensureEditableBranch, createBranchFlow, runBranchDiff, runSuggestions, mergeBranchFlow, discardBranchFlow,
  } = useBranchFlows(core, run, refreshBranches);
  const { addRegistryProject, loadRegistry } = useRegistry(core, run, ensureEditableBranch, refreshBranches);
  const { submit, setSchedule } = useProjectEdits(core, run, ensureEditableBranch, refreshBranches, runBranchDiff, selectProject);
  const derived = useDerived(s);

  const formInvalid = !s.form.bus || !(+s.form.mw > 0);

  const actions = useMemo(
    () => ({
      run, toastMsg: core.toastMsg, selectProject, pick, focusSel, setForm, submit, setSchedule,
      selectBranch, ensureBranches, refreshBranches, addRegistryProject, loadRegistry,
      createBranchFlow, runBranchDiff, runSuggestions, mergeBranchFlow, discardBranchFlow,
      /** Header shortcut: open the Review tab with the new-branch form showing. */
      newBranchQuick: () => {
        void ensureBranches();
        patch({ tab: "compare", showNewBranch: true });
      },
      setTab: (tab: Tab) => {
        patch({ tab });
        if (tab === "compare") void ensureBranches();
      },
      onForecast: (id: string) => {
        if (ref.current.activeBranch !== "main") return;
        const x = ref.current.forecasts.find((y) => y.id === id);
        patch(x ? { forecastId: id, g30: x.growth_2030, g35: x.growth_2035 } : { forecastId: id });
      },
      toggleRegistry: () => {
        if (!ref.current.registryLoaded) void loadRegistry();
        patch((st) => ({ showRegistry: !st.showRegistry }));
      },
      zoomIn: () => mapApi.current?.zoomBy(1),
      zoomOut: () => mapApi.current?.zoomBy(-1),
      zoomFit: () => mapApi.current?.fit(true),
      newApplicationAt: (busId: number) => {
        setForm({ bus: String(busId) });
        patch({ drawer: true });
      },
    }),
    [
      addRegistryProject, core.toastMsg, createBranchFlow, discardBranchFlow, ensureBranches, focusSel, loadRegistry,
      mapApi, mergeBranchFlow, patch, pick, refreshBranches, ref, run, runBranchDiff, runSuggestions, selectBranch,
      selectProject, setForm, setSchedule, submit,
    ],
  );

  return { s, patch, actions, derived, mapApi, formInvalid };
}

export type Planner = ReturnType<typeof usePlanner>;
