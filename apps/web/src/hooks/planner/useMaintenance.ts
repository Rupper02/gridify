// A branch's proposals beyond the run: its projects as stored, planned maintenance windows and simulated
// reinforcements. All are stored on the branch (the API). Windows refresh the plan by themselves (only
// their years re-solve); a reinforcement changes the queue's trials, so it waits for Run (lib/refresh.ts).

import { useCallback } from "react";

import { api, failureText } from "../../api";
import { WORK_UI, draftBody } from "../../lib/maintenance";
import type { ElementSel } from "../../types";
import { editableBranch } from "./core";
import type { Core, MaintDraft } from "./core";
import type { EditedFn } from "./useAutoRefresh";

export function useMaintenance(core: Core, edited: EditedFn) {
  const { patch, ref, toastMsg } = core;
  /** Load a branch's stored projects, outages and reinforcements (on switch and boot, and after an agent's proposal is approved). */
  const loadExtras = useCallback(
    async (bid: string) => {
      try {
        const [outages, reinforcements, candidates] = await Promise.all([api.listOutages(bid), api.listReinforcements(bid), api.listCandidates(bid)]);
        if (ref.current.activeBranch === bid) patch({ outages, reinforcements, candidates });
      } catch (e) {
        toastMsg(`Could not load the branch's proposals: ${failureText(e)}`, "warn");
      }
    },
    [patch, ref, toastMsg],
  );

  const setDraft = useCallback((d: Partial<MaintDraft>) => patch((st) => ({ maintDraft: { ...st.maintDraft, ...d } })), [patch]);

  /** Schedule a maintenance window on an element, on a branch (main is read-only). */
  const addOutage = useCallback(
    async (sel: ElementSel, bid: string) => {
      if (!editableBranch({ ref, toastMsg }, "schedule maintenance", bid)) return;
      const d = ref.current.maintDraft;
      try {
        const o = await api.addOutage(bid, draftBody(sel, d));
        patch((x) => (x.activeBranch === bid ? { outages: [...x.outages.filter((y) => y.outage_id !== o.outage_id), o], year: d.year } : {}));
        toastMsg(`${WORK_UI[d.work].label} scheduled for ${d.season.toLowerCase()} ${d.year}.`); // the stamp says when it is studied
        edited("works");
      } catch (e) {
        toastMsg(`Could not schedule it: ${failureText(e)}`, "warn");
      }
    },
    [edited, patch, ref, toastMsg],
  );

  const removeOutage = useCallback(
    async (outageId: string) => {
      const bid = editableBranch({ ref, toastMsg }, "remove planned works");
      if (!bid) return;
      const before = ref.current.outages;
      patch({ outages: before.filter((o) => o.outage_id !== outageId) });
      try {
        await api.removeOutage(bid, outageId);
        edited("works");
      } catch (e) {
        patch({ outages: before });
        toastMsg(`Could not remove it: ${failureText(e)}`, "warn");
      }
    },
    [edited, patch, ref, toastMsg],
  );

  const removeReinforcement = useCallback(
    async (rid: string) => {
      const bid = editableBranch({ ref, toastMsg }, "remove a reinforcement");
      if (!bid) return;
      const before = ref.current.reinforcements;
      patch({ reinforcements: before.filter((r) => r.reinforcement_id !== rid) });
      try {
        await api.removeReinforcement(bid, rid);
        edited("reinforcement");
      } catch (e) {
        patch({ reinforcements: before });
        toastMsg(`Could not remove the reinforcement: ${failureText(e)}`, "warn");
      }
    },
    [edited, patch, ref, toastMsg],
  );

  return { loadExtras, setDraft, addOutage, removeOutage, removeReinforcement };
}
