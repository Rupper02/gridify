// Shared fixtures for the unit tests (not a test file itself).

import type { QueueItem } from "../types";
import type { Plan } from "./plan";

/** A plan as `GET /forecasts` serves it today. */
export const plan: Plan = { years: [2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033, 2034, 2035], phase1: 2030, phase2: 2035 };

export const item = (over: Partial<QueueItem>): QueueItem => ({
  rank: 1, request_id: "X", bus_id: 1, technology: "solar", rating_mw: 10, readiness_score: 0.5, strategic_fit: 0.5,
  grid_need: 0.5, rank_score: 0.5, status: "Phase1", reason: null, commissioning_year: null, recommended_year: 2028,
  worst_line_loading_pct: null, readiness_rationale: "", lon: 0, lat: 52, applicant: "", scheduled_year: null,
  against_recommendation: false, ...over,
});
