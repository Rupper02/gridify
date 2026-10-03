// Copilot "Maintenance": plan an outage, a repowering or a replacement, then either find the best
// window (the engine studies every season of every year: windows.best_windows) or schedule a season
// and year the operator names. Pure: a state plus an answer gives the next state, so the whole
// conversation is unit-tested. Free text is parsed by fixed rules (no LLM); every verdict and figure
// shown comes from the engine.

import type { BestWindowRequest, ElementKind, ElementSel, Model, Outage, Repower, Season, Verdict, WindowOption, Work, YearResult } from "../types";
import { lineName, trafoName } from "./derive";
import type { ModelIndex } from "./derive";

export const PLAN_YEARS: [number, number] = [2026, 2035];
export const SEASONS: Season[] = ["Winter", "Spring", "Summer", "Autumn"];
/** How many ranked windows the chat shows (the engine ranks them all). */
export const WINDOWS_SHOWN = 5;

export interface ElementOption {
  kind: ElementKind;
  id: string;
  label: string;
}
export interface MaintCtx {
  /** Where a window is scheduled ("a new branch" on main). */
  branchName: string;
  /** The selected element first, then the worst-loaded in the viewed year. */
  suggestions: ElementOption[];
  /** Resolve a typed element ("line 16", "T30", "EX-3000", "Boston to Spalding") or null. */
  findElement: (text: string) => ElementOption | null;
}
export type MaintStep = "element" | "work" | "kind" | "repower" | "factor" | "weeks" | "when" | "window" | "searching" | "results" | "done";
export interface MaintMsg {
  user: boolean;
  text: string;
  summary?: [string, string][];
  /** Ranked windows from the engine, each with a schedule button. */
  windows?: WindowOption[];
  action?: "schedule" | "run";
  loading?: boolean;
}
export interface MaintChat {
  step: MaintStep;
  element: ElementOption | null;
  work: Work | null;
  kind: "outage" | "derate" | null;
  repower: Repower | null;
  factor: number | null;
  weeks: number | null;
  /** The search range [from, to]; the whole plan unless the operator names one. */
  years: [number, number];
  season: Season | null;
  year: number | null;
  /** Windows scheduled from this chat ("Summer 2029"). */
  scheduled: string[];
  messages: MaintMsg[];
}

const bot = (text: string, extra: Partial<MaintMsg> = {}): MaintMsg => ({ user: false, text, ...extra });
const NOUN: Record<ElementKind, string> = { line: "line", trafo: "transformer", gen: "generator" };
const WORK_LABEL: Record<Work, string> = { maintenance: "Maintenance", repowering: "Repowering", replacement: "Like-for-like replacement" };

// ---- elements -------------------------------------------------------------------------------------
const genLabel = (g: Model["generators"][number]): string => `${g.applicant || g.request_id} (${g.request_id}, ${g.technology})`;
function optionFor(ix: ModelIndex, kind: ElementKind, id: string): ElementOption | null {
  if (kind === "line" && ix.line.has(+id)) return { kind, id: String(+id), label: `${lineName(ix, +id)} (line ${+id})` };
  if (kind === "trafo" && ix.trafo.has(+id)) return { kind, id: String(+id), label: `${trafoName(ix, +id)} (T${+id})` };
  if (kind === "gen" && ix.gen.has(id)) return { kind, id, label: genLabel(ix.gen.get(id)!) };
  return null;
}

