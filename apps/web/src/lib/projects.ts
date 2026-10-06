// Projects as the planner shows them: which branch is a project's plan of record, what a project
// can do (its capabilities), how a source kind and an import report read, and the import form's
// known-limit fields. Pure; the API validates, imports and stores.

import type { Assumption, BandPreset, Capabilities, Control, FileLevel, ImportFormat, ImportPathway, ImportReport, Project } from "../types";

export const DEFAULT_PROJECT_ID = "nged-bickerfen";

/** Every capability on, as the built-in project has them (what the planner assumes before the projects load). */
export const ALL_CAPABILITIES: Capabilities = { boundary: true, regions: true, registry: true, editions: true, summer_case: true, crs: "wgs84" };

/** A source kind by the label the API serves (`GET /projects/formats`); the kind itself until they are in. */
export const kindLabel = (kind: string, formats: ImportFormat[]): string => formats.find((f) => f.kind === kind)?.label ?? kind;

/** The plan-of-record branch of a project, as the API serves it (`main_id`); "" until the projects are in. */
export function mainIdOf(projects: Project[], projectId: string): string {
  return projects.find((p) => p.project_id === projectId)?.main_id ?? "";
}

export function projectOf(projects: Project[], projectId: string): Project | null {
  return projects.find((p) => p.project_id === projectId) ?? null;
}

/** What a project can do, as short chips (what is missing is said in the import report instead). */
export function capabilityChips(c: Capabilities): string[] {
  const out: string[] = [];
  if (c.boundary) out.push("transmission boundary");
  if (c.regions) out.push("demand groups");
  if (c.registry) out.push("registry");
  if (c.editions) out.push("editions");
  if (c.summer_case) out.push("summer case");
  else out.push("winter peak only");
  if (c.crs === "synthetic") out.push("synthetic layout");
  return out;
}

export interface ReportLine {
  tone: "good" | "warn" | "bad";
  text: string;
}

/** An import report as lines: the counts, the cases, every error and warning. */
export function reportLines(r: ImportReport | null): ReportLine[] {
  if (!r) return [];
  const c = r.counts;
  const lines: ReportLine[] = [
    { tone: r.ok ? "good" : "bad", text: `${c.buses ?? 0} buses · ${c.lines ?? 0} lines · ${c.transformers ?? 0} transformers · ${c.loads ?? 0} loads · ${c.generators ?? 0} generators` },
  ];
  if (r.converged) lines.push({ tone: r.feasible ? "good" : "warn", text: r.feasible ? "The base case solves within every limit." : `The base case solves but breaks a limit: ${r.reason ?? "see the warnings"}.` });
  else if (r.ok) lines.push({ tone: "bad", text: `The base case does not converge: ${r.reason ?? "see the warnings"}.` });
  if (r.cases.length) lines.push({ tone: r.cases.includes("summer_min") ? "good" : "warn", text: r.cases.includes("summer_min") ? "Studied at winter peak and summer minimum." : "Studied at winter peak only: no seasonal ratings or minimum-demand factor." });
  if (r.islands > 1) lines.push({ tone: "warn", text: `${r.islands} separate parts, each with its own infeed or out of service.` });
  lines.push(...r.errors.map((e) => ({ tone: "bad" as const, text: e })));
  lines.push(...r.warnings.filter((w) => !w.startsWith("the network has")).map((w) => ({ tone: "warn" as const, text: w })));
  return lines;
}

export const SOURCE_LABEL: Record<string, string> = { file: "Not in the file", "operator-entered": "Entered at import", "engine-default": "Planning assumption" };

/** Assumptions grouped by where they come from: the file's gaps, the operator's entries, the engine's defaults. */
export function assumptionGroups(rows: Assumption[]): { source: string; label: string; rows: Assumption[] }[] {
  const order = ["file", "operator-entered", "engine-default"];
  return order
    .map((source) => ({ source, label: SOURCE_LABEL[source] ?? source, rows: rows.filter((a) => (a.source ?? "engine-default") === source) }))
    .filter((g) => g.rows.length);
}

/** One line for an assumption: its message and, when it names elements, how many. */
export const assumptionText = (a: Assumption): string => {
  if (!a.count) return a.message;
  const kind = a.element_kind ?? "element";
  return `${a.message} (${a.count} ${a.count === 1 ? kind : kind.endsWith("s") ? `${kind}es` : `${kind}s`})`;
};

