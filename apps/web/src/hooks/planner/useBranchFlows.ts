// Branch flows ("git for grids"): switch, open, set the demand profile, diff, merge, discard, rebase onto main.

import { useCallback, useMemo } from "react";

import { ApiError, api } from "../../api";
import type { RebasePick, RebasePreview } from "../../types";
import { parentName } from "../../lib/derive";
import { refusedCheck } from "../../lib/gate";
import { latestWins } from "../../lib/latest";
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
  const begin = useMemo(() => latestWins(), []); // one per planner: the diff and gate loads, latest wins

  /** Switch the active branch: the whole view (map, queue, roadmap, panels) follows it. */
  const selectBranch = useCallback(
    (id: string) => {
      patch({ menuOpen: false });
      if (id === ref.current.activeBranch) return;
      patch({ activeBranch: id, diff: null, diffMode: false, suggestions: null, mergeCheck: null, findings: [], findingCounts: null, reviews: [], thread: null, trace: [], sel: null, outages: [], reinforcements: [], candidates: [], chat: EMPTY_CHAT });
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
        patch({ activeBranch: b.branch_id, menuOpen: false, diff: null, diffMode: false, suggestions: null, mergeCheck: null, findings: [], findingCounts: null, reviews: [], thread: null, trace: [], sel: null, candidates: [], chat: { ...EMPTY_CHAT } });
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

  /** The consequence diff of the active branch vs main (with the optional narration). Only the latest load
   * applies: a diff asked while a run was still solving must not land on top of the one for its result. */
  const refreshDiff = useCallback(
    async (bid: string) => {
      if (!bid || bid === mainIdOf(ref.current.projects, ref.current.projectId)) return;
      const isLatest = begin("diff");
      try {
        const diff = await api.diffBranch(bid, { with_narration: true });
        if (isLatest() && ref.current.activeBranch === bid) patch({ diff });
      } catch {
        /* the review tab shows the diff as unavailable */
      }
    },
    [begin, patch, ref],
  );

  /** The merge gate's verdict for a branch (after its diff, so main's years are already cached). */
  const refreshMergeCheck = useCallback(
    async (bid: string) => {
      if (!bid || bid === mainIdOf(ref.current.projects, ref.current.projectId)) return;
      const isLatest = begin("mergeCheck");
      try {
        const mergeCheck = await api.mergeCheck(bid);
        if (isLatest() && ref.current.activeBranch === bid) patch({ mergeCheck });
      } catch {
        /* the Review tab keeps showing "checking" */
      }
    },
    [begin, patch, ref],
  );

  /** Show the diff; while a run is still solving it is not asked for (the run asks when it is done). */
  const toggleDiff = useCallback(() => {
    const st = ref.current;
    if (st.activeBranch === mainIdOf(st.projects, st.projectId)) return;
    const on = !st.diffMode;
    patch({ diffMode: on, ...(on ? { tab: "review" as const, sideOpen: true } : {}) });
    if (on && !st.diff && !st.solving) void refreshDiff(st.activeBranch);
  }, [patch, ref, refreshDiff]);

  /**
   * Merge the active branch into its parent (main, or the branch it was opened from: what the gate judged it against).
   * A refusal (409) carries the verdict: it goes into the Review tab and a toast; nothing changes until the operator
   * re-runs or acknowledges.
   */
  const mergeBranch = useCallback(
    async (opts: { acknowledge?: boolean } = {}) => {
      const st = ref.current;
      const mainId = mainIdOf(st.projects, st.projectId);
      if (!st.activeBranch || st.activeBranch === mainId) return;
      const branch = st.branches.find((b) => b.branch_id === st.activeBranch);
      const name = branch?.name ?? "The branch";
      const into = branch?.parent_id || mainId;
      const intoName = parentName(st.branches, branch, mainId);
      try {
        await api.mergeBranch(st.activeBranch, { into, acknowledge: !!opts.acknowledge });
        await refreshBranches();
        toastMsg(into === mainId ? `${name} merged into main, the new plan of record.` : `${name} merged into ${intoName}.`);
        patch({ activeBranch: into, diff: null, diffMode: false, suggestions: null, mergeCheck: null, findings: [], findingCounts: null, reviews: [], thread: null, trace: [], sel: null, tab: into === mainId ? "queue" : "review", chat: EMPTY_CHAT });
        void loadExtras(into);
        void run({ activeBranch: into });
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

  /** What rebasing the active branch onto main as it is now would do; null (with a toast) when it cannot be told. */
  const previewRebase = useCallback(async (): Promise<RebasePreview | null> => {
    const bid = ref.current.activeBranch;
    try {
      return await api.rebasePreview(bid);
    } catch (e) {
      toastMsg(`Could not prepare the rebase: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
      return null;
    }
  }, [ref, toastMsg]);

  /**
   * Rebase the active branch onto main with the operator's pick for every conflict. Only the operator starts it.
   * The branch then holds main's current state plus its own changes, and its result is out of date until it runs.
   */
  const rebaseBranch = useCallback(
    async (picks: Record<string, RebasePick>): Promise<boolean> => {
      const bid = ref.current.activeBranch;
      let taken = 0;
      try {
        taken = (await api.rebaseBranch(bid, picks)).taken;
      } catch (e) {
        toastMsg(`Rebase refused: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
        return false;
      }
      await refreshBranches();
      if (ref.current.activeBranch !== bid) return true;
      patch({ diff: null, mergeCheck: null, suggestions: null });
      await loadExtras(bid);
      void refreshMergeCheck(bid);
      toastMsg(`Rebased onto main: ${taken ? `${taken} of main's change${taken === 1 ? "" : "s"} taken in` : "this branch's values kept wherever both sides changed"}. If the result shows out of date, re-run it before merging.`);
      return true;
    },
    [loadExtras, patch, ref, refreshBranches, refreshMergeCheck, toastMsg],
  );

  return { selectBranch, createBranch, ensureEditableBranch, setProfile, refreshDiff, refreshMergeCheck, toggleDiff, mergeBranch, discardBranch, previewRebase, rebaseBranch };
}
