// Copilot "Recommendations": deterministic answers built from the last run and the engine's levers
// (/branches/{id}/suggestions). Every figure is the engine's; this module only chooses which figures
// to say. Pure, so the phrasing is unit-tested.

import { fmtMw } from "../theme";
import type { QueueItem, Suggestion } from "../types";
import { byStatus, deferredMw } from "./derive";

export type RecIntent =
  | { kind: "project"; id: string }
  | { kind: "gsp" }
  | { kind: "best" }
  | { kind: "unknown" };

/** What a typed question asks for: a deferred project by id, the GSP limit, or the best lever. */
export function recIntent(text: string, q: QueueItem[]): RecIntent {
  const t = text.toLowerCase();
  const deferred = byStatus(q, "Deferred");
  const hit = deferred.find((x) => t.includes(x.request_id.toLowerCase()));
  if (hit) return { kind: "project", id: hit.request_id };
  if (t.includes("gsp") || t.includes("limit") || t.includes("boundary")) return { kind: "gsp" };
  if (t.includes("best") || t.includes("most") || t.includes("2030")) return { kind: "best" };
  return { kind: "unknown" };
}

export function recsOpening(branchName: string, profileLabel: string, q: QueueItem[]): string {
  const df = byStatus(q, "Deferred");
  if (!df.length) return `I'm reading the last run on ${branchName} (${profileLabel} demand). Nothing is deferred, so there is nothing to unblock. Ask what limits the network, or add projects and re-run.`;
  return `I'm reading the last run on ${branchName} (${profileLabel} demand). ${df.length} project${df.length > 1 ? "s are" : " is"} deferred, ${fmtMw(deferredMw(q))} MW in total. Pick one to unblock, or ask what limits the network.`;
}

export function recsQuickReplies(q: QueueItem[]): string[] {
  const df = byStatus(q, "Deferred").filter((x) => x.reason?.kind === "grid");
  const out = df.slice(0, 2).map((x, i) => `${i ? "Explain" : "Unblock"} ${x.request_id}`);
  out.push("What limits the GSP?", "Best lever before 2030");
  return out;
}

/** The headline a lever card shows: the MW it frees (first-order, so ≈) and by when. */
export function leverFrees(s: Suggestion): string {
  if (s.freed_mw_2030 > 0) return `≈${fmtMw(s.freed_mw_2030)} MW by 2030`;
  if (s.freed_mw_2035 > 0) return `≈${fmtMw(s.freed_mw_2035)} MW by 2035`;
  return "frees nothing on its own";
}
export const leverConnects = (s: Suggestion): string =>
  s.newly_connected_project_ids.length ? `Connects ${s.newly_connected_project_ids.join(", ")}` : "Connects nothing on its own";
/** A lever can be tried on a branch only when it is a network reinforcement (not an operating change). */
export const leverTryable = (s: Suggestion): boolean => s.reinforcements.length > 0;

export function projectAnswer(x: QueueItem, levers: Suggestion[]): string {
  const why = x.reason ? `${x.request_id} is deferred: ${x.reason.short}.` : `${x.request_id} is deferred.`;
  if (x.reason?.kind === "readiness") return `${why} The grid could take it; the project isn't ready yet, so no network lever applies.`;
  if (!levers.length) return `${why} None of the engine's levers (parallel circuits, reactive absorption, a supergrid transformer) connects it on this network.`;
  return `${why} I re-solved ${levers.length} lever${levers.length > 1 ? "s" : ""}:`;
}

export function gspAnswer(exportMw: number | null, limit: number | null, year: number, sgtCount: number | null): string {
  if (exportMw == null || limit == null) return "The GSP export limit isn't modelled for this network.";
  const pct = Math.round((exportMw / limit) * 100);
  const sgt = sgtCount ? ` across ${sgtCount} supergrid transformers` : "";
  return `The boundary is the GSP export to transmission: ${fmtMw(exportMw)} of ${fmtMw(limit)} MW in ${year} (${pct}%)${sgt}, at its worst case, summer minimum. With one transformer out the limit halves (reported in the N-1 screen, not enforced).`;
}

export function bestAnswer(levers: Suggestion[]): string {
  if (!levers.length) return "No lever in the engine's set frees capacity on this branch.";
  const best = [...levers].sort((a, b) => b.freed_mw_2030 - a.freed_mw_2030 || b.freed_mw_2035 - a.freed_mw_2035)[0];
  return `The lever that lands the most MW before 2030 is "${best.action}", ${leverFrees(best)}. Each figure is first-order: re-run with it to measure the knock-on.`;
}

export const sortByMw2030 = (levers: Suggestion[]): Suggestion[] =>
  [...levers].sort((a, b) => b.freed_mw_2030 - a.freed_mw_2030 || b.freed_mw_2035 - a.freed_mw_2035);
