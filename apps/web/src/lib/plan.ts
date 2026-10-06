// The plan's years and its two phases, as the engine defines them (GET /forecasts: `plan_years`, and the
// policy `horizons` Phase 1 and Phase 2 end at). The planner never writes a plan year itself: every year
// bound, phase title and roadmap band reads from here.

import type { Horizon, Status } from "../types";

export interface Plan {
  years: number[];
  /** The year Phase 1 ends (Clean Power 2030). */
  phase1: number;
  /** The year Phase 2 ends (the strategic window). */
  phase2: number;
}

export type Phase = Extract<Status, "Phase1" | "Phase2">;
/** Where a year sits in the plan: the first year is today's grid, then each phase up to its horizon. */
export type Lens = "today" | Phase;

export const planOf = (years: number[], horizons: Horizon[]): Plan => ({ years, phase1: horizons[0].year, phase2: horizons[1].year });

export const firstYear = (p: Plan): number => p.years[0];
export const lastYear = (p: Plan): number => p.years[p.years.length - 1];
export const clampYear = (p: Plan, y: number): number => Math.min(lastYear(p), Math.max(firstYear(p), y));

export const lensOf = (p: Plan, y: number): Lens => (y <= firstYear(p) ? "today" : y <= p.phase1 ? "Phase1" : "Phase2");

/** "Phase 1 · by 2030", "Phase 2 · 2031 to 2035". */
export const phaseTitle = (p: Plan, phase: Phase): string =>
  phase === "Phase1" ? `Phase 1 · by ${p.phase1}` : `Phase 2 · ${p.phase1 + 1} to ${p.phase2}`;

const OTHER_TITLE: Record<Exclude<Status, Phase> | "Prelim", string> = {
  Deferred: "Deferred",
  Rejected: "Not assessed · application to complete",
  Prelim: "Preliminary · unranked",
};
/** A planning state in full: a phase with its years, or the state's name. */
export const statusTitle = (p: Plan, s: Status | "Prelim"): string =>
  s === "Phase1" || s === "Phase2" ? phaseTitle(p, s) : OTHER_TITLE[s];