export interface LimitField {
  key: string;
  label: string;
  hint: string;
}

/** What the operator may enter at import (the API's ImportMeta), each recorded as operator-entered. */
export const LIMIT_FIELDS: LimitField[] = [
  { key: "gsp_export_limit_mw", label: "Export limit to the external grid (MW)", hint: "the transmission boundary the plan is checked against" },
  { key: "gsp_name", label: "Boundary name", hint: "how the limit is called in reasons" },
  { key: "gsp_sgt_mw", label: "One supergrid transformer's rating (MVA)", hint: "sizes the 'add a transformer' lever; without it the lever is not offered" },
  { key: "min_demand_factor", label: "Minimum demand as a share of maximum (0–1)", hint: "required for the summer-minimum case unless the file carries it" },
  { key: "summer_rating_ratio", label: "Summer / winter line rating ratio (0–1.5)", hint: "required for the summer-minimum case unless the file carries it" },
  { key: "intermediate_rating_ratio", label: "Spring and autumn / winter rating ratio (0–1.5)", hint: "for planned works in those seasons" },
];

/** The entered limits, blanks dropped and numbers checked; a message for a field that is not a number. */
export function limitsFromForm(values: Record<string, string>): { limits: Record<string, string>; error: string | null } {
  const limits: Record<string, string> = {};
  for (const f of LIMIT_FIELDS) {
    const v = (values[f.key] ?? "").trim();
    if (!v) continue;
    if (f.key !== "gsp_name" && !Number.isFinite(Number(v))) return { limits, error: `${f.label} must be a number` };
    limits[f.key] = v;
  }
  return { limits, error: null };
}

// ---- a project's control mode -----------------------------------------------------------------------------

/** How a project's offer runs it, in words; null: not stated. */
export function controlText(c: Control | null | undefined): string | null {
  if (!c) return null;
  if (c.mode === "voltage") return `Voltage control at ${c.vm_pu} pu, reactive range ±${c.q_range_pf} pf`;
  return (c.pf ?? 1) >= 1 ? "Unity power factor" : `${c.pf} power factor, ${c.absorbing === false ? "injecting" : "absorbing"}`;
}

export interface ControlForm {
  mode: "pf" | "voltage";
  pf: string;
  absorbing: boolean;
  vm: string;
  range: string;
}
export const EMPTY_CONTROL: ControlForm = { mode: "pf", pf: "", absorbing: true, vm: "", range: "" };

/** The typed control mode as the API takes it, or what is missing or out of range. The ranges mirror the engine's
 * `types.Control` (it validates them again): pre-validation, so the form says what is wrong before posting. */
export function controlFromForm(f: ControlForm): { control: Control | null; error: string | null } {
  if (f.mode === "pf") {
    const pf = Number(f.pf);
    if (!f.pf.trim() || !(pf >= 0.5 && pf <= 1)) return { control: null, error: "Power factor between 0.5 and 1 (1 is unity)" };
    return { control: { mode: "pf", pf, absorbing: f.absorbing }, error: null };
  }
  const vm = Number(f.vm), range = Number(f.range);
  if (!f.vm.trim() || !(vm >= 0.9 && vm <= 1.1)) return { control: null, error: "Setpoint between 0.9 and 1.1 pu" };
  if (!f.range.trim() || !(range >= 0.5 && range < 1)) return { control: null, error: "Reactive range as a power factor between 0.5 and 1 (e.g. 0.95)" };
  return { control: { mode: "voltage", vm_pu: vm, q_range_pf: range }, error: null };
}

// ---- the study basis: what the import must state that a grid file does not carry ------------------------------

/** The study basis as typed: the forecast by pathway and year, its source, the N-1 floor and the limits by level (kV as text). */
export interface StudyBasisForm {
  forecast: Record<string, Record<number, string>>;
  source: string;
  n1MinKv: string;
  bands: Record<string, { vmin: string; vmax: string }>;
}

export const EMPTY_BASIS: StudyBasisForm = { forecast: {}, source: "", n1MinKv: "", bands: {} };

const kvText = (kv: number): string => `${kv}`;

