// What limits a branch, as the Limits tab reads the engine's reduction of a run (GET /branches/{id}/limits): the
// tab's badge and summary line, each binding element's figures in words and as sparkline points, and where a
// binding element, a deferred project's chain or an N-1 cause points on the map. Pure: every figure is the engine's.

import { caseLabel } from "../theme";
import type { Chain, Cluster, ElementBinding, Limits, Model, Sel } from "../types";
import { plural } from "./derive";
import { yearSpan } from "./findings";
import { elementSel } from "./gate";

/** How many rows show before "Show all": the binding set reads as an overview, the causes as the few that matter most. */
export const MAX_BINDING = 8;
export const MAX_CLUSTERS = 6;

/** The elements over a limit, else the projects deferred, else nothing: what the tab's badge counts. */
export function limitsBadge(l: Limits | null): string {
  if (!l) return "";
  const breaches = l.binding.filter((b) => b.severity === "breach").length;
  return String(breaches || l.chains.length || "");
}

/** "41 elements bind or come near a limit · 2 projects deferred · 36 N-1 causes (513 rows in 15 outage/case pairs) · 1 works window". */
export function summaryLine(l: Limits): string {
  const binding = l.binding.filter((b) => b.severity !== "ok").length;
  return [
    `${plural(binding, "element")} bind${binding === 1 ? "s" : ""} or come${binding === 1 ? "s" : ""} near a limit`,
    `${plural(l.chains.length, "project")} deferred`,
    `${plural(l.clusters.length, "N-1 cause")} (${plural(l.n1_rows, "row")} in ${plural(l.n1_pairs, "outage/case pair")})`,
    `${plural(l.works.length, "works window")}`,
  ].join(" · ");
}

/** A figure with its unit as the engine gives it: "132.6%", "1.062 pu". */
export const figureText = (value: number, unit: string): string => (unit === "%" ? `${value}%` : `${value} ${unit}`.trim());

/** "132.6% at winter peak in 2031": the worst year's envelope figure and the case that set it. */
export const worstText = (b: ElementBinding): string => `${figureText(b.worst.value, b.unit)}${b.worst.case ? ` at ${caseLabel(b.worst.case)}` : ""} in ${b.worst.year}`;

/** "breaches from 2031", "near from 2028", or "" when it never comes near. */
export function fromText(b: ElementBinding): string {
  if (b.first_breach_year != null) return `breaches from ${b.first_breach_year}`;
  if (b.first_near_year != null) return `near from ${b.first_near_year}`;
  return "";
}

/** The sparkline's points: one per plan year, null where the trajectory has no figure for it (not solved). */
export function trajectoryPoints(b: ElementBinding, years: number[]): { year: number; pct: number | null }[] {
  const byYear = new Map(b.trajectory.map((p) => [p.year, p.value]));
  return years.map((year) => ({ year, pct: byYear.get(year) ?? null }));
}

/** Where a binding element shows on the map (a bus through the region or a line on it). */
export const bindingSel = (b: ElementBinding, model: Model | null): Sel | null => elementSel(b.kind, b.element_id, model);

/** Where the element that stops a deferred project shows on the map; null for the GSP boundary or an intake reason. */
export const chainSel = (c: Chain, model: Model | null): Sel | null => elementSel(c.element_kind, c.element_id, model);

/** A weak link's element from its key ("line:12", "trafo:3", "voltage:19" for a bus); null for an island or a collapse. */
export function clusterSel(c: Cluster, model: Model | null): Sel | null {
  if (c.kind !== "weak_link") return null;
  const [kind, id] = c.key.split(":");
  return elementSel(kind, id, model);
}

/** "50 rows · 2027–2035 · worst 132.6%". */
export function clusterLine(c: Cluster): string {
  const parts = [plural(c.n_rows, "row"), yearSpan(c.years)];
  if (c.worst != null) parts.push(`worst ${figureText(c.worst, c.unit)}`);
  return parts.join(" · ");
}

/** What the engine's probe of a deferred project found, in words (empty until it is studied): what fits at its own
 * busbar, whether parallel circuits would carry its full MW, and the best move. Every figure is the probe's. */
export function chainStudy(c: Chain): string[] {
  if (!c.studied) return [];
  const out: string[] = [];
  if (c.fits_mw != null) out.push(`fits ${c.fits_mw} MW at its own busbar`);
  if (c.chain_connects != null) out.push(c.chain_connects ? "parallel circuits reach its full MW" : "parallel circuits do not reach its full MW");
  if (c.best_move) out.push(`best move: ${c.best_move.name} takes ${c.best_move.mw} MW${c.best_move.case ? ` at ${caseLabel(c.best_move.case)}` : ""}`);
  return out;
}
