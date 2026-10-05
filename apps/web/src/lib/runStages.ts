// The run overlay's stages, bound to the job's real stage strings (apps/api jobs + the engine's
// progress reports): ranking, the greedy trials per phase, every year of the plan, the briefing.

export interface RunStage {
  label: string;
  note: string;
}

export function runStages(profileLabel: string, nOutages: number): RunStage[] {
  return [
    { label: "Ranking the queue", note: "readiness · grid need · fit" },
    { label: "Phase 1 trials at 2030 demand", note: `${profileLabel} demand, both study cases` },
    { label: "Phase 2 trials at 2035 demand", note: "winter peak and summer minimum" },
    { label: "Every year, 2026 to 2035", note: `N-1 screen${nOutages ? ` · ${nOutages} planned outage${nOutages > 1 ? "s" : ""}` : ""}` },
    { label: "Drafting the briefing", note: "plain-English summary" },
  ];
}

/** Which stage a job stage string belongs to (queued and starting count as ranking). */
export function stageIndex(stage: string): number {
  const s = stage.toLowerCase();
  if (s.startsWith("narration") || s === "done") return 4;
  if (s.startsWith("year") || s === "queue decided") return 3;
  if (s.startsWith("phase 2035")) return 2;
  if (s.startsWith("phase 2030")) return 1;
  return 0;
}

/** The overlay's readout: the engine's own words for what it is doing. */
export function stageReadout(stage: string): string {
  if (!stage || stage === "queued") return "queued on the engine";
  if (stage === "starting") return "building the network";
  if (stage === "waiting for the solver") return "waiting for the solver: an agent's study step is finishing, then this run starts";
  if (stage === "ranking") return "one power flow at 2035 demand to read grid need";
  if (stage === "narration") return "phrasing results, physics already fixed";
  if (stage === "queue decided") return "queue decided, solving each year";
  return stage;
}

/** Where a run stands, as the result stamp, the roadmap and the readings card all say it (one source, so they
 * never disagree): the years still solving, every year in while the job still writes the findings and the
 * briefing, a run that stopped before its last year, or done. */
export type RunPhase = "none" | "refreshing" | "queue" | "years" | "finishing" | "stopped" | "done";

export interface RunStatus {
  phase: RunPhase;
  label: string; // the result stamp's line (the stamp adds what it knows, e.g. the planned outages, to "done")
  roadmap: string; // the roadmap's short note
  note: string; // the readings card's note under the figures ("" for none)
}

export function runStatus(o: { hasResult: boolean; solving: boolean; refreshing: boolean; stage: string; yearsSolved: number; yearsTotal: number }): RunStatus {
  if (!o.hasResult) return { phase: "none", label: "No run yet", roadmap: o.solving ? "solving years…" : "", note: "" };
  if (o.refreshing && o.solving) return { phase: "refreshing", label: "Updating the years your edit touches…", roadmap: "updating years…", note: "" };
  const counted = `${o.yearsSolved} of ${o.yearsTotal}`;
  const allIn = o.yearsSolved >= o.yearsTotal;
  const at = stageIndex(o.stage); // the shown result may still be the previous run's, all years in: the stage says where this run is
  if (o.solving && at < 3)
    return { phase: "queue", label: "Deciding the queue · then every year", roadmap: "deciding the queue…", note: "A new run is deciding the queue; these figures are the previous run's." };
  if (o.solving && at === 3 && !allIn)
    return { phase: "years", label: `Solving years · ${counted} in`, roadmap: "solving years…", note: "Solving the remaining years in the background." };
  if (o.solving) {
    const briefing = o.stage.toLowerCase().startsWith("narration");
    return {
      phase: "finishing",
      label: briefing ? "All years solved · writing the briefing…" : "All years solved · finishing the run…",
      roadmap: "finishing…",
      note: briefing ? "Every year is solved; the briefing is being written." : "Every year is solved; the run is recording its findings.",
    };
  }
  if (!allIn)
    return { phase: "stopped", label: `${counted} years solved · the run stopped`, roadmap: `${counted} years solved`, note: "The run stopped before every year was solved: run it again to finish." };
  return { phase: "done", label: "All years solved", roadmap: "all years solved", note: "" };
}
