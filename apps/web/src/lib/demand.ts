// The demand side on the map and in the cards: who the network supplies, region by region and year
// by year. Pure: the engine (demand.py) decides every figure and alert; this only merges the model's
// regions with a year's results, colours them by their worst alert, and words the P2/8 classes.
// It is a simplified P2/8-style check (MW only, no customer counts), and the copy says so.

import type { Feature, Point } from "geojson";

import { C } from "../theme";
import type { Alert, AlertLevel, Model, Region, RegionYear, Sel, YearResult } from "../types";

/** A region's state in a year: its worst alert, ok, or not solved yet (no year result). */
export type RegionState = AlertLevel | "ok" | "unsolved";

export const REGION_STATE: Record<RegionState, { c: string; label: string }> = {
  breach: { c: C.red, label: "Breach" },
  warn: { c: C.amber, label: "Warning" },
  ok: { c: "#9fb3c9", label: "Within limits" },
  unsolved: { c: C.mute2, label: "Not solved yet" },
};

/** P2/8 demand classes as the engine reads them (config.P2_8_CLASSES), in plain English. */
export const P2_CLASS: Record<string, { range: string; meaning: string }> = {
  A: { range: "up to 1 MW", meaning: "A small group: it may stay off until the fault is repaired." },
  B: { range: "1 to 12 MW", meaning: "After a first circuit outage, supply is restored within about 3 hours; no second circuit is required." },
  C: { range: "12 to 60 MW", meaning: "After a first circuit outage, only 12 MW or a third of the group (the larger) may wait for restoration." },
  D: { range: "60 to 300 MW", meaning: "After a first circuit outage, only 20 MW may wait for restoration; the rest must stay on." },
  E: { range: "300 to 1500 MW", meaning: "All demand must stay on through a first circuit outage." },
  F: { range: "above 1500 MW", meaning: "All demand must stay on through a first circuit outage (a transmission-scale group)." },
};

export const classMeaning = (cls: string): string => P2_CLASS[cls]?.meaning ?? "Class not recognised.";

/** Short titles for the engine's alert kinds (demand.ALERT_CHECKS); unknown kinds fall back. */
export const ALERT_KIND: Record<string, string> = {
  firm_capacity: "Demand above firm capacity",
  n1_stranded: "Demand cut off by one outage",
  voltage: "Customers outside the voltage band",
  headroom: "Firm headroom running low",
};
export const alertTitle = (kind: string): string => ALERT_KIND[kind] ?? kind.replace(/_/g, " ");

/** Worst alert level per region in a year. */
export function regionLevels(alerts: Alert[] | undefined): Map<string, AlertLevel> {
  const out = new Map<string, AlertLevel>();
  for (const a of alerts ?? []) if (out.get(a.region_id) !== "breach") out.set(a.region_id, a.level);
  return out;
}

/** A region as the map and card show it: today's group, overlaid with the year's figures if solved. */
export interface RegionRow {
  region_id: string;
  name: string;
  bsp: string;
  buses: number[];
  demand_mw: number;
  firm_mw: number;
  p2_class: string;
  state: RegionState;
  /** The year's figures, or null before a run (or on a result without the demand side). */
  year: RegionYear | null;
}

/** The model's regions merged with a year's results. Regions with no buses cannot be drawn and are left out. */
export function regionRows(model: Pick<Model, "regions"> | null, yr: YearResult | null): RegionRow[] {
  const byId = new Map((yr?.regions ?? []).map((r) => [r.region_id, r]));
  const levels = regionLevels(yr?.alerts);
  const solved = !!yr?.regions;
  return (model?.regions ?? [])
    .filter((r: Region) => r.buses.length > 0)
    .map((r) => {
      const y = byId.get(r.region_id) ?? null;
      return {
        region_id: r.region_id,
        name: r.name,
        bsp: r.bsp,
        buses: r.buses,
        demand_mw: y?.demand_mw ?? r.peak_demand_mw,
        firm_mw: y?.firm_mw ?? r.firm_mw,
        p2_class: y?.p2_class ?? r.p2_class,
        state: !solved || !y ? "unsolved" : (levels.get(r.region_id) ?? "ok"),
        year: y,
      };
    });
}

/** Counts of the year's alerts by level, and the region to show first (most breaches, then warnings, then least headroom). */
export function alertSummary(yr: YearResult | null): { breach: number; warn: number; worst: string | null } {
  const alerts = yr?.alerts ?? [];
  const score = new Map<string, number>();
  let breach = 0;
  let warn = 0;
  alerts.forEach((a) => {
    if (a.level === "breach") breach += 1;
    else warn += 1;
    score.set(a.region_id, (score.get(a.region_id) ?? 0) + (a.level === "breach" ? 1000 : 1));
  });
  const head = new Map((yr?.regions ?? []).map((r) => [r.region_id, r.headroom_mw]));
  let worst: string | null = null;
  for (const [id, v] of score) {
    const w = worst == null ? -1 : score.get(worst)!;
    if (v > w || (v === w && (head.get(id) ?? Infinity) < (head.get(worst!) ?? Infinity))) worst = id;
  }
  return { breach, warn, worst };
}

