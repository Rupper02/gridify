// Copilot "New project": a guided intake that collects what the engine needs, one question at a
// time, then adds the application to the branch's preliminary queue. Pure: a state plus an answer
// gives the next state, so the whole conversation is unit-tested. No LLM: the questions and the
// checks are fixed; the engine does the ranking and the power flow afterwards.

import { EVID, READINESS_FLOOR, TECH, techLabel } from "../theme";
import type { Tech } from "../types";

export type SlotKey = "tech" | "mw" | "load" | "bus" | "year" | "ready" | "name";
export interface ChatMsg {
  user: boolean;
  text: string;
  /** Bot extras: the finished application, or an action button. */
  summary?: [string, string][];
  action?: "add" | "run";
}
export interface BusOption {
  id: number;
  label: string;
}
export interface IntakeCtx {
  maxMw: number;
  branchName: string;
  profileLabel: string;
  busOptions: BusOption[];
  /** Resolve a typed bus ("1102", "Boston") to a bus id, or null. */
  findBus: (text: string) => BusOption | null;
}
export interface Intake {
  step: SlotKey | "done";
  tech: Tech | null;
  mw: number | null;
  load: number | null;
  bus: BusOption | null;
  year: number | null;
  ready: string[] | null;
  name: string | null;
  readySel: string[];
  messages: ChatMsg[];
}

const ORDER: SlotKey[] = ["tech", "mw", "load", "bus", "year", "ready", "name"];
const TECH_OPTIONS: Tech[] = ["solar", "wind", "battery", "hybrid", "gas", "gas_engine", "biomass", "electrolyser", "demand"];
const bot = (text: string, extra: Partial<ChatMsg> = {}): ChatMsg => ({ user: false, text, ...extra });

/** Free text to a technology id ("Solar + battery", "a data centre", "CCGT"). */
export function techFromText(v: string): Tech | null {
  const s = v.toLowerCase();
  if (s.includes("solar + battery") || s.includes("hybrid") || (s.includes("solar") && s.includes("batter"))) return "hybrid";
  if (s.includes("solar") || s.includes("pv")) return "solar";
  if (s.includes("wind")) return "wind";
  if (s.includes("batter") || s.includes("storage") || s.includes("bess")) return "battery";
  if (s.includes("engine")) return "gas_engine";
  if (s.includes("gas") || s.includes("ccgt") || s.includes("ocgt")) return "gas";
  if (s.includes("biomass") || s.includes("efw") || s.includes("waste")) return "biomass";
  if (s.includes("hydrogen") || s.includes("electrolys")) return "electrolyser";
  if (s.includes("demand") || s.includes("data") || s.includes(" ev") || s.startsWith("ev")) return "demand";
  return null;
}

export function readinessScore(sel: readonly string[]): number {
  return Math.round((READINESS_FLOOR + EVID.filter((e) => sel.includes(e.label)).reduce((a, e) => a + e.w, 0)) * 100) / 100;
}

/** The steps this application still needs, given what is known (import-only projects skip export). */
function needs(st: Intake): SlotKey[] {
  const t = st.tech ? TECH[st.tech] : null;
  return ORDER.filter((k) => {
    if (k === "mw") return !t?.importOnly;
    if (k === "load") return !t || t.imports;
    return true;
  });
}

export function question(st: Intake, ctx: IntakeCtx): { text: string; opts: string[]; multi?: string[] } {
  switch (st.step) {
    case "tech":
      return { text: "Which technology?", opts: TECH_OPTIONS.map((t) => TECH[t].label) };
    case "mw":
      return { text: `Export capacity in MW? The intake cap is ${ctx.maxMw} MW.`, opts: ["20", "49.9", "100"] };
    case "load":
      if (st.tech && TECH[st.tech].importOnly)
        return { text: `${techLabel(st.tech)} is studied as demand: it draws its import at winter peak, grown by the branch demand profile, and half of it at summer minimum. What is the peak import in MW?`, opts: ["10", "20", "60"] };
      return { text: "It charges at winter peak, so the engine studies its import too. How many MW does it draw from the grid?", opts: [`Same as export (${st.mw ?? 0})`, "Half of export", String(Math.round((st.mw ?? 0) / 4) || 5)] };
    case "bus":
      return {
        text: ctx.busOptions.length
          ? "Where does it connect? These buses have the most headroom on their circuits in the last run on this branch:"
          : "Where does it connect? Give a bus number or a substation name.",
        opts: ctx.busOptions.map((b) => b.label),
      };
    case "year":
      return { text: "Requested energisation year? Phase 1 hosts 2027 to 2030, Phase 2 hosts 2031 to 2035.", opts: ["2028", "2029", "2030", "2032"] };
    case "ready":
      return { text: "What evidence is in place? Pick all that apply, then Done. This sets the readiness score used for ranking.", opts: [], multi: EVID.map((e) => e.label) };
    case "name":
      return { text: "Last one: what is the project called?", opts: st.bus ? [`${st.bus.label.split("·")[1]?.trim().replace(/\s\d+(\.\d+)?\skV$/, "") || "New"} ${techLabel(st.tech)}`] : [] };
    default:
      return { text: "", opts: [] };
  }
}

export function startIntake(ctx: IntakeCtx): Intake {
  return {
    step: "tech", tech: null, mw: null, load: null, bus: null, year: null, ready: null, name: null, readySel: [],
    messages: [bot(`New project for the preliminary queue on ${ctx.branchName}. I'll ask for what the engine needs, one thing at a time. Which technology?`)],
  };
}

