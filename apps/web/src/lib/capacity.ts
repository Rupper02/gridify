// How strong the grid is, as the Capacity tab and the map's Headroom layer read it: when each element of the binding set
// needs reinforcement (the engine's limits), and the room to connect at each substation today (the engine's
// hosting-capacity study: generation at summer minimum and demand at winter peak, the two headroom studies a DNO
// publishes per substation). Pure: every figure is the engine's.

import { C, fmtMw } from "../theme";
import type { ElementBinding, Limits, Model, StudyItem, StudyResult, YearResult } from "../types";
import { trafoSub } from "./derive";
import type { LineTiers } from "./mapFeatures";

// ---- when an element needs reinforcement ------------------------------------------------------------
/** In the viewed year: over its limit by now, over it later in the plan, near it, or holding with margin. */
export type Need = "now" | "later" | "near" | "holds";

export const NEED: Record<Need, { c: string; label: string }> = {
  now: { c: C.red, label: "Over its limit by this year" },
  later: { c: C.amber, label: "Over its limit later in the plan" },
  near: { c: "#e6d7a8", label: "Near its limit" },
  holds: { c: C.phase1, label: "Holds through the plan" },
};

export const bindingKey = (kind: string, id: number): string => `${kind}:${id}`;

/** The binding set by element ("line:12", "trafo:3", "bus:19"). */
export const bindingIndex = (l: Limits | null): Map<string, ElementBinding> =>
  new Map((l?.binding ?? []).map((b) => [bindingKey(b.kind, b.element_id), b]));

/** An element's need in `year`; one the binding set leaves out holds with margin in every plan year. A binding element
 * that only an N-1 outage breaches holds intact (its outages are in the tab). */
export function needOf(b: ElementBinding | undefined, year: number): Need {
  if (!b) return "holds";
  if (b.first_breach_year != null) return b.first_breach_year <= year ? "now" : "later";
  return b.first_near_year != null ? "near" : "holds";
}

/** The year a map tag names: when it breaches, else when it comes near; null when it holds. */
export const needYear = (b: ElementBinding | undefined): number | null => b?.first_breach_year ?? b?.first_near_year ?? null;

export interface NeedYear {
  year: number;
  breach: ElementBinding[];
  near: ElementBinding[];
}

/** The binding set by the year each element first breaches (or, never breaching, first comes near), earliest first; the
 * engine's order (worst first) within a year. */
export function needTimeline(l: Limits): NeedYear[] {
  const by = new Map<number, NeedYear>();
  const at = (year: number): NeedYear => {
    const y = by.get(year) ?? { year, breach: [], near: [] };
    by.set(year, y);
    return y;
  };
  l.binding.forEach((b) => {
    if (b.first_breach_year != null) at(b.first_breach_year).breach.push(b);
    else if (b.first_near_year != null) at(b.first_near_year).near.push(b);
  });
  return [...by.values()].sort((a, b) => a.year - b.year);
}

/** The kind of works that relieves it, by what binds (the engine sizes none: its first-order margin is beside it). */
export function leverText(b: ElementBinding): string {
  if (b.kind === "line") return "a higher-rated or a second circuit";
  if (b.kind === "trafo") return "a larger or an additional transformer";
  return b.worst.value < 1 ? "voltage support, or a stronger feed to the busbar" : "reactive absorption, or a stronger feed to the busbar";
}

/** "≈3.4 MW over in 2035" / "≈6.8 MW room in 2035": the engine's first-order margin at the worst year ("" for a busbar). */
export function marginText(b: ElementBinding): string {
  if (b.headroom_mw == null) return "";
  return b.headroom_mw < 0 ? `≈${fmtMw(-b.headroom_mw)} MW over in ${b.worst.year}` : `≈${fmtMw(b.headroom_mw)} MW room in ${b.worst.year}`;
}

/** How many circuits and transformers stay clear of their limits in every plan year (the binding set leaves them out). */
export function holdCounts(m: Model, l: Limits): { lines: number; linesHold: number; trafos: number; trafosHold: number } {
  const tight = (kind: string) => new Set(l.binding.filter((b) => b.kind === kind && b.severity !== "ok").map((b) => b.element_id));
  const tl = tight("line");
  const tt = tight("trafo");
  const lines = m.lines.filter((x) => x.in_service !== false);
  return {
    lines: lines.length,
    linesHold: lines.filter((x) => !tl.has(x.line_id)).length,
    trafos: m.transformers.length,
    trafosHold: m.transformers.filter((t) => !tt.has(t.trafo_id)).length,
  };
}

