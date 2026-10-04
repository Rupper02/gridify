// Loading the branch list.

import { useCallback } from "react";

import { api } from "../../api";
import type { Core } from "./core";

export function useBranchList({ patch, ref }: Core) {
  const refreshBranches = useCallback(async () => {
    try {
      const branches = await api.listBranches(ref.current.projectId);
      patch({ branches, branchesLoaded: true });
      return branches;
    } catch {
      return null;
    }
  }, [patch, ref]);

  return { refreshBranches };
}
