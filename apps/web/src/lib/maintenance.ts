// Planned works in words: what a window is (maintenance, repowering, replacement), how it reads on the
// map and the roadmap, and what the engine's study of it says (verdict, curtailment, demand at risk,
// N-1 during the window, what the work leaves behind). Pure: every figure restates the engine's study.
// A new kind of work is one entry in WORK_UI; a new verdict is one entry in VERDICTS and HEADLINE.

import { C, caseLabel, fmtMw, techLabel } from "../theme";
import type { Tone } from "./diff";
import type { Curtailment, ElementKind, ElementSel, N1During, N1Violation, OptimizeResult, Outage, OutageStudy, QueueItem, Repower, Season, Verdict, Work } from "../types";
import { busLabel, elementInfo, lineName, nameElements, outageSel, outageStudyOf, plural, trafoName, type ModelIndex } from "./derive";
import { type Plan, lastYear } from "./plan";

// ---- the schedule form -------------------------------------------------------------------------
export interface MaintDraft {
  season: Season;
  year: number;
  weeks: number;
  work: Work;
  /** Maintenance only. */
  kind: "outage" | "derate";
  /** Repowering only (kept while another work is picked, so switching back remembers it). */
  repower: Repower;
  factor: number;
}

/** The form's defaults; its year is the viewed year, seeded when an element is selected (useSelection). */
export const INITIAL_DRAFT: MaintDraft = { season: "Summer", year: 0, weeks: 4, work: "maintenance", kind: "outage", repower: "uprate", factor: 1.5 };

/** The uprate factors offered: 1.25x to 4x in quarter steps (the API accepts 1 < factor <= 4). */
export const FACTOR_MIN = 1.25;
export const FACTOR_MAX = 4;
export const FACTOR_STEP = 0.25;
export const stepFactor = (f: number, dir: 1 | -1): number =>
  Math.min(FACTOR_MAX, Math.max(FACTOR_MIN, Math.round((f + dir * FACTOR_STEP) / FACTOR_STEP) * FACTOR_STEP));

export type OutageBody = Omit<Outage, "outage_id" | "created_at">;

/** The API body for a draft on an element: only the fields its work takes (the API rejects the rest). */
export function draftBody(sel: ElementSel, d: MaintDraft): OutageBody {
  const base = { element_kind: sel.kind, element_id: String(sel.id), season: d.season, year: d.year, weeks: d.weeks, work: d.work };
  if (d.work === "maintenance") return { ...base, kind: d.kind, repower: null, factor: null };
  if (d.work === "replacement") return { ...base, kind: "outage", repower: null, factor: null };
  return { ...base, kind: "outage", repower: d.repower, factor: d.repower === "uprate" ? d.factor : null };
}

/** "Add a parallel circuit", per element kind (a generator gets a second unit). */
export const PARALLEL_LABEL: Record<ElementKind, string> = {
  line: "Add a parallel circuit",
  trafo: "Add a parallel transformer",
  gen: "Add a second unit",
};

const fx = (f: number | null | undefined): string => `${+(f ?? 0).toFixed(2)}x`;
const ratingWord = (k: ElementKind): string => (k === "gen" ? "export rating" : "rating");

/** What a repowered element is like after its window ("back at 1.5x its rating"). */
export function repowerChange(o: Pick<Outage, "element_kind" | "repower" | "factor">): string {
  if (o.repower === "add_parallel") return o.element_kind === "gen" ? "back with a second unit" : o.element_kind === "trafo" ? "back with a parallel transformer" : "back with a parallel circuit";
  return `back at ${fx(o.factor)} its ${ratingWord(o.element_kind)}`;
}

interface WorkUi {
  label: string;
  /** The map tag ("OUT", "50%", "REPOWER", "REPLACE"). */
  tag: (o: Pick<Outage, "kind">) => string;
  /** The roadmap chip's compact tag ("OUT", "50%", "RPW", "RPL"). */
  chip: (o: Pick<Outage, "kind">) => string;
  /** The window in a row ("full outage", "repowering, uprate to 1.5x"). */
  describe: (o: Pick<Outage, "kind" | "element_kind" | "repower" | "factor">) => string;
  /** What the form says is studied, and what happens after the window (`lastYear`: the plan's last year). */
  hint: (d: MaintDraft, kind: ElementKind, lastYear: number) => string;
}

/** A derate window's rating, in percent (mirrors the engine's config.OUTAGE_DERATE_FACTOR, 0.5). */
export const DERATE_PCT = 50;

