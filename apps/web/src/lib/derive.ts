// Pure view helpers: everything here is a function of API data + UI state, with no side effects,
// so it is unit-testable without a browser or a map.

import { BRANCH_HUES, C, MAIN_HUE, ORDER, PLAN_YEARS, ST, fmtMw, profileOf, techLabel } from "../theme";
import type {
  Branch,
  BranchReinforcement,
  ElementSel,
  Line,
  Model,
  OptimizeResult,
  Outage,
  OutageStudy,
  QueueItem,
  RegistryItem,
  Status,
  Transformer,
  Verdict,
  Work,
  YearResult,
} from "../types";

export const isAccepted = (x: QueueItem): boolean => x.status === "Phase1" || x.status === "Phase2";

/** GB statutory voltage band for a nominal voltage (ESQCR): ±10 % at 132 kV and above, ±6 % below. */
export const voltageBand = (kv: number | null | undefined): [number, number] => (kv != null && kv >= 132 ? [0.9, 1.1] : [0.94, 1.06]);

/**
 * The year a project energises in the plan: the operator's override if set, else the optimizer's
 * recommendation. Only ACCEPTED projects get a year; deferred and rejected ones can't be hosted.
 */
export function effYearOf(x: QueueItem): number | null {
  if (!isAccepted(x)) return null;
  return x.scheduled_year != null ? x.scheduled_year : x.recommended_year;
}

export const sumMw = (xs: { rating_mw: number | null }[]): number =>
  Math.round(xs.reduce((a, b) => a + (b.rating_mw ?? 0), 0) * 10) / 10;
export const byStatus = (q: QueueItem[], st: Status): QueueItem[] => q.filter((x) => x.status === st);
/** A project's headline MW: its export, or its import for demand-type projects that export nothing. */
export const headlineMw = (x: { rating_mw: number | null; import_mw?: number | null }): number =>
  (x.rating_mw ?? 0) > 0 ? (x.rating_mw ?? 0) : (x.import_mw ?? 0);

// ---- the year being viewed ----------------------------------------------------------------------
/** The stored result for a year; while a run is still solving, the nearest year already solved. */
export function yearResultFor(r: OptimizeResult | null, year: number): { yr: YearResult | null; exact: boolean } {
  if (!r || !r.years) return { yr: null, exact: false };
  const hit = r.years[String(year)];
  if (hit) return { yr: hit, exact: true };
  const solved = Object.keys(r.years).map(Number);
  if (!solved.length) return { yr: null, exact: false };
  const near = solved.reduce((a, b) => (Math.abs(b - year) < Math.abs(a - year) ? b : a));
  return { yr: r.years[String(near)], exact: false };
}

export const lensFor = (year: number): { label: string; c: string } =>
  year <= 2026
    ? { label: "as-is today", c: C.mute }
    : year <= 2030
      ? { label: "Phase 1 · Clean Power lens", c: C.phase1 }
      : { label: "Phase 2 · Strategic lens", c: C.phase2 };

// ---- branches ----------------------------------------------------------------------------------
/** A branch's identity hue: main is silver; open branches take the hues in creation order. */
export function branchHue(branches: Branch[], id: string): string {
  if (!id || id === "main") return MAIN_HUE;
  const others = branches.filter((b) => b.branch_id !== "main").sort((a, b) => a.created_at.localeCompare(b.created_at));
  const i = others.findIndex((b) => b.branch_id === id);
  return BRANCH_HUES[(i < 0 ? 0 : i) % BRANCH_HUES.length];
}

export interface Staleness {
  stale: boolean;
  text: string;
}
/**
 * Whether the result on screen is out of date for the branch as it stands now: the profile changed,
 * or outages, reinforcements or scheduled years changed since the run (`studied` is what it covered).
 */
