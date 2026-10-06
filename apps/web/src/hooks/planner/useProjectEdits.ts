// Edits to the projects on the active branch: set an energisation year, state a control mode.

import { useCallback } from "react";

import { api } from "../../api";
import { mainIdOf } from "../../lib/projects";
import type { Control } from "../../types";
import type { Core } from "./core";
import type { EditedFn } from "./useAutoRefresh";

export function useProjectEdits({ patch, ref, toastMsg }: Core, edited: EditedFn) {
  /**
   * Set/override a project's energisation year, a plan year (null = back to the optimizer's recommendation).
   * Persisted on the branch; applied optimistically, rolled back if the save fails. It doesn't change
   * accept/defer/rank: it's a planning decision on top of the verdict. main is read-only.
   */
  const setSchedule = useCallback(
    async (rid: string, year: number | null) => {
      const st = ref.current;
      const mainId = mainIdOf(st.projects, st.projectId);
      const bid = st.activeBranch || mainId;
      if (bid === mainId) {
        toastMsg("main is read-only. Open a branch to change an energisation year.", "warn");
        return;
      }
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
        edited("schedule");
      } catch (e) {
        applyYear(prev);
        toastMsg(`Couldn't save the year for ${rid}: ${e instanceof Error ? e.message : "unknown error"}`, "warn");
      }
    },
    [edited, patch, ref, toastMsg],
  );

  /**
   * State how a project's connection offer runs it (a power factor, or voltage control). Stored on the branch;
   * it changes the project's physics, so the result shows as out of date until the next run. main is read-only.
   */
  const setControl = useCallback(
    async (rid: string, control: Control): Promise<boolean> => {
      const st = ref.current;
      const mainId = mainIdOf(st.projects, st.projectId);
      const bid = st.activeBranch || mainId;
      if (bid === mainId) {
        toastMsg("main is read-only. Open a branch to state a project's control mode.", "warn");
        return false;
      }
      try {
        const row = await api.changeCandidate(bid, rid, { control });
        patch((s) => ({ candidates: s.candidates.map((c) => (c.request_id === rid ? row : c)) }));
        edited("project");
        return true;
      } catch (e) {
        toastMsg(`Couldn't save the control mode for ${rid}: ${e instanceof Error ? e.message : "unknown error"}`, "warn");
        return false;
      }
    },
    [edited, patch, ref, toastMsg],
  );

  return { setSchedule, setControl };
}