export const WORK_UI: Record<Work, WorkUi> = {
  maintenance: {
    label: "Maintenance",
    tag: (o) => (o.kind === "derate" ? `${DERATE_PCT}%` : "OUT"),
    chip: (o) => (o.kind === "derate" ? `${DERATE_PCT}%` : "OUT"),
    describe: (o) => (o.kind === "derate" ? `derate to ${DERATE_PCT}%` : "full outage"),
    hint: (d) => `${d.kind === "derate" ? `Studied at ${DERATE_PCT}% of its rating` : "Studied out of service"} during the window. Back as it was after it.`,
  },
  repowering: {
    label: "Repowering",
    tag: () => "REPOWER",
    chip: () => "RPW",
    describe: (o) => (o.repower === "add_parallel" ? `repowering, ${PARALLEL_LABEL[o.element_kind].toLowerCase()}` : `repowering, uprate to ${fx(o.factor)}`),
    hint: (d, kind, lastYear) =>
      d.year + 1 > lastYear
        ? `Studied out of service during the window. It comes ${repowerChange({ element_kind: kind, repower: d.repower, factor: d.factor })} from ${d.year + 1}, after the last plan year, so no solved year shows it.`
        : `Studied out of service during the window. From ${d.year + 1} the later years are solved with it ${repowerChange({ element_kind: kind, repower: d.repower, factor: d.factor })}. The connection queue is not re-run for it.`,
  },
  replacement: {
    label: "Replacement",
    tag: () => "REPLACE",
    chip: () => "RPL",
    describe: () => "like-for-like replacement",
    hint: () => "Studied out of service during the window. Back like-for-like after it.",
  },
};
export const WORKS: Work[] = ["maintenance", "repowering", "replacement"];


/** The map tag of a window: "REPOWER · Summer". */
export const outageTag = (o: Outage): string => `${WORK_UI[o.work].tag(o)} · ${o.season}`;
/** The roadmap chip's tag: "OUT", "50%", "RPW" (repowering) or "RPL" (replacement). */
export const outageChipTag = (o: Outage): string => WORK_UI[o.work].chip(o);
/** A window in a row: "Summer 2029 · 4 weeks · full outage". */
export const outageLine = (o: Outage): string => `${o.season} ${o.year} · ${o.weeks} weeks · ${WORK_UI[o.work].describe(o)}`;

export const seasonHint = (season: Season): string =>
  season === "Winter"
    ? "Studied at winter peak with the branch demand profile."
    : season === "Summer"
      ? "Studied at summer minimum, the export-critical case."
      : "Studied in both cases, with the intermediate seasonal ratings.";

/** The form's full hint: the season's case(s), then what the work does. */
export const draftHint = (d: MaintDraft, kind: ElementKind, plan: Plan): string => `${seasonHint(d.season)} ${WORK_UI[d.work].hint(d, kind, lastYear(plan))}`;

// ---- verdicts ----------------------------------------------------------------------------------
interface VerdictUi {
  label: string;
  c: string;
  ink: string;
  tone: Tone | "warn";
  /** The summary phrase for n windows with this verdict ("1 needs curtailment"); null to leave out. */
  count: ((n: number) => string) | null;
}
export const VERDICTS: Record<Verdict, VerdictUi> = {
  unstudied: { label: "Not studied", c: C.mute, ink: C.mute, tone: "neutral", count: (n) => `${n} in a season this grid cannot study` },
  feasible: { label: "Feasible", c: C.phase1, ink: C.greenInk, tone: "good", count: null },
  curtailment: { label: "Curtailment", c: C.amber, ink: C.amberInk, tone: "warn", count: (n) => `${n} need${n === 1 ? "s" : ""} curtailment` },
  demand_at_risk: { label: "Demand at risk", c: C.red, ink: C.redInk, tone: "bad", count: (n) => `${n} put${n === 1 ? "s" : ""} demand at risk` },
  not_feasible: { label: "Not feasible", c: C.red, ink: C.redInk, tone: "bad", count: (n) => `${n} not feasible` },
};

const cap = (s: string): string => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** What the planner knows to name things with. */
export interface NameCtx {
  result: OptimizeResult | null;
  ix: ModelIndex | null;
  outages: Outage[];
  queue: QueueItem[];
}

