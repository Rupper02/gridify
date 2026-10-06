// The merge gate and the findings ledger as the planner shows them. Pure: the API decides every
// verdict (engine gate.merge_verdict) and every finding (findings.extract_findings); this only turns
// them into a state for the Merge button, titles, grouping, and where a finding points on the map.

import type { Finding, FindingSeverity, GateFinding, MergeCheck, Model, Outage, Sel } from "../types";
import { alertTitle } from "./demand";
import { type ModelIndex, type Staleness, nameElements, outageSel } from "./derive";
import { VERDICT } from "./diff";

/** Where the Merge button stands. */
export type GateState = "closed" | "checking" | "stale" | "blocked" | "warnings" | "ready";

export interface GateView {
  state: GateState;
  headline: string;
}

const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`;

/**
 * The gate's state from the server's check and what the client already knows: a result the client
 * sees as stale is stale whatever an older check said; a branch that is not open cannot merge.
 */
export function gateState(mc: MergeCheck | null, stale: Staleness, open: boolean, running: boolean): GateView {
  if (!open) return { state: "closed", headline: "This branch is not open." };
  if (running) return { state: "checking", headline: "Solving the plan…" };
  if (stale.stale) return { state: "stale", headline: `Re-run before merging: ${stale.text}` };
  if (!mc) return { state: "checking", headline: "Checking whether this branch can merge…" };
  if (!mc.fresh) return { state: "stale", headline: `Re-run before merging: ${mc.stale_reasons[0] ?? "the result is out of date"}.` };
  const v = mc.verdict;
  if (v.blockers.length) {
    // being behind main is not a problem the branch introduces: it is fixed by a rebase, not by an edit
    const behind = v.blockers.filter((b) => b.kind === "behind_base").length;
    const own = v.blockers.length - behind;
    const rebase = behind ? `main moved on after this branch was opened (${plural(behind, "change")}): rebase it first` : "";
    const headline = own ? `Blocked: ${plural(own, "problem")} this branch introduces${rebase ? `, and ${rebase}` : ""}.` : `Blocked: ${rebase}.`;
    return { state: "blocked", headline };
  }
  if (v.warnings.length) return { state: "warnings", headline: `Ready to merge, with ${plural(v.warnings.length, "warning")} to acknowledge.` };
  return { state: "ready", headline: "Ready to merge: no new problem in any plan year." };
}

export const firstBlocker = (mc: MergeCheck | null): GateFinding | null => mc?.verdict.blockers[0] ?? null;

/** Warnings need the operator's acknowledgement before the merge goes through. */
export const needsConfirm = (mc: MergeCheck | null): boolean => !!mc && mc.verdict.ok && mc.verdict.warnings.length > 0;

/** A gate finding's sentence with the engine's element indices named by place. */
export const gateText = (f: GateFinding, ix: ModelIndex | null): string => nameElements(f.message, ix);

/** Short titles for the gate's kinds (config.MERGE_GATE_LEVELS); unknown kinds fall back to the kind. */
export const GATE_KIND: Record<string, string> = {
  stale: "Out of date", no_result: "No result", unstudied_years: "Years not solved", non_convergent: "Power flow fails",
  behind_base: "Behind main", fork_unknown: "Fork point unknown", new_overload: "New overload", overload_worse: "Overload worse",
  new_voltage_violation: "New voltage breach", voltage_worse: "Voltage worse", gsp_over_limit: "GSP over its limit",
  gsp_worse: "GSP export worse", gsp_near_limit: "GSP near its limit", n1_new_islanded: "New N-1: demand cut off",
  n1_new_limit: "New N-1 finding", n1_worse: "N-1 finding worse", alert_new_breach: "New customer breach",
  alert_new_warn: "New customer warning", alert_worse: "Customer alert worse", work_worse_severe: "Planned work infeasible",
  work_worse: "Planned work harder", work_infeasible: "Planned work infeasible on both", work_new: "New planned work with a cost", against_recommendation: "Against the recommendation",
  profile_differs: "Demand profile changes", proposals_removed: "Removes proposals", preexisting: "Already on main",
  deferred_on_grid: "Still deferred",
};
export const gateTitle = (kind: string): string => GATE_KIND[kind] ?? kind.replace(/_/g, " ");

// ---- findings -------------------------------------------------------------------------------------
export const SEVERITY: Record<FindingSeverity, { c: string; label: string }> = {
  breach: { c: "#ff6b6b", label: "Breach" },
  warn: { c: "#ffc36b", label: "Warning" },
  info: { c: "#7d8da3", label: "Note" },
};
const SEV_ORDER: Record<string, number> = { breach: 0, warn: 1, info: 2 };

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
    return `Planned work: ${(VERDICT as Record<string, { label: string }>)[v]?.label ?? v}`;
  }
  if (f.kind === "deferred" && f.context.grid === false) return "Deferred at intake";
  return FINDING_KIND[f.kind] ?? f.kind.replace(/_/g, " ");
}

/** Findings grouped for the tab: plan-wide ones first (no year), then year by year, breaches first within each. */
export function findingsByYear(fs: Finding[]): { year: number | null; rows: Finding[] }[] {
  const by = new Map<number | null, Finding[]>();
  fs.forEach((f) => by.set(f.year, [...(by.get(f.year) ?? []), f]));
  const years = [...by.keys()].sort((a, b) => (a == null ? -1 : b == null ? 1 : a - b));
  return years.map((year) => ({
    year,
    rows: [...by.get(year)!].sort((a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9) || a.kind.localeCompare(b.kind)),
  }));
}

/** Where a finding points on the map: the element, the project, the region, or the region a bus sits in. */
export function findingSel(f: Finding, model: Model | null, outages: Outage[]): Sel | null {
  const id = f.element_id;
  if (id == null) return null;
  switch (f.element_kind) {
    case "line":
      return { kind: "line", id: Number(id) };
    case "trafo":
      return { kind: "trafo", id: Number(id) };
    case "project":
      return { kind: "project", id };
    case "region":
      return { kind: "region", id };
    case "outage": {
      const o = outages.find((x) => x.outage_id === id);
      return o ? outageSel(o) : null;
    }
    case "bus": {
      const bus = Number(id);
      const region = (model?.regions ?? []).find((r) => r.buses.includes(bus));
      if (region) return { kind: "region", id: region.region_id };
      const line = (model?.lines ?? []).find((l) => l.from_bus === bus || l.to_bus === bus);
      return line ? { kind: "line", id: line.line_id } : null;
    }
    default:
      return null;
  }
}

/** How many findings are open, and how many of those are breaches and warnings (the tab's badge). */
export function openCounts(fs: Finding[]): { open: number; breach: number; warn: number } {
  const open = fs.filter((f) => f.status === "open");
  return { open: open.length, breach: open.filter((f) => f.severity === "breach").length, warn: open.filter((f) => f.severity === "warn").length };
}

/** The verdict a refused merge carries (the 409 body `{code, message, fresh, verdict}`), as a check the Review tab can show. */
export function refusedCheck(detail: unknown, prev: MergeCheck | null, branchId: string): MergeCheck | null {
  if (!detail || typeof detail !== "object") return null;
  const d = detail as { code?: string; fresh?: boolean; verdict?: MergeCheck["verdict"] };
  if (!d.verdict || !d.code) return null;
  const fresh = d.fresh !== false;
  return {
    branch_id: branchId,
    into: prev?.into ?? "main",
    branch_status: prev?.branch_status ?? "open",
    fresh,
    stale_reasons: fresh ? [] : [d.verdict.blockers[0]?.message ?? "the result is out of date"],
    requires_acknowledgement: d.code === "warnings_unacknowledged",
    verdict: d.verdict,
    evidence: prev?.evidence ?? {},
    checked_at: new Date().toISOString(),
  };
}
