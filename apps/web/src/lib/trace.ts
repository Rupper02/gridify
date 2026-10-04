// The agents as the planner shows them. Pure: the API runs the agents and records every step; this
// folds a reply's event stream into text and stage chips, names tools and stages, reads a message's
// evidence line, tells a superseded review, and words the header pill.

import type { AgentsStatus, Review, ThreadMessage, TraceEvent, TraceStage } from "../types";

export const STAGES: TraceStage[] = ["PLAN", "ASSEMBLE", "RUN", "CHECK", "PROPOSE", "CITE"];
export const STAGE_LABEL: Record<TraceStage, string> = { PLAN: "Plan", ASSEMBLE: "Assemble", RUN: "Run", CHECK: "Check", PROPOSE: "Propose", CITE: "Cite" };

/** The planning stage a tool belongs to, by name prefix (mirrors the API's `streaming.STAGE_BY_TOOL_PREFIX`; first match wins, "" is the default). */
export const STAGE_BY_TOOL_PREFIX: [string, TraceStage][] = [
  ["study_", "RUN"],
  ["merge_check", "CHECK"],
  ["findings", "CHECK"],
  ["propose_", "PROPOSE"],
  ["", "ASSEMBLE"],
];
export const stageOf = (tool: string): TraceStage => STAGE_BY_TOOL_PREFIX.find(([p]) => tool.startsWith(p))![1];

/** One tool call of a reply, as a chip: its stage, and whether it is still running. */
export interface TraceChip {
  step_id: string;
  tool: string;
  stage: TraceStage;
  status: "running" | "done" | "failed";
  summary: string;
  solves: number;
  /** The latest stage a running study reported ("part 1 of 2", "winter peak"); gone once it is done. */
  progress?: string;
}

export interface FoldedTrace {
  text: string;
  chips: TraceChip[];
  cited: boolean;
  final: Extract<TraceEvent, { t: "final" }> | null;
  error: string | null;
}

/** A reply's events so far, folded: the text, one chip per tool call (done once its result arrived), the end. */
export function foldTrace(events: TraceEvent[]): FoldedTrace {
  const out: FoldedTrace = { text: "", chips: [], cited: false, final: null, error: null };
  for (const ev of events) {
    if (ev.t === "token") out.text += ev.text;
    else if (ev.t === "tool_call") out.chips.push({ step_id: ev.step_id, tool: ev.tool, stage: ev.stage, status: "running", summary: "", solves: 0 });
    else if (ev.t === "progress") {
      const c = out.chips.find((x) => x.step_id === ev.step_id);
      if (c && c.status === "running") c.progress = progressLabel(ev.stage);
    }
    else if (ev.t === "tool_result") {
      const c = out.chips.find((x) => x.step_id === ev.step_id);
      const status = ev.summary.startsWith("error") ? "failed" : "done";
      if (c) Object.assign(c, { status, summary: ev.summary, solves: ev.solves, progress: undefined });
      else out.chips.push({ step_id: ev.step_id, tool: ev.tool, stage: stageOf(ev.tool), status, summary: ev.summary, solves: ev.solves });
    } else if (ev.t === "cite") out.cited = true;
    else if (ev.t === "final") {
      out.final = ev;
      out.cited = true;
      if (ev.text && !out.text) out.text = ev.text;
    } else if (ev.t === "error") out.error = ev.message;
  }
  return out;
}

/** A progress stage without the study's own name ("contingency_ranking: winter peak" reads "winter peak" next to the chip's label). */
export const progressLabel = (stage: string): string => (stage.includes(": ") ? stage.slice(stage.indexOf(": ") + 2) : stage);

/** A stored message's recorded tool calls as finished chips. */
export function traceFromMessage(m: Pick<ThreadMessage, "tool_trace">): TraceChip[] {
  return (m.tool_trace ?? []).map((t) => ({ step_id: t.step_id, tool: t.tool, stage: stageOf(t.tool), status: "done" as const, summary: "", solves: t.solves ?? 0 }));
}

/** "study_hosting_capacity" → "hosting capacity study"; "propose_branch" → "propose branch"; "merge_check" → "merge check". */
export function toolLabel(tool: string): string {
  if (tool.startsWith("study_")) return `${tool.slice(6).replace(/_/g, " ")} study`;
  return tool.replace(/_/g, " ");
}

/** A tool's arguments on one line, skipping the empty ones. */
export function argsLine(args: Record<string, unknown>): string {
  return Object.entries(args ?? {})
    .filter(([, v]) => v != null && v !== "" && !(typeof v === "object" && !Object.keys(v as object).length))
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" · ");
}

/** The line under an answer: what it queried and the steps it rests on. */
export function evidenceLine(m: Pick<ThreadMessage, "evidence" | "tool_trace">): string | null {
  const e = m.evidence;
  if (!e) return null;
  const n = e.steps?.length ?? m.tool_trace?.length ?? 0;
  return `queried ${e.branch_id ?? "main"} @ ${(e.snapshot_id ?? "").slice(0, 10)} · ${n} ${n === 1 ? "step" : "steps"} · engine ${(e.engine ?? "").slice(0, 10)}`;
}

/** The soft flags on an answer (figures no tool produced), as sentences. */
export const flagLines = (flags: string[] | null | undefined): string[] => (flags ?? []).map((f) => f.charAt(0).toUpperCase() + f.slice(1));

/** A review is of an earlier run when the shown result's key differs from the one it was written for. */
export const isSuperseded = (review: Pick<Review, "run_key">, runKey: string | null | undefined): boolean => !!runKey && review.run_key !== runKey;

/** The header pill: starting (the API's runtime is not up yet), idle, running or paused. */
export function agentsPill(st: AgentsStatus | null): { label: string; tone: "neutral" | "good" | "warn" | "bad"; title: string } {
  if (!st) return { label: "agents", tone: "neutral", title: "Checking the agents…" };
  if (st.status === "starting") return { label: "agents starting", tone: "neutral", title: "The agents are starting with the API; they answer, review and propose as soon as they are up." };
  if (st.status === "paused") {
    const why = st.paused_reason === "budget" ? "today's budget is spent" : `by the operator${st.paused_reason && st.paused_reason !== "operator" ? `: ${st.paused_reason}` : ""}`;
    return { label: "agents paused", tone: "warn", title: `Paused ${why}. Resume from the Ask tab.` };
  }
  if (st.status === "running") return { label: `agents · ${st.running} running`, tone: "good", title: `${st.running} agent ${st.running === 1 ? "run" : "runs"} in progress.` };
  return { label: "agents idle", tone: "good", title: "The agents watch the project: a review after every branch run, a sweep after merges and data changes." };
}
