// The grid model indexed by id, and what its elements are called. Pure: names come from the engine's `naming`
// (`place`, `display_name`), with a fallback for an element it left unnamed.

import { CASE_LABEL } from "../theme";
import type { Bus, Generator, Line, Model, Reason, Sel, Transformer, YearResult } from "../types";

export interface ModelIndex {
  bus: Map<number, Bus>;
  line: Map<number, Line>;
  trafo: Map<number, Transformer>;
  gen: Map<string, Generator>;
}

export function indexModel(m: Model): ModelIndex {
  return {
    bus: new Map(m.buses.map((b) => [b.bus_id, b])),
    line: new Map(m.lines.map((l) => [l.line_id, l])),
    trafo: new Map(m.transformers.map((t) => [t.trafo_id, t])),
    gen: new Map(m.generators.map((g) => [g.request_id, g])),
  };
}

/** A substation's name from a busbar name ("BOSTON 33kV MAIN1" -> "Boston"). */
export const placeName = (busName: string | null | undefined): string => {
  const s = String(busName || "").replace(/\s*\d+(\.\d+)?\s*kV.*$/i, "").replace(/[_-]+/g, " ").trim();
  return s ? s.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()) : "";
};

/** Where a bus is, in words ("Sleaford 132 kV"); "bus 19" only when nothing near it is named. */
export const busName = (ix: ModelIndex, id: number | null | undefined): string => {
  if (id == null) return "–";
  const b = ix.bus.get(id);
  const p = b?.place || placeName(b?.name);
  return b && p ? `${p} ${+b.vn_kv} kV` : `bus ${id}`;
};
export const lineName = (ix: ModelIndex, id: number): string => {
  const l = ix.line.get(id);
  return l?.display_name || (l ? `${l.line_name} ${+l.voltage_kv} kV` : `Line ${id}`);
};
/** A transformer's substation: its HV busbar name minus the voltage and bay suffix. */
export const trafoSub = (t: Transformer): string => placeName(t.hv_name || t.name) || `T${t.trafo_id}`;
export const trafoRatio = (t: Transformer): string => (t.hv_kv && t.lv_kv ? `${+t.hv_kv}/${+t.lv_kv} kV` : "–");
export const trafoName = (ix: ModelIndex, id: number): string => {
  const t = ix.trafo.get(id);
  return t ? t.display_name || `${trafoSub(t)} ${trafoRatio(t)} transformer` : `Transformer ${id}`;
};
/** A line's thermal capacity, √3 · V · I. */
export const lineMva = (l: Line): number => (l.voltage_kv ? (Math.sqrt(3) * l.voltage_kv * l.rating_a) / 1000 : 0);

/** The element a breach names, as a selection (none for the GSP or a non-convergent case). */
export function reasonSel(r: Reason): Sel | null {
  if (r.element_id == null) return null;
  if (r.type === "line") return { kind: "line", id: r.element_id };
  if (r.type === "trafo") return { kind: "trafo", id: r.element_id };
  if (r.type === "voltage") return { kind: "bus", id: r.element_id };
  return null;
}

/** A breach in words: what, where, by how much, in which case. */
export function reasonText(r: Reason, ix: ModelIndex | null): { title: string; figure: string; when: string } {
  const when = CASE_LABEL[r.case ?? ""] ?? "";
  if (r.type === "line") return { title: ix ? lineName(ix, r.element_id!) : `Line ${r.element_id}`, figure: `${Math.round(r.value ?? 0)}% of rating`, when };
  if (r.type === "trafo") return { title: ix ? trafoName(ix, r.element_id!) : `Transformer ${r.element_id}`, figure: `${Math.round(r.value ?? 0)}% of rating`, when };
  if (r.type === "voltage") {
    const v = r.value ?? 0;
    return { title: ix ? busName(ix, r.element_id) : `Bus ${r.element_id}`, figure: `${v.toFixed(3)} pu (${v > (r.limit ?? 1) ? "above" : "below"} ${r.limit?.toFixed(2)})`, when };
  }
  if (r.type === "gsp") return { title: "GSP export to transmission", figure: `${Math.round(r.value ?? 0)} MW of ${Math.round(r.limit ?? 0)} MW`, when };
  if (r.type === "gsp_import") return { title: "GSP import from transmission", figure: `${Math.round(r.value ?? 0)} MW of ${Math.round(r.limit ?? 0)} MW`, when };
  if (r.type === "voltage_collapse") return { title: ix ? busName(ix, r.element_id) : `Bus ${r.element_id}`, figure: `voltage collapse: ${(r.value ?? 0).toFixed(2)} pu, below the ${r.limit} pu floor`, when };
  return { title: "Power flow", figure: r.message, when };
}

export const KIND_LABEL: Record<string, string> = { line: "Line overloads", trafo: "Transformer overloads", voltage: "Voltage outside its band", gsp: "GSP export limit", gsp_import: "GSP import limit", non_convergent: "No solution", voltage_collapse: "No valid operating point" };

/** Each element ever breached across the plan, with the first year it breaches and its worst figure: "what limits
 * the plan, and from when". */
/** A breach further past its limit than another of the same element: a voltage further from 1.0 pu, else a higher figure. */
const worse = (a: Reason, b: Reason): boolean =>
  a.type === "voltage" ? Math.abs((a.value ?? 1) - 1) > Math.abs((b.value ?? 1) - 1) : (a.value ?? 0) > (b.value ?? 0);

export interface Limiter {
  key: string;
  reason: Reason;
  first: number;
  years: number[];
}
export function limiters(years: Record<string, YearResult>): Limiter[] {
  const out = new Map<string, Limiter>();
  Object.values(years)
    .sort((a, b) => a.year - b.year)
    .forEach((y) =>
      y.violations.forEach((r) => {
        const key = `${r.type}:${r.element_id ?? ""}`;
        const cur = out.get(key);
        if (!cur) out.set(key, { key, reason: r, first: y.year, years: [y.year] });
        else {
          if (!cur.years.includes(y.year)) cur.years.push(y.year);
          if (worse(r, cur.reason)) cur.reason = r;
        }
      }),
    );
  return [...out.values()].sort((a, b) => a.first - b.first || a.key.localeCompare(b.key));
}

/** The year's figure for a selected element and the case that set it. */
export function caseOf(yr: YearResult | null, kind: "lines" | "trafos" | "buses", id: number): string | null {
  if (!yr) return null;
  for (const [c, groups] of Object.entries(yr.envelope_case ?? {})) if (groups[kind]?.includes(id)) return c;
  return null;
}
