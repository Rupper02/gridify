import { describe, expect, it } from "vitest";

import type { OptimizeResult, PhaseResult, QueueItem } from "../types";
import { alertGroupsFor, bindingSets, buildProjList, effYearOf, filterSortQueue, isStale, readyFromForm, timelineRollup, violationCount } from "./derive";

const item = (over: Partial<QueueItem>): QueueItem => ({
  rank: 1, request_id: "X", bus_id: 1, technology: "solar", rating_mw: 10, readiness_score: 0.5, strategic_fit: 0.5,
  grid_need: 0.5, rank_score: 0.5, status: "Phase1", reason: null, commissioning_year: null, recommended_year: 2028,
  worst_line_loading_pct: null, readiness_rationale: "", lon: 0, lat: 52, applicant: "", scheduled_year: null,
  against_recommendation: false, ...over,
});

describe("effYearOf", () => {
  it("uses the operator's year over the recommendation, and only for accepted projects", () => {
    expect(effYearOf(item({ recommended_year: 2028 }))).toBe(2028);
    expect(effYearOf(item({ recommended_year: 2028, scheduled_year: 2027 }))).toBe(2027);
    expect(effYearOf(item({ status: "Deferred", recommended_year: 2028 }))).toBeNull();
    expect(effYearOf(item({ status: "Rejected", scheduled_year: 2027 }))).toBeNull();
  });
});

describe("buildProjList + timelineRollup", () => {
  const q = [
    item({ request_id: "online", recommended_year: 2028 }),
    item({ request_id: "new", recommended_year: 2030 }),
    item({ request_id: "future", status: "Phase2", recommended_year: 2033 }),
    item({ request_id: "early", recommended_year: 2030, scheduled_year: 2027 }),
    item({ request_id: "deferred", status: "Deferred", reason: { type: "line", element_id: 5, value: 120, message: "", kind: "grid", element: { line_id: 5 }, short: "", why: "", action: "" } }),
    item({ request_id: "nowhere", lon: null, lat: null }),
  ];
  it("classifies online / new / ghost / blocked and flags against-recommendation", () => {
    const by = Object.fromEntries(buildProjList(q, 2030).map((p) => [p.x.request_id, p]));
    expect(by.online.online && !by.online.isNew && by.online.variant === "p1").toBe(true);
    expect(by.new.isNew && by.new.label.endsWith("online 2030")).toBe(true);
    expect(by.future.future && by.future.variant === "ghost" && by.future.label).toContain("planned 2033");
    expect(by.early.offRec).toBe(true);
    expect(by.deferred.blocked && by.deferred.variant === "def").toBe(true);
    expect(by.nowhere).toBeUndefined(); // no coordinates -> not drawn
  });
  it("rolls up what is online by the year and what is new that year; deferred never counts", () => {
    const t = timelineRollup(q, 2030);
    expect(t.online.map((x) => x.request_id).sort()).toEqual(["early", "new", "nowhere", "online"]);
    expect(t.fresh.map((x) => x.request_id)).toEqual(["new"]);
    expect(t.onlineMw).toBe(40);
    expect(timelineRollup(q, 2026).online).toEqual([]);
  });
  it("collects the binding elements of deferred projects only", () => {
    const { bindLines, bindBuses } = bindingSets(q);
    expect([...bindLines]).toEqual([5]);
    expect(bindBuses.size).toBe(0);
  });
});

