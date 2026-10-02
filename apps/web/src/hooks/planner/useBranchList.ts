// Loading the branch list.

import { useCallback } from "react";

import { api } from "../../api";
import type { Core } from "./core";

export function useBranchList({ patch, ref, toastMsg }: Core) {
  const refreshBranches = useCallback(async () => {
    try {
      const branches = await api.listBranches();
      patch({ branches, branchesLoaded: true });
      return branches;
    } catch {
      return null;
    }
  }, [patch]);

  const ensureBranches = useCallback(async () => {
    if (ref.current.branchesLoaded) return;
    try {
      const branches = await api.listBranches();
      patch({ branches, branchesLoaded: true });
    } catch {
      toastMsg("Could not load branches — check the API is running.");
    }
  }, [patch, ref, toastMsg]);

  return { refreshBranches, ensureBranches };
}
