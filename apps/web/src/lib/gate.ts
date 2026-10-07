// The merge gate and the findings ledger as the planner shows them. Pure: the API decides every
// verdict (engine gate.merge_verdict) and every finding (findings.extract_findings); this only turns
// them into a state for the Merge button, titles, grouping, and where a finding points on the map.

import { C } from "../theme";
import type { Finding, FindingSeverity, GateFinding, MergeCheck, Model, Outage, Sel } from "../types";
import { alertTitle } from "./demand";
import { type ModelIndex, type Staleness, nameElements, outageSel, plural } from "./derive";
import { VERDICTS } from "./maintenance";
import type { RunView } from "./runStages";

/** Where the Merge button stands (`unfinished`: the last run failed or stopped, so Retry runs it again). */
export type GateState = "closed" | "checking" | "unfinished" | "failed" | "stale" | "blocked" | "warnings" | "ready";

export interface GateView {
  state: GateState;
  headline: string;
}

/**
 * The gate's state from the server's check and what the client already knows: a run on its way is still checking,
 * a result the client sees as stale is stale whatever an older check said; a branch that is not open cannot merge.
 */
export function gateState(mc: MergeCheck | null, stale: Staleness, open: boolean, run: Pick<RunView, "inProgress" | "problem">, error: string | null = null): GateView {
  if (!open) return { state: "closed", headline: "This branch is not open." };
  if (run.problem) return { state: "unfinished", headline: "Re-run before merging: the last run did not finish." };
  if (run.inProgress) return { state: "checking", headline: "Solving the plan…" };
  if (stale.stale) return { state: "stale", headline: `Re-run before merging: ${stale.text}` };
  if (!mc) return error ? { state: "failed", headline: `Could not check whether this branch can merge: ${error}` } : { state: "checking", headline: "Checking whether this branch can merge…" };
  if (!mc.fresh) return { state: "stale", headline: `Re-run before merging: ${mc.stale_reasons[0] ?? "the result is out of date"}.` };
  const v = mc.verdict;
  if (v.blockers.length) {
    // being behind main is not a problem the branch introduces: it is fixed by a rebase, not by an edit
    const behind = v.blockers.filter((b) => b.kind === "behind_base").length;
    const own = v.blockers.length - behind;
    const rebase = behind ? `its parent moved on after this branch was opened (${plural(behind, "change")}): rebase it first` : "";
    const headline = own ? `Blocked: ${plural(own, "problem")} this branch introduces${rebase ? `, and ${rebase}` : ""}.` : `Blocked: ${rebase}.`;
    return { state: "blocked", headline };
  }
  if (v.warnings.length) return { state: "warnings", headline: `Ready to merge, with ${plural(v.warnings.length, "warning")} to acknowledge.` };
  return { state: "ready", headline: "Ready to merge: no new problem in any plan year." };
}

/** A gate finding's sentence with the engine's element indices named by place. */
export const gateText = (f: GateFinding, ix: ModelIndex | null): string => nameElements(f.message, ix);

/** Short titles for the gate's kinds (config.MERGE_GATE_LEVELS); unknown kinds fall back to the kind. */
export const GATE_KIND: Record<string, string> = {
  stale: "Out of date", no_result: "No result", unstudied_years: "Years not solved", non_convergent: "Power flow fails",
  behind_base: "Behind its parent", fork_unknown: "Fork point unknown", new_overload: "New overload", overload_worse: "Overload worse",
  new_voltage_violation: "New voltage breach", voltage_worse: "Voltage worse", gsp_over_limit: "GSP over its limit",
  gsp_worse: "GSP export worse", gsp_near_limit: "GSP near its limit", n1_new_islanded: "New N-1: demand cut off",
  n1_new_limit: "New N-1 finding", n1_new_collapse: "New N-1: no post-fault steady state", n1_worse: "N-1 finding worse", alert_new_breach: "New customer breach",
  alert_new_warn: "New customer warning", alert_worse: "Customer alert worse", work_worse_severe: "Planned work infeasible",
  work_worse: "Planned work harder", work_infeasible: "Planned work infeasible on both", work_new: "New planned work with a cost", against_recommendation: "Against the recommendation",
  profile_differs: "Demand profile changes", proposals_removed: "Removes proposals", preexisting: "Already on its parent",
  deferred_on_grid: "Still deferred",
};
export const gateTitle = (kind: string): string => GATE_KIND[kind] ?? kind.replace(/_/g, " ");

