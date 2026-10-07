// The consequence diff, per plan year: what the Review tab says about the viewed year, what the
// map draws in diff mode (lines AND transformers), and the planned works on main vs the branch.
// Pure: given the API's diff (engine: diff.diff_results), no React.

import { C } from "../theme";
import type { BranchReinforcement, Diff, LoadingDelta, OnMerge, Outage, Verdict, WorkChange, WorkDelta, YearDelta } from "../types";
import { type ModelIndex, lineName, plural, trafoName } from "./derive";
import { VERDICTS, WORK_UI } from "./maintenance";

/** A loading change (percentage points) below this is not drawn on the map (its tag would read 0%). */
export const MAP_DELTA_MIN = 1;
/** A mover is worth a sentence in the Review tab from this many points. */
const MOVER_MIN = 5;
const MOVERS_PER_KIND = 3;

export type Tone = "bad" | "good" | "neutral";

/** The diff of the viewed year, or null when the diff has none for it (not solved on both runs). */
export const yearDeltaFor = (d: Diff | null, year: number): YearDelta | null => d?.years?.[String(year)] ?? null;

export interface MapDelta {
  delta: number;
  head: number;
}
/** Diff mode on the map: the loading change vs main per line and per transformer, changed ones only. */
export interface DiffMap {
  lines: Map<number, MapDelta>;
  trafos: Map<number, MapDelta>;
}

const changed = (xs: LoadingDelta[]): Map<number, MapDelta> =>
  new Map(xs.filter((t) => Math.abs(t.delta) >= MAP_DELTA_MIN).map((t) => [t.element_id, { delta: t.delta, head: t.head_pct ?? 0 }]));

export function diffMapFor(yd: YearDelta | null): DiffMap {
  return { lines: changed(yd?.top_line_deltas ?? []), trafos: changed(yd?.top_trafo_deltas ?? []) };
}

/** Diff mode colours a changed element by where it lands: red over 100%, amber otherwise. */
export const diffColor = (d: MapDelta): string => (d.head > 100 ? C.red : C.amber);

/** A map tag's text: the change, and the loading it reaches when that is over 100%. */
export const deltaTag = (d: MapDelta): string => `${d.delta > 0 ? "+" : ""}${Math.round(d.delta)}%${d.head > 100 ? ` · ${Math.round(d.head)}%` : ""}`;

export interface EffectItem {
  tone: Tone;
  text: string;
}
export interface Namers {
  line: (id: number) => string;
  trafo: (id: number) => string;
}

const pct = (x: number | null): string => `${Math.round(x ?? 0)}%`;

function elementItems(y: number, ids: { over: number[]; cleared: number[]; top: LoadingDelta[] }, name: (id: number) => string): EffectItem[] {
  const out: EffectItem[] = [];
  ids.over.forEach((id) => {
    const t = ids.top.find((x) => x.element_id === id);
    out.push({ tone: "bad", text: `${name(id)} newly over 100% in ${y}${t ? ` (${pct(t.base_pct)} to ${pct(t.head_pct)})` : ""}.` });
  });
  ids.cleared.forEach((id) => out.push({ tone: "good", text: `${name(id)} back within its rating in ${y}.` }));
  ids.top
    .filter((t) => Math.abs(t.delta) >= MOVER_MIN && t.crossed !== "newly_overloaded" && t.crossed !== "cleared")
    .slice(0, MOVERS_PER_KIND)
    .forEach((t) =>
      out.push({
        tone: t.delta > 0 && (t.head_pct ?? 0) > 90 ? "bad" : t.delta < 0 ? "good" : "neutral",
        text: `${name(t.element_id)} ${t.delta > 0 ? "rises" : "falls"} from ${pct(t.base_pct)} to ${pct(t.head_pct)} in ${y}.`,
      }),
    );
  return out;
}

