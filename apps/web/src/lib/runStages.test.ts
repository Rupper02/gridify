import { describe, expect, it } from "vitest";
import { runStatus } from "./runStages";

const base = { hasResult: true, solving: false, refreshing: false, stage: "", yearsSolved: 10, yearsFailed: 0, yearsTotal: 10 };

describe("runStatus", () => {
  it("says the same thing everywhere while years are still solving", () => {
    const st = runStatus({ ...base, solving: true, yearsSolved: 4, stage: "year 2029: both cases, N-1" });
    expect(st.phase).toBe("years");
    expect(st.label).toBe("Solving years · 4 of 10 in");
    expect(st.roadmap).toBe("solving years…");
  });
  it("is deciding the queue while a new run starts over a previous result with every year in", () => {
    for (const stage of ["queued", "starting", "ranking", "phase 2030: intact state", "phase 2035: N-1 screen"]) {
      const st = runStatus({ ...base, solving: true, stage });
      expect(st.phase).toBe("queue");
      expect(st.roadmap).toBe("deciding the queue…");
    }
  });
  it("is finishing, not done, once every year is in but the job still runs", () => {
    const st = runStatus({ ...base, solving: true, stage: "narration" });
    expect(st.phase).toBe("finishing");
    expect(st.label).toContain("writing the briefing");
    expect(st.roadmap).toBe("finishing…");
  });
  it("says a run stopped short instead of solving for ever", () => {
    const st = runStatus({ ...base, yearsSolved: 4 });
    expect(st.phase).toBe("stopped");
    expect(st.label).toBe("4 of 10 years solved · the run stopped");
  });
  it("is done only when nothing runs and every year is in", () => {
    expect(runStatus(base)).toMatchObject({ phase: "done", label: "All years solved", roadmap: "all years solved", note: "" });
  });
  it("names an edit's quiet refresh and the empty start", () => {
    expect(runStatus({ ...base, solving: true, refreshing: true }).phase).toBe("refreshing");
    expect(runStatus({ ...base, hasResult: false }).label).toBe("No run yet");
  });
});
