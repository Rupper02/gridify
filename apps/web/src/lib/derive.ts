// Pure view helpers: everything here is a function of API data + UI state, with no side effects,
// so it is unit-testable without a browser or a map.

import { BRANCH_HUES, C, LENS, MAIN_HUE, ORDER, ST, fmtMw, profileOf, techLabel } from "../theme";
import { type Plan, lensOf, statusTitle } from "./plan";
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
/** A project's headline MW: its export, else its import; null when it states neither (an incomplete application). */
export const headlineMw = (x: { rating_mw: number | null; import_mw?: number | null }): number | null =>
  (x.rating_mw ?? 0) > 0 ? (x.rating_mw as number) : (x.import_mw ?? x.rating_mw ?? null);

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

// ---- branches ----------------------------------------------------------------------------------
/** A branch's identity hue: main is silver; open branches take the hues in creation order. */
export function branchHue(branches: Branch[], id: string, mainId = "main"): string {
  if (!id || id === mainId) return MAIN_HUE;
  const others = branches.filter((b) => b.branch_id !== mainId).sort((a, b) => a.created_at.localeCompare(b.created_at));
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
/** What a branch's parent is called in copy: "main" for its project's main, else the parent branch's name. */
export const parentName = (branches: Branch[], b: Pick<Branch, "parent_id"> | null | undefined, mainId: string): string =>
  !b?.parent_id || b.parent_id === mainId ? "main" : (branches.find((x) => x.branch_id === b.parent_id)?.name ?? b.parent_id);

/** "behind main · 2": an open branch lacking changes its parent received after it was opened (rebase it), else null. */
export const behindLabel = (b: Pick<Branch, "behind"> | null | undefined, parent = "main"): string | null =>
  b?.behind ? `behind ${parent} · ${b.behind}` : null;

export function staleness(
  r: OptimizeResult | null,
  branch: Pick<Branch, "scenario"> | null,
  outages: Outage[],
  reinforcements: BranchReinforcement[],
  prelimCount: number,
  changed = 0,
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
  if (changed)
    return { stale: true, text: `${changed} project${changed > 1 ? "s" : ""} changed (connection point, size or year) since this run.` };
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
export function queueGroups(q: QueueItem[], prelim: RegistryItem[], plan: Plan) {
  const groups: { g: QueueGroup; rows: (QueueItem | RegistryItem)[] }[] = [];
  const add = (g: QueueGroup, rows: (QueueItem | RegistryItem)[]) => rows.length && groups.push({ g, rows });
  add({ key: "prelim", title: "Preliminary", meta: "not simulated yet", c: ST.Prelim.c, dashed: true }, prelim);
  const p1 = byStatus(q, "Phase1");
  const p2 = byStatus(q, "Phase2");
  const df = byStatus(q, "Deferred");
  const rj = byStatus(q, "Rejected");
  const meta = (xs: QueueItem[]) => `${xs.length} · ${sumMw(xs)} MW`;
  add({ key: "Phase1", title: statusTitle(plan, "Phase1"), meta: meta(p1), c: ST.Phase1.c, dashed: false }, p1);
  add({ key: "Phase2", title: statusTitle(plan, "Phase2"), meta: meta(p2), c: ST.Phase2.c, dashed: false }, p2);
  add({ key: "Deferred", title: statusTitle(plan, "Deferred"), meta: meta(df), c: ST.Deferred.c, dashed: true }, df);
  add({ key: "Rejected", title: statusTitle(plan, "Rejected"), meta: `${rj.length}`, c: ST.Rejected.c, dashed: true }, rj);
  return groups;
}

/** Projects added to the branch since the last run (not in its queue yet). */
export const preliminaryOf = (added: RegistryItem[], r: OptimizeResult | null): RegistryItem[] => {
  const inRun = new Set((r?.queue ?? []).map((q) => q.request_id));
  return added.filter((a) => !inRun.has(a.request_id));
};

/** The branch's stored projects plus the ones added in this session that the store has not been re-read for (by id, the store wins). */
export const knownProjects = (stored: RegistryItem[], added: RegistryItem[]): RegistryItem[] => [
  ...stored,
  ...added.filter((a) => !stored.some((c) => c.request_id === a.request_id)),
];

/** How many stored projects differ from what the shown run ranked (connection point, rating, import or year): an edit the next run must see. */
export function changedProjects(stored: RegistryItem[], q: QueueItem[]): number {
  const by = new Map(q.map((x) => [x.request_id, x]));
  return stored.filter((c) => {
    const x = by.get(c.request_id);
    return (
      !!x &&
      (x.bus_id !== c.bus_id || (x.rating_mw ?? 0) !== (c.rating_mw ?? 0) || (x.import_mw ?? null) !== (c.import_mw ?? null) || (x.commissioning_year ?? null) !== (c.commissioning_year ?? null) ||
        JSON.stringify(x.control ?? null) !== JSON.stringify(c.control ?? null))
    );
  }).length;
}

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
  /** Run, but its power flow did not converge: no figures. */
  failed: boolean;
}
export function roadmapYears(
  plan: Plan,
  r: OptimizeResult | null,
  prelim: RegistryItem[],
  outages: Outage[],
  branchOnly: Set<string>,
  shortName: (o: Outage) => string,
): RoadmapYear[] {
  const q = r?.queue ?? [];
  return plan.years.map((y) => {
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
    const failed = r?.years?.[String(y)]?.converged === false; // run, but the power flow did not converge
    return { y, chips, mw: Math.round(mw), band: failed ? C.red : LENS[lensOf(plan, y)].c, solved: !!r?.years?.[String(y)], failed };
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
  /** Each line's name, parallel circuits numbered (filled by indexModel). */
  lineNames: Map<number, string>;
}
/** A busbar code rather than a name: no spaces, and digits or underscores in it. */
const isCode = (name: string | null | undefined): boolean => !!name && !/\s/.test(name.trim()) && /[\d_]/.test(name);
export function indexModel(m: Model): ModelIndex {
  // the engine names the model (`naming.py`, the names the agents use too); the rules below are its mirror, for a model
  // served before it carried names (and the tests' small fixtures)
  if (m.buses.some((b) => b.place !== undefined)) return namedIndex(m);
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
  const ix: ModelIndex = {
    bus: new Map(m.buses.map((b) => [b.bus_id, b])),
    line: new Map(m.lines.map((l) => [l.line_id, l])),
    trafo: new Map(m.transformers.map((t) => [t.trafo_id, t])),
    gen: new Map((m.generators ?? []).map((g) => [g.request_id, g])),
    place,
    lineNames: new Map(),
  };
  // number parallel circuits that would otherwise share a name
  const byName = new Map<string, number[]>();
  [...ix.line.keys()].sort((a, b) => a - b).forEach((id) => {
    const n = baseLineName(ix, id);
    byName.set(n, [...(byName.get(n) ?? []), id]);
  });
  byName.forEach((ids, n) => ids.forEach((id, i) => ix.lineNames.set(id, ids.length > 1 ? `${n}, circuit ${i + 1}` : n)));
  return ix;
}
/** The index of a model the engine has named: its places and names as given. */
function namedIndex(m: Model): ModelIndex {
  return {
    bus: new Map(m.buses.map((b) => [b.bus_id, b])),
    line: new Map(m.lines.map((l) => [l.line_id, l])),
    trafo: new Map(m.transformers.map((t) => [t.trafo_id, t])),
    gen: new Map((m.generators ?? []).map((g) => [g.request_id, g])),
    place: new Map(m.buses.filter((b) => b.place).map((b) => [b.bus_id, b.place!])),
    lineNames: new Map(m.lines.filter((l) => l.display_name).map((l) => [l.line_id, l.display_name!])),
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
/** Where a project connects, in words ("Sleaford 132 kV"); "bus 19" only when nothing near it is named. */
export const busWhere = (ix: ModelIndex | null, id: number | null | undefined): string => {
  if (id == null) return "–";
  const b = ix?.bus.get(id);
  const p = ix ? busPlace(ix, id) : "";
  return b && p ? `${p} ${+b.vn_kv} kV` : `bus ${id}`;
};
export const busLabel = (ix: ModelIndex, id: number | null | undefined): string => {
  if (id == null) return "–";
  const b = ix.bus.get(id);
  return b ? `Bus ${id} · ${busPlace(ix, id) || "bus"} ${+b.vn_kv} kV` : `Bus ${id}`;
};
const baseLineName = (ix: ModelIndex, id: number): string => {
  const l = ix.line.get(id);
  if (!l) return `Line ${id}`;
  const a = busPlace(ix, l.from_bus);
  const b = busPlace(ix, l.to_bus);
  if (a && b && a !== b) return `${a} to ${b} ${+l.voltage_kv} kV`;
  return `${a || l.line_name || `Line ${id}`} ${+l.voltage_kv} kV`.trim();
};
/** A line by the places it joins; parallel circuits on the same route read "circuit 1", "circuit 2". */
export const lineName = (ix: ModelIndex, id: number): string => ix.lineNames.get(id) ?? baseLineName(ix, id);
/** A transformer's substation is its HV busbar name minus the voltage/bay suffix. */
export const trafoSub = (t: Transformer): string => placeName(t.hv_name || t.name) || `T${t.trafo_id}`;
export const trafoRatio = (t: Transformer): string => (t.hv_kv && t.lv_kv ? `${+t.hv_kv}/${+t.lv_kv} kV` : "–");
export const trafoName = (ix: ModelIndex, id: number): string => {
  const t = ix.trafo.get(id);
  return t ? t.display_name || `${trafoSub(t)} ${trafoRatio(t)} transformer` : `Transformer ${id}`;
};
/** Capacity of a line = √3 · V · I. */
export const lineMva = (l: Line): number => (l.voltage_kv ? (Math.sqrt(3) * l.voltage_kv * l.rating_a) / 1000 : 0);

export interface WorstElement {
  pct: number;
  name: string;
  sel: ElementSel;
}
/** The most loaded line or transformer in a year (worst case across the two study cases). */
/** The year's N-1 screen in two counts: the single outages that breach a limit (in any case), and every breach (the
 * screen lists each element an outage breaches as its own finding). */
export function n1Counts(yr: YearResult | null): { outages: number; breaches: number } {
  const v = yr?.n1_violations ?? [];
  return { outages: new Set(v.map((x) => `${x.outage_type}:${x.outage_id}`)).size, breaches: v.length };
}

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

// one reference or a list of them ("line 16", "lines 0 and 1", "transformers 29, 30 and 31"); not one the API already
// named, whose id sits in brackets after its name ("Bicker Fen to Boston 132 kV, circuit 2 (line 1)"), and not a figure
// written after the word ("worst line 93%", "a line 4 km long"): as the engine's naming._REF
const NOT_A_FIGURE = String.raw`(?![.,]\d)(?!\s*%)(?!\s*(?:km|MW|MVAr|MVA|kV|kA|pu)\b)`;
const REF: Record<"line" | "transformer", RegExp> = {
  line: new RegExp(String.raw`(?<!\()\b(lines?) (\d+(?:(?:,? and |, )\d+)*)\b` + NOT_A_FIGURE, "gi"),
  transformer: new RegExp(String.raw`(?<!\()\b(transformers?) (\d+(?:(?:,? and |, )\d+)*)\b` + NOT_A_FIGURE, "gi"),
};
const joinNames = (xs: string[]): string => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);
const nameRefs = (text: string, kind: "line" | "transformer", name: (id: number) => string | null): string =>
  text.replace(REF[kind], (m, _k, ids: string) => {
    const named = (ids.match(/\d+/g) ?? []).map((x) => name(+x));
    return named.every((n) => n) ? joinNames(named as string[]) : m;
  });

/** Engine text names elements by index ("line 16", "lines 0 and 1", "transformer 30", "bus 7"): say where they are. */
export function nameElements(text: string, ix: ModelIndex | null): string {
  if (!ix || !text) return text;
  const lines = nameRefs(text, "line", (id) => (ix.line.has(id) ? lineName(ix, id) : null));
  const trafos = nameRefs(lines, "transformer", (id) => (ix.trafo.has(id) ? trafoName(ix, id) : null));
  // a bus keeps its number and gains its place, unless it is already named ("(bus 19)") or placed ("bus 19 (Sleaford)")
  return trafos.replace(/(?<!\()\b([Bb])us (\d+)\b(?! ·| \()/g, (m, _b, id) => (ix.bus.has(+id) && busPlace(ix, +id) ? `${m} (${busPlace(ix, +id)})` : m));
}