/** The year's alerts for one region, breaches first (the engine's order). */
export const alertsFor = (yr: YearResult | null, regionId: string): Alert[] => (yr?.alerts ?? []).filter((a) => a.region_id === regionId);

type LonLat = { lon: number; lat: number };

/** The distinct positions of a region's buses (several voltage levels often share one site). */
export function regionSites(buses: number[], at: Map<number, LonLat>): [number, number][] {
  const seen = new Set<string>();
  const out: [number, number][] = [];
  buses.forEach((b) => {
    const p = at.get(b);
    if (!p || p.lon == null || p.lat == null) return;
    const k = `${p.lon.toFixed(5)},${p.lat.toFixed(5)}`;
    if (!seen.has(k)) {
      seen.add(k);
      out.push([p.lon, p.lat]);
    }
  });
  return out;
}

/** Where a region's label and the camera go: the mean of its sites. */
export function regionCentroid(buses: number[], at: Map<number, LonLat>): [number, number] | null {
  const s = regionSites(buses, at);
  if (!s.length) return null;
  return [s.reduce((a, p) => a + p[0], 0) / s.length, s.reduce((a, p) => a + p[1], 0) / s.length];
}

/** Halo radius in px at the reference zoom, by demand (√MW so a 300 MW group does not swamp the map). */
/** It starts wider than a substation's transformer icon so the halo shows around it. */
export const haloRadius = (demandMw: number): number => 15 + Math.sqrt(Math.max(0, demandMw)) * 1.8;

/** One halo per region site, coloured by state, sized by demand. Severe regions sort last so they draw on top. */
export function regionFeatures(model: Model, yr: YearResult | null, sel: Sel | null): Feature<Point>[] {
  const at = new Map(model.buses.map((b) => [b.bus_id, b]));
  const order: Record<RegionState, number> = { unsolved: 0, ok: 1, warn: 2, breach: 3 };
  return regionRows(model, yr)
    .sort((a, b) => order[a.state] - order[b.state] || b.demand_mw - a.demand_mw)
    .flatMap((r) =>
      regionSites(r.buses, at).map(([lon, lat]) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [lon, lat] },
        properties: {
          id: r.region_id,
          r: haloRadius(r.demand_mw),
          color: REGION_STATE[r.state].c,
          sel: sel?.kind === "region" && sel.id === r.region_id ? 1 : 0,
        },
      })),
    );
}

/** Demand against firm capacity for the bar: the filled share (capped at 1), and its colour. */
export function firmFill(demandMw: number, firmMw: number): { frac: number; over: boolean; c: string } {
  if (firmMw <= 0) return { frac: 0, over: false, c: C.mute2 };
  const f = demandMw / firmMw;
  return { frac: Math.min(1, Math.max(0, f)), over: f > 1, c: f > 1 ? C.red : f > 0.9 ? C.amber : C.accent };
}

const mw = (x: number): string => (Math.abs(x) >= 100 ? Math.round(x).toString() : x.toFixed(1));

/** The figure under a region's name on the map: "demand / firm MW · class". */
export const regionFigure = (r: Pick<RegionRow, "demand_mw" | "firm_mw" | "p2_class">): string =>
  r.firm_mw > 0 ? `${mw(r.demand_mw)} / ${mw(r.firm_mw)} MW · ${r.p2_class}` : `${mw(r.demand_mw)} MW · no firm figure · ${r.p2_class}`;

/** The engine names an N-1 outage "line 13" or "trafo 4"; word it so derive.nameElements can name the element. */
export const outagePhrase = (raw: string | null): string => (raw ? raw.replace(/^trafo (\d+)$/i, "transformer $1") : "");

/** Label priority: breaches first, then warnings, then the larger groups. Groups with no firm figure and no
 *  alert (a customer's own connection, often a generation site drawing a few kW) keep their halo but no label. */
export function labelOrder(rows: RegionRow[]): RegionRow[] {
  const order: Record<RegionState, number> = { breach: 0, warn: 1, ok: 2, unsolved: 3 };
  return rows.filter((r) => r.firm_mw > 0 || r.state === "breach" || r.state === "warn").sort((a, b) => order[a.state] - order[b.state] || b.demand_mw - a.demand_mw);
}
