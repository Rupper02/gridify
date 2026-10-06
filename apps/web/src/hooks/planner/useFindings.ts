// The findings ledger for the active branch: what its last run found, and the operator's call on each.

import { useCallback } from "react";

import { api, failureText } from "../../api";
import type { FindingStatus } from "../../types";
import type { Core } from "./core";

export function useFindings({ patch, ref, toastMsg }: Core) {
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

  return { loadFindings, setFindingStatus };
}
