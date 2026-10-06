// The findings ledger as the Findings tab reads it. The API stores one row per finding per plan year (an
// overload that holds from 2027 to 2035 is nine rows), so the rows that are the same finding across years
// fold into one group here: the tab then counts breaches, not years, and a group opens to its per-year rows
// (each still its own finding to acknowledge or trace). Pure: every figure is the engine's.

import type { Finding, FindingSeverity, FindingStatus } from "../types";
import { SEV_ORDER, findingTitle } from "./gate";

/** The context fields that, with the kind, element and case, identify a finding across plan years (the rest varies by year). */
const IDENTITY_CONTEXT: Record<string, string[]> = {
  n1: ["breach_type", "breach_element_id", "outage_name"],
  alert: ["alert_kind"],
  work: ["verdict", "work"],
  deferred: ["grid"],
};

/** The order kinds read in within a criticality: the network first, then the demand side and the works, then the queue. */
const KIND_ORDER = ["overload", "voltage", "gsp_over_limit", "gsp_near_limit", "n1", "alert", "work", "non_convergent", "deferred", "rejected", "against_recommendation"];
const kindRank = (kind: string): number => {
  const i = KIND_ORDER.indexOf(kind);
  return i < 0 ? KIND_ORDER.length : i;
};

export const FINDING_STATUSES: FindingStatus[] = ["open", "acknowledged", "resolved"];

/** What identifies a finding across plan years. */
export const groupKey = (f: Finding): string =>
  [f.kind, f.element_kind ?? "", f.element_id ?? "", f.case ?? "", ...(IDENTITY_CONTEXT[f.kind] ?? []).map((k) => String(f.context[k] ?? ""))].join("|");

/** A per-unit voltage: its worst value is the one furthest from 1.0 pu, not the largest. */
export const isPu = (f: Finding): boolean => f.kind === "voltage" || f.context.breach_type === "voltage" || f.context.alert_kind === "voltage";

const badness = (f: Finding): number => (f.value == null ? -Infinity : isPu(f) ? Math.abs(f.value - 1) : f.value);

/** How a finding's figure reads: pu for voltages, % for loadings, MW for exports and the demand side, else the number. */
export function figureText(f: Finding): string {
  if (f.value == null) return "";
  if (isPu(f)) return `${f.value.toFixed(3)} pu`;
  if (f.kind === "overload" || f.context.breach_type === "line" || f.context.breach_type === "trafo") return `${Math.round(f.value)}%`;
  const mw = f.kind.startsWith("gsp") || f.kind === "alert" || f.context.breach_type === "islanded";
  const v = Math.round(f.value * 10) / 10;
  return mw ? `${v} MW` : `${v}`;
}

export interface FindingGroup {
  key: string;
  kind: string;
  /** The worst criticality any of its years reaches. */
  severity: FindingSeverity;
  title: string;
  /** One row per plan year it appears in (a plan-wide finding: one row), by year. */
  rows: Finding[];
  years: number[];
  /** The year with the worst figure (the largest loading or MW, the voltage furthest from 1.0 pu); the first row when none has a figure. */
  worst: Finding;
}

/** The rows folded across plan years, worst first within a kind. */
export function groupFindings(fs: Finding[]): FindingGroup[] {
  const by = new Map<string, Finding[]>();
  fs.forEach((f) => {
    const k = groupKey(f);
    by.set(k, [...(by.get(k) ?? []), f]);
  });
  const groups: FindingGroup[] = [...by.entries()].map(([key, rows]) => {
    rows.sort((a, b) => (a.year ?? -Infinity) - (b.year ?? -Infinity));
    const worst = rows.reduce((w, f) => (badness(f) > badness(w) ? f : w), rows[0]);
    const severity = rows.reduce<FindingSeverity>((s, f) => ((SEV_ORDER[f.severity] ?? 9) < (SEV_ORDER[s] ?? 9) ? f.severity : s), rows[0].severity);
    const years = [...new Set(rows.map((f) => f.year).filter((y): y is number => y != null))].sort((a, b) => a - b);
    return { key, kind: worst.kind, severity: severity in SEV_ORDER ? severity : "info", title: findingTitle(worst), rows, years, worst };
  });
  return groups.sort((a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9) || kindRank(a.kind) - kindRank(b.kind) || badness(b.worst) - badness(a.worst) || a.key.localeCompare(b.key));
}

/** A criticality's section: its groups, and the same groups by title ("Over its rating", "N-1 finding", ...). */
export interface FindingSection {
  severity: FindingSeverity;
  groups: FindingGroup[];
  kinds: { title: string; kind: string; groups: FindingGroup[] }[];
  /** How many ledger rows (one per year) the section holds. */
  rows: number;
  years: number[];
}

/** The ledger by criticality (breaches, then warnings, then notes), each folded across plan years; an empty criticality is left out. */
export function findingSections(fs: Finding[]): FindingSection[] {
  const groups = groupFindings(fs);
  return (Object.keys(SEV_ORDER) as FindingSeverity[])
    .sort((a, b) => SEV_ORDER[a] - SEV_ORDER[b])
    .map((severity) => {
      const own = groups.filter((g) => g.severity === severity);
      const kinds: FindingSection["kinds"] = [];
      own.forEach((g) => {
        const k = kinds.find((x) => x.title === g.title);
        if (k) k.groups.push(g);
        else kinds.push({ title: g.title, kind: g.kind, groups: [g] });
      });
      const years = [...new Set(own.flatMap((g) => g.years))].sort((a, b) => a - b);
      return { severity, groups: own, kinds, rows: own.reduce((n, g) => n + g.rows.length, 0), years };
    })
    .filter((s) => s.groups.length > 0);
}

/** The sections per ledger status (the tab shows one status at a time; the badge reads the open breaches). */
export const sectionsByStatus = (fs: Finding[]): Record<FindingStatus, FindingSection[]> =>
  Object.fromEntries(FINDING_STATUSES.map((st) => [st, findingSections(fs.filter((f) => f.status === st))])) as Record<FindingStatus, FindingSection[]>;

/** How many groups a status holds by criticality, and how many ledger rows they fold. */
export function sectionCounts(sections: FindingSection[]): { groups: number; breach: number; warn: number; info: number; rows: number } {
  const n = (sev: FindingSeverity) => sections.find((s) => s.severity === sev)?.groups.length ?? 0;
  return { groups: sections.reduce((a, s) => a + s.groups.length, 0), breach: n("breach"), warn: n("warn"), info: n("info"), rows: sections.reduce((a, s) => a + s.rows, 0) };
}

/** "2027–2035", "2030", "2030, 2032", "2027–2028, 2030–2035"; "plan-wide" for a finding without a year. */
export function yearSpan(years: number[]): string {
  const ys = [...new Set(years)].sort((a, b) => a - b);
  if (!ys.length) return "plan-wide";
  const runs: string[] = [];
  let start = ys[0];
  let prev = ys[0];
  const flush = () => runs.push(start === prev ? `${start}` : `${start}–${prev}`);
  for (const y of ys.slice(1)) {
    if (y === prev + 1) {
      prev = y;
      continue;
    }
    flush();
    start = prev = y;
  }
  flush();
  return runs.join(", ");
}