export function staleness(
  r: OptimizeResult | null,
  branch: Pick<Branch, "scenario"> | null,
  outages: Outage[],
  reinforcements: BranchReinforcement[],
  prelimCount: number,
): Staleness {
  if (!r || !branch) return { stale: false, text: "" };
  const was = profileOf(r.params.scenario).label;
  const now = profileOf(branch.scenario).label;
  if (r.params.scenario !== branch.scenario)
    return { stale: true, text: `This result was solved on ${was} demand. The branch is now set to ${now}, so the numbers below are out of date.` };
  const studied = new Set(r.studied?.outage_ids ?? []);
  const fresh = outages.filter((o) => !studied.has(o.outage_id)).length;
  const gone = (r.studied?.outage_ids ?? []).filter((id) => !outages.some((o) => o.outage_id === id)).length;
  if (fresh || gone)
    return { stale: true, text: fresh ? `${fresh} new maintenance window${fresh > 1 ? "s have" : " has"} not been studied yet.` : "A studied maintenance window was removed." };
  const sig = (xs: { kind: string; element_id: number; action: string }[]) =>
    xs.map((x) => `${x.kind}:${x.element_id}:${x.action}`).sort().join("|");
  if (sig(r.studied?.reinforcements ?? []) !== sig(reinforcements))
    return { stale: true, text: "The proposed reinforcements changed since this run." };
  const sched = r.studied?.schedule ?? {};
  if (r.queue.some((q) => (q.scheduled_year ?? undefined) !== sched[q.request_id]))
    return { stale: true, text: "An energisation year changed. The years below still show the old schedule." };
  if (prelimCount)
    return { stale: true, text: `${prelimCount} preliminary project${prelimCount > 1 ? "s are" : " is"} not in this run yet.` };
  return { stale: false, text: "" };
}

// ---- the queue ----------------------------------------------------------------------------------
export interface QueueGroup {
  key: "prelim" | "Phase1" | "Phase2" | "Deferred" | "Rejected";
  title: string;
  meta: string;
  c: string;
  dashed: boolean;
}
export function queueGroups(q: QueueItem[], prelim: RegistryItem[]) {
  const groups: { g: QueueGroup; rows: (QueueItem | RegistryItem)[] }[] = [];
  const add = (g: QueueGroup, rows: (QueueItem | RegistryItem)[]) => rows.length && groups.push({ g, rows });
  add({ key: "prelim", title: "Preliminary", meta: "not simulated yet", c: ST.Prelim.c, dashed: true }, prelim);
  const p1 = byStatus(q, "Phase1");
  const p2 = byStatus(q, "Phase2");
  const df = byStatus(q, "Deferred");
  const rj = byStatus(q, "Rejected");
  const meta = (xs: QueueItem[]) => `${xs.length} · ${sumMw(xs)} MW`;
  add({ key: "Phase1", title: "Phase 1 · by 2030", meta: meta(p1), c: ST.Phase1.c, dashed: false }, p1);
  add({ key: "Phase2", title: "Phase 2 · 2031 to 2035", meta: meta(p2), c: ST.Phase2.c, dashed: false }, p2);
  add({ key: "Deferred", title: "Deferred", meta: meta(df), c: ST.Deferred.c, dashed: true }, df);
  add({ key: "Rejected", title: "Rejected at intake", meta: `${rj.length}`, c: ST.Rejected.c, dashed: true }, rj);
  return groups;
}

/** Projects added to the branch since the last run (not in its queue yet). */
export const preliminaryOf = (added: RegistryItem[], r: OptimizeResult | null): RegistryItem[] => {
  const inRun = new Set((r?.queue ?? []).map((q) => q.request_id));
  return added.filter((a) => !inRun.has(a.request_id));
};

// ---- the roadmap dock ---------------------------------------------------------------------------
export interface RoadmapChip {
  id: string;
  kind: "project" | "prelim" | "outage";
  status: Status | "Prelim" | null;
  tech: string | null;
  branchOnly: boolean;
  /** Outage chips: what the window is for, and its verdict once studied. */
  work?: Work;
  verdict?: Verdict | null;
}
export interface RoadmapYear {
  y: number;
  chips: RoadmapChip[];
  mw: number;
  band: string;
  solved: boolean;
}
export function roadmapYears(
  r: OptimizeResult | null,
  prelim: RegistryItem[],
  outages: Outage[],
  branchOnly: Set<string>,
  shortName: (o: Outage) => string,
): RoadmapYear[] {
  const q = r?.queue ?? [];
  return PLAN_YEARS.map((y) => {
    const chips: RoadmapChip[] = q
      .filter((x) => effYearOf(x) === y)
      .sort((a, b) => ORDER[a.status] - ORDER[b.status])
      .map((x) => ({ id: x.request_id, kind: "project", status: x.status, tech: x.technology, branchOnly: branchOnly.has(x.request_id) }));
    prelim
      .filter((p) => p.commissioning_year === y)
      .forEach((p) => chips.push({ id: p.request_id, kind: "prelim", status: "Prelim", tech: p.technology, branchOnly: true }));
    outages
      .filter((o) => o.year === y)
      .forEach((o) =>
        chips.push({
          id: shortName(o), kind: "outage", status: null, tech: null, branchOnly: false,
          work: o.work ?? "maintenance", verdict: outageStudyOf(o, r).study?.verdict ?? null,
        }),
      );
    const mw = q.filter((x) => {
      const e = effYearOf(x);
      return e != null && e <= y;
    }).reduce((a, x) => a + (x.rating_mw ?? 0), 0);
    return { y, chips, mw: Math.round(mw), band: y <= 2026 ? C.mute : y <= 2030 ? C.phase1 : C.phase2, solved: !!r?.years?.[String(y)] };
  });
}

