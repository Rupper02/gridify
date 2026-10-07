// The run as the planner tracks and shows it: one state machine for the branch's run (useRun is its only writer),
// the overlay's stages bound to the job's real stage strings (apps/api jobs + the engine's progress reports), and
// the one view every card, button and gate reads, so they never disagree about whether a run is under way.

import { type Plan, firstYear, lastYear } from "./plan";

// ---- the run state --------------------------------------------------------------------------------------------
/**
 * Where the branch's run stands. `pending` covers the quiet debounce and the wait for the job id; `running` carries
 * the job the planner polls; `failed` and `cancelled` stay until the next request (the stamp shows them with a Retry).
 * A quiet run is an edit's own refresh: no card, the stamp says it is updating.
 */
export type RunState =
  | { kind: "idle" }
  | { kind: "pending"; branchId: string; quiet: boolean }
  | { kind: "running"; branchId: string; jobId: string; quiet: boolean; stage: string; fraction: number; startedAt: string }
  | { kind: "failed"; branchId: string; error: string; at: string }
  | { kind: "cancelled"; branchId: string; at: string };

export const RUN_IDLE: RunState = { kind: "idle" };

/** A result for the branch is on its way: pending or running. */
export const runInProgress = (run: RunState): run is Extract<RunState, { kind: "pending" | "running" }> => run.kind === "pending" || run.kind === "running";

// ---- the overlay's stages -------------------------------------------------------------------------------------
export interface RunStage {
  label: string;
  note: string;
}

export function runStages(plan: Plan, profileLabel: string, nOutages: number): RunStage[] {
  return [
    { label: "Ranking the queue", note: "readiness · grid need · fit" },
    { label: `Phase 1 trials at ${plan.phase1} demand`, note: profileLabel ? `${profileLabel} demand, both study cases` : "both study cases" },
    { label: `Phase 2 trials at ${plan.phase2} demand`, note: "winter peak and summer minimum" },
    { label: `Every year, ${firstYear(plan)} to ${lastYear(plan)}`, note: `N-1 screen${nOutages ? ` · ${nOutages} planned outage${nOutages > 1 ? "s" : ""}` : ""}` },
    { label: "Drafting the briefing", note: "plain-English summary" },
  ];
}

// the job's stages after the queue is decided: the plan years, then the findings ledger and the briefing
const isBriefing = (s: string) => s.startsWith("narration") || s.startsWith("writing") || s === "done";
const isYears = (s: string) => s.startsWith("year") || s === "queue decided";

/** Which stage a job stage string belongs to (queued and starting count as ranking; the engine names a
 * phase by its horizon: "phase 2030: trial 3/12"). */
export function stageIndex(stage: string, plan: Plan): number {
  const s = stage.toLowerCase();
  if (isBriefing(s)) return 4;
  if (isYears(s)) return 3;
  if (s.startsWith(`phase ${plan.phase2}`)) return 2;
  if (s.startsWith(`phase ${plan.phase1}`)) return 1;
  return 0;
}

/** The overlay's readout: the engine's own words for what it is doing. */
export function stageReadout(stage: string, plan: Plan): string {
  if (!stage || stage === "queued") return "queued on the engine";
  if (stage === "starting") return "building the network";
  if (stage === "waiting for the solver") return "waiting for the solver: an agent's study step is finishing, then this run starts";
  if (stage === "ranking") return `one power flow at ${plan.phase2} demand to read grid need`;
  if (stage === "writing findings") return "recording the findings in the ledger";
  if (stage === "narration") return "phrasing results, physics already fixed";
  if (stage === "queue decided") return "queue decided, solving each year";
  return stage;
}

// ---- the one view ---------------------------------------------------------------------------------------------
/** The run as every card reads it: the result stamp's line, the roadmap's note, the readings' note, and the flags
 * the buttons, the stale box and the merge gate share. */