// ---- findings -------------------------------------------------------------------------------------
export const SEVERITY: Record<FindingSeverity, { c: string; label: string }> = {
  breach: { c: C.red, label: "Breach" },
  warn: { c: C.amber, label: "Warning" },
  info: { c: C.mute2, label: "Note" },
};
/** Worst first: breach, warn, info (the engine's severities). */
export const SEV_ORDER: Record<string, number> = { breach: 0, warn: 1, info: 2 };

/** Short titles for the ledger's kinds (findings.EXTRACTORS); alerts and works read their detail. */
const FINDING_KIND: Record<string, string> = {
  overload: "Over its rating", voltage: "Outside the voltage band", gsp_over_limit: "GSP over its export limit",
  gsp_near_limit: "GSP near its export limit", n1: "N-1 finding", deferred: "Deferred", rejected: "Not assessed",
  against_recommendation: "Scheduled against the recommendation", non_convergent: "Power flow did not converge",
};
export function findingTitle(f: Finding): string {
  if (f.kind === "alert") return alertTitle(String(f.context.alert_kind ?? ""));
  if (f.kind === "work") {
    const v = String(f.context.verdict ?? "");
    return `Planned work: ${(VERDICTS as Record<string, { label: string } | undefined>)[v]?.label ?? v}`;
  }
  if (f.kind === "deferred" && f.context.grid === false) return "Deferred at intake";
  return FINDING_KIND[f.kind] ?? f.kind.replace(/_/g, " ");
}

/** Where a bus shows on the map: the demand region it sits in, else a line on it (a bus is not selectable by itself). */
export function busSel(model: Model | null, bus: number): Sel | null {
  const region = (model?.regions ?? []).find((r) => r.buses.includes(bus));
  if (region) return { kind: "region", id: region.region_id };
  const line = (model?.lines ?? []).find((l) => l.from_bus === bus || l.to_bus === bus);
  return line ? { kind: "line", id: line.line_id } : null;
}

/** Where an element the engine names by kind and index points on the map (a bus through `busSel`); null for the GSP. */
export function elementSel(kind: string | null | undefined, id: number | string | null | undefined, model: Model | null): Sel | null {
  if (id == null) return null;
  if (kind === "line") return { kind: "line", id: Number(id) };
  if (kind === "trafo") return { kind: "trafo", id: Number(id) };
  if (kind === "bus" || kind === "voltage") return busSel(model, Number(id));
  return null;
}

/** Where a finding points on the map: the element, the project, the region, or the region a bus sits in. */
export function findingSel(f: Finding, model: Model | null, outages: Outage[]): Sel | null {
  const id = f.element_id;
  if (id == null) return null;
  switch (f.element_kind) {
    case "project":
      return { kind: "project", id };
    case "region":
      return { kind: "region", id };
    case "outage": {
      const o = outages.find((x) => x.outage_id === id);
      return o ? outageSel(o) : null;
    }
    default:
      return elementSel(f.element_kind, id, model);
  }
}

/** The verdict a refused merge carries (the 409 body `{code, message, fresh, verdict}`), as a check the Review tab can show. */
export function refusedCheck(detail: unknown, prev: MergeCheck | null, branchId: string, into: string): MergeCheck | null {
  if (!detail || typeof detail !== "object") return null;
  const d = detail as { code?: string; fresh?: boolean; verdict?: MergeCheck["verdict"] };
  if (!d.verdict || !d.code) return null;
  const fresh = d.fresh !== false;
  return {
    branch_id: branchId,
    into: prev?.into ?? into,
    branch_status: prev?.branch_status ?? "open",
    fresh,
    stale_reasons: fresh ? [] : [d.verdict.blockers[0]?.message ?? "the result is out of date"],
    requires_acknowledgement: d.code === "warnings_unacknowledged",
    verdict: d.verdict,
    evidence: prev?.evidence ?? {},
    checked_at: new Date().toISOString(),
  };
}
