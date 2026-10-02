// Edits to the projects on the active branch: submit the add-project form, set an energisation year.

import { useCallback } from "react";

import { api } from "../../api";
import { EVID } from "../../theme";
import type { Branch, RegistryItem } from "../../types";
import type { Core } from "./core";
import type { RunFn } from "./useRun";

export function useProjectEdits(
  { patch, ref, toastMsg }: Core,
  run: RunFn,
  ensureEditableBranch: () => Promise<string | null>,
  refreshBranches: () => Promise<Branch[] | null>,
  runBranchDiff: () => Promise<void>,
  selectProject: (id: string, zoom?: boolean) => void,
) {
  const submit = useCallback(
    async (andRun: boolean) => {
      const f = ref.current.form;
      if (!f.bus || !(+f.mw > 0)) return;
      // Every add targets a branch (main is the plan of record). On main we auto-open a branch.
      const branchId = await ensureEditableBranch();
      if (!branchId) return;
      let row: RegistryItem;
      try {
        row = await api.addCandidate({
          applicant: f.name.trim() || "Manual application",
          bus_id: +f.bus,
          technology: f.tech,
          rating_mw: +f.mw,
          readiness_score: f.readiness,
          readiness_rationale: EVID.filter((e) => f[e.k]).map((e) => e.label).join("; ") || "No evidence supplied",
          branch_id: branchId,
          manual: true,
        });
      } catch (e) {
        toastMsg(`Could not add the project: ${e instanceof Error ? e.message : "check the API is running"}`);
        return;
      }
      await refreshBranches();
      // the view follows the active branch: re-run so the project lands on the map + Queue
      patch((st) => ({ drawer: false, pickMode: false, activeBranch: branchId, suggestions: null, form: { ...st.form, name: "", bus: "" } }));
      await run({ activeBranch: branchId });
      if (andRun) selectProject(row.request_id);
      if (ref.current.diff) void runBranchDiff();
      toastMsg(`${row.request_id} added to the branch — now on the map and in the Queue.`);
    },
    [ensureEditableBranch, patch, ref, refreshBranches, run, runBranchDiff, selectProject, toastMsg],
  );

  /**
   * Set/override a project's energisation year (null = back to the optimizer's recommendation).
   * Persisted on the branch; applied optimistically, rolled back if the save fails. It doesn't change
   * accept/defer/rank: it's a planning decision on top of the verdict.
   */
  const setSchedule = useCallback(
    async (rid: string, yr: number | null) => {
      const year = yr == null ? null : Math.max(2026, Math.min(2035, yr));
      const applyYear = (val: number | null) =>
        patch((st) =>
          st.result
            ? { result: { ...st.result, queue: st.result.queue.map((it) => (it.request_id === rid ? { ...it, scheduled_year: val } : it)) } }
            : {},
        );
      const prev = ref.current.result?.queue.find((x) => x.request_id === rid)?.scheduled_year ?? null;
      applyYear(year);
      try {
        await api.setSchedule(ref.current.activeBranch || "main", rid, year);
      } catch (e) {
        applyYear(prev);
        toastMsg(`Couldn’t save the year for ${rid}: ${e instanceof Error ? e.message : "unknown error"}`);
      }
    },
    [patch, ref, toastMsg],
  );

  return { submit, setSchedule };
}
