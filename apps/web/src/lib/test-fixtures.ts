// Shared fixtures for the unit tests (not a test file itself).

import type { QueueItem } from "../types";

export const item = (over: Partial<QueueItem>): QueueItem => ({
  rank: 1, request_id: "X", bus_id: 1, technology: "solar", rating_mw: 10, readiness_score: 0.5, strategic_fit: 0.5,
  grid_need: 0.5, rank_score: 0.5, status: "Phase1", reason: null, commissioning_year: null, recommended_year: 2028,
  worst_line_loading_pct: null, readiness_rationale: "", lon: 0, lat: 52, applicant: "", scheduled_year: null,
  against_recommendation: false, ...over,
});
