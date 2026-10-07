// What limits the active branch, and the findings ledger behind it: the engine's own reduction of the last run
// (GET /branches/{id}/limits), the ledger (GET /branches/{id}/findings) and the operator's call on each finding.

import { useCallback, useMemo } from "react";

import { NOT_SOLVED_RETRIES, NOT_SOLVED_RETRY_MS, api, failureText, notSolved } from "../../api";
import { latestWins } from "../../lib/latest";
import type { FindingStatus } from "../../types";
import type { Core } from "./core";

export function useLimits({ patch, ref, toastMsg }: Core) {
  const begin = useMemo(() => latestWins(), []); // one per planner: the limits loads, latest wins

  /** What limits a branch. Only the latest load applies (one asked mid-run must not land on top of the one for its
   * result); a `not_solved` refusal (the branch has not run for what it holds yet, or the engine is busy) is asked
   * again a few times before the tab shows it with a Retry; any other failure shows at once. */
  const loadLimits = useCallback(
    async (bid: string, attempt = 0) => {
      if (!bid) return;
      const isLatest = begin("limits");
      patch({ limitsError: null });
      try {
        const limits = await api.branchLimits(bid);
        if (isLatest() && ref.current.activeBranch === bid) patch({ limits });
      } catch (e) {
        if (!isLatest() || ref.current.activeBranch !== bid) return;
        if (notSolved(e) && attempt < NOT_SOLVED_RETRIES) setTimeout(() => void loadLimits(bid, attempt + 1), NOT_SOLVED_RETRY_MS);
        else patch({ limitsError: failureText(e) });
      }
    },
    [begin, patch, ref],
  );

  /** Load a branch's findings (ignored if the planner has moved to another branch meanwhile). */
  const loadFindings = useCallback(
    async (bid: string) => {
      try {
        const r = await api.listFindings(bid);
        if (ref.current.activeBranch === bid) patch({ findings: r.findings });
      } catch (e) {
        if (ref.current.activeBranch === bid) toastMsg(`Could not load the findings: ${failureText(e)}`, "warn");
      }
    },
    [patch, ref, toastMsg],
  );

  /** Acknowledge, resolve or reopen a finding: optimistic, rolled back with a toast on failure. */
  const setFindingStatus = useCallback(
    async (id: string, status: FindingStatus, note = "") => {
      const before = ref.current.findings;
      patch({ findings: before.map((f) => (f.finding_id === id ? { ...f, status } : f)) });
      try {
        const row = await api.setFindingStatus(id, status, note);
        patch((st) => ({ findings: st.findings.map((f) => (f.finding_id === id ? row : f)) }));
      } catch (e) {
        patch({ findings: before });
        toastMsg(`Could not update the finding: ${failureText(e)}`, "warn");
      }
    },
    [patch, ref, toastMsg],
  );

  return { loadLimits, loadFindings, setFindingStatus };
}
