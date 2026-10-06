// The registry of not-yet-built projects: load it, pull one onto the active branch (as preliminary).

import { useCallback } from "react";

import { api } from "../../api";
import type { RegistryItem } from "../../types";
import type { Core } from "./core";

/** Remember a project added to a branch: it shows as Preliminary until a run includes it. */
export const withAdded = (added: Record<string, RegistryItem[]>, bid: string, row: RegistryItem) => ({
  ...added,
  [bid]: [...(added[bid] ?? []).filter((a) => a.request_id !== row.request_id), { ...row, branch_id: bid }],
});

export function useRegistry(
  { patch, ref, toastMsg }: Core,
  ensureEditableBranch: () => Promise<string | null>,
  refreshBranches: () => Promise<unknown>,
) {
  const loadRegistry = useCallback(async () => {
    if (ref.current.registryLoaded) return;
    try {
      const registry = await api.getRegistry(ref.current.projectId);
      patch({ registry, registryLoaded: true });
    } catch {
      toastMsg("Could not load the registry. Check the API is running.", "warn");
    }
  }, [patch, ref, toastMsg]);

  /** Pull a project from the registry onto the active branch. It waits, unranked, for the next run. */
  const addRegistryProject = useCallback(
    async (requestId: string) => {
      const bid = await ensureEditableBranch();
      if (!bid) return;
      try {
        const row = await api.addFromRegistry(bid, requestId);
        // the branch's stored projects too: the project card reads its control mode from them
        patch((st) => ({
          added: withAdded(st.added, bid, row),
          candidates: st.activeBranch === bid ? [...st.candidates.filter((c) => c.request_id !== row.request_id), row] : st.candidates,
        }));
        void refreshBranches();
        toastMsg(`${requestId} added to Preliminary. Run to rank it against the queue.`);
      } catch {
        toastMsg("Could not add that project. Check the API is running.", "warn");
      }
    },
    [ensureEditableBranch, patch, refreshBranches, toastMsg],
  );

  return { loadRegistry, addRegistryProject };
}