/**
 * A preset's limits for each of the file's levels: the band with the highest threshold the level reaches, within that
 * band's top (EN 50160 stops at 36 kV). A level the preset sets nothing for keeps what was typed there. The presets are
 * served (engine `config.VOLTAGE_BAND_PRESETS`); this rule mirrors how the engine reads bands by level (`network.band_at`).
 */
export function presetBands(preset: BandPreset, levels: FileLevel[], typed: StudyBasisForm["bands"]): StudyBasisForm["bands"] {
  const out: StudyBasisForm["bands"] = { ...typed };
  const asc = [...preset.bands].sort((a, b) => a.min_kv - b.min_kv);
  for (const l of levels) {
    const band = asc.filter((b) => l.kv >= b.min_kv && (b.max_kv == null || l.kv <= b.max_kv)).pop();
    if (band) out[kvText(l.kv)] = { vmin: `${band.vmin_pu}`, vmax: `${band.vmax_pu}` };
  }
  return out;
}

const num = (v: string | undefined): number | null => {
  const t = (v ?? "").trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
};

/**
 * The study basis as the import form's fields (the forecast and the limits as JSON tables), or the first thing
 * missing or wrong. `years` are the plan years after the first (today is ×1.00). The API checks it all again.
 */
export function studyBasisFields(
  f: StudyBasisForm,
  years: number[],
  levels: FileLevel[],
  pathways: ImportPathway[],
  factorMax: number,
): { fields: Record<string, string>; error: string | null } {
  const forecasts: Record<string, Record<string, number>> = {};
  for (const p of pathways) {
    const row = f.forecast[p.id] ?? {};
    const vals = years.map((y) => num(row[y]));
    if (vals.every((v) => v === null)) {
      if (p.required) return { fields: {}, error: `Enter the ${p.label} forecast for every year, ${years[0]} to ${years[years.length - 1]}` };
      continue;
    }
    const bad = years.find((_, i) => vals[i] === null || !((vals[i] as number) > 0 && (vals[i] as number) <= factorMax));
    if (bad !== undefined) return { fields: {}, error: `The ${p.label} forecast needs a growth factor between 0 and ${factorMax} for every year, 1.02 being +2 % (${bad} is missing or out of range)` };
    forecasts[p.id] = Object.fromEntries(years.map((y, i) => [`${y}`, vals[i] as number]));
  }
  const n1 = num(f.n1MinKv);
  if (n1 === null || Number.isNaN(n1)) return { fields: {}, error: "Choose the lowest voltage level the N-1 screen covers" };
  const bands = [];
  for (const l of levels) {
    const b = f.bands[kvText(l.kv)];
    const lo = num(b?.vmin), hi = num(b?.vmax);
    if (lo === null || hi === null || Number.isNaN(lo) || Number.isNaN(hi)) return { fields: {}, error: `Enter the voltage limits at ${l.kv} kV (or pick a preset)` };
    if (!(lo < 1 && hi > 1)) return { fields: {}, error: `The limits at ${l.kv} kV must hold 1.00 pu between them (min below, max above)` };
    bands.push({ kv: l.kv, vmin_pu: lo, vmax_pu: hi });
  }
  const fields: Record<string, string> = { forecasts: JSON.stringify(forecasts), n1_min_kv: `${n1}`, voltage_bands: JSON.stringify(bands) };
  if (f.source.trim()) fields.forecast_source = f.source.trim();
  return { fields, error: null };
}

/** A pathway's year-on-year factors as typed, multiplied up: its multiple of today's peak by year (null while any year is missing). */
export function cumulativeOf(row: Record<number, string> | undefined, years: number[]): Record<number, number> | null {
  let m = 1;
  const out: Record<number, number> = {};
  for (const y of years) {
    const r = num(row?.[y]);
    if (r === null || Number.isNaN(r) || r <= 0) return null;
    m *= r;
    out[y] = m;
  }
  return out;
}

/** What an N-1 floor covers, for the choice's label. */
export const n1Covers = (l: FileLevel): string => {
  const parts = [l.n1_trafos ? `${l.n1_trafos} transformer${l.n1_trafos === 1 ? "" : "s"}` : "", l.n1_lines ? `${l.n1_lines} line${l.n1_lines === 1 ? "" : "s"}` : ""].filter(Boolean);
  return parts.length ? parts.join(", ") : "nothing to screen";
};