// ---- readings -----------------------------------------------------------------------------------
/** The model's buses and elements by id, for naming things the engine reports by index. */
export interface ModelIndex {
  bus: Map<number, Model["buses"][number]>;
  line: Map<number, Line>;
  trafo: Map<number, Transformer>;
  gen: Map<string, Model["generators"][number]>;
  /** Where each bus is: its own name, or for a coded busbar ("BOST1_MAIN1") a neighbour's. */
  place: Map<number, string>;
}
/** A busbar code rather than a name: no spaces, and digits or underscores in it. */
const isCode = (name: string | null | undefined): boolean => !!name && !/\s/.test(name.trim()) && /[\d_]/.test(name);
export function indexModel(m: Model): ModelIndex {
  const place = new Map<number, string>();
  m.buses.forEach((b) => !isCode(b.name) && placeName(b.name) && place.set(b.bus_id, placeName(b.name)));
  // coded busbars take the place of a transformer on them, else of a named neighbour on a line
  const borrow = (id: number, other: number) => !place.has(id) && place.has(other) && place.set(id, place.get(other)!);
  m.transformers.forEach((t) => {
    borrow(t.hv_bus, t.lv_bus);
    borrow(t.lv_bus, t.hv_bus);
  });
  m.lines.forEach((l) => {
    if (l.from_bus == null || l.to_bus == null) return;
    borrow(l.from_bus, l.to_bus);
    borrow(l.to_bus, l.from_bus);
  });
  return {
    bus: new Map(m.buses.map((b) => [b.bus_id, b])),
    line: new Map(m.lines.map((l) => [l.line_id, l])),
    trafo: new Map(m.transformers.map((t) => [t.trafo_id, t])),
    gen: new Map((m.generators ?? []).map((g) => [g.request_id, g])),
    place,
  };
}
/** A bus's place name (empty when nothing near it is named). */
export const busPlace = (ix: ModelIndex, id: number | null | undefined): string =>
  id == null ? "" : (ix.place.get(id) ?? "");

/** A substation's name from a busbar name ("BOSTON 33kV MAIN1" -> "Boston"). */
export const placeName = (busName: string | null | undefined): string => {
  const s = String(busName || "").replace(/\s*\d+(\.\d+)?\s*kV.*$/i, "").replace(/[_-]+/g, " ").trim();
  return s ? s.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()) : "";
};
export const busLabel = (ix: ModelIndex, id: number | null | undefined): string => {
  if (id == null) return "–";
  const b = ix.bus.get(id);
  return b ? `Bus ${id} · ${busPlace(ix, id) || "bus"} ${+b.vn_kv} kV` : `Bus ${id}`;
};
export const lineName = (ix: ModelIndex, id: number): string => {
  const l = ix.line.get(id);
  if (!l) return `Line ${id}`;
  const a = busPlace(ix, l.from_bus);
  const b = busPlace(ix, l.to_bus);
  if (a && b && a !== b) return `${a} to ${b} ${+l.voltage_kv} kV`;
  return `${a || l.line_name || `Line ${id}`} ${+l.voltage_kv} kV`.trim();
};
/** A transformer's substation is its HV busbar name minus the voltage/bay suffix. */
export const trafoSub = (t: Transformer): string => placeName(t.hv_name || t.name) || `T${t.trafo_id}`;
export const trafoRatio = (t: Transformer): string => (t.hv_kv && t.lv_kv ? `${+t.hv_kv}/${+t.lv_kv} kV` : "–");
export const trafoName = (ix: ModelIndex, id: number): string => {
  const t = ix.trafo.get(id);
  return t ? `${trafoSub(t)} ${trafoRatio(t)} transformer` : `Transformer ${id}`;
};
/** Capacity of a line = √3 · V · I. */
export const lineMva = (l: Line): number => (l.voltage_kv ? (Math.sqrt(3) * l.voltage_kv * l.rating_a) / 1000 : 0);

