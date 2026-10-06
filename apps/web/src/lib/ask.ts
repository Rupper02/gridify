// Ask: what the planner suggests asking the agents, from what is in view, and what to refresh after a
// proposal the operator approved. Pure, so both are unit-tested. The agents name elements the way the
// engine does ("line 12"), so a suggested question carries the engine's name next to the place. A
// proposal's arguments are phrased in words here too (`proposalText`), elements and branches by name.

import { fmtMw, techLabel } from "../theme";
import type { Branch, Outage, QueueItem, Sel, ThreadView } from "../types";
import { type ModelIndex, busWhere, lineName, trafoName } from "./derive";

export interface AskContext {
  q: QueueItem[];
  sel: Sel | null;
  outages: Outage[];
  year: number;
  ix: ModelIndex | null;
  /** The grid's voltage a new connection is asked about: its second line level, or its only one. */
  connectKv: number | null;
  /** The grid models a transmission boundary (a GSP export limit) to ask about. */
  boundary: boolean;
  /** The steward's "next checks" from its latest health brief, once read: they lead the suggestions. */
  nextChecks?: string[];
}

const MAX_QUESTIONS = 5;
const MAX_NEXT_CHECKS = 3;

/** Questions worth asking about the state in view: the steward's next checks, the first deferred project, the selection, the year's works, the GSP. */
export function suggestedQuestions(c: AskContext): string[] {
  const out: string[] = (c.nextChecks ?? []).slice(0, MAX_NEXT_CHECKS);
  const deferred = c.q.filter((x) => x.status === "Deferred" && x.reason?.kind === "grid");
  if (deferred.length) out.push(`How could ${deferred[0].request_id} connect? What would it take?`);
  if (c.sel?.kind === "project") {
    const x = c.q.find((p) => p.request_id === c.sel!.id);
    if (x) out.push(x.status === "Deferred" ? `Why is ${x.request_id} deferred, and what are its options?` : `What does ${x.request_id} do to the network in ${c.year}?`);
  }
  if (c.sel?.kind === "line" || c.sel?.kind === "trafo") {
    const noun = c.sel.kind === "line" ? "line" : "transformer";
    const place = c.ix ? (c.sel.kind === "line" ? lineName(c.ix, c.sel.id) : trafoName(c.ix, c.sel.id)) : "";
    // the name a person uses, the id in brackets for the agent's tools (the convention every agent answer follows)
    out.push(`When is the best window to take ${place ? `${place} (${noun} ${c.sel.id})` : `${noun} ${c.sel.id}`} out for 4 weeks?`);
  }
  if (c.sel?.kind === "gen") out.push(`When is the best window to take generator ${c.sel.id} out for 8 weeks?`);
  if (c.outages.some((o) => o.year === c.year)) out.push(`What do the planned works in ${c.year} do to the network, and is anything at risk during them?`);
  if (c.boundary) out.push("What limits the GSP export by the end of the plan?");
  out.push(`Where can 50 MW of export connect${c.connectKv != null ? ` at ${+c.connectKv} kV` : ""} today?`);
  return [...new Set(out)].slice(0, MAX_QUESTIONS);
}

/** The "next checks" of the latest brief in the project's health thread (empty for any other thread, or none). */
export function latestNextChecks(t: Pick<ThreadView, "kind" | "messages"> | null | undefined): string[] {
  if (t?.kind !== "health") return [];
  const brief = [...t.messages].reverse().find((m) => m.role === "assistant" && m.evidence?.next_checks?.length);
  return brief?.evidence?.next_checks ?? [];
}

/** What the planner refreshes after a proposal the operator approved, by the tool that made it. */
export type ProposalEffect = "run" | "project" | "reinforcement" | "works" | "branch" | "rebase";
export const PROPOSAL_EFFECT: Record<string, ProposalEffect> = {
  propose_run: "run",
  propose_rebase: "rebase",
  propose_candidate: "project",
  propose_candidate_change: "project",
  propose_reinforcement: "reinforcement",
  propose_works_window: "works",
  propose_branch: "branch",
};
export const proposalEffect = (tool: string): ProposalEffect | null => PROPOSAL_EFFECT[tool] ?? null;

// ---- a proposal in words --------------------------------------------------------------------------

type Args = Record<string, unknown>;
interface ProposalCtx {
  ix: ModelIndex | null;
  branches: Branch[];
}

const str = (v: unknown): string => (v == null ? "" : String(v));
const num = (v: unknown): number | null => {
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  return Number.isFinite(n) ? n : null;
};
const mw = (v: unknown): string => `${fmtMw(num(v))} MW`;
const cap = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);
const joinClauses = (xs: string[]): string => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);
const branchName = (c: ProposalCtx, id: unknown): string => c.branches.find((b) => b.branch_id === str(id))?.name ?? (str(id) || "the branch");

/** "Sleaford 132 kV busbar (bus 19)", or "bus 19" when nothing near it is named. */
function busText(ix: ModelIndex | null, id: unknown): string {
  const n = num(id);
  const where = busWhere(ix, n);
  return where.startsWith("bus ") || where === "–" ? `bus ${str(id)}` : `${where} busbar (bus ${n})`;
}

