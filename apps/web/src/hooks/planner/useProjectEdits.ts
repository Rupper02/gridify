// Edits to the projects on the active branch: set an energisation year.

import { useCallback } from "react";

import { api } from "../../api";
import type { Core } from "./core";

export function useProjectEdits({ patch, ref, toastMsg }: Core) {
  /**
   * Set/override a project's energisation year (null = back to the optimizer's recommendation).
   * Persisted on the branch; applied optimistically, rolled back if the save fails. It doesn't change
   * accept/defer/rank: it's a planning decision on top of the verdict. main is read-only.
   */
  const setSchedule = useCallback(
    async (rid: string, yr: number | null) => {
      const bid = ref.current.activeBranch || "main";
      if (bid === "main") {
        toastMsg("main is read-only. Open a branch to change an energisation year.", "warn");
        return;
      }
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
        await api.setSchedule(bid, rid, year);
      } catch (e) {
        applyYear(prev);
        toastMsg(`Couldn't save the year for ${rid}: ${e instanceof Error ? e.message : "unknown error"}`, "warn");
      }
    },
    [patch, ref, toastMsg],
  );

  return { setSchedule };
}
