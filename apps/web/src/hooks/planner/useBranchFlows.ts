// Branch flows ("git for grids"): switch, open, set the demand profile, diff, merge, discard.

import { useCallback } from "react";

import { ApiError, api } from "../../api";
import { refusedCheck } from "../../lib/gate";
import { mainIdOf } from "../../lib/projects";
import { EMPTY_CHAT } from "./core";
import type { Core } from "./core";
import type { EditedFn } from "./useAutoRefresh";
import type { RunFn } from "./useRun";

export function useBranchFlows(
  { patch, ref, toastMsg }: Core,
  run: RunFn,
  refreshBranches: () => Promise<unknown>,
  loadExtras: (branchId: string) => Promise<void>,
  edited: EditedFn,
) {
  /** Switch the active branch: the whole view (map, queue, roadmap, panels) follows it. */
  const selectBranch = useCallback(
    (id: string) => {
      patch({ menuOpen: false });
      if (id === ref.current.activeBranch) return;
      patch({ activeBranch: id, diff: null, diffMode: false, suggestions: null, mergeCheck: null, findings: [], findingCounts: null, reviews: [], thread: null, trace: [], sel: null, outages: [], reinforcements: [], chat: EMPTY_CHAT });
      void loadExtras(id);
      void run({ activeBranch: id });
    },
    [loadExtras, patch, ref, run],
  );

  /** Open a branch off main (it inherits main's projects, outages and demand profile) and switch to it. */
  const createBranch = useCallback(
    async (name?: string): Promise<string | null> => {
      const st = ref.current;
      const mainId = mainIdOf(st.projects, st.projectId);
      const main = st.branches.find((b) => b.branch_id === mainId);
      const n = st.branches.filter((b) => b.branch_id !== mainId).length + 1;
      const label = (name ?? "").trim() || `draft-${n}`;
      try {
        const b = await api.createBranch({ name: label, from_branch: mainId, scenario: main?.scenario ?? "ht" });
        await refreshBranches();
        patch({ activeBranch: b.branch_id, menuOpen: false, diff: null, diffMode: false, suggestions: null, mergeCheck: null, findings: [], findingCounts: null, reviews: [], thread: null, trace: [], sel: null, chat: { ...EMPTY_CHAT } });
        toastMsg(`Opened ${b.name} off main. Changes stay here until you merge.`);  // every project's plan of record is called main
        void loadExtras(b.branch_id);
        void run({ activeBranch: b.branch_id });
        return b.branch_id;
      } catch {
        toastMsg("Could not open a branch. Check the API is running.", "warn");
        return null;
      }
    },
    [loadExtras, patch, ref, refreshBranches, run, toastMsg],
  );

  /** Edits always target a branch (main is the plan of record). On main, open one first. */
  const ensureEditableBranch = useCallback(async (): Promise<string | null> => {
    const st = ref.current;
    if (st.activeBranch && st.activeBranch !== mainIdOf(st.projects, st.projectId)) return st.activeBranch;
    const keep = { chat: st.chat, sel: st.sel }; // the action that needed a branch carries on in it
    const id = await createBranch();
    if (id) patch(keep);
    return id;
  }, [createBranch, patch, ref]);

  /** Store a demand profile on the active branch. The shown result goes stale until the next run. */
  const setProfile = useCallback(
    async (scenario: string) => {
      const st = ref.current;
      const fc = st.forecasts.find((f) => f.id === scenario);
      if (!fc) return;
      const bid = st.activeBranch || mainIdOf(st.projects, st.projectId);
      const before = st.branches;
      patch({ branches: st.branches.map((b) => (b.branch_id === bid ? { ...b, scenario, growth_2030: fc.growth_2030, growth_2035: fc.growth_2035 } : b)) });
      try {
        await api.updateScenario(bid, scenario, fc.growth_2030, fc.growth_2035);
        edited("profile");
      } catch {
        patch({ branches: before });
        toastMsg("Could not store the demand profile. Check the API is running.", "warn");
      }
    },
    [edited, patch, ref, toastMsg],
  );

  /** The consequence diff of the active branch vs main (with the optional narration). */
  const refreshDiff = useCallback(
    async (bid: string) => {
      if (!bid || bid === mainIdOf(ref.current.projects, ref.current.projectId)) return;
      try {
        const diff = await api.diffBranch(bid, { with_narration: true });
        if (ref.current.activeBranch === bid) patch({ diff });
      } catch {
        /* the review tab shows the diff as unavailable */
      }
    },
    [patch, ref],
  );

  /** The merge gate's verdict for a branch (after its diff, so main's years are already cached). */
  const refreshMergeCheck = useCallback(
    async (bid: string) => {
      if (!bid || bid === mainIdOf(ref.current.projects, ref.current.projectId)) return;
      try {
        const mergeCheck = await api.mergeCheck(bid);
        if (ref.current.activeBranch === bid) patch({ mergeCheck });
      } catch {
        /* the Review tab keeps showing "checking" */
      }
    },
    [patch, ref],
  );

  const toggleDiff = useCallback(() => {
    const st = ref.current;
    if (st.activeBranch === mainIdOf(st.projects, st.projectId)) return;
    const on = !st.diffMode;
    patch({ diffMode: on, ...(on ? { tab: "review" as const, sideOpen: true } : {}) });
    if (on && !st.diff) void refreshDiff(st.activeBranch);
  }, [patch, ref, refreshDiff]);

  /**
   * Merge the active branch into main through the gate. A refusal (409) carries the verdict: it goes
   * into the Review tab and a toast; nothing changes until the operator re-runs or acknowledges.
   */
  const mergeBranch = useCallback(
    async (opts: { acknowledge?: boolean } = {}) => {
      const st = ref.current;
      const mainId = mainIdOf(st.projects, st.projectId);
      if (!st.activeBranch || st.activeBranch === mainId) return;
      const name = st.branches.find((b) => b.branch_id === st.activeBranch)?.name ?? "The branch";
      try {
        await api.mergeBranch(st.activeBranch, { into: mainId, acknowledge: !!opts.acknowledge });
        await refreshBranches();
        toastMsg(`${name} merged into main, the new plan of record.`);
        patch({ activeBranch: mainId, diff: null, diffMode: false, suggestions: null, mergeCheck: null, findings: [], findingCounts: null, reviews: [], thread: null, trace: [], sel: null, tab: "queue", chat: EMPTY_CHAT });
        void loadExtras(mainId);
        void run({ activeBranch: mainId });
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          const refusal = refusedCheck(e.detail, st.mergeCheck, st.activeBranch);
          if (refusal) {
            patch({ mergeCheck: refusal, tab: "review", sideOpen: true });
            toastMsg(`Merge refused: ${e.message}`, "warn");
            return;
          }
        }
        toastMsg(`Merge failed: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
      }
    },
    [loadExtras, patch, ref, refreshBranches, run, toastMsg],
  );

  const discardBranch = useCallback(async () => {
    const st = ref.current;
    const mainId = mainIdOf(st.projects, st.projectId);
    if (!st.activeBranch || st.activeBranch === mainId) return;
    const name = st.branches.find((b) => b.branch_id === st.activeBranch)?.name ?? "The branch";
    try {
      await api.discardBranch(st.activeBranch);
      await refreshBranches();
      patch({ activeBranch: mainId, diff: null, diffMode: false, suggestions: null, mergeCheck: null, findings: [], findingCounts: null, reviews: [], thread: null, trace: [], sel: null, chat: EMPTY_CHAT });
      void loadExtras(mainId);
      void run({ activeBranch: mainId });
      toastMsg(`${name} discarded. Back on main.`);
    } catch {
      toastMsg("Discard failed. Check the API is running.", "warn");
    }
  }, [loadExtras, patch, ref, refreshBranches, run, toastMsg]);

  return { selectBranch, createBranch, ensureEditableBranch, setProfile, refreshDiff, refreshMergeCheck, toggleDiff, mergeBranch, discardBranch };
}
