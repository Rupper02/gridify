// Projects: the grids the planner can plan on. Boot loads the list and opens the default project;
// switching loads that project's model, branches and demand pathways (an import's are the forecast entered
// with it), runs its main and fetches its boundary card on
// its own; importing a file adds a project (the API validates it) and the projects screen shows the
// report; deleting an import removes it and falls back to the built-in project. The project's
// assumptions load on demand.
//
// Loading is told, not assumed: the result stamp says the grid is loading, and a step that fails (the
// API still starting, or restarting under --reload) is retried with a growing pause (lib/boot.ts) and
// then shown on the stamp with a Retry, never only as a toast that fades.

import { useCallback, useEffect } from "react";

import { api, failureText, onWarehouse } from "../../api";
import { retrying, retryable } from "../../lib/boot";
import { DEFAULT_PROJECT_ID, mainIdOf } from "../../lib/projects";
import type { Project } from "../../types";
import { BRANCH_FRESH } from "./core";
import type { Core, PlannerState } from "./core";
import type { RunFn } from "./useRun";

/** What a project switch resets: everything that belonged to the previous project's grid, branches and result. */
const FRESH: Partial<PlannerState> = {
  ...BRANCH_FRESH, model: null, boundary: null, modelLoading: true, modelError: null, branches: [], activeBranch: "",
  result: null, resultAt: "", added: {}, agents: null, agentRuns: [], runsOpen: false, healthChecks: [], registry: [], registryLoaded: false, assumptions: null, showAssumptions: false,
};