/** The network effect of the branch in one year, in sentences, most serious first within each kind. */
export function yearEffect(yd: YearDelta, name: Namers): EffectItem[] {
  const y = yd.year;
  const items: EffectItem[] = [
    ...elementItems(y, { over: yd.newly_overloaded_line_ids, cleared: yd.cleared_line_ids, top: yd.top_line_deltas }, name.line),
    ...elementItems(y, { over: yd.newly_overloaded_trafo_ids, cleared: yd.cleared_trafo_ids, top: yd.top_trafo_deltas }, name.trafo),
  ];
  if (Math.abs(yd.worst_line_delta) >= 1)
    items.push({ tone: yd.worst_line_delta > 0 ? "bad" : "good", text: `Worst line loading ${yd.worst_line_delta > 0 ? "rises" : "falls"} ${Math.abs(Math.round(yd.worst_line_delta))} points, to ${pct(yd.worst_line_head)}.` });
  if (Math.abs(yd.worst_trafo_delta) >= 1)
    items.push({ tone: yd.worst_trafo_delta > 0 ? "bad" : "good", text: `Worst transformer loading ${yd.worst_trafo_delta > 0 ? "rises" : "falls"} ${Math.abs(Math.round(yd.worst_trafo_delta))} points, to ${pct(yd.worst_trafo_head)}.` });
  if (Math.abs(yd.min_vm_delta) >= 0.002)
    items.push({ tone: yd.min_vm_delta < 0 ? "bad" : "good", text: `Lowest voltage ${yd.min_vm_delta > 0 ? "lifts" : "drops"} ${Math.abs(yd.min_vm_delta).toFixed(3)} pu.` });
  if (Math.abs(yd.gsp_export_delta) >= 1) {
    const over = yd.gsp_limit_mw != null && yd.gsp_export_head > yd.gsp_limit_mw;
    const limit = yd.gsp_limit_mw != null ? ` (limit ${Math.round(yd.gsp_limit_mw)} MW)` : "";
    items.push({
      tone: over ? "bad" : "neutral",
      text: `Peak GSP export ${yd.gsp_export_delta > 0 ? "rises" : "falls"} from ${Math.round(yd.gsp_export_base)} to ${Math.round(yd.gsp_export_head)} MW${limit}.`,
    });
  }
  // an outage with no credible post-fault steady state is ONE finding however many elements it takes with it, so the
  // count below understates it: say it first, and never read a lower total as an improvement while it rose
  const collapses = (yd.n1_collapse_head ?? 0) - (yd.n1_collapse_base ?? 0);
  if (collapses !== 0)
    items.push({
      tone: collapses > 0 ? "bad" : "good",
      text: `${plural(Math.abs(collapses), "outage")} ${collapses > 0 ? "more" : "fewer"} with no credible post-fault steady state (${yd.n1_collapse_base ?? 0} to ${yd.n1_collapse_head ?? 0}).`,
    });
  if (yd.n1_findings_delta !== 0)
    items.push({
      tone: yd.n1_findings_delta > 0 || collapses > 0 ? "bad" : "good",
      text: `The N-1 screen finds ${plural(Math.abs(yd.n1_findings_delta), "second-fault problem")} ${yd.n1_findings_delta > 0 ? "more" : "fewer"} (${yd.n1_findings_base} to ${yd.n1_findings_head})${collapses > 0 ? ", a collapsed outage counting once" : ""}.`,
    });
  if (yd.energised_only_head.length)
    items.push({ tone: "neutral", text: `In service on this branch only: ${yd.energised_only_head.join(", ")}.` });
  return items;
}

/** Years worth flagging on the year selector: a new overload, more N-1 findings, or a window made worse. */
export function flaggedYears(d: Diff | null): Set<number> {
  const out = new Set<number>();
  Object.values(d?.years ?? {}).forEach((y) => {
    if (y.newly_overloaded_line_ids.length || y.newly_overloaded_trafo_ids.length || y.n1_findings_delta > 0 || (y.n1_collapse_head ?? 0) > (y.n1_collapse_base ?? 0)) out.add(y.year);
  });
  (d?.works ?? []).forEach((w) => w.change === "worse" && out.add(w.year));
  return out;
}

