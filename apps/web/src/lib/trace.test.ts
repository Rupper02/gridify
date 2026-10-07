import { describe, expect, it } from "vitest";

import type { AgentRun, ThreadMessage, TraceEvent } from "../types";
import { evidenceLine, flagFigure, flagLines, foldTrace, noteState, progressLabel, traceFromMessage } from "./trace";

describe("foldTrace", () => {
  const events: TraceEvent[] = [
    { t: "tool_call", tool: "queue", stage: "ASSEMBLE", step_id: "r:1", args: {} },
    { t: "tool_result", tool: "queue", stage: "ASSEMBLE", step_id: "r:1", summary: "5 projects", solves: 0 },
    { t: "tool_call", tool: "study_tap_margin", stage: "RUN", step_id: "r:2", args: {} },
    { t: "token", text: "Two transformers " },
    { t: "token", text: "are at a stop." },
  ];
  it("folds tokens into text and tool calls into chips, running until their result lands", () => {
    const f = foldTrace(events);
    expect(f.text).toBe("Two transformers are at a stop.");
    expect(f.chips.map((c) => [c.tool, c.status])).toEqual([
      ["queue", "done"],
      ["study_tap_margin", "running"],
    ]);
    expect(f.chips[0].summary).toBe("5 projects");
    expect(f.cited).toBe(false);
    expect(f.final).toBeNull();
  });
  it("shows a running study's latest stage and drops it once the result lands", () => {
    const mid = foldTrace([...events, { t: "progress", tool: "study_tap_margin", step_id: "r:2", stage: "tap_margin: part 1 of 2", fraction: 0 }]);
    expect(mid.chips[1].progress).toBe("part 1 of 2");
    const done = foldTrace([
      ...events,
      { t: "progress", tool: "study_tap_margin", step_id: "r:2", stage: "tap_margin: part 2 of 2", fraction: 0.5 },
      { t: "tool_result", tool: "study_tap_margin", stage: "RUN", step_id: "r:2", summary: "2 at a stop", solves: 4 },
    ]);
    expect(done.chips[1].status).toBe("done");
    expect(done.chips[1].progress).toBeUndefined();
    expect(progressLabel("contingency_ranking: winter peak")).toBe("winter peak");
    expect(progressLabel("years done")).toBe("years done");
  });
  it("marks a failed step, the citation, the final event and an error", () => {
    const f = foldTrace([
      ...events,
      { t: "tool_result", tool: "study_tap_margin", stage: "RUN", step_id: "r:2", summary: "error: budget spent", solves: 0 },
      { t: "cite", stage: "CITE" },
      { t: "final", status: "done", text: "ignored: text already streamed", flags: ["figure 9 appears in no tool output of this run"] },
    ]);
    expect(f.chips[1].status).toBe("failed");
    expect(f.cited).toBe(true);
    expect(f.final?.status).toBe("done");
    expect(f.text).toBe("Two transformers are at a stop.");
    expect(foldTrace([{ t: "error", message: "boom" }]).error).toBe("boom");
    expect(foldTrace([{ t: "final", status: "done", text: "only the final" }]).text).toBe("only the final");
  });
});

const msg = (over: Partial<ThreadMessage> = {}): ThreadMessage => ({
  message_id: "m-1", thread_id: "th-1", seq: 2, role: "assistant", content: "x", status: "done", workflow_id: "w", run_id: "r", usage: null,
  tool_trace: [{ step_id: "r:1", tool: "queue", stage: "ASSEMBLE", args: {}, solves: 0 }, { step_id: "r:2", tool: "study_tap_margin", stage: "RUN", args: {}, solves: 2 }],
  cost_credits: null, flags: ["figure 9 appears in no tool output of this run"],
  evidence: { steps: ["r:1", "r:2"], branch_id: "br-1", snapshot_id: "network@abcdef0123456789", engine: "0123456789abcdef" }, created_at: "2026-10-03T10:00:00Z", ...over,
});

describe("stored messages", () => {
  it("turns a stored trace into finished chips and an evidence line", () => {
    const chips = traceFromMessage(msg());
    expect(chips.map((c) => [c.stage, c.status, c.solves])).toEqual([["ASSEMBLE", "done", 0], ["RUN", "done", 2]]);
    expect(evidenceLine(msg())).toBe("queried br-1 @ network@ab · 2 steps · engine 0123456789");
    expect(evidenceLine(msg({ evidence: null }))).toBeNull();
    expect(flagLines(msg().flags)).toEqual(["Figure 9 appears in no tool output of this run"]);
  });
});

describe("the note", () => {
  const digest = (over: Partial<AgentRun> = {}): AgentRun => ({
    run_id: "d-1", project_id: "p", kind: "digest", agent: "digest", workflow_id: null, branch_id: "br-1", thread_id: null, event_id: null, parent_run_id: null,
    status: "running", started_at: "2026-10-03T10:00:00Z", finished_at: null, model: null, input_tokens: null, output_tokens: null, cost_credits: null, solves: null, summary: null, error: null, ...over,
  });
  it("tells a note being written, one of an earlier run, none yet, and the current one", () => {
    expect(noteState(null, "k1", [digest()], "br-1").kind).toBe("writing");
    expect(noteState(null, "k1", [digest({ branch_id: "br-2" })], "br-1").kind).toBe("none"); // another branch's digest
    expect(noteState({ run_key: "k1" }, "k2", [digest({ status: "done" })], "br-1").kind).toBe("earlier");
    expect(noteState({ run_key: "k1" }, "k1", [], "br-1").kind).toBe("current");
    expect(noteState({ run_key: "k1" }, null, [], "br-1").kind).toBe("current"); // no result shown yet: nothing to compare
  });
  it("picks the figure a flag names", () => {
    expect(flagFigure("figure 98765.4 appears in no tool output of this conversation")).toBe("98765.4");
    expect(flagFigure("no figure here")).toBe("no figure here");
  });
});
