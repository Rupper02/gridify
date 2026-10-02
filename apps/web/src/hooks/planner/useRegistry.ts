// The registry of not-yet-built projects: load it, pull one onto the active branch.

import { useCallback } from "react";

import { api } from "../../api";
import type { Branch } from "../../types";
import type { Core } from "./core";
import type { RunFn } from "./useRun";

export function useRegistry(
  { patch, ref, toastMsg }: Core,
  run: RunFn,
  ensureEditableBranch: () => Promise<string | null>,
  refreshBranches: () => Promise<Branch[] | null>,
) {
  /** Pull a project from the registry onto the active branch, then re-run so it appears. */
  const addRegistryProject = useCallback(
    async (requestId: string) => {
      const branchId = await ensureEditableBranch();
      if (!branchId) return;
      // take it off the registry list straight away: the re-run that reflects it can take a while
      const setPending = (on: boolean) =>
        patch((st) => {
          const p = { ...st.pendingAdds };
          if (on) p[requestId] = true;
          else delete p[requestId];
          return { pendingAdds: p };
        });
      setPending(true);
      try {
        const row = await api.addFromRegistry(branchId, requestId);
        await refreshBranches();
        patch({ diff: null, suggestions: null });
        await run({ activeBranch: branchId });
        toastMsg(`${requestId}${row?.applicant ? ` · ${row.applicant}` : ""} added to the branch — the map and Queue update when the run finishes.`);
      } catch {
        setPending(false);
        toastMsg("Could not add that project — check the API is running.");
      }
    },
    [ensureEditableBranch, patch, refreshBranches, run, toastMsg],
  );

  const loadRegistry = useCallback(async () => {
    if (ref.current.registryLoaded) return;
    try {
      const registry = await api.getRegistry();
      patch({ registry, registryLoaded: true });
    } catch {
      toastMsg("Could not load the registry — check the API is running.");
    }
  }, [patch, ref, toastMsg]);

  return { addRegistryProject, loadRegistry };
}