describe("filterSortQueue", () => {
  const q = [
    item({ request_id: "B", rank: 2, rating_mw: 5, readiness_score: 0.9, applicant: "Acme" }),
    item({ request_id: "A", rank: 1, rating_mw: 50, readiness_score: 0.3, status: "Deferred" }),
    item({ request_id: "C", rank: null, rating_mw: 1, status: "Rejected", bus_id: 77 }),
  ];
  it("filters by status and free text, and sorts by the chosen column", () => {
    expect(filterSortQueue(q, "All", "", "rank", 1).map((x) => x.request_id)).toEqual(["A", "B", "C"]); // null rank last
    expect(filterSortQueue(q, "Deferred", "", "rank", 1).map((x) => x.request_id)).toEqual(["A"]);
    expect(filterSortQueue(q, "All", "acme", "rank", 1).map((x) => x.request_id)).toEqual(["B"]);
    expect(filterSortQueue(q, "All", "bus 77", "rank", 1).map((x) => x.request_id)).toEqual(["C"]);
    expect(filterSortQueue(q, "All", "", "mw", -1).map((x) => x.request_id)).toEqual(["A", "B", "C"]);
    expect(filterSortQueue(q, "All", "", "status", 1).map((x) => x.request_id)).toEqual(["B", "A", "C"]);
  });
});

describe("alertGroupsFor", () => {
  const phase = (over: Partial<PhaseResult>): PhaseResult => ({
    accepted: [], worst_line_loading_pct: 50, worst_trafo_loading_pct: 50, min_vm_pu: 0.98, max_vm_pu: 1.02,
    overloaded_line_ids: [], line_loading: {}, bus_vm: {}, voltage_violation_bus_ids: [], gsp_export_mw: 0, gsp_import_mw: 0, gsp_limit_mw: null,
    n1_screened: 0, n1_violations: [], ...over,
  });
  const r: OptimizeResult = {
    params: { growth_2030: 1.08, growth_2035: 1.35, scenario: "ht", w_readiness: 0.5, w_need: 0.35, w_strategic: 0.15 },
    queue: [item({ request_id: "D", status: "Deferred", reason: { type: "trafo", element_id: 3, value: 110, message: "m", kind: "grid", element: null, short: "Overloads transformer 3", why: "w", action: "a" } })],
    phases: {
      "2030": phase({ line_loading: { 1: 95, 2: 50 } }),
      "2035": phase({
        overloaded_line_ids: [1], line_loading: { 1: 120 }, voltage_violation_bus_ids: [9], bus_vm: { 9: 1.12 },
        n1_screened: 27, n1_violations: [{ outage_type: "line", outage_id: 5, outage_name: "L1", type: "voltage", element_id: 75, value: 0.928, message: "m" }],
      }),
    },
    justification: "", snapshot_id: "s", branch_id: "main",
  };
  it("groups violations, grid deferrals and near-limit lines, and counts what needs attention", () => {
    const groups = alertGroupsFor(r, 1.08, 1.35);
    expect(groups.map((g) => g.key)).toEqual(["viol", "n1", "dg", "watch"]);
    expect(groups[0].items.map((a) => a.title)).toEqual(["Line 1 overloaded · 120%", "Voltage breach at bus 9"]);
    expect(groups[1].items[0].title).toBe("Line 5 out → bus 75 at 0.928 pu"); // the N-1 screen is reported, not a gate
    expect(groups[3].items[0].title).toBe("Line 1 at 95%"); // 2030: 95% is within 12% of the rating
    expect(violationCount(groups)).toBe(3);
    expect(alertGroupsFor(null, 1, 1)).toEqual([]);
  });
});

describe("small helpers", () => {
  it("isStale flags a changed branch, growth or candidate count", () => {
    const lp = { g30: 1.08, g35: 1.35, scenario: "ht", branch: "main", n: 3 };
    expect(isStale(lp, "main", 1.08, 1.35, 3)).toBe(false);
    expect(isStale(lp, "br-1", 1.08, 1.35, 3)).toBe(true);
    expect(isStale(lp, "main", 1.1, 1.35, 3)).toBe(true);
    expect(isStale(lp, "main", 1.08, 1.35, 4)).toBe(true);
    expect(isStale(null, "main", 1.08, 1.35, 3)).toBe(false);
  });
  it("readyFromForm sums the evidence over a 0.1 floor", () => {
    expect(readyFromForm({ land: false, planning: false, finance: false })).toBe(0.1);
    expect(readyFromForm({ land: true, planning: true, finance: true })).toBe(1);
    expect(readyFromForm({ land: true, planning: false, finance: false })).toBe(0.4);
  });
});