const NOTE: Partial<Record<Tech, string>> = {
  gas: "Gas is treated as firm in both study cases, so it exports at winter peak as well as summer minimum.",
  gas_engine: "Gas engines are treated as firm in both study cases.",
  biomass: "Biomass and EfW are treated as firm in both study cases.",
  hybrid: "Solar is at nil at winter peak and the battery charges then, so both cases matter.",
  battery: "Batteries charge at their import capacity at winter peak.",
};

/** Apply one answer: validate it, fill the slot, ask the next question (or finish). */
export function answer(st: Intake, raw: string, ctx: IntakeCtx): Intake {
  const v = String(raw ?? "").trim();
  if (!v || st.step === "done") return st;
  const msgs = [...st.messages, { user: true, text: v }];
  const reask = (text: string): Intake => ({ ...st, messages: [...msgs, bot(text)] });
  const next = { ...st, messages: msgs, readySel: [] as string[] };
  let lead = "";
  switch (st.step) {
    case "tech": {
      const t = techFromText(v);
      if (!t) return reask("I didn't recognise that technology. Pick one of the options.");
      next.tech = t;
      if (TECH[t].importOnly) next.mw = 0;
      lead = NOTE[t] ? `${NOTE[t]} ` : "";
      break;
    }
    case "mw": {
      const n = parseFloat(v);
      if (!(n > 0)) return reask("I need a number in MW, for example 49.9.");
      if (n > ctx.maxMw) return reask(`${n} MW is above the ${ctx.maxMw} MW intake cap, so it would be rejected at intake. Can you give a lower export figure?`);
      next.mw = n;
      break;
    }
    case "load": {
      const s = v.toLowerCase();
      const n = s.startsWith("same") ? (st.mw ?? 0) : s.startsWith("half") ? (st.mw ?? 0) / 2 : parseFloat(v.match(/[\d.]+/)?.[0] ?? "");
      const importOnly = !!st.tech && TECH[st.tech].importOnly;
      if (!(n >= 0) || Number.isNaN(n) || (importOnly && !(n > 0))) return reask("I need the import in MW, for example 20.");
      if (n > ctx.maxMw) return reask(`${n} MW is above the ${ctx.maxMw} MW intake cap. Can you give a lower figure?`);
      next.load = Math.round(n * 10) / 10;
      break;
    }
    case "bus": {
      const b = ctx.findBus(v);
      if (!b) return reask("I couldn't find that bus in the network model. Give a bus number, a substation name, or pick a suggestion.");
      next.bus = b;
      break;
    }
    case "year": {
      const y = parseInt(v, 10);
      if (!(y >= 2026 && y <= 2035)) return reask("Pick a year between 2026 and 2035.");
      next.year = y;
      break;
    }
    case "ready":
      next.ready = EVID.map((e) => e.label).filter((l) => v.includes(l));
      break;
    case "name":
      next.name = v;
      break;
  }
  const steps = needs(next);
  const i = steps.indexOf(st.step as SlotKey);
  const after = steps.slice(i + 1).find((k) => !filled(next, k));
  if (after) {
    next.step = after;
    next.messages = [...msgs, bot(lead + question(next, ctx).text)];
    return next;
  }
  next.step = "done";
  next.messages = [
    ...msgs,
    bot(`Here is the application. I'll add it to the preliminary queue on ${ctx.branchName}. It stays unranked until the next run.`, { summary: summaryOf(next, ctx), action: "add" }),
  ];
  return next;
}

const filled = (st: Intake, k: SlotKey): boolean => {
  const val = { tech: st.tech, mw: st.mw, load: st.load, bus: st.bus, year: st.year, ready: st.ready, name: st.name }[k];
  return val != null;
};

/** Done on the readiness step: the ticked evidence as an answer. */
export const readinessAnswer = (sel: string[]): string =>
  `${sel.length ? sel.join(", ") : "None yet"} · ${Math.round(readinessScore(sel) * 100)}%`;

export function summaryOf(st: Intake, ctx: IntakeCtx): [string, string][] {
  return [
    ["Name", st.name ?? "–"],
    ["Technology", techLabel(st.tech)],
    ["Export", `${st.mw ?? 0} MW`],
    ["Import", `${st.load ?? 0} MW`],
    ["Connection", st.bus?.label ?? "–"],
    ["Requested year", String(st.year ?? "–")],
    ["Readiness", `${Math.round(readinessScore(st.ready ?? []) * 100)}%`],
    ["Tested on", `${ctx.profileLabel} demand`],
  ];
}

/** The draft-application slots, for the grid above the chat ("asking…" on the current one). */
export function draftSlots(st: Intake): { key: SlotKey; label: string; value: string; current: boolean }[] {
  const val: Record<SlotKey, string | null> = {
    tech: st.tech ? techLabel(st.tech) : null,
    mw: st.mw != null ? `${st.mw} MW` : null,
    load: st.load != null ? `${st.load} MW` : null,
    bus: st.bus ? st.bus.label.split("·")[0].trim() : null,
    year: st.year != null ? String(st.year) : null,
    ready: st.ready ? `${Math.round(readinessScore(st.ready) * 100)}%` : null,
    name: st.name,
  };
  const labels: [SlotKey, string][] = [["tech", "Technology"], ["mw", "Export"], ["load", "Import (load)"], ["bus", "Connection"], ["year", "Energise"], ["ready", "Readiness"]];
  return labels.map(([key, label]) => ({ key, label, value: val[key] ?? (st.step === key ? "asking…" : "–"), current: st.step === key }));
}