/** The element picked on the map (if any), then the most loaded lines and transformers in the year. */
export function elementSuggestions(ix: ModelIndex, yr: YearResult | null, sel: ElementSel | null, n = 3): ElementOption[] {
  const out: ElementOption[] = [];
  const picked = sel ? optionFor(ix, sel.kind, String(sel.id)) : null;
  if (picked) out.push({ ...picked, label: `${picked.label} (selected)` });
  const loaded: [ElementKind, string, number][] = [
    ...Object.entries(yr?.line_loading ?? {}).map(([id, v]) => ["line", id, v] as [ElementKind, string, number]),
    ...Object.entries(yr?.trafo_loading ?? {}).map(([id, v]) => ["trafo", id, v] as [ElementKind, string, number]),
  ].sort((a, b) => b[2] - a[2] || a[0].localeCompare(b[0]) || +a[1] - +b[1]);
  for (const [kind, id, pct] of loaded) {
    if (out.length >= n + (picked ? 1 : 0)) break;
    if (picked && picked.kind === kind && picked.id === id) continue;
    const o = optionFor(ix, kind, id);
    if (o) out.push({ ...o, label: `${o.label} · ${Math.round(pct)}%` });
  }
  return out;
}

/** A typed element to a line, transformer or existing generator; numbers first, then names. */
export function findElement(m: Model, ix: ModelIndex, text: string): ElementOption | null {
  const t = text.trim();
  const gen = t.match(/\bEX-[\w-]+/i);
  if (gen) {
    const id = [...ix.gen.keys()].find((k) => k.toLowerCase() === gen[0].toLowerCase());
    if (id) return optionFor(ix, "gen", id);
  }
  const tr = t.match(/\b(?:trafo|transformer)\s*#?\s*(\d+)\b|\bT(\d+)\b/i);
  if (tr) return optionFor(ix, "trafo", tr[1] ?? tr[2]);
  const ln = t.match(/\b(?:line|circuit)\s*#?\s*(\d+)\b|\bL(\d+)\b/i);
  if (ln) return optionFor(ix, "line", ln[1] ?? ln[2]);
  if (/^\d+$/.test(t)) return optionFor(ix, "line", t) ?? optionFor(ix, "trafo", t);
  const q = t.toLowerCase().replace(/\s*\((selected)\)|\s*·\s*\d+%$/g, "").trim();
  if (!q) return null;
  const line = m.lines.filter((l) => lineName(ix, l.line_id).toLowerCase().includes(q)).sort((a, b) => b.voltage_kv - a.voltage_kv || a.line_id - b.line_id)[0];
  if (line) return optionFor(ix, "line", String(line.line_id));
  const trafo = m.transformers.find((x) => trafoName(ix, x.trafo_id).toLowerCase().includes(q));
  if (trafo) return optionFor(ix, "trafo", String(trafo.trafo_id));
  const g = (m.generators ?? []).find((x) => (x.applicant || "").toLowerCase().includes(q));
  return g ? optionFor(ix, "gen", g.request_id) : null;
}

// ---- parsing --------------------------------------------------------------------------------------
export function workFromText(v: string): Work | null {
  const s = v.toLowerCase();
  if (/repow|uprat|upgrad/.test(s)) return "repowering";
  if (/replac|renew|swap/.test(s)) return "replacement";
  if (/maint|inspect|servic|repair|outage|overhaul/.test(s)) return "maintenance";
  return null;
}
export function kindFromText(v: string): "outage" | "derate" | null {
  const s = v.toLowerCase();
  if (/derat|half|50\s*%|partial|reduc/.test(s)) return "derate";
  if (/\bout\b|full|isolat|energi/.test(s)) return "outage";
  return null;
}
export function repowerFromText(v: string): Repower | null {
  const s = v.toLowerCase();
  if (/parallel|second|another|extra|add/.test(s)) return "add_parallel";
  if (/uprat|rating|factor|\d\s*x\b|\bx\s*\d|%/.test(s)) return "uprate";
  return null;
}
/** A rating multiplier: "1.5", "1.5x", "x2", "+50%" (1 < factor <= 4), else null. */
export function factorFromText(v: string): number | null {
  const pct = v.match(/\+?\s*(\d+(?:\.\d+)?)\s*%/);
  const n = pct ? 1 + parseFloat(pct[1]) / 100 : parseFloat(v.match(/\d+(?:\.\d+)?/)?.[0] ?? "");
  return n > 1 && n <= 4 ? Math.round(n * 100) / 100 : null;
}
/** Weeks out: "6", "6 weeks", "2 months" (4 weeks each); 1..26, else null. */
export function weeksFromText(v: string): number | null {
  const n = parseFloat(v.match(/\d+(?:\.\d+)?/)?.[0] ?? (/\ba month\b/i.test(v) ? "1" : ""));
  const w = Math.round(/month/i.test(v) ? n * 4 : n);
  return w >= 1 && w <= 26 ? w : null;
}
/** "Summer 2029", "autumn of 2031" (fall = autumn). */
export function windowFromText(v: string): { season: Season | null; year: number | null } {
  const s = v.toLowerCase().replace(/\bfall\b/, "autumn");
  const season = SEASONS.find((x) => s.includes(x.toLowerCase())) ?? null;
  const y = v.match(/\b(20\d\d)\b/);
  const year = y && +y[1] >= PLAN_YEARS[0] && +y[1] <= PLAN_YEARS[1] ? +y[1] : null;
  return { season, year };
}
/** A search range named in the text ("between 2028 and 2031", "2028-2031", "from 2029"), else the plan. */
export function rangeFromText(v: string): [number, number] {
  const ys = [...v.matchAll(/\b(20\d\d)\b/g)].map((x) => +x[1]).filter((y) => y >= PLAN_YEARS[0] && y <= PLAN_YEARS[1]);
  if (ys.length >= 2) return [Math.min(ys[0], ys[1]), Math.max(ys[0], ys[1])];
  if (ys.length === 1) return /\b(before|by|until|to)\b/i.test(v) ? [PLAN_YEARS[0], ys[0]] : [ys[0], PLAN_YEARS[1]];
  return [...PLAN_YEARS];
}

// ---- the conversation -----------------------------------------------------------------------------
/** The steps this work needs (derate is for maintenance; a factor only for an uprate). */
function needs(st: MaintChat): MaintStep[] {
  const steps: MaintStep[] = ["element", "work"];
  if (st.work === "maintenance") steps.push("kind");
  if (st.work === "repowering") steps.push("repower");
  if (st.work === "repowering" && st.repower === "uprate") steps.push("factor");
  return [...steps, "weeks", "when"];
}
const filled = (st: MaintChat, k: MaintStep): boolean =>
  ({ element: st.element, work: st.work, kind: st.kind, repower: st.repower, factor: st.factor, weeks: st.weeks } as Record<string, unknown>)[k] != null;

export function maintQuestion(st: MaintChat, ctx: MaintCtx): { text: string; opts: string[] } {
  const noun = st.element ? NOUN[st.element.kind] : "element";
  switch (st.step) {
    case "element":
      return {
        text: ctx.suggestions.length
          ? "Which element? Type a line, transformer or generator by name or number, or pick one. These are the most loaded in the viewed year:"
          : "Which element? Type a line, transformer or generator by name or number (for example line 16, T30 or EX-3000).",
        opts: ctx.suggestions.map((o) => o.label),
      };
    case "work":
      return { text: `What is the work on the ${noun}?`, opts: Object.values(WORK_LABEL) };
    case "kind":
      return { text: `Is the ${noun} fully out for the work, or derated to half its rating?`, opts: ["Fully out", "Derated to 50%"] };
    case "repower":
      return { text: `How does the ${noun} come back after the window?`, opts: ["Uprated", st.element?.kind === "gen" ? "With a parallel unit" : "With a parallel circuit"] };
    case "factor":
      return { text: `By what factor is its ${st.element?.kind === "gen" ? "export rating" : "rating"} uprated? Between 1 and 4.`, opts: ["1.25x", "1.5x", "2x"] };
    case "weeks":
      return { text: "How many weeks is it out?", opts: ["2 weeks", "4 weeks", "8 weeks"] };
    case "when":
      return { text: "Shall I find the best window across the plan, or do you have a season and year in mind?", opts: ["Find the best window", "A specific season and year"] };
    case "window":
      return { text: "Which season and year? For example Summer 2029.", opts: ["Spring 2028", "Summer 2029", "Autumn 2030"] };
    default:
      return { text: "", opts: [] };
  }
}

export function startMaint(ctx: MaintCtx): MaintChat {
  const st: MaintChat = {
    step: "element", element: null, work: null, kind: null, repower: null, factor: null, weeks: null,
    years: [...PLAN_YEARS], season: null, year: null, scheduled: [], messages: [],
  };
  return { ...st, messages: [bot(`Plan an outage, a repowering or a replacement, scheduled on ${ctx.branchName}. ${maintQuestion(st, ctx).text}`)] };
}

/** Apply one answer: validate it, fill the slot, ask the next question, start the search or finish. */
export function maintAnswer(st: MaintChat, raw: string, ctx: MaintCtx): MaintChat {
  const v = String(raw ?? "").trim();
  if (!v || st.step === "searching") return st;
  const msgs = [...st.messages, { user: true, text: v }];
  const reask = (text: string): MaintChat => ({ ...st, messages: [...msgs, bot(text)] });
  const next: MaintChat = { ...st, messages: msgs };
  switch (st.step) {
    case "element": {
      const e = ctx.suggestions.find((o) => o.label === v) ?? ctx.findElement(v);
      if (!e) return reask("I couldn't find that in the network model. Give a line or transformer number (line 16, T30), a generator id (EX-3000), a place name, or pick a suggestion.");
      next.element = { ...e, label: e.label.replace(/\s*\(selected\)$|\s*·\s*\d+%$/g, "") };
      break;
    }
    case "work": {
      const w = workFromText(v);
      if (!w) return reask("Is it maintenance, a repowering or a like-for-like replacement?");
      next.work = w;
      if (w !== "maintenance") next.kind = "outage";
      if (w === "repowering") {
        next.repower = repowerFromText(v);
        next.factor = next.repower === "uprate" ? factorFromText(v) : null;
      }
      break;
    }
    case "kind": {
      const k = kindFromText(v);
      if (!k) return reask("Fully out, or derated to 50%?");
      next.kind = k;
      break;
    }
    case "repower": {
      const r = repowerFromText(v);
      if (!r) return reask("Uprated, or with a parallel circuit?");
      next.repower = r;
      if (r === "uprate") next.factor = factorFromText(v);
      break;
    }
    case "factor": {
      const f = factorFromText(v);
      if (f == null) return reask("I need a factor above 1 and up to 4, for example 1.5.");
      next.factor = f;
      break;
    }
    case "weeks": {
      const w = weeksFromText(v);
      if (w == null) return reask("I need a number of weeks between 1 and 26.");
      next.weeks = w;
      break;
    }
    case "when":
    case "results":
    case "done": {
      const win = windowFromText(v);
      if (win.season && win.year) return finish(next, win.season, win.year, ctx);
      if (/best|find|optimal|recommend|any|when|search|again/i.test(v)) return search(next, rangeFromText(v));
      if (/specific|season|year|mind|choose|pick|own/i.test(v)) return { ...next, step: "window", messages: [...msgs, bot(maintQuestion({ ...next, step: "window" }, ctx).text)] };
      return reask(st.step === "when" ? "Say \"find the best window\", or give a season and year such as Summer 2029." : "Give a season and year to schedule, or ask me to find the best window again.");
    }
    case "window": {
      const win = windowFromText(v);
      if (!win.season || !win.year) return reask(`I need a season and a year between ${PLAN_YEARS[0]} and ${PLAN_YEARS[1]}, for example Summer 2029.`);
      return finish(next, win.season, win.year, ctx);
    }
  }
  const steps = needs(next);
  const after = steps.slice(steps.indexOf(st.step) + 1).find((k) => k === "when" || !filled(next, k));
  next.step = after ?? "when";
  next.messages = [...msgs, bot(maintQuestion(next, ctx).text)];
  return next;
}

function search(st: MaintChat, years: [number, number]): MaintChat {
  const span = years[0] === years[1] ? `${years[0]}` : `${years[0]} to ${years[1]}`;
  return {
    ...st, step: "searching", years,
    messages: [...st.messages, bot(`Studying ${describe(st)} in every season of ${span}, each against the plan as it stands that year…`, { loading: true })],
  };
}

function finish(st: MaintChat, season: Season, year: number, ctx: MaintCtx): MaintChat {
  const next = { ...st, season, year, step: "done" as const };
  return {
    ...next,
    messages: [...st.messages, bot(`Here is the window. I'll schedule it on ${ctx.branchName}; the next run studies it with the plan for ${year}.`, { summary: summaryOf(next), action: "schedule" })],
  };
}

/** The search has started: the loading message follows the job's stage. */
export function searchProgress(st: MaintChat, stage: string, fraction: number): MaintChat {
  const i = st.messages.length - 1;
  if (i < 0 || !st.messages[i].loading) return st;
  const base = st.messages[i].text.split(" · ")[0];
  return { ...st, messages: [...st.messages.slice(0, i), { ...st.messages[i], text: `${base} · ${stage} (${Math.round(fraction * 100)}%)` }] };
}

/** The engine's ranking is in: show the best windows with what each costs. */
export function withWindows(st: MaintChat, options: WindowOption[], ctx: MaintCtx): MaintChat {
  const msgs = st.messages.filter((m) => !m.loading);
  if (!options.length) return { ...st, step: "when", messages: [...msgs, bot("The engine returned no windows for that range. Try a wider range, or give a season and year.")] };
  const best = options[0];
  const clean = options.filter((o) => o.verdict === "feasible").length;
  const head = clean
    ? `${clean} of ${options.length} windows keep every limit with the ${NOUN[st.element!.kind]} out. The best is ${best.season} ${best.year}.`
    : `No window keeps every limit with it out. The least costly is ${best.season} ${best.year}: ${windowLine(best)}`;
  return {
    ...st, step: "results",
    messages: [...msgs, bot(`${head} Ranked by verdict, then curtailment, demand at risk, second-fault findings and loading. Schedule one on ${ctx.branchName}, or give another season and year.`, { windows: options.slice(0, WINDOWS_SHOWN) })],
  };
}

export function searchFailed(st: MaintChat, why: string): MaintChat {
  return { ...st, step: "when", messages: [...st.messages.filter((m) => !m.loading), bot(`The engine could not study the windows: ${why}. Try again, or give a season and year.`)] };
}

/** A window was scheduled on the branch: offer the run that studies it. */
export function scheduledOn(st: MaintChat, season: Season, year: number, branchName: string, profileLabel: string): MaintChat {
  const key = `${season} ${year}`;
  return {
    ...st, step: st.step === "done" ? "done" : st.step,
    scheduled: [...st.scheduled.filter((k) => k !== key), key],
    messages: [
      ...st.messages.map((m) => ({ ...m, action: m.action === "schedule" ? undefined : m.action })),
      { user: true, text: `Schedule ${key}` },
      bot(`Scheduled ${describe(st)} for ${key} on ${branchName}. The plan is studying it now on ${profileLabel} demand; its verdict appears in Outages.`),
    ],
  };
}

// ---- what the engine is asked, and how its answer is said ----------------------------------------
const workFields = (st: MaintChat) => ({
  element_kind: st.element!.kind, element_id: st.element!.id, work: st.work ?? "maintenance",
  kind: st.work === "maintenance" ? (st.kind ?? "outage") : "outage",
  repower: st.work === "repowering" ? st.repower : null,
  factor: st.work === "repowering" && st.repower === "uprate" ? st.factor : null,
  weeks: st.weeks ?? 4,
});
export const searchRequest = (st: MaintChat): BestWindowRequest => ({ ...workFields(st), years: st.years });
export const outageBody = (st: MaintChat, season: Season, year: number): Omit<Outage, "outage_id" | "created_at"> => ({ ...workFields(st), season, year });

export function describe(st: MaintChat): string {
  const what = st.element ? st.element.label : "the element";
  if (st.work === "repowering")
    return `repowering ${what} (${st.repower === "add_parallel" ? (st.element?.kind === "gen" ? "a parallel unit" : "a parallel circuit") : `${st.factor ?? "?"}x`})`;
  if (st.work === "replacement") return `replacing ${what}`;
  return `${what} ${st.kind === "derate" ? "derated to 50%" : "out"} for maintenance`;
}

export function summaryOf(st: MaintChat): [string, string][] {
  return [
    ["Element", st.element?.label ?? "–"],
    ["Work", st.work ? WORK_LABEL[st.work] : "–"],
    ...(st.work === "maintenance" ? [["Condition", st.kind === "derate" ? "Derated to 50%" : "Fully out"] as [string, string]] : []),
    ...(st.work === "repowering" ? [["Comes back", st.repower === "add_parallel" ? "With a parallel circuit" : `Uprated ${st.factor}x`] as [string, string]] : []),
    ["Duration", `${st.weeks ?? 4} weeks`],
    ["Window", st.season && st.year ? `${st.season} ${st.year}` : "–"],
  ];
}

export const VERDICT: Record<Verdict, { label: string; tone: "ok" | "warn" | "bad" }> = {
  feasible: { label: "Feasible", tone: "ok" },
  curtailment: { label: "With curtailment", tone: "warn" },
  demand_at_risk: { label: "Demand at risk", tone: "bad" },
  not_feasible: { label: "Not feasible", tone: "bad" },
};

/** One window in plain English, from the engine's figures only. */
export function windowLine(o: WindowOption): string {
  const parts: string[] = [];
  if (o.verdict === "feasible") parts.push(`every limit holds, worst line ${Math.round(o.worst_line_loading_pct)}%`);
  if (o.verdict === "curtailment") parts.push(`about ${o.curtailed_mw.toFixed(1)} MW of generation constrained to hold the limits`);
  if (o.verdict === "demand_at_risk") parts.push(`${o.demand_at_risk_mw.toFixed(1)} MW of demand at risk`);
  if (o.verdict === "not_feasible") parts.push("a limit stays breached even with nearby generation constrained");
  if (o.n1_findings) parts.push(`${o.n1_findings} second-fault finding${o.n1_findings === 1 ? "" : "s"} during the window`);
  const s = parts.join("; ");
  return `${s[0].toUpperCase()}${s.slice(1)}.`;
}

/** The slots shown above the chat ("asking…" on the current one). */
export function maintSlots(st: MaintChat): { key: string; label: string; value: string; current: boolean }[] {
  const cur = (k: MaintStep[]) => k.includes(st.step);
  const val = (v: string | null, k: MaintStep[]) => v ?? (cur(k) ? "asking…" : "–");
  return [
    { key: "element", label: "Element", value: val(st.element?.label ?? null, ["element"]), current: cur(["element"]) },
    { key: "work", label: "Work", value: val(st.work ? WORK_LABEL[st.work] : null, ["work", "kind", "repower", "factor"]), current: cur(["work", "kind", "repower", "factor"]) },
    { key: "weeks", label: "Duration", value: val(st.weeks != null ? `${st.weeks} weeks` : null, ["weeks"]), current: cur(["weeks"]) },
    { key: "window", label: "Window", value: val(st.season && st.year ? `${st.season} ${st.year}` : st.step === "searching" ? "searching…" : null, ["when", "window"]), current: cur(["when", "window", "searching"]) },
  ];
}