/** The first plan year the GSP exports over its limit, with that year's figures; null when it never does. */
export function gspOver(years: Record<string, YearResult> | undefined): { year: number; export_mw: number; limit_mw: number; case: string | null } | null {
  const ys = Object.values(years ?? {}).sort((a, b) => a.year - b.year);
  const y = ys.find((x) => x.gsp_limit_mw != null && x.gsp_export_mw > x.gsp_limit_mw);
  return y ? { year: y.year, export_mw: y.gsp_export_mw, limit_mw: y.gsp_limit_mw!, case: y.gsp_case ?? null } : null;
}

// ---- the room to connect today ----------------------------------------------------------------------
export type Direction = "export" | "import";

/** The case each direction is measured in: generation at minimum demand, demand at peak (README, study cases). */
export const HOSTING_CASE: Record<Direction, string> = { export: "summer_min", import: "winter_peak" };

/** The busbars the room is measured at: every transformer terminal at the grid's two highest voltage levels, where a
 * connection would go. */
export function hostingBuses(m: Model, tiers: LineTiers): number[] {
  const floor = tiers.mid ?? tiers.high;
  if (floor == null) return [];
  const kv = new Map(m.buses.map((b) => [b.bus_id, b.vn_kv]));
  const ids = new Set<number>();
  m.transformers.forEach((t) => [t.hv_bus, t.lv_bus].forEach((b) => (kv.get(b) ?? 0) >= floor && ids.add(b)));
  return [...ids].sort((a, b) => a - b);
}

export const hostingParams = (buses: number[], d: Direction) => ({ bus_ids: buses, direction: d, cases: [HOSTING_CASE[d]] });

/** What the room is read for: the branch and its reinforcements (the study reads neither its projects nor its demand). */
export const hostingKey = (branch: string, reinforcementIds: string[]): string => `${branch}|${[...reinforcementIds].sort().join(",")}`;

export interface HostingState {
  key: string;
  status: "idle" | "reading" | "absent" | "measuring" | "ready" | "failed";
  export: StudyResult | null;
  import: StudyResult | null;
  stage: string;
  fraction: number;
  error: string | null;
}
export const HOSTING_IDLE: HostingState = { key: "", status: "idle", export: null, import: null, stage: "", fraction: 0, error: null };

export interface Room {
  mw: number;
  bus: number;
  kv: number;
  /** The probe's resolution: a room under one step is "<step". */
  step: number;
  /** Nothing bound within the engine's intake cap: the room is at least this. */
  capped: boolean;
  /** The limit the next MW would break, in the engine's words ("" when capped). */
  why: string;
}

export interface SiteRoom {
  name: string;
  /** A transformer there: what the map selects for the site. */
  trafo: number;
  gen: Room | null;
  dem: Room | null;
}

/** The room at each substation (named as the map's substation labels are): its best busbar per direction. */
export function siteRooms(m: Model, exp: StudyResult | null, imp: StudyResult | null): Map<string, SiteRoom> {
  const kv = new Map(m.buses.map((b) => [b.bus_id, b.vn_kv]));
  const sites = new Map<string, SiteRoom>();
  const siteOf = new Map<number, string>();
  m.transformers.forEach((t) => {
    const name = trafoSub(t);
    if (!sites.has(name)) sites.set(name, { name, trafo: t.trafo_id, gen: null, dem: null });
    [t.hv_bus, t.lv_bus].forEach((b) => !siteOf.has(b) && siteOf.set(b, name));
  });
  const room = (it: StudyItem): Room => ({
    mw: it.value ?? 0,
    bus: +it.element_id,
    kv: kv.get(+it.element_id) ?? 0,
    step: Number(it.extra.step_mw ?? 0),
    capped: it.limit != null,
    why: (it.extra.binding as { message?: string } | null)?.message ?? "",
  });
  const take = (items: StudyItem[] | undefined, side: "gen" | "dem") =>
    (items ?? []).forEach((it) => {
      const s = sites.get(siteOf.get(+it.element_id) ?? "");
      if (s && (!s[side] || (it.value ?? 0) > s[side]!.mw)) s[side] = room(it);
    });
  take(exp?.items, "gen");
  take(imp?.items, "dem");
  return new Map([...sites].filter(([, s]) => s.gen || s.dem));
}

/** A room's colour: at least 50 MW, 20, 5 (the study's step), or less. */
export const roomColor = (mw: number): string => (mw >= 50 ? C.phase1 : mw >= 20 ? "#e6d7a8" : mw >= 5 ? C.amber : C.red);
export const ROOM_KEY: [string, string][] = [[C.phase1, "50+ MW"], ["#e6d7a8", "20–50"], [C.amber, "5–20"], [C.red, "under 5"]];

/** "≥300" when nothing bound within the cap, "<5" under one probe step, else the MW. */
export const roomText = (r: Room): string => (r.capped ? `≥${fmtMw(r.mw)}` : r.mw < r.step ? `<${fmtMw(r.step)}` : fmtMw(r.mw));
