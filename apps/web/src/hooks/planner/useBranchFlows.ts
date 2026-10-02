// Branch flows ("git for grids"): switch, open, diff, suggestions, merge, discard.

import { useCallback } from "react";

import { api } from "../../api";
import type { Branch } from "../../types";
import type { Core } from "./core";
import type { RunFn } from "./useRun";

export function useBranchFlows(
  { patch, ref, toastMsg }: Core,
  run: RunFn,
  refreshBranches: () => Promise<Branch[] | null>,
) {
  /** Switch the active branch: the whole view (map, Queue, tiles, roadmap) follows it. */
  const selectBranch = useCallback(
    (id: string) => {
      if (id === ref.current.activeBranch) return;
      patch({ activeBranch: id, diff: null, suggestions: null, sel: null, pendingAdds: {} });
      void run({ activeBranch: id });
    },
    [patch, ref, run],
  );

  /** Adds always target a branch (main is the plan of record). On main, auto-create + switch to one. */
  const ensureEditableBranch = useCallback(async (): Promise<string | null> => {
    const st = ref.current;
    if (st.activeBranch && st.activeBranch !== "main") return st.activeBranch;
    try {
      const b = await api.createBranch({ name: "Draft plan", from_branch: "main", scenario: st.forecastId });
      await refreshBranches();
      patch({ activeBranch: b.branch_id, showNewBranch: false, diff: null, suggestions: null });
      toastMsg(`Opened branch “${b.name}” off main — your changes stay here until you merge.`);
      return b.branch_id;
    } catch {
      toastMsg("Could not open a branch — check the API is running.");
      return null;
    }
  }, [patch, ref, refreshBranches, toastMsg]);

  const createBranchFlow = useCallback(async () => {
    const st = ref.current;
    if (st.creatingBranch) return;
    const name = st.newBranchName.trim() || "Untitled branch";
    patch({ creatingBranch: true });
    try {
      const b = await api.createBranch({ name, from_branch: "main", scenario: st.newBranchForecast });
      const branches = await refreshBranches();
      patch({ creatingBranch: false, showNewBranch: false, newBranchName: "", activeBranch: b.branch_id, diff: null, suggestions: null });
      toastMsg(`Branch “${b.name}” created off main. Add projects, then Diff vs main.`);
      void run({ activeBranch: b.branch_id, branches: branches ?? undefined });
    } catch {
      patch({ creatingBranch: false });
      toastMsg("Could not create the branch — check the API is running.");
    }
  }, [patch, ref, refreshBranches, run, toastMsg]);

  const runBranchDiff = useCallback(async () => {
    const st = ref.current;
    if (st.comparing || !st.activeBranch || st.activeBranch === "main") return;
    patch({ comparing: true });
    try {
      const diff = await api.diffBranch(st.activeBranch, { with_narration: true });
      patch({ diff, comparing: false });
    } catch {
      patch({ comparing: false });
      toastMsg("Diff failed — check the API is running.");
    }
  }, [patch, ref, toastMsg]);

  const runSuggestions = useCallback(async () => {
    const st = ref.current;
    if (st.loadingSuggestions || !st.activeBranch || st.activeBranch === "main") return;
    patch({ loadingSuggestions: true });
    try {
      const suggestions = await api.getSuggestions(st.activeBranch, { with_narration: true, limit: 5 });
      patch({ suggestions, loadingSuggestions: false });
    } catch {
      patch({ loadingSuggestions: false });
      toastMsg("Suggestions failed — check the API is running.");
    }
  }, [patch, ref, toastMsg]);

  const mergeBranchFlow = useCallback(async () => {
    const st = ref.current;
    if (!st.activeBranch || st.activeBranch === "main") return;
    try {
      await api.mergeBranch(st.activeBranch, { into: "main" });
      const branches = await refreshBranches();
      toastMsg("Branch merged into main — the new plan of record. Re-running…");
      patch({ activeBranch: "main", diff: null, suggestions: null });
      void run({ activeBranch: "main", branches: branches ?? undefined });
    } catch {
      toastMsg("Merge failed — check the API is running.");
    }
  }, [patch, ref, refreshBranches, run, toastMsg]);

  const discardBranchFlow = useCallback(async () => {
    const st = ref.current;
    if (!st.activeBranch || st.activeBranch === "main") return;
    try {
      await api.discardBranch(st.activeBranch);
      const branches = await refreshBranches();
      patch({ activeBranch: "main", diff: null, suggestions: null });
      void run({ activeBranch: "main", branches: branches ?? undefined });
      toastMsg("Branch discarded — back on main.");
    } catch {
      toastMsg("Discard failed — check the API is running.");
    }
  }, [patch, ref, refreshBranches, run, toastMsg]);

  return { selectBranch, ensureEditableBranch, createBranchFlow, runBranchDiff, runSuggestions, mergeBranchFlow, discardBranchFlow };
}