export function useProjects({ patch, ref, mapApi, toastMsg }: Core, run: RunFn) {
  const loadProjects = useCallback(async (): Promise<Project[] | null> => {
    try {
      const projects = await api.listProjects();
      patch({ projects });
      return projects;
    } catch (e) {
      toastMsg(`Could not load the projects: ${failureText(e)}`, "warn");
      return null;
    }
  }, [patch, toastMsg]);

  /** The project's transmission boundary card, fetched after the grid is up: on a cold API it is a full power flow. */
  const loadBoundary = useCallback(
    async (pid: string) => {
      try {
        const boundary = await retrying(() => api.getBoundary(pid), { shouldRetry: (e) => ref.current.projectId === pid && retryable(e) });
        if (ref.current.projectId === pid) patch({ boundary });
      } catch (e) {
        if (ref.current.projectId === pid) toastMsg(`Could not load the boundary card: ${failureText(e)}`, "warn");
      }
    },
    [patch, ref, toastMsg],
  );

  /**
   * Load a project's grid into the planner and run its main. The model and the branches come first
   * (the map is drawn as soon as they are in); the run starts and the boundary card follows on its own.
   * A failure is retried, then recorded for the stamp. Ignored if the planner moved to another project meanwhile.
   */
  const loadProject = useCallback(
    async (pid: string, projects?: Project[]) => {
      const mainId = mainIdOf(projects ?? ref.current.projects, pid);
      const caps = (projects ?? ref.current.projects).find((p) => p.project_id === pid)?.capabilities;
      const current = () => ref.current.projectId === pid;
      patch({ modelLoading: true, modelError: null });
      try {
        const [model, branches, forecasts] = await retrying(() => Promise.all([api.getModel(pid), api.listBranches(pid), api.getProjectForecasts(pid)]), {
          shouldRetry: (e) => current() && retryable(e),
        });
        if (!current()) return;
        patch((st) => ({
          model, branches, forecasts, activeBranch: mainId, modelLoading: false,
          layer: caps && !caps.regions && st.layer === "demand" ? "flow" : st.layer, // no demand groups, no Demand layer
        }));
      } catch (e) {
        if (current()) patch({ modelLoading: false, modelError: failureText(e) });
        return;
      }
      mapApi.current?.fit(false);
      void run({ activeBranch: mainId });
      void loadBoundary(pid);
    },
    [loadBoundary, mapApi, patch, ref, run],
  );

  /** Switch to a project: the map, the branches, the queue and every panel follow it. */
  const openProject = useCallback(
    async (pid: string) => {
      if (pid === ref.current.projectId) {
        patch({ projectsOpen: false });
        return;
      }
      patch({ projectId: pid, projectsOpen: false, menuOpen: false, ...FRESH });
      await loadProject(pid);
    },
    [loadProject, patch, ref],
  );

  /**
   * Import a grid as a project. The API validates it and answers with the project and its report;
   * a refusal (415, 413, 422 with the report) is thrown for the projects screen to show.
   */
  const importProject = useCallback(
    async (file: File, name: string, limits: Record<string, string>): Promise<Project> => {
      const p = await api.importProject(file, name, limits);
      await loadProjects();
      toastMsg(`Imported ${p.name}: ${p.report?.counts.buses ?? "?"} buses, ${p.report?.cases.length ?? 0} study case${p.report?.cases.length === 1 ? "" : "s"}.`);
      return p;
    },
    [loadProjects, toastMsg],
  );

  const deleteProject = useCallback(
    async (pid: string) => {
      const name = ref.current.projects.find((p) => p.project_id === pid)?.name ?? pid;
      try {
        await api.deleteProject(pid);
        await loadProjects();
        toastMsg(`${name} removed, with its branches.`);
        if (ref.current.projectId === pid) await openProject(DEFAULT_PROJECT_ID);
      } catch (e) {
        toastMsg(`Could not remove ${name}: ${failureText(e)}`, "warn");
      }
    },
    [loadProjects, ref, openProject, toastMsg],
  );

  const openProjects = useCallback(() => patch({ projectsOpen: true, menuOpen: false }), [patch]);
  const closeProjects = useCallback(() => patch({ projectsOpen: false }), [patch]);

  /** Show or hide what the active project's model assumes (loaded on first use). */
  const toggleAssumptions = useCallback(async () => {
    const st = ref.current;
    if (st.showAssumptions) {
      patch({ showAssumptions: false });
      return;
    }
    patch({ showAssumptions: true });
    if (st.assumptions) return;
    try {
      const r = await api.getAssumptions(st.projectId);
      if (ref.current.projectId === st.projectId) patch({ assumptions: r.assumptions });
    } catch (e) {
      toastMsg(`Could not load the assumptions: ${failureText(e)}`, "warn");
    }
  }, [patch, ref, toastMsg]);

  // ---- boot: the projects and the forecasts, then the default project ---------------------------------------
  /** `isCancelled` stops a boot the component has left behind (React's development double-mount). */
  const boot = useCallback(
    async (isCancelled: () => boolean) => {
      patch({ modelLoading: true, modelError: null });
      try {
        const [projects, fc] = await retrying(() => Promise.all([api.listProjects(), api.getForecasts()]), { shouldRetry: (e) => !isCancelled() && retryable(e) });
        if (isCancelled()) return;
        patch({ projects, forecasts: fc.forecasts, defaultScenario: fc.defaultScenario, plan: fc.plan, year: fc.plan.phase1 });
        await loadProject(ref.current.projectId, projects);
      } catch (e) {
        if (!isCancelled()) patch({ modelLoading: false, modelError: failureText(e) });
      }
    },
    [loadProject, patch, ref],
  );

  // whether what the warehouse served was its previous version (the pipeline writing a new one): the stamp says so
  useEffect(() => {
    onWarehouse((stale) => {
      if (ref.current.warehouseStale !== stale) patch({ warehouseStale: stale });
    });
    return () => onWarehouse(null);
  }, [patch, ref]);

  useEffect(() => {
    let cancelled = false;
    void boot(() => cancelled);
    return () => {
      cancelled = true;
    };
  }, [boot]);

  /** Try again after a failed load (the stamp's Retry): the projects too, if they never arrived. */
  const retryLoad = useCallback(
    () => (ref.current.projects.length ? loadProject(ref.current.projectId) : boot(() => false)),
    [boot, loadProject, ref],
  );

  return { loadProjects, openProject, importProject, deleteProject, openProjects, closeProjects, toggleAssumptions, retryLoad };
}