export interface WorstElement {
  pct: number;
  name: string;
  sel: ElementSel;
}
/** The most loaded line or transformer in a year (worst case across the two study cases). */
export function worstElement(yr: YearResult | null, ix: ModelIndex | null): WorstElement | null {
  if (!yr || !ix) return null;
  let best: WorstElement | null = null;
  for (const [id, v] of Object.entries(yr.line_loading ?? {}))
    if (!best || v > best.pct) best = { pct: v, name: lineName(ix, +id), sel: { kind: "line", id: +id } };
  for (const [id, v] of Object.entries(yr.trafo_loading ?? {}))
    if (!best || v > best.pct) best = { pct: v, name: trafoName(ix, +id), sel: { kind: "trafo", id: +id } };
  return best;
}

/** GSP export gauge: 24 ticks, cyan, the last ones amber above 90 %. */
export function gspTicks(exportMw: number, limit: number | null, n = 24): string[] {
  const filled = limit ? Math.round(Math.min(1, Math.max(0, exportMw / limit)) * n) : 0;
  return Array.from({ length: n }, (_, i) => (i < filled ? (i >= Math.round(n * 0.875) ? C.amber : C.accent) : "rgba(255,255,255,0.09)"));
}

// ---- elements and planned outages ---------------------------------------------------------------
export interface ElementInfo {
  name: string;
  short: string;
  kindLabel: string;
  rating: string;
  loadLabel: string;
  load: string;
  loadPct: number | null;
  ll: [number, number] | null;
}
export function elementInfo(sel: ElementSel, ix: ModelIndex, yr: YearResult | null, year: number): ElementInfo | null {
  if (sel.kind === "line") {
    const l = ix.line.get(sel.id);
    if (!l) return null;
    const pct = yr?.line_loading?.[sel.id] ?? null;
    return {
      name: lineName(ix, sel.id),
      short: lineShort(ix, sel.id),
      kindLabel: `Circuit · ${+l.voltage_kv} kV`,
      rating: `${fmtMw(lineMva(l))} MVA`,
      loadLabel: `Loading in ${year}`,
      load: pct == null ? "–" : `${Math.round(pct)}%`,
      loadPct: pct,
      ll: [(l.from_lon + l.to_lon) / 2, (l.from_lat + l.to_lat) / 2],
    };
  }
  if (sel.kind === "trafo") {
    const t = ix.trafo.get(sel.id);
    if (!t) return null;
    const pct = yr?.trafo_loading?.[sel.id] ?? null;
    return {
      name: trafoName(ix, sel.id),
      short: `${trafoSub(t).slice(0, 8)} T${t.trafo_id}`,
      kindLabel: `Transformer · ${trafoRatio(t)}`,
      rating: `${fmtMw(t.sn_mva)} MVA`,
      loadLabel: `Loading in ${year}`,
      load: pct == null ? "–" : `${Math.round(pct)}%`,
      loadPct: pct,
      ll: [t.hv_lon, t.hv_lat],
    };
  }
  const g = ix.gen.get(sel.id);
  if (!g) return null;
  return {
    name: g.applicant || g.request_id,
    short: g.request_id,
    kindLabel: `Existing generation · ${techLabel(g.technology)}`,
    rating: `${fmtMw(g.rating_mw)} MW`,
    loadLabel: "Output at summer min",
    load: g.technology === "battery" ? "exporting" : "full",
    loadPct: null,
    ll: [g.lon, g.lat],
  };
}
const lineShort = (ix: ModelIndex, id: number): string => {
  const l = ix.line.get(id);
  const a = busPlace(ix, l?.from_bus).slice(0, 3).toUpperCase();
  const b = busPlace(ix, l?.to_bus).slice(0, 3).toUpperCase();
  return a && b ? `${a}-${b}` : `L${id}`;
};