/** A curtailed generator or project by name: the fleet's applicant, else the project's, else its technology. */
export function curtailedName(c: Pick<Curtailment, "id" | "name">, ix: ModelIndex | null, queue: QueueItem[]): string {
  const fleet = ix?.gen.get(c.id);
  if (fleet) return fleet.applicant ? `${fleet.applicant} (${c.id})` : `${techLabel(fleet.technology)} ${c.id}`;
  const p = queue.find((q) => q.request_id === c.id);
  if (p) return p.applicant ? `${p.applicant} (${c.id})` : `${techLabel(p.technology)} ${c.id}`;
  return `${techLabel(c.name)} ${c.id}`;
}

/** One violation a study reports, in words with the element's name. */
export function violationText(v: OutageStudy["violations"][number], ix: ModelIndex | null): string {
  const id = v.element_id ?? -1;
  const at = cap(caseLabel(v.case));
  if (!ix) return `${at}: ${v.message}`;
  if (v.type === "line") return `${at}: ${lineName(ix, id)} reaches ${Math.round(v.value ?? 0)}%`;
  if (v.type === "trafo") return `${at}: ${trafoName(ix, id)} reaches ${Math.round(v.value ?? 0)}%`;
  if (v.type === "voltage") return `${at}: ${busLabel(ix, id)} at ${(v.value ?? 0).toFixed(3)} pu, outside its band`;
  if (v.type === "gsp") return `${at}: GSP export ${Math.round(v.value ?? 0)} MW, over the ${Math.round(v.limit ?? 0)} MW limit`;
  return `${at}: ${nameElements(v.message, ix)}`;
}

/** The headline sentence of a study, per verdict. */
const HEADLINE: Record<Verdict, (s: OutageStudy, ctx: NameCtx) => string> = {
  unstudied: (s) => s.message || "Not studied: this grid has no study case for the season.",
  feasible: (s) =>
    `Within limits in ${s.cases.map(caseLabel).join(" and ")}. Worst line ${Math.round(s.worst_line_loading_pct)}%, worst transformer ${Math.round(s.worst_trafo_loading_pct)}%.`,
  curtailment: (s, ctx) =>
    `Holds the limits if generation is constrained: ${s.curtailment.map((c) => `${curtailedName(c, ctx.ix, ctx.queue)} by ${fmtMw(c.mw)} MW at ${caseLabel(c.case)}`).join(", ")}.`,
  demand_at_risk: (s) => `${fmtMw(s.demand_at_risk_mw)} MW of demand at risk during the window.`,
  not_feasible: () => "Limits stay breached even with generation constrained.",
};

/** The other windows of a group by name ("Kirton to Boston 33 kV (full outage)"). */
function windowName(id: string, ctx: NameCtx): string {
  const o = ctx.outages.find((x) => x.outage_id === id);
  if (!o) return id;
  const name = ctx.ix ? (elementInfo(outageSel(o), ctx.ix, null, o.year)?.name ?? o.element_id) : o.element_id;
  return `${name} (${WORK_UI[o.work].describe(o)})`;
}

/** Engine text names generators by id ("generator EX-3000"): use the fleet's name. */
const nameGens = (text: string, ix: ModelIndex | null): string =>
  ix ? text.replace(/\bgenerator (EX-[\w-]+)/g, (m, id) => (ix.gen.get(id)?.applicant ? `${ix.gen.get(id)!.applicant} (${id})` : m)) : text;

export interface WindowView {
  state: "unstudied" | "solving" | "studied";
  verdict: Verdict | null;
  /** The chip: label and colour (null until studied). */
  chip: { label: string; c: string } | null;
  /** The detail, one sentence per line. */
  lines: string[];
  /** The colour the detail reads in. */
  c: string;
}

