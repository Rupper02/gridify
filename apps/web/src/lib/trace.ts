// The agents as the planner shows them. Pure: the API runs the agents and records every step; this
// folds a reply's event stream into text and stage chips, names tools and stages, reads a message's
// evidence line, words the header pill, reads the runs list (elapsed, cost) and tells where the
// engineer's note on a branch stands.

import type { AgentRun, AgentsStatus, RunNote, ThreadMessage, TraceEvent, TraceStage } from "../types";

export const STAGE_LABEL: Record<TraceStage, string> = { PLAN: "Plan", ASSEMBLE: "Assemble", RUN: "Run", CHECK: "Check", PROPOSE: "Propose", CITE: "Cite" };


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
      else out.chips.push({ step_id: ev.step_id, tool: ev.tool, stage: ev.stage, status, summary: ev.summary, solves: ev.solves });
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
  return (m.tool_trace ?? []).map((t) => ({ step_id: t.step_id, tool: t.tool, stage: t.stage ?? "ASSEMBLE", status: "done" as const, summary: "", solves: t.solves ?? 0 }));
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

/** The figure a flag names ("figure 98765.4 appears in no tool output…" → "98765.4"); the flag itself when it names no number. */
export const flagFigure = (flag: string): string => /figure\s+(-?\d[\d,.]*)/i.exec(flag)?.[1] ?? flag;

// ---- the runs list ------------------------------------------------------------------------------

/** A run still going: queued for the runtime, or running. */
export const isLiveRun = (r: Pick<AgentRun, "status">): boolean => r.status === "queued" || r.status === "running";

const RUN_STATUS: Record<string, string> = { queued: "queued", running: "running", done: "done", failed: "failed", skipped: "skipped", skipped_paused: "skipped · paused", cancelled: "cancelled" };
export const runStatusLabel = (status: string): string => RUN_STATUS[status] ?? status.replace(/_/g, " ");

/** An API timestamp as epoch ms (a naive one is read as UTC, which is what the API writes); NaN when unreadable. */
const epoch = (iso: string): number => Date.parse(/(Z|[+-]\d\d:?\d\d)$/i.test(iso) ? iso : `${iso}Z`);

/** "48s", "1m 20s", "1h 05m". */
export function fmtElapsed(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

/** How long a run took, or has been going (to `now`); null before it started. */
export function runElapsed(r: Pick<AgentRun, "started_at" | "finished_at">, now: number): string | null {
  if (!r.started_at) return null;
  const a = epoch(r.started_at);
  const b = r.finished_at ? epoch(r.finished_at) : now;
  return Number.isFinite(a) && Number.isFinite(b) ? fmtElapsed(b - a) : null;
}

/** OpenRouter's billed cost in dollars, two decimals; "–" when the run has none recorded. */
export const fmtCost = (credits: number | null | undefined): string => (credits == null ? "–" : `$${credits.toFixed(2)}`);

/** The first sentence of a summary (up to the first full stop that ends a clause), trimmed. */
export function firstSentence(text: string | null | undefined): string {
  const t = (text ?? "").trim();
  const m = /^(.+?[.!?])(?:\s|$)/.exec(t);
  return m ? m[1] : t;
}

/** Where the engineer's note on a branch stands: being written (a `digest` run is live for the branch), of an earlier
 * run than the result shown (its run key differs), not written yet, or current. No result shown yet: nothing to compare. */
export type NoteState = { kind: "writing"; run: AgentRun } | { kind: "earlier" } | { kind: "none" } | { kind: "current" };
export function noteState(note: Pick<RunNote, "run_key"> | null, runKey: string | null | undefined, runs: AgentRun[], branchId: string): NoteState {
  const run = runs.find((r) => r.kind === "digest" && r.branch_id === branchId && isLiveRun(r));
  if (run) return { kind: "writing", run };
  if (!note) return { kind: "none" };
  if (runKey && note.run_key !== runKey) return { kind: "earlier" };
  return { kind: "current" };
}

/** The header pill: starting (the API's runtime is not up yet), idle, running or paused. */
export function agentsPill(st: AgentsStatus | null): { label: string; tone: "neutral" | "good" | "warn" | "bad"; title: string } {
  if (!st) return { label: "agents", tone: "neutral", title: "Checking the agents…" };
  if (st.status === "starting") return { label: "agents starting", tone: "neutral", title: "The agents are starting with the API; they answer and propose as soon as they are up." };
  if (st.status === "paused") {
    const why = `by the operator${st.paused_reason && st.paused_reason !== "operator" ? `: ${st.paused_reason}` : ""}`;
    return { label: "agents paused", tone: "warn", title: `Paused ${why}. Resume from the Ask tab.` };
  }
  if (st.status === "running") return { label: `agents · ${st.running} running`, tone: "good", title: `${st.running} agent ${st.running === 1 ? "run" : "runs"} in progress.` };
  return { label: "agents idle", tone: "good", title: "The agents answer questions and propose; a note is written after every run." };
}
