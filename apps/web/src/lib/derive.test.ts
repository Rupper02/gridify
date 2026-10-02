import { describe, expect, it } from "vitest";

import type { OptimizeResult, PhaseResult, QueueItem } from "../types";
import { alertGroupsFor, bindingSets, buildProjList, effYearOf, filterSortQueue, interpolateGrowthForYear, isStale, readyFromForm, timelineRollup, violationCount } from "./derive";

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
    expect(by.deferred).toBeUndefined(); // deferred: flagged elsewhere, never drawn at any year
    expect(buildProjList(q, 2026).some((p) => p.x.status === "Deferred")).toBe(false);
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
      "2028": phase({ line_loading: { 1: 95, 2: 50 } }),
      "2032": phase({
        overloaded_line_ids: [1], line_loading: { 1: 120 }, voltage_violation_bus_ids: [9], bus_vm: { 9: 1.12 },
        n1_screened: 27, n1_violations: [{ outage_type: "line", outage_id: 5, outage_name: "L1", type: "voltage", element_id: 75, value: 0.928, message: "m" }],
      }),
    },
    justification: "", snapshot_id: "s", branch_id: "main",
  };
  it("groups violations, grid deferrals and near-limit lines for the given phase, and counts what needs attention", () => {
    const groups2032 = alertGroupsFor(r, "2032", 1.25);
    expect(groups2032.map((g) => g.key)).toEqual(["viol", "n1", "dg"]);
    expect(groups2032[0].items.map((a) => a.title)).toEqual(["Line 1 overloaded · 120%", "Voltage breach at bus 9"]);
    expect(groups2032[1].items[0].title).toBe("Line 5 out → bus 75 at 0.928 pu"); // the N-1 screen is reported, not a gate
    expect(violationCount(groups2032)).toBe(4); // 1 overload + 1 voltage + 1 N-1 + 1 deferred = 4
    
    const groups2028 = alertGroupsFor(r, "2028", 1.08);
    expect(groups2028.map((g) => g.key)).toEqual(["dg", "watch"]);
    expect(groups2028[1].items[0].title).toBe("Line 1 at 95%"); // 2028: 95% is within 12% of the rating
    expect(violationCount(groups2028)).toBe(1); // only the deferred project
    
    expect(alertGroupsFor(null, "2030", 1.0)).toEqual([]);
  });
  
  it("fails if alerts badge count ignores N-1 violations", () => {
    // Regression: N-1 violations must be included in the alerts badge count
    const groups = alertGroupsFor(r, "2032", 1.25);
    const n1Group = groups.find(g => g.key === "n1");
    expect(n1Group).toBeDefined();
    expect(n1Group!.items.length).toBeGreaterThan(0);
    
    const count = violationCount(groups);
    // If N-1 is excluded, count would be 3 (overload + voltage + deferred)
    // With N-1 included, count is 4
    expect(count).toBe(4);
    expect(count).toBeGreaterThan(3); // must be > count without N-1
  });
});

describe("interpolateGrowthForYear", () => {
  it("returns 1.0 before base year", () => {
    expect(interpolateGrowthForYear(2024, 1.08, 1.35)).toBe(1.0);
    expect(interpolateGrowthForYear(2026, 1.08, 1.35)).toBe(1.0);
  });
  
  it("interpolates linearly between base and 2030", () => {
    const g2027 = interpolateGrowthForYear(2027, 1.08, 1.35);
    expect(g2027).toBeGreaterThan(1.0);
    expect(g2027).toBeLessThan(1.08);
    
    const g2028 = interpolateGrowthForYear(2028, 1.08, 1.35);
    expect(g2028).toBeGreaterThan(g2027);
    expect(g2028).toBeLessThan(1.08);
  });
  
  it("returns exact anchor values at 2030 and 2035", () => {
    expect(interpolateGrowthForYear(2030, 1.08, 1.35)).toBe(1.08);
    expect(interpolateGrowthForYear(2035, 1.08, 1.35)).toBe(1.35);
  });
  
  it("interpolates linearly between 2030 and 2035", () => {
    const g2032 = interpolateGrowthForYear(2032, 1.08, 1.35);
    expect(g2032).toBeGreaterThan(1.08);
    expect(g2032).toBeLessThan(1.35);
    // 2032 is 2/5 of the way from 2030 to 2035
    expect(g2032).toBeCloseTo(1.08 + (1.35 - 1.08) * 0.4, 4);
  });
  
  it("holds at 2035 value after 2035", () => {
    expect(interpolateGrowthForYear(2040, 1.08, 1.35)).toBe(1.35);
    expect(interpolateGrowthForYear(2050, 1.08, 1.35)).toBe(1.35);
  });
  
  it("fails if 2028 shows the 2035 growth factor", () => {
    // Regression test: 2028 must not use 1.35 (the 2035 factor)
    const g2028 = interpolateGrowthForYear(2028, 1.08, 1.35);
    expect(g2028).not.toBe(1.35);
    expect(g2028).toBeLessThan(1.08);
  });
  
  it("handles single-year phase keys without crashing or inventing 2030/2035 data", () => {
    // Single-year study result with only "2028" phase key
    const singleYearResult: OptimizeResult = {
      params: { growth_2030: 1.08, growth_2035: 1.35, scenario: "ht", w_readiness: 0.5, w_need: 0.35, w_strategic: 0.15 },
      queue: [item({ request_id: "P1", status: "Phase1", recommended_year: 2028 })],
      phases: {
        "2028": phase({
          accepted: ["P1"],
          overloaded_line_ids: [3],
          line_loading: { 3: 105, 4: 92 },
          voltage_violation_bus_ids: [7],
          bus_vm: { 7: 0.92 },
          n1_violations: [{ outage_type: "trafo", outage_id: 2, outage_name: "T2", type: "line", element_id: 10, value: 110, message: "overload" }],
        }),
      },
      justification: "", snapshot_id: "s", branch_id: "main",
    };
    
    // Should not throw
    const groups = alertGroupsFor(singleYearResult, 1.08, 1.35);
    
    // Should have violations from the 2028 phase
    expect(groups.length).toBeGreaterThan(0);
    const violGroup = groups.find(g => g.key === "viol");
    expect(violGroup).toBeDefined();
    expect(violGroup!.items.length).toBe(2); // 1 overload + 1 voltage violation
    
    // Tags should be "2028", not "2030" or "2035"
    expect(violGroup!.items.every(a => a.tag === "2028")).toBe(true);
    
    // Should report line 3 and bus 7 from 2028 phase
    expect(violGroup!.items.some(a => a.title.includes("Line 3"))).toBe(true);
    expect(violGroup!.items.some(a => a.title.includes("bus 7"))).toBe(true);
    
    // N-1 group should also have 2028 tag
    const n1Group = groups.find(g => g.key === "n1");
    expect(n1Group?.items[0].tag).toBe("N-1 · 2028");
    
    // Watch group should have 2028 tag for line 4 at 92%
    const watchGroup = groups.find(g => g.key === "watch");
    expect(watchGroup?.items[0].tag).toBe("2028");
    expect(watchGroup?.items[0].title).toBe("Line 4 at 92%");
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
