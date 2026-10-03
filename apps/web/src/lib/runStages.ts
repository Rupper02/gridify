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
  if (stage === "ranking") return "one power flow at 2035 demand to read grid need";
  if (stage === "narration") return "phrasing results, physics already fixed";
  if (stage === "queue decided") return "queue decided, solving each year";
  return stage;
}
