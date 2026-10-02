// Running the plan for the active branch, and booting the planner (load the model, then the first run).

import { useCallback, useEffect, useRef } from "react";

import { api } from "../../api";
import type { Branch, OptimizeResult, RegistryItem, RunParams, Status } from "../../types";
import type { Core } from "./core";

/** Values an action may need before React has applied the state it just set (e.g. the branch to run). */
export interface RunOverride {
  activeBranch?: string;
  branches?: Branch[];
  forecastId?: string;
  g30?: number;
  g35?: number;
}

export type RunFn = (over?: RunOverride) => Promise<void>;

export function useRun({ patch, ref, mapApi, toastMsg }: Core, refreshBranches: () => Promise<Branch[] | null>) {
  // in-flight bookkeeping lives in refs, not React state: a coalesced re-run must see the previous
  // run finish synchronously, before React has flushed `running: false`
  const inFlight = useRef(false);
  const runAgain = useRef<RunOverride | null>(null);
  const stepTimer = useRef<number | undefined>(undefined);

  /**
   * Run the plan for the active branch. A run already in flight (several registry adds in a row, a
   * branch switch) is never dropped: it is coalesced into ONE re-run when the current one finishes.
   */
  const run: RunFn = useCallback(
    async (over: RunOverride = {}) => {
      const st = ref.current;
      if (inFlight.current) {
        runAgain.current = { ...(runAgain.current ?? {}), ...over };
        return;
      }
      inFlight.current = true;
      const prev = st.result;
      const prevStatus: Record<string, Status> = prev ? Object.fromEntries(prev.queue.map((q) => [q.request_id, q.status])) : {};
      // The view follows the active branch: main runs the plan of record (existing fleet, empty
      // queue); a branch runs its own scenario + the projects pulled onto it.
      const bid = over.activeBranch ?? st.activeBranch;
      const onBranch = !!bid && bid !== "main";
      const branches = over.branches ?? st.branches;
      const br = onBranch ? branches.find((b) => b.branch_id === bid) : undefined;
      const g30 = br ? br.growth_2030 : (over.g30 ?? st.g30);
      const g35 = br ? br.growth_2035 : (over.g35 ?? st.g35);
      const scenario = br ? br.scenario : (over.forecastId ?? st.forecastId);
      const studyYear = st.timelineYear;  // use current timeline year for study
      const params: RunParams = { g30, g35, scenario, branch: onBranch ? bid : "main", n: st.cands.length };
      patch({ running: true, step: 0, stage: "queued", hover: null });
      window.clearInterval(stepTimer.current);
      // every run is a background job on the API; its stage + fraction drive the overlay. A run that
      // has happened before (same branch, same inputs, same engine) is served from the durable cache
      // and finishes at once. The main branch still carries the header's forecast choice.
      const onProgress = (stage: string, fraction: number) => patch({ stage, step: Math.min(5, Math.floor(fraction * 5 + 1e-9)) });
      let res: OptimizeResult;
      let cands: RegistryItem[];
      try {
        res = onBranch || scenario === st.forecastId
          ? await api.runBranchJob(bid || "main", { with_justification: true, study_year: studyYear }, onProgress)
          : await api.optimize({ scenario, growth_2030: g30, growth_2035: g35, with_justification: true, study_year: studyYear });
        cands = await api.getCandidates();
      } catch (e) {
        window.clearInterval(stepTimer.current);
        inFlight.current = false;
        runAgain.current = null;
        patch({ running: false, step: 0, stage: "" });
        toastMsg(`The simulation failed: ${e instanceof Error ? e.message : "check the API is running"}`);
        return;
      }
      const inQueue = new Set(res.queue.map((x) => x.request_id));
      patch((x) => ({
        runId: x.runId + 1,
        // registry adds that this run now reflects are no longer "pending"
        pendingAdds: Object.fromEntries(Object.entries(x.pendingAdds).filter(([id]) => !inQueue.has(id))) as Record<string, true>,
        result: res,
        cands,
        prevStatus,
        running: false,
        step: 5,
        stage: "",
        lastParams: params,
      }));
      inFlight.current = false;
      const again = runAgain.current;
      if (again) {
        runAgain.current = null;
        await run(again);
      }
    },
    [patch, ref, toastMsg],
  );

  // ---- boot --------------------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [model, cands, forecasts, maxMw, boundary] = await Promise.all([
          api.getModel(), api.getCandidates(), api.getForecasts(), api.getMaxConnectionMw(), api.getBoundary(),
        ]);
        if (cancelled) return;
        // growth is fixed per pathway (no sliders): sync g30/g35 to the default forecast's cited values
        const def = forecasts.find((f) => f.id === ref.current.forecastId) ?? forecasts[0];
        const over: RunOverride = def ? { forecastId: def.id, g30: def.growth_2030, g35: def.growth_2035 } : {};
        patch({ model, cands, forecasts, maxMw, boundary, ...over });
        mapApi.current?.fit(false);
        void refreshBranches();
        void run(over);
      } catch (e) {
        if (!cancelled) toastMsg(`Could not load the model: ${e instanceof Error ? e.message : "is the API running?"}`);
      }
    })();
    return () => {
      cancelled = true;
      window.clearInterval(stepTimer.current);
    };
  }, [mapApi, patch, ref, refreshBranches, run, toastMsg]);

  return run;
}
