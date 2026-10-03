// Loading the branch list.

import { useCallback } from "react";

import { api } from "../../api";
import type { Core } from "./core";

export function useBranchList({ patch }: Core) {
  const refreshBranches = useCallback(async () => {
    try {
      const branches = await api.listBranches();
      patch({ branches, branchesLoaded: true });
      return branches;
    } catch {
      return null;
    }
  }, [patch]);

  return { refreshBranches };
}
