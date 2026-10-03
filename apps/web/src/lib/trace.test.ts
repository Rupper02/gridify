import { describe, expect, it } from "vitest";

import type { AgentsStatus, ThreadMessage, TraceEvent } from "../types";
import { agentsPill, argsLine, evidenceLine, flagLines, foldTrace, isSuperseded, stageOf, toolLabel, traceFromMessage } from "./trace";

describe("stages and labels", () => {
  it("maps a tool to its planning stage by prefix, defaulting to ASSEMBLE", () => {
    expect(stageOf("study_hosting_capacity")).toBe("RUN");
    expect(stageOf("merge_check")).toBe("CHECK");
    expect(stageOf("findings")).toBe("CHECK");
    expect(stageOf("propose_branch")).toBe("PROPOSE");
    expect(stageOf("queue")).toBe("ASSEMBLE");
  });
  it("names tools in words", () => {
    expect(toolLabel("study_hosting_capacity")).toBe("hosting capacity study");
    expect(toolLabel("propose_works_window")).toBe("propose works window");
    expect(toolLabel("merge_check")).toBe("merge check");
  });
  it("puts the non-empty arguments on one line", () => {
    expect(argsLine({ branch_id: "br-1", params: {}, year: 2031, note: "" })).toBe("branch_id: br-1 · year: 2031");
    expect(argsLine({ params: { bus_ids: [1, 2] } })).toBe('params: {"bus_ids":[1,2]}');
  });
});

describe("foldTrace", () => {
  const events: TraceEvent[] = [
    { t: "tool_call", tool: "queue", stage: "ASSEMBLE", step_id: "r:1", args: {} },
    { t: "tool_result", tool: "queue", step_id: "r:1", summary: "5 projects", solves: 0 },
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
  it("marks a failed step, the citation, the final event and an error", () => {
    const f = foldTrace([
      ...events,
      { t: "tool_result", tool: "study_tap_margin", step_id: "r:2", summary: "error: budget spent", solves: 0 },
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
  tool_trace: [{ step_id: "r:1", tool: "queue", args: {}, solves: 0 }, { step_id: "r:2", tool: "study_tap_margin", args: {}, solves: 2 }],
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

describe("reviews and the pill", () => {
  it("knows a superseded review by the run key", () => {
    expect(isSuperseded({ run_key: "k1" }, "k1")).toBe(false);
    expect(isSuperseded({ run_key: "k1" }, "k2")).toBe(true);
    expect(isSuperseded({ run_key: "k1" }, null)).toBe(false); // no result shown yet: nothing to compare
  });
  it("words the agents pill for every state", () => {
    const base: AgentsStatus = { status: "idle", enabled: true, launched: true, running: 0, budget: null, last_events: [], models: {} };
    expect(agentsPill(null).label).toBe("agents");
    expect(agentsPill({ ...base, status: "off", enabled: false, reason: "no key" })).toMatchObject({ label: "agents off", tone: "neutral", title: "no key" });
    expect(agentsPill(base)).toMatchObject({ label: "agents idle", tone: "good" });
    expect(agentsPill({ ...base, status: "running", running: 2 })).toMatchObject({ label: "agents · 2 running", tone: "good" });
    expect(agentsPill({ ...base, status: "paused", paused_reason: "budget" }).title).toContain("budget");
    expect(agentsPill({ ...base, status: "paused", paused_reason: "operator" })).toMatchObject({ tone: "warn" });
  });
});
