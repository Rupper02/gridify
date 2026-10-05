// Projects as the planner shows them: which branch is a project's plan of record, what a project
// can do (its capabilities), how a source kind and an import report read, and the import form's
// known-limit fields. Pure; the API validates, imports and stores.

import type { Assumption, Capabilities, ImportReport, Project } from "../types";

export const DEFAULT_PROJECT_ID = "nged-bickerfen";

/** Every capability on, as the built-in project has them (what the planner assumes before the projects load). */
export const ALL_CAPABILITIES: Capabilities = { boundary: true, regions: true, registry: true, editions: true, summer_case: true, crs: "wgs84" };

export const KIND_LABEL: Record<string, string> = {
  nged: "NGED LTDS open data",
  cgmes: "CIM/CGMES exchange",
  pandapower_json: "pandapower JSON",
  matpower: "MATPOWER case",
};
export const kindLabel = (kind: string): string => KIND_LABEL[kind] ?? kind;

/** The plan-of-record branch of a project (`main` for the built-in one, `<id>-main` for an import). */
export function mainIdOf(projects: Project[], projectId: string): string {
  return projects.find((p) => p.project_id === projectId)?.main_id ?? "main";
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
  if (r.islands > 1) lines.push({ tone: "warn", text: `${r.islands} separate parts; those without an infeed were dropped.` });
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
export const assumptionText = (a: Assumption): string => (a.count ? `${a.message} (${a.count} ${a.element_kind ?? "element"}${a.count === 1 ? "" : "s"})` : a.message);

export interface LimitField {
  key: string;
  label: string;
  hint: string;
}

/** What the operator may enter at import (the API's ImportMeta), each recorded as operator-entered. */
export const LIMIT_FIELDS: LimitField[] = [
  { key: "gsp_export_limit_mw", label: "Export limit to the external grid (MW)", hint: "the transmission boundary the plan is checked against" },
  { key: "gsp_name", label: "Boundary name", hint: "how the limit is called in reasons" },
  { key: "min_demand_factor", label: "Minimum demand as a share of maximum (0–1)", hint: "enables the summer-minimum case" },
  { key: "summer_rating_ratio", label: "Summer / winter line rating ratio (0–1.5)", hint: "applied to every line" },
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
