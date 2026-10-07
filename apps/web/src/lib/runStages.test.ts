import { describe, expect, it } from "vitest";
import { type RunState, runView } from "./runStages";

const years = { hasResult: true, yearsSolved: 10, yearsFailed: 0, yearsTotal: 10 };
const running = (stage: string, quiet = false): RunState => ({ kind: "running", branchId: "b", jobId: "j", quiet, token: 1, requestedAt: 0, stage, fraction: 0.5, startedAt: "10:00" });

describe("runView", () => {
  it("says the same thing everywhere while years are still solving, and shows the card only for a loud run", () => {
    const v = runView(running("year 2029: both cases, N-1"), { ...years, yearsSolved: 4 });
    expect(v).toMatchObject({ inProgress: true, overlay: true, quiet: false, problem: null, label: "Solving years · 4 of 10 in", roadmap: "solving years…" });
  });
  it("is deciding the queue while a new run starts over a previous result with every year in", () => {
    for (const stage of ["queued", "starting", "ranking", "phase 2030: intact state", "phase 2035: N-1 screen"]) {
      expect(runView(running(stage), years).roadmap).toBe("deciding the queue…");
    }
  });
  it("is finishing, not done, once every year is in but the job still runs", () => {
    const v = runView(running("writing findings"), years);
    expect(v.label).toContain("finishing the run");
    expect(v.roadmap).toBe("finishing…");
  });
  it("keeps a quiet refresh off the card from the debounce to the end", () => {
    const pending = runView({ kind: "pending", branchId: "b", quiet: true, token: 1, requestedAt: 0 }, years);
    expect(pending).toMatchObject({ inProgress: true, overlay: false, quiet: true, label: "Updating the years your edit touches…" });
    expect(runView(running("year 2029", true), years).overlay).toBe(false);
    expect(runView({ kind: "pending", branchId: "b", quiet: false, token: 1, requestedAt: 0 }, years)).toMatchObject({ inProgress: true, overlay: false, quiet: false });
  });
  it("carries a failed or stopped run as a persistent problem, not in progress", () => {
    const failed = runView({ kind: "failed", branchId: "b", error: "boom", at: "10:02" }, years);
    expect(failed).toMatchObject({ inProgress: false, overlay: false, problem: "The run failed: boom" });
    const stopped = runView({ kind: "cancelled", branchId: "b", at: "10:02" }, years);
    expect(stopped.problem).toContain("stopped before every year");
  });
  it("is done only when idle and every year is in, and says when a stored result stopped short", () => {
    expect(runView({ kind: "idle" }, years)).toMatchObject({ inProgress: false, problem: null, label: "All years solved", roadmap: "all years solved", note: "" });
    expect(runView({ kind: "idle" }, { ...years, yearsSolved: 4 }).label).toBe("4 of 10 years solved · the run stopped");
    expect(runView({ kind: "idle" }, { ...years, hasResult: false }).label).toBe("No run yet");
  });
});
