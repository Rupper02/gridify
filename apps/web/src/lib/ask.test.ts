import { describe, expect, it } from "vitest";

import type { Outage, Reason } from "../types";
import { suggestedQuestions } from "./ask";
import { item } from "./test-fixtures";

const grid: Reason = { type: "line", kind: "grid", element: { line_id: 77 }, short: "Overloads line 77", why: "", action: "", message: "", element_id: 77, value: 155, limit: 100, case: "summer_min" } as unknown as Reason;
const outage = (year: number): Outage => ({ outage_id: `mw-${year}`, element_kind: "gen", element_id: "EX-1", season: "Summer", year, weeks: 8, kind: "outage", work: "maintenance", repower: null, factor: null });

describe("suggested questions", () => {
  it("lead with the first project deferred on the grid, then the GSP and hosting questions", () => {
    const q = [item({ request_id: "CR-1", status: "Phase1" }), item({ request_id: "CR-2061", status: "Deferred", reason: grid })];
    const out = suggestedQuestions({ q, sel: null, outages: [], year: 2030, ix: null, connectKv: 33, boundary: true });
    expect(out[0]).toBe("How could CR-2061 connect? What would it take?");
    expect(out).toContain("What limits the GSP export by the end of the plan?");
    expect(out.length).toBeLessThanOrEqual(5);
  });
  it("ask about the selection: a deferred project's options, a line's or generator's best window", () => {
    const q = [item({ request_id: "CR-2061", status: "Deferred", reason: grid })];
    expect(suggestedQuestions({ q, sel: { kind: "project", id: "CR-2061" }, outages: [], year: 2030, ix: null, connectKv: 33, boundary: true })).toContain("Why is CR-2061 deferred, and what are its options?");
    expect(suggestedQuestions({ q: [], sel: { kind: "line", id: 77 }, outages: [], year: 2030, ix: null, connectKv: 33, boundary: true })[0]).toBe("When is the best window to take line 77 out for 4 weeks?");
    expect(suggestedQuestions({ q: [], sel: { kind: "gen", id: "EX-3001" }, outages: [], year: 2030, ix: null, connectKv: 33, boundary: true })[0]).toContain("generator EX-3001");
  });
  it("ask about the planned works of the viewed year only", () => {
    expect(suggestedQuestions({ q: [], sel: null, outages: [outage(2032)], year: 2032, ix: null, connectKv: 33, boundary: true })[0]).toContain("planned works in 2032");
    expect(suggestedQuestions({ q: [], sel: null, outages: [outage(2032)], year: 2030, ix: null, connectKv: 33, boundary: true }).some((s) => s.includes("planned works"))).toBe(false);
  });
  it("never repeat a question and never exceed five", () => {
    const q = [item({ request_id: "CR-2061", status: "Deferred", reason: grid })];
    const out = suggestedQuestions({ q, sel: { kind: "project", id: "CR-2061" }, outages: [outage(2030)], year: 2030, ix: null, connectKv: 33, boundary: true });
    expect(new Set(out).size).toBe(out.length);
    expect(out.length).toBeLessThanOrEqual(5);
  });
});