/** An element by name with the engine's id in brackets ("Boston to Spalding 132 kV (line 4)"). */
function elementText(ix: ModelIndex | null, kind: string, id: unknown): string {
  const n = num(id);
  if (kind === "gsp") return "the GSP export limit";
  if (kind === "line") return ix && n != null && ix.line.has(n) ? `${lineName(ix, n)} (line ${n})` : `line ${str(id)}`;
  if (kind === "trafo" || kind === "transformer") return ix && n != null && ix.trafo.has(n) ? `${trafoName(ix, n)} (transformer ${n})` : `transformer ${str(id)}`;
  if (kind === "gen") {
    const g = ix?.gen.get(str(id));
    return g ? `${g.applicant || techLabel(g.technology)} (${str(id)})` : `generator ${str(id)}`;
  }
  return `${kind} ${str(id)}`;
}

/** How a project is to run, from a `Control` as the agent passed it. */
function controlText(v: unknown): string {
  const c = (v ?? {}) as { mode?: unknown; pf?: unknown; absorbing?: unknown; vm_pu?: unknown };
  if (c.mode === "voltage") return `under voltage control${num(c.vm_pu) != null ? ` at ${num(c.vm_pu)} pu` : ""}`;
  return `at power factor ${num(c.pf) ?? "–"}${c.absorbing ? " (absorbing)" : ""}`;
}

/** Each proposal tool in words; elements and buses through the model index, branches by name. The raw arguments stay on hover. */
export const PROPOSAL_TEXT: Record<string, (a: Args, c: ProposalCtx) => string> = {
  propose_run: (a, c) => `Run ${branchName(c, a.branch_id)} now`,
  propose_rebase: (a, c) => `Rebase ${branchName(c, a.branch_id)} onto its parent`,
  propose_branch: (a) => `Open a branch '${str(a.name) || "unnamed"}' off main${str(a.note) ? `: ${str(a.note)}` : ""}`,
  propose_candidate: (a, c) => {
    const what = [str(a.technology), num(a.rating_mw) != null ? mw(a.rating_mw) : ""].filter(Boolean).join(", ");
    const year = num(a.commissioning_year);
    return `Add ${str(a.applicant) || "a project"}${what ? ` (${what})` : ""} at ${busText(c.ix, a.bus_id)}${num(a.import_mw) != null ? `, importing ${mw(a.import_mw)}` : ""}${year != null ? ` asking for ${year}` : ""} on ${branchName(c, a.branch_id)}`;
  },
  propose_candidate_change: (a, c) => {
    const rid = str(a.request_id) || "the project";
    const rating = num(a.rating_mw);
    const imp = num(a.import_mw);
    const year = num(a.commissioning_year);
    const clauses: ((subject: string) => string)[] = [];
    if (rating != null) clauses.push((s) => `resize ${s} to ${mw(rating)}${imp != null ? ` (import ${mw(imp)})` : " (its import follows)"}`);
    else if (imp != null) clauses.push((s) => `set ${s} to import ${mw(imp)}`);
    if (a.bus_id != null) clauses.push((s) => `move ${s} to ${busText(c.ix, a.bus_id)}`);
    if (year != null) clauses.push((s) => `ask for ${s} in ${year}`);
    if (a.control != null) clauses.push((s) => `run ${s} ${controlText(a.control)}`);
    if (!clauses.length) return `Change ${rid} on ${branchName(c, a.branch_id)}`;
    return `${cap(joinClauses(clauses.map((f, i) => f(i === 0 ? rid : "it"))))} on ${branchName(c, a.branch_id)}`;
  },
  propose_reinforcement: (a, c) => {
    const kind = str(a.kind);
    const el = elementText(c.ix, kind, a.element_id);
    const factor = num(a.factor);
    const what =
      str(a.action) === "add_parallel"
        ? kind === "line" ? `Add a parallel circuit on ${el}` : kind === "trafo" ? `Add a second unit at ${el}` : `Add capacity at ${el}`
        : `${kind === "gsp" ? "Raise" : "Uprate"} ${el}${factor != null ? ` ×${Math.round(factor * 100) / 100}` : ""}`;
    return `${what} on ${branchName(c, a.branch_id)}`;
  },
  propose_works_window: (a, c) => {
    const weeks = num(a.weeks);
    return `Schedule ${weeks != null ? `${weeks} ${weeks === 1 ? "week" : "weeks"} of ` : ""}${str(a.work) || "work"} on ${elementText(c.ix, str(a.element_kind), a.element_id)} in ${[str(a.season), str(a.year)].filter(Boolean).join(" ")} on ${branchName(c, a.branch_id)}`;
  },
};

/** A proposal in words, or null for a tool this registry does not know (the card then shows its arguments as given). */
export function proposalText(tool: string, args: Args | null | undefined, ix: ModelIndex | null, branches: Branch[]): string | null {
  const phrase = PROPOSAL_TEXT[tool];
  return phrase ? phrase(args ?? {}, { ix, branches }) : null;
}