export interface RunView {
  /** Pending or running: the stale box waits, Merge reads "checking", the profile cannot change. */
  inProgress: boolean;
  /** The run card shows: a loud run, from its start to its end. */
  overlay: boolean;
  /** An edit's own refresh is on its way: no card, the stamp says it is updating. */
  quiet: boolean;
  /** Why the last run did not finish (it failed, or stopped before every year was solved); null otherwise. */
  problem: string | null;
  label: string; // the result stamp's line (the stamp adds what it knows, e.g. the planned outages, when settled)
  roadmap: string; // the roadmap's short note
  note: string; // the readings card's note under the figures ("" for none)
}

export function runView(run: RunState, o: { hasResult: boolean; yearsSolved: number; yearsFailed: number; yearsTotal: number }): RunView {
  const inProgress = runInProgress(run);
  const quiet = inProgress && run.quiet;
  const base = { inProgress, overlay: run.kind === "running" && !run.quiet, quiet, problem: null, note: "" };
  if (run.kind === "failed") return { ...base, problem: `The run failed: ${run.error}`, label: `The run failed at ${run.at}`, roadmap: "run failed" };
  if (run.kind === "cancelled")
    return { ...base, problem: "The run stopped before every year was solved: run it again to finish.", label: `The run stopped at ${run.at}`, roadmap: "run stopped" };
  if (quiet) return { ...base, label: "Updating the years your edit touches…", roadmap: "updating years…" };
  if (run.kind === "pending") return { ...base, label: "Starting the run…", roadmap: "starting…" };
  const counted = `${o.yearsSolved} of ${o.yearsTotal}`;
  if (run.kind === "running") {
    // the shown result may still be the previous run's, every year in: the job's stage says where this run is
    const stage = run.stage.toLowerCase();
    if (isBriefing(stage)) {
      const briefing = stage.startsWith("narration");
      return {
        ...base,
        label: briefing ? "All years solved · writing the briefing…" : "All years solved · finishing the run…",
        roadmap: "finishing…",
        note: briefing ? "Every year is solved; the briefing is being written." : "Every year is solved; the run is recording its findings.",
      };
    }
    if (isYears(stage)) return { ...base, label: `Solving years · ${counted} in`, roadmap: "solving years…", note: "Solving the remaining years in the background." };
    return { ...base, label: "Deciding the queue · then every year", roadmap: "deciding the queue…", note: o.hasResult ? "A new run is deciding the queue; these figures are the previous run's." : "" };
  }
  if (!o.hasResult) return { ...base, label: "No run yet", roadmap: "" };
  if (o.yearsSolved < o.yearsTotal)
    return { ...base, label: `${counted} years solved · the run stopped`, roadmap: `${counted} years solved`, note: "The run stopped before every year was solved: run it again to finish." };
  if (o.yearsFailed) {
    const failed = `${o.yearsFailed} of ${o.yearsTotal}`;
    return { ...base, label: `All years run · ${failed} do not converge`, roadmap: `${failed} years do not converge` };
  }
  return { ...base, label: "All years solved", roadmap: "all years solved" };
}

/** The Run button wherever it appears (the header, the stale box, the narrow pill): one label and one reason to be
 * disabled. A click during a quiet refresh shows that run's card instead of starting another. */
export function runButton(view: RunView, stale: boolean, profileLabel: string, hasModel: boolean): { label: string; disabled: boolean; title: string } {
  const verb = stale ? "Re-run" : "Run";
  const label = profileLabel ? `${verb} on ${profileLabel}` : verb;
  if (!hasModel) return { label, disabled: true, title: "The grid is still loading." };
  if (view.quiet) return { label, disabled: false, title: "A refresh is under way: show its progress." };
  if (view.inProgress) return { label, disabled: true, title: "A run is under way." };
  return { label, disabled: false, title: stale ? "The shown result is out of date: run the plan again." : "Run the plan: the queue, then every year." };
}
