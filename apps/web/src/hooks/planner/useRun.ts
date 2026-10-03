// Running the plan for the active branch, and booting the planner (load the model, then the first run).
//
// A run is one background job: the greedy queue first, then every year of the plan with the viewed
// year first. The overlay shows until the queue and the viewed year are in; the remaining years keep
// arriving as partial results (`solving`), so the slider never starts a run of its own.

import { useCallback, useEffect, useRef } from "react";

import { api } from "../../api";
import type { OptimizeResult, Status } from "../../types";
import type { Core } from "./core";

/** Values an action may need before React has applied the state it just set (e.g. the branch to run). */
export interface RunOverride {
  activeBranch?: string;
}

export type RunFn = (over?: RunOverride) => Promise<void>;

const hhmm = () => new Date().toTimeString().slice(0, 5);

export function useRun({ patch, ref, mapApi, toastMsg }: Core, afterRun: (branchId: string) => void) {
  // in-flight bookkeeping lives in refs, not React state: a coalesced re-run must see the previous
  // run finish synchronously, before React has flushed `running: false`
  const inFlight = useRef(false);
  const runAgain = useRef<RunOverride | null>(null);

  /**
   * Run the plan for the active branch. A run already in flight (a branch switch, a profile change)
   * is never dropped: it is coalesced into ONE re-run when the current one finishes.
   */
  const run: RunFn = useCallback(
    async (over: RunOverride = {}) => {
      const st = ref.current;
      if (inFlight.current) {
        runAgain.current = { ...(runAgain.current ?? {}), ...over };
        return;
      }
      inFlight.current = true;
      const bid = over.activeBranch ?? st.activeBranch ?? "main";
      const prev = st.result;
      const prevStatus: Record<string, Status> = prev ? Object.fromEntries(prev.queue.map((q) => [q.request_id, q.status])) : {};
      patch({ running: true, solving: true, stage: "queued", fraction: 0, menuOpen: false });
      const current = () => ref.current.activeBranch === bid; // ignore results for a branch we left

      const onPartial = (p: OptimizeResult) => {
        if (!current()) return;
        const viewed = !!p.years?.[String(ref.current.year)];
        patch((x) => ({ result: p, prevStatus, ...(viewed && x.running ? { running: false, resultAt: hhmm() } : {}) }));
      };
      let res: OptimizeResult;
      try {
        res = await api.runBranchJob(
          bid,
          { with_justification: true, view_year: st.year },
          { onProgress: (stage, fraction) => patch({ stage, fraction }), onPartial },
        );
      } catch (e) {
        inFlight.current = false;
        runAgain.current = null;
        patch({ running: false, solving: false, stage: "" });
        toastMsg(`The simulation failed: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
        return;
      }
      if (current()) {
        const inQueue = new Set(res.queue.map((x) => x.request_id));
        patch((x) => ({
          runId: x.runId + 1,
          result: res,
          resultAt: x.running || !x.resultAt ? hhmm() : x.resultAt,
          prevStatus,
          running: false,
          solving: false,
          stage: "",
          fraction: 1,
          // projects this run now includes are no longer preliminary
          added: { ...x.added, [bid]: (x.added[bid] ?? []).filter((a) => !inQueue.has(a.request_id)) },
        }));
        afterRun(bid);
      }
      inFlight.current = false;
      const again = runAgain.current;
      if (again) {
        runAgain.current = null;
        await run(again);
      }
    },
    [afterRun, patch, ref, toastMsg],
  );

  // ---- boot --------------------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [model, fc, boundary, branches] = await Promise.all([
          api.getModel(), api.getForecasts(), api.getBoundary(), api.listBranches(),
        ]);
        if (cancelled) return;
        patch({ model, forecasts: fc.forecasts, maxMw: fc.maxMw, boundary, branches, branchesLoaded: true });
        mapApi.current?.fit(false);
        void run({ activeBranch: "main" });
      } catch (e) {
        if (!cancelled) toastMsg(`Could not load the model: ${e instanceof Error ? e.message : "is the API running?"}`, "warn");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mapApi, patch, run, toastMsg]);

  return run;
}
