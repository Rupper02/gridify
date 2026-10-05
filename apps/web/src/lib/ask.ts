// Ask: what the planner suggests asking the agents, from what is in view, and what to refresh after a
// proposal the operator approved. Pure, so both are unit-tested. The agents name elements the way the
// engine does ("line 12"), so a suggested question carries the engine's name next to the place.

import type { Outage, QueueItem, Sel } from "../types";
import { type ModelIndex, lineName, trafoName } from "./derive";

export interface AskContext {
  q: QueueItem[];
  sel: Sel | null;
  outages: Outage[];
  year: number;
  ix: ModelIndex | null;
}

const MAX_QUESTIONS = 5;

/** Questions worth asking about the state in view: the first deferred project, the selection, the year's works, the GSP. */
export function suggestedQuestions(c: AskContext): string[] {
  const out: string[] = [];
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
  out.push("What limits the GSP export by 2035?", "Where can 50 MW of export connect at 33 kV today?");
  return [...new Set(out)].slice(0, MAX_QUESTIONS);
}

/** What the planner refreshes after a proposal the operator approved, by the tool that made it. */
export type ProposalEffect = "run" | "project" | "reinforcement" | "works" | "branch";
export const PROPOSAL_EFFECT: Record<string, ProposalEffect> = {
  propose_run: "run",
  propose_candidate: "project",
  propose_candidate_change: "project",
  propose_reinforcement: "reinforcement",
  propose_works_window: "works",
  propose_branch: "branch",
};
export const proposalEffect = (tool: string): ProposalEffect | null => PROPOSAL_EFFECT[tool] ?? null;
