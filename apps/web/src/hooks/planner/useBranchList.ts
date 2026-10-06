// Loading the branch list.

import { useCallback } from "react";

import { api, failureText } from "../../api";
import type { Core } from "./core";

export function useBranchList({ patch, ref, toastMsg }: Core) {
  const refreshBranches = useCallback(async () => {
    const pid = ref.current.projectId;
    try {
      const branches = await api.listBranches(pid);
      if (ref.current.projectId === pid) patch({ branches });
      return branches;
    } catch (e) {
      if (ref.current.projectId === pid) toastMsg(`Could not load the branches: ${failureText(e)}`, "warn");
      return null;
    }
  }, [patch, ref, toastMsg]);

  return { refreshBranches };
}
