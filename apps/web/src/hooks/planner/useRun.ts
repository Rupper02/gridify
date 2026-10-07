// Running the plan for the active branch (the planner boots in useProjects: the projects, then the default one).
//
// One state machine, `s.run` (lib/runStages.ts), and this hook is its only writer. Every way a run starts (the Run
// button, an edit's quiet refresh, a branch or project switch, an approved proposal, the boot) comes through `run`:
// a request for the branch already pending or running starts no new job (a loud one only shows the card of a quiet
// one), a request for another branch supersedes the run in flight. A run is one background job: the greedy queue
// first, then every year of the plan with the viewed year first; the years arrive as partial results, so the slider
// never starts a run of its own. The card stays until the job ends; a job that fails or stops stays on the stamp
// with a Retry until the next request.

import { useCallback, useEffect, useRef } from "react";

import { RunCancelled, api, failureText } from "../../api";
import { mainIdOf } from "../../lib/projects";
import { AUTO_REFRESH_DEBOUNCE_MS } from "../../lib/refresh";
import { RUN_IDLE, runInProgress } from "../../lib/runStages";
import type { OptimizeResult } from "../../types";
import type { Core, RunState } from "./core";

/** Values an action may need before React has applied the state it just set (e.g. the branch to run). */
export interface RunOverride {
  activeBranch?: string;
  /** An edit's own refresh: no card, the stamp shows it updating; a burst of them within the debounce is one job. */
  quiet?: boolean;
  /** The inputs changed since the run on its way was asked for: retire that job and start one with the current inputs. */
  restart?: boolean;
}

export type RunFn = (over?: RunOverride) => Promise<void>;

const hhmm = () => new Date().toTimeString().slice(0, 5);

export function useRun({ patch, ref }: Core, afterRun: (branchId: string) => void) {
  // the quiet debounce's timer: the one thing about a run that is not in `s.run` (set only while `s.run` is pending)
  const debounce = useRef<number | undefined>(undefined);
  const seq = useRef(0); // the request token: a restart hands out a new one and the old job's loop sees it is no longer wanted
  useEffect(() => () => window.clearTimeout(debounce.current), []);

  /** Start the job for the request `token` holds pending and follow it to its end. */
  const solve = useCallback(
    async (bid: string, token: number) => {
      debounce.current = undefined;
      const st = ref.current;
      if (!(st.run.kind === "pending" && st.run.token === token)) return; // superseded during the debounce
      let jobId: string | null = null;
      /** Still the planner's run: the state holds this very request. Another request for the branch (a restart after an
       * edit), a request for another branch or a branch or project switch (FRESH) retires it. */
      const mine = (r: RunState = ref.current.run) => runInProgress(r) && r.token === token;
      let retired = false;
      /** The job is no longer the planner's run: ask it to stop (what it solved stays cached on the API). */
      const retire = () => {
        if (!jobId || retired) return;
        retired = true;
        void api.cancelJob(jobId).catch(() => {});
      };
      let res: OptimizeResult;
      try {
        res = await api.runBranchJob(
          bid,
          { view_year: st.year },
          {
            onStart: (id) => {
              jobId = id;
              if (mine())
                patch((x) => (x.run.kind === "pending" && x.run.token === token
                  ? { run: { kind: "running", branchId: bid, jobId: id, quiet: x.run.quiet, token, requestedAt: x.run.requestedAt, stage: "queued", fraction: 0, startedAt: hhmm() } }
                  : {}));
              else retire(); // retired before it had an id (a job another request already runs is simply followed)
            },
            onProgress: (stage, fraction) => {
              if (!mine()) return retire();
              patch((x) => (x.run.kind === "running" && x.run.token === token ? { run: { ...x.run, stage, fraction } } : {}));
            },
            onPartial: (p) => {
              if (!mine()) return;
              // a quiet refresh keeps the years on screen until their re-solved versions land
              patch((x) => (mine(x.run) ? { result: x.run.kind === "running" && x.run.quiet && x.result ? { ...p, years: { ...x.result.years, ...p.years } } : p } : {}));
            },
          },
        );
      } catch (e) {
        if (!mine()) return; // superseded: the newer run speaks for the branch
        const at = hhmm();
        const run: RunState = e instanceof RunCancelled ? { kind: "cancelled", branchId: bid, at } : { kind: "failed", branchId: bid, error: failureText(e), at };
        patch((x) => (mine(x.run) ? { run } : {}));
        return;
      }
      if (!mine()) return;
      const inQueue = new Set(res.queue.map((q) => q.request_id));
      patch((x) =>
        mine(x.run)
          ? {
              result: res,
              resultAt: hhmm(),
              run: RUN_IDLE,
              // projects this run now includes are no longer preliminary
              added: { ...x.added, [bid]: (x.added[bid] ?? []).filter((a) => !inQueue.has(a.request_id)) },
            }
          : {},
      );
      afterRun(bid);
    },
    [afterRun, patch, ref],
  );

  /** Solve after the debounce (a burst of edits is one job). */
  const later = useCallback((bid: string, token: number, ms: number) => {
    debounce.current = window.setTimeout(() => void solve(bid, token), ms);
  }, [solve]);

  /**
   * Ask for a run of a branch (the active one unless named). The branch's run already on its way is kept: a loud
   * request shows its card, a quiet one within the debounce extends it. A `restart` (the inputs changed since that run
   * was asked for) retires it and starts one with the current inputs, as loud as the run it replaces. A run of another
   * branch is superseded.
   */
  const run: RunFn = useCallback(
    async (over: RunOverride = {}) => {
      const st = ref.current;
      const bid = over.activeBranch || st.activeBranch || mainIdOf(st.projects, st.projectId);
      const r = st.run;
      const same = runInProgress(r) && r.branchId === bid;
      const quiet = !!over.quiet && (!same || r.quiet);
      if (same && !over.restart) {
        if (!quiet && r.quiet) patch({ run: { ...r, quiet: false }, menuOpen: false });
        if (r.kind === "pending" && debounce.current !== undefined) {
          window.clearTimeout(debounce.current);
          if (quiet) later(bid, r.token, AUTO_REFRESH_DEBOUNCE_MS); // the burst of edits goes on
          else void solve(bid, r.token); // Run now
        }
        return;
      }
      window.clearTimeout(debounce.current);
      debounce.current = undefined;
      const token = ++seq.current;
      // the gate's verdict and the diff belong to the result being replaced: drop them now, so Merge reads "checking"
      // and Review "comparing" until the new result's land (never a stale verdict or comparison)
      patch({ run: { kind: "pending", branchId: bid, quiet, token, requestedAt: Date.now() }, mergeCheck: null, diff: null, ...(quiet ? {} : { menuOpen: false }) });
      if (quiet) later(bid, token, AUTO_REFRESH_DEBOUNCE_MS);
      else await solve(bid, token);
    },
    [later, patch, ref, solve],
  );

  return run;
}
