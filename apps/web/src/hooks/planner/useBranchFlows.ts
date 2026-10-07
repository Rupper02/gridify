// Branch flows ("git for grids"): switch, open, set the demand profile, diff, merge, discard, rebase onto main.

import { useCallback, useMemo } from "react";

import { ApiError, NOT_SOLVED_RETRIES, NOT_SOLVED_RETRY_MS, api, failureText, notSolved } from "../../api";
import type { RebasePick, RebasePreview } from "../../types";
import { parentName } from "../../lib/derive";
import { refusedCheck } from "../../lib/gate";
import { latestWins } from "../../lib/latest";
import { mainIdOf } from "../../lib/projects";
import { runInProgress } from "../../lib/runStages";
import { BRANCH_FRESH } from "./core";
import type { Core, PlannerState } from "./core";
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

  /** Show a branch: its view starts fresh (BRANCH_FRESH), its works and projects load, and its plan runs (cached when
   * unchanged; the request supersedes a run of the branch we left, cancelling its job). */
  const switchTo = useCallback(
    (bid: string, extra: Partial<PlannerState> = {}) => {
      patch({ ...BRANCH_FRESH, activeBranch: bid, menuOpen: false, ...extra });
      void loadExtras(bid);
      void run({ activeBranch: bid });
    },
    [loadExtras, patch, run],
  );

  /** Switch the active branch: the whole view (map, queue, roadmap, panels) follows it. */
  const selectBranch = useCallback(
    (id: string) => {
      patch({ menuOpen: false });
      if (id !== ref.current.activeBranch) switchTo(id);
    },
    [patch, ref, switchTo],
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
        const b = await api.createBranch({ name: label, from_branch: mainId, ...(main ? { scenario: main.scenario } : {}) });
        await refreshBranches();
        switchTo(b.branch_id);
        toastMsg(`Opened ${b.name} off main. Changes stay here until you merge.`);  // every project's plan of record is called main
        return b.branch_id;
      } catch (e) {
        toastMsg(`Could not open a branch: ${failureText(e)}`, "warn");
        return null;
      }
    },
    [ref, refreshBranches, switchTo, toastMsg],
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
      const bid = st.activeBranch;
      const before = st.branches;
      patch({ branches: st.branches.map((b) => (b.branch_id === bid ? { ...b, scenario, growth_2030: fc.growth_2030, growth_2035: fc.growth_2035 } : b)) });
      try {
        await api.updateScenario(bid, scenario, fc.growth_2030, fc.growth_2035);
        edited("profile");
        // a run on its way is for the old profile: restart it for this one rather than wait a minute for a stale result
        if (runInProgress(ref.current.run) && ref.current.run.branchId === bid) void run({ restart: true });
      } catch (e) {
        patch({ branches: before });
        toastMsg(`Could not store the demand profile: ${failureText(e)}`, "warn");
      }
    },
    [edited, patch, ref, run, toastMsg],
  );

  /** The consequence diff of the active branch vs its parent. Only the latest load
   * applies: a diff asked while a run was still solving must not land on top of the one for its result. A read the
   * API refused because the engine was busy (`not_solved`: an agent's study or a job holding the solver as the run
   * ended) is asked again a few times before it is shown in Review with a Retry; any other failure shows at once. */
  const refreshDiff = useCallback(
    async (bid: string, attempt = 0) => {
      if (!bid || bid === mainIdOf(ref.current.projects, ref.current.projectId)) return;
      const isLatest = begin("diff");
      patch({ diffError: null });
      try {
        const diff = await api.diffBranch(bid);
        if (isLatest() && ref.current.activeBranch === bid) patch({ diff });
      } catch (e) {
        if (!isLatest() || ref.current.activeBranch !== bid) return;
        if (notSolved(e) && attempt < NOT_SOLVED_RETRIES) setTimeout(() => void refreshDiff(bid, attempt + 1), NOT_SOLVED_RETRY_MS);
        else patch({ diffError: failureText(e) });
      }
    },
    [begin, patch, ref],
  );

  /** The merge gate's verdict for a branch (after its diff, so the parent's years are already cached). A failure is
   * shown in Review with a Retry, never as a "checking" that never ends; a `not_solved` refusal is retried as the diff's. */
  const refreshMergeCheck = useCallback(
    async (bid: string, attempt = 0) => {
      if (!bid || bid === mainIdOf(ref.current.projects, ref.current.projectId)) return;
      const isLatest = begin("mergeCheck");
      patch({ gateError: null });
      try {
        const mergeCheck = await api.mergeCheck(bid);
        if (isLatest() && ref.current.activeBranch === bid) patch({ mergeCheck });
      } catch (e) {
        if (!isLatest() || ref.current.activeBranch !== bid) return;
        if (notSolved(e) && attempt < NOT_SOLVED_RETRIES) setTimeout(() => void refreshMergeCheck(bid, attempt + 1), NOT_SOLVED_RETRY_MS);
        else patch({ gateError: failureText(e) });
      }
    },
    [begin, patch, ref],
  );

  /** Show the diff; while a run is on its way it is not asked for (the run asks when it is done). */
  const toggleDiff = useCallback(() => {
    const st = ref.current;
    if (st.activeBranch === mainIdOf(st.projects, st.projectId)) return;
    const on = !st.diffMode;
    patch({ diffMode: on, ...(on ? { tab: "review" as const, sideOpen: true } : {}) });
    if (on && !st.diff && !runInProgress(st.run)) void refreshDiff(st.activeBranch);
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
        switchTo(into, { tab: into === mainId ? "queue" : "review" });
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          const refusal = refusedCheck(e.detail, st.mergeCheck, st.activeBranch, into);
          if (refusal) {
            patch({ mergeCheck: refusal, tab: "review", sideOpen: true });
            toastMsg(`Merge refused: ${e.message}`, "warn");
            return;
          }
        }
        toastMsg(`Merge failed: ${failureText(e)}`, "warn");
      }
    },
    [patch, ref, refreshBranches, switchTo, toastMsg],
  );

  const discardBranch = useCallback(async () => {
    const st = ref.current;
    const mainId = mainIdOf(st.projects, st.projectId);
    if (!st.activeBranch || st.activeBranch === mainId) return;
    const name = st.branches.find((b) => b.branch_id === st.activeBranch)?.name ?? "The branch";
    try {
      await api.discardBranch(st.activeBranch);
      await refreshBranches();
      switchTo(mainId);
      toastMsg(`${name} discarded. Back on main.`);
    } catch (e) {
      toastMsg(`Discard failed: ${failureText(e)}`, "warn");
    }
  }, [ref, refreshBranches, switchTo, toastMsg]);

  /** What rebasing the active branch onto its parent as it is now would do; null (with a toast) when it cannot be told. */
  const previewRebase = useCallback(async (): Promise<RebasePreview | null> => {
    const bid = ref.current.activeBranch;
    try {
      return await api.rebasePreview(bid);
    } catch (e) {
      toastMsg(`Could not prepare the rebase: ${failureText(e)}`, "warn");
      return null;
    }
  }, [ref, toastMsg]);

  /** After a rebase of `bid` (the operator's, or an agent's the operator approved): the branch list, its works and
   * projects, and a fresh gate verdict; the diff is of the state before, so it goes. */
  const afterRebase = useCallback(
    async (bid: string) => {
      await refreshBranches();
      if (ref.current.activeBranch !== bid) return;
      patch({ diff: null, diffError: null, mergeCheck: null, gateError: null });
      await loadExtras(bid);
      void refreshMergeCheck(bid);
    },
    [loadExtras, patch, ref, refreshBranches, refreshMergeCheck],
  );

  /**
   * Rebase the active branch onto its parent with the operator's pick for every conflict. Only the operator starts it.
   * The branch then holds its parent's current state plus its own changes, and its result is out of date until it runs.
   */
  const rebaseBranch = useCallback(
    async (picks: Record<string, RebasePick>): Promise<boolean> => {
      const st = ref.current;
      const bid = st.activeBranch;
      const parent = parentName(st.branches, st.branches.find((b) => b.branch_id === bid), mainIdOf(st.projects, st.projectId));
      let taken = 0;
      try {
        taken = (await api.rebaseBranch(bid, picks)).taken;
      } catch (e) {
        toastMsg(`Rebase refused: ${failureText(e)}`, "warn");
        return false;
      }
      await afterRebase(bid);
      toastMsg(`Rebased onto ${parent}: ${taken ? `${taken} of its change${taken === 1 ? "" : "s"} taken in` : "this branch's values kept wherever both sides changed"}. If the result shows out of date, re-run it before merging.`);
      return true;
    },
    [afterRebase, ref, toastMsg],
  );

  /** Review the branch: open the Review tab (Merge lives there). A run on its way asks for both itself
   * when it is done, so nothing is asked of a result that is not there yet. */
  const goReview = useCallback(() => {
    patch({ tab: "review", sideOpen: true });
    const st = ref.current;
    if (runInProgress(st.run)) return;
    if (!st.diff) void refreshDiff(st.activeBranch);
    if (!st.mergeCheck) void refreshMergeCheck(st.activeBranch);
  }, [patch, ref, refreshDiff, refreshMergeCheck]);

  return { goReview, selectBranch, createBranch, ensureEditableBranch, setProfile, refreshDiff, refreshMergeCheck, toggleDiff, mergeBranch, discardBranch, previewRebase, rebaseBranch, afterRebase };
}
