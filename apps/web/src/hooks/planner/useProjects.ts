// Projects: the grids the planner can plan on. Boot loads the list and opens the default project;
// switching loads that project's model, boundary and branches, then runs its main; importing a file
// adds a project (the API validates it) and the projects screen shows the report; deleting an import
// removes it and falls back to the built-in project. The project's assumptions load on demand.

import { useCallback, useEffect } from "react";

import { api } from "../../api";
import { DEFAULT_PROJECT_ID, mainIdOf } from "../../lib/projects";
import type { Project } from "../../types";
import { EMPTY_CHAT } from "./core";
import type { Core, PlannerState } from "./core";
import type { RunFn } from "./useRun";

/** What a project switch resets: everything that belonged to the previous project's branches and result. */
const FRESH: Partial<PlannerState> = {
  result: null, resultAt: "", prevStatus: {}, added: {}, outages: [], reinforcements: [],
  diff: null, diffMode: false, suggestions: null, mergeCheck: null, findings: [], findingCounts: null, reviews: [], thread: null, trace: [], study: null,
  registry: [], registryLoaded: false, assumptions: null, showAssumptions: false, sel: null, chat: EMPTY_CHAT,
};

export function useProjects({ patch, ref, mapApi, toastMsg }: Core, run: RunFn) {
  const loadProjects = useCallback(async (): Promise<Project[] | null> => {
    try {
      const projects = await api.listProjects();
      patch({ projects });
      return projects;
    } catch {
      return null;
    }
  }, [patch]);

  /** Load a project's grid into the planner and run its main (ignored if the planner moved to another project meanwhile). */
  const loadProject = useCallback(
    async (pid: string, projects?: Project[]) => {
      const mainId = mainIdOf(projects ?? ref.current.projects, pid);
      const caps = (projects ?? ref.current.projects).find((p) => p.project_id === pid)?.capabilities;
      const [model, boundary, branches] = await Promise.all([api.getModel(pid), api.getBoundary(pid), api.listBranches(pid)]);
      if (ref.current.projectId !== pid) return;
      patch((st) => ({
        model, boundary, branches, branchesLoaded: true, activeBranch: mainId,
        layer: caps && !caps.regions && st.layer === "demand" ? "flow" : st.layer, // no demand groups, no Demand layer
      }));
      mapApi.current?.fit(false);
      void run({ activeBranch: mainId });
    },
    [mapApi, patch, ref, run],
  );

  /** Switch to a project: the map, the branches, the queue and every panel follow it. */
  const openProject = useCallback(
    async (pid: string) => {
      if (pid === ref.current.projectId) {
        patch({ projectsOpen: false });
        return;
      }
      patch({ projectId: pid, projectsOpen: false, menuOpen: false, ...FRESH });
      try {
        await loadProject(pid);
      } catch (e) {
        toastMsg(`Could not open the project: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
      }
    },
    [loadProject, patch, ref, toastMsg],
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
        toastMsg(`Could not remove ${name}: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
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
    } catch {
      toastMsg("Could not load the assumptions. Check the API is running.", "warn");
    }
  }, [patch, ref, toastMsg]);

  // ---- boot: the projects and the forecasts, then the default project ---------------------------------------
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [projects, fc] = await Promise.all([api.listProjects(), api.getForecasts()]);
        if (cancelled) return;
        patch({ projects, forecasts: fc.forecasts, maxMw: fc.maxMw });
        await loadProject(ref.current.projectId, projects);
      } catch (e) {
        if (!cancelled) toastMsg(`Could not load the model: ${e instanceof Error ? e.message : "is the API running?"}`, "warn");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadProject, patch, ref, toastMsg]);

  return { loadProjects, openProject, importProject, deleteProject, openProjects, closeProjects, toggleAssumptions };
}