/** A planned window and what its study says, in plain English. */
export function windowView(o: Outage, ctx: NameCtx): WindowView {
  const { state, study } = outageStudyOf(o, ctx.result);
  if (state === "unstudied") return { state, verdict: null, chip: null, lines: ["Not studied yet. Re-run to see the effect."], c: C.mute };
  if (!study) return { state, verdict: null, chip: null, lines: ["Solving this year…"], c: C.mute };
  const v = VERDICTS[study.verdict] ? study.verdict : study.ok ? "feasible" : "not_feasible";
  const lines = [HEADLINE[v](study, ctx)];
  if (v !== "feasible" && study.violations.length) lines.push(`${study.violations.map((x) => violationText(x, ctx.ix)).join(". ")}.`);
  if (study.with_ids?.length)
    lines.push(`Studied together with the other ${o.season.toLowerCase()} ${o.year} work: ${study.with_ids.map((id) => windowName(id, ctx)).join(", ")}.`);
  const n1 = study.n1_during;
  if (n1 && n1.findings > 0) {
    lines.push(`A second fault during the window: ${plural(n1.findings, "finding")}${n1.second_fault_at_risk_mw > 0 ? `, ${fmtMw(n1.second_fault_at_risk_mw)} MW at risk` : ""}.`);
    secondFaultLines(n1, ctx.ix).forEach((l) => lines.push(l));
  } else if (n1 && n1.screened > 0) lines.push(`A second fault during the window: ${plural(n1.screened, "fault")} screened, none breaches a limit.`);
  if (o.work !== "maintenance" && study.after) lines.push(`After the window: ${nameGens(nameElements(study.after, ctx.ix), ctx.ix)}.`);
  return { state, verdict: v, chip: { label: VERDICTS[v].label, c: VERDICTS[v].c }, lines, c: VERDICTS[v].ink };
}

/** How many second-fault findings a window card lists by name; the rest are counted. */
export const SECOND_FAULTS_SHOWN = 3;

/** One second-fault finding of the screen during a window, in words, elements named by place. */
export function secondFaultText(v: N1Violation, ix: ModelIndex | null): string {
  if (v.type === "islanded") return cap(nameElements(v.message, ix)); // the message already names the fault
  const fault = `${v.outage_type === "trafo" ? "Transformer" : "Line"} ${v.outage_id} out as well`;
  return nameElements(`${fault}: ${v.message}`, ix);
}

/** The listed second faults of a window, worst first, then a count of the rest. */
export function secondFaultLines(n1: N1During, ix: ModelIndex | null): string[] {
  const all = n1.violations ?? [];
  const shown = all.slice(0, SECOND_FAULTS_SHOWN).map((v) => `${secondFaultText(v, ix)}.`);
  const rest = all.length - shown.length;
  if (rest > 0) shown.push(`And ${plural(rest, "more second-fault finding")}.`);
  return shown;
}

/** The verdict colour a tag or chip borders in, or null while unstudied. */
export const verdictColor = (v: Verdict | null | undefined): string | null => (v && VERDICTS[v] ? VERDICTS[v].c : null);

// ---- the outages tab -----------------------------------------------------------------------------
/** The windows grouped by year, years ascending, seasons in calendar order within a year. */
const SEASON_ORDER: Record<Season, number> = { Winter: 0, Spring: 1, Summer: 2, Autumn: 3 };
export function windowsByYear(outages: Outage[]): { year: number; rows: Outage[] }[] {
  const years = [...new Set(outages.map((o) => o.year))].sort((a, b) => a - b);
  return years.map((year) => ({
    year,
    rows: outages.filter((o) => o.year === year).sort((a, b) => (SEASON_ORDER[a.season] ?? 0) - (SEASON_ORDER[b.season] ?? 0)),
  }));
}

/** "3 windows · 1 needs curtailment · 1 puts demand at risk · 1 not studied yet". */
export function windowSummary(outages: Outage[], r: OptimizeResult | null): string {
  const counts = new Map<Verdict | "pending", number>(); // pending: not in the shown run yet (a re-run studies it)
  outages.forEach((o) => {
    const { state, study } = outageStudyOf(o, r);
    const k = state === "unstudied" ? "pending" : study?.verdict;
    if (k) counts.set(k, (counts.get(k) ?? 0) + 1);
  });
  const parts = [plural(outages.length, "window")];
  (Object.keys(VERDICTS) as Verdict[]).forEach((v) => {
    const n = counts.get(v);
    const say = VERDICTS[v].count;
    if (n && say) parts.push(say(n));
  });
  const fresh = counts.get("pending");
  if (fresh) parts.push(`${fresh} not studied yet`);
  return parts.join(" · ");
}

// ---- the element card ----------------------------------------------------------------------------
/** Repowerings of an element in years before the viewed one: "Repowered in 2029: back at 1.5x its rating." */
export function repoweredNotes(sel: ElementSel, outages: Outage[], year: number): string[] {
  return outages
    .filter((o) => o.work === "repowering" && o.element_kind === sel.kind && o.element_id === String(sel.id) && o.year < year)
    .sort((a, b) => a.year - b.year)
    .map((o) => `Repowered in ${o.year}: ${repowerChange(o)} from ${o.year + 1}.`);
}