// ---- planned works --------------------------------------------------------------------------------
export const WORK_CHANGE: Record<WorkChange, { label: string; tone: Tone }> = {
  worse: { label: "Harder on this branch", tone: "bad" },
  better: { label: "Easier on this branch", tone: "good" },
  unchanged: { label: "Unchanged", tone: "neutral" },
  unstudied: { label: "Not studied on main", tone: "neutral" },
};

/** A verdict with its MW: "Curtailment 40 MW", "Demand at risk 12 MW", "Feasible". */
export function verdictText(v: Verdict | null, curtailed: number | null, atRisk: number | null): string {
  if (v == null) return "Not studied";
  const label = VERDICTS[v]?.label ?? v;
  if (v === "curtailment" && curtailed) return `${label} ${Math.round(curtailed * 10) / 10} MW`;
  if (v === "demand_at_risk" && atRisk) return `${label} ${Math.round(atRisk * 10) / 10} MW`;
  return label;
}

/** A window only the branch schedules that costs something (curtailment, demand at risk, second faults during it):
 * main carries none of it, so it reads as a new risk even when the branch's projects do not change it. */
export const isNewWorkRisk = (w: WorkDelta): boolean =>
  w.on_base === false && (w.verdict_on_branch !== "feasible" || (w.n1_findings_branch ?? 0) > 0);

/** The row's tone: a new risk is bad; otherwise what the branch's projects do to the window. */
export const workTone = (w: WorkDelta): Tone => (isNewWorkRisk(w) ? "bad" : WORK_CHANGE[w.change].tone);

export const verdictOnMain = (w: WorkDelta): string => verdictText(w.verdict_on_main, w.curtailed_mw_main, w.demand_at_risk_mw_main);
export const verdictOnBranch = (w: WorkDelta): string => verdictText(w.verdict_on_branch, w.curtailed_mw_branch, w.demand_at_risk_mw_branch);

const workLabel = (w: string): string => (WORK_UI as Record<string, { label: string } | undefined>)[w]?.label ?? w;

/** A simulated reinforcement as a line of text: its label, or what it does to which element. */
export const reinforcementLabel = (r: Pick<BranchReinforcement, "label" | "action" | "kind" | "element_id">): string =>
  r.label || `${r.action} ${r.kind} ${r.element_id}`;

/** A window's title: the work and the element it takes out, by name ("Maintenance · Boston to Spalding 132 kV"). */
export function workTitle(w: WorkDelta, o: Outage | undefined, ix: ModelIndex | null): string {
  return o ? outageTitle(o, ix, w.work) : `${workLabel(w.work)} · ${w.outage_id}`;
}

/** A planned window's title from the window itself (`work`: the work to name, the window's own by default). */
export function outageTitle(o: Outage, ix: ModelIndex | null, w: string = o.work): string {
  const work = workLabel(w);
  const id = o.element_id;
  const g = ix?.gen.get(id);
  const element = !ix
    ? `${o.element_kind} ${id}`
    : o.element_kind === "line"
      ? lineName(ix, Number(id))
      : o.element_kind === "trafo"
        ? trafoName(ix, Number(id))
        : g
          ? `${g.applicant || g.technology} (${id})`
          : id;
  return `${work} · ${element}`;
}

/** How many planned works and reinforcements merging adds to or removes from the base. */
export const mergeChangeCount = (m: OnMerge | undefined): number =>
  m ? m.works_added.length + m.works_removed.length + m.reinforcements_added.length + m.reinforcements_removed.length : 0;

/** The branch's windows for the Review tab: the viewed year's first, then the ones made worse, then by year. */
export function worksInOrder(works: WorkDelta[], year: number): WorkDelta[] {
  const rank = (w: WorkDelta) => (w.year === year ? 0 : w.change === "worse" ? 1 : 2);
  return [...works].sort((a, b) => rank(a) - rank(b) || a.year - b.year || a.outage_id.localeCompare(b.outage_id));
}