export const outageSel = (o: Outage): ElementSel =>
  o.element_kind === "gen" ? { kind: "gen", id: o.element_id } : { kind: o.element_kind, id: Number(o.element_id) };

/**
 * Where a planned window stands in a result: not in the run yet ("unstudied"), in the run but its
 * year not solved yet ("solving"), or studied (with the engine's study). See lib/maintenance.ts.
 */
export function outageStudyOf(o: Outage, r: OptimizeResult | null): { state: "unstudied" | "solving" | "studied"; study: OutageStudy | null } {
  if (!r?.studied?.outage_ids?.includes(o.outage_id)) return { state: "unstudied", study: null };
  const study = r.years?.[String(o.year)]?.outage_studies?.find((s) => s.outage_id === o.outage_id) ?? null;
  return { state: study ? "studied" : "solving", study };
}


export function projectLabel(x: QueueItem | RegistryItem): string {
  return x.applicant || techLabel(x.technology);
}

export const deferredMw = (q: QueueItem[]): number => sumMw(byStatus(q, "Deferred"));

// ---- connection points for the intake -----------------------------------------------------------
export interface BusOption {
  id: number;
  label: string;
}
/**
 * Buses where a new connection would land with the most room: connection-level buses (33 kV and
 * above) whose most loaded attached circuit is least loaded in the viewed year. A pointer only:
 * the engine decides feasibility when the project is run.
 */
export function busSuggestions(m: Model, ix: ModelIndex, yr: YearResult | null, n = 3): BusOption[] {
  if (!yr) return [];
  const worst = new Map<number, number>();
  m.lines.forEach((l) => {
    const pct = yr.line_loading?.[l.line_id];
    if (pct == null) return;
    [l.from_bus, l.to_bus].forEach((b) => b != null && worst.set(b, Math.max(worst.get(b) ?? 0, pct)));
  });
  return m.buses
    .filter((b) => b.vn_kv >= 33 && worst.has(b.bus_id) && busPlace(ix, b.bus_id))
    .sort((a, b) => (worst.get(a.bus_id) ?? 0) - (worst.get(b.bus_id) ?? 0))
    .filter((b, i, xs) => xs.findIndex((x) => busPlace(ix, x.bus_id) === busPlace(ix, b.bus_id)) === i) // one per substation
    .slice(0, n)
    .map((b) => ({ id: b.bus_id, label: busLabel(ix, b.bus_id) }));
}

/** A typed connection point ("1102", "bus 1102", "Boston") to a bus, preferring 33 kV and above. */
export function findBus(m: Model, ix: ModelIndex, text: string): BusOption | null {
  const num = text.match(/\b(\d{1,6})\b/);
  if (num && ix.bus.has(+num[1])) return { id: +num[1], label: busLabel(ix, +num[1]) };
  const t = text.toLowerCase().replace(/bus|·|\d+(\.\d+)?\s*kv/g, " ").trim();
  if (!t) return null;
  const hits = m.buses.filter((b) => {
    const p = busPlace(ix, b.bus_id).toLowerCase();
    return !!p && (p.includes(t) || t.includes(p));
  });
  const best = hits.sort((a, b) => b.vn_kv - a.vn_kv)[0];
  return best ? { id: best.bus_id, label: busLabel(ix, best.bus_id) } : null;
}

/** Engine text names elements by index ("line 16", "transformer 30", "bus 7"): say where they are. */
export function nameElements(text: string, ix: ModelIndex | null): string {
  if (!ix || !text) return text;
  return text
    .replace(/\b([Ll])ine (\d+)\b/g, (m, _l, id) => (ix.line.has(+id) ? lineName(ix, +id) : m))
    .replace(/\b([Tt])ransformer (\d+)\b/g, (m, _t, id) => (ix.trafo.has(+id) ? trafoName(ix, +id) : m))
    .replace(/\b([Bb])us (\d+)\b(?! ·)/g, (m, b, id) => (ix.bus.has(+id) && busPlace(ix, +id) ? `${m} (${busPlace(ix, +id)})` : m));
}
