// A branch's proposals beyond projects: planned maintenance windows and simulated reinforcements.
// Both are stored on the branch (the API) and studied by the next run; until then the result is stale.

import { useCallback } from "react";

import { api } from "../../api";
import { WORK_UI, draftBody } from "../../lib/maintenance";
import type { ElementSel, Suggestion } from "../../types";
import type { Core, MaintDraft } from "./core";

export function useMaintenance({ patch, ref, toastMsg }: Core) {
  /** Load the outages and reinforcements of a branch (on switch and boot). */
  const loadExtras = useCallback(
    async (bid: string) => {
      try {
        const [outages, reinforcements] = await Promise.all([api.listOutages(bid), api.listReinforcements(bid)]);
        if (ref.current.activeBranch === bid) patch({ outages, reinforcements });
      } catch {
        /* an older API without these endpoints: nothing planned */
      }
    },
    [patch, ref],
  );

  const setDraft = useCallback((d: Partial<MaintDraft>) => patch((st) => ({ maintDraft: { ...st.maintDraft, ...d } })), [patch]);

  /** Schedule a maintenance window on an element, on a branch (main is read-only). */
  const addOutage = useCallback(
    async (sel: ElementSel, bid: string) => {
      const st = ref.current;
      if (bid === "main") {
        toastMsg("main is read-only. Open a branch to schedule maintenance.", "warn");
        return;
      }
      const d = st.maintDraft;
      try {
        const o = await api.addOutage(bid, draftBody(sel, d));
        patch((x) => (x.activeBranch === bid ? { outages: [...x.outages.filter((y) => y.outage_id !== o.outage_id), o], year: d.year } : {}));
        toastMsg(`${WORK_UI[d.work].label} scheduled for ${d.season.toLowerCase()} ${d.year}. Re-run to study it.`);
      } catch (e) {
        toastMsg(`Could not schedule it: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
      }
    },
    [patch, ref, toastMsg],
  );

  const removeOutage = useCallback(
    async (outageId: string) => {
      const st = ref.current;
      if (st.activeBranch === "main") return;
      const before = st.outages;
      patch({ outages: before.filter((o) => o.outage_id !== outageId) });
      try {
        await api.removeOutage(st.activeBranch, outageId);
      } catch {
        patch({ outages: before });
        toastMsg("Could not remove it. Check the API is running.", "warn");
      }
    },
    [patch, ref, toastMsg],
  );

  /** Try a Copilot lever on the branch: store its reinforcements; the next run measures them. */
  const tryLever = useCallback(
    async (bid: string, s: Suggestion): Promise<boolean> => {
      try {
        const added = await Promise.all(
          s.reinforcements.map((r) => api.addReinforcement(bid, { kind: r.kind, element_id: r.element_id, action: r.action, factor: r.factor, label: s.action })),
        );
        if (ref.current.activeBranch === bid) patch((x) => ({ reinforcements: [...x.reinforcements, ...added] }));
        return true;
      } catch (e) {
        toastMsg(`Could not add the lever: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
        return false;
      }
    },
    [patch, ref, toastMsg],
  );

  const removeReinforcement = useCallback(
    async (rid: string) => {
      const st = ref.current;
      const before = st.reinforcements;
      patch({ reinforcements: before.filter((r) => r.reinforcement_id !== rid) });
      try {
        await api.removeReinforcement(st.activeBranch, rid);
      } catch {
        patch({ reinforcements: before });
      }
    },
    [patch, ref],
  );

  return { loadExtras, setDraft, addOutage, removeOutage, tryLever, removeReinforcement };
}
