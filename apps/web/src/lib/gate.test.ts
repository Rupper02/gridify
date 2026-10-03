import { describe, expect, it } from "vitest";

import type { Finding, GateFinding, MergeCheck, Model, Outage } from "../types";
import { findingSel, findingTitle, findingsByYear, firstBlocker, gateState, gateText, gateTitle, needsConfirm, openCounts, refusedCheck } from "./gate";

const gf = (over: Partial<GateFinding> = {}): GateFinding => ({
  kind: "new_overload", level: "blocker", year: 2031, case: null, element_kind: "line", element_id: "12", value: 104, base_value: 90,
  limit: 100, message: "line 12 newly over its rating in 2031: 104% on this branch, 90% on main.", finding_fingerprint: "abc", ...over,
});

const check = (over: Partial<MergeCheck> = {}, verdict: Partial<MergeCheck["verdict"]> = {}): MergeCheck => ({
  branch_id: "br-1", into: "main", branch_status: "open", fresh: true, stale_reasons: [], requires_acknowledgement: false,
  verdict: { ok: true, blockers: [], warnings: [], context: [], years_compared: [2026, 2027], summary: "Ready", ...verdict },
  evidence: {}, checked_at: "2026-10-03T00:00:00Z", ...over,
});

const fresh = { stale: false, text: "" };

describe("gateState", () => {
  it("follows the branch, the client's staleness, the run, then the server's verdict", () => {
    expect(gateState(null, fresh, false, false).state).toBe("closed");
    expect(gateState(check(), fresh, true, true).state).toBe("checking");
    expect(gateState(null, fresh, true, false).state).toBe("checking");
    const s = gateState(check(), { stale: true, text: "An energisation year changed." }, true, false);
    expect(s.state).toBe("stale");
    expect(s.headline).toContain("energisation year");
    const srv = gateState(check({ fresh: false, stale_reasons: ["the plan years have not been solved"] }), fresh, true, false);
    expect(srv.state).toBe("stale");
    expect(srv.headline).toContain("plan years");
  });
  it("is blocked, warnings or ready by the verdict and words the count", () => {
    const b = gateState(check({}, { ok: false, blockers: [gf(), gf({ element_id: "13" })] }), fresh, true, false);
    expect(b.state).toBe("blocked");
    expect(b.headline).toBe("Blocked: 2 problems this branch introduces.");
    const w = gateState(check({}, { warnings: [gf({ kind: "against_recommendation", level: "warning" })] }), fresh, true, false);
    expect(w.state).toBe("warnings");
    expect(w.headline).toContain("1 warning to acknowledge");
    expect(gateState(check(), fresh, true, false)).toEqual({ state: "ready", headline: "Ready to merge: no new problem in any plan year." });
  });
});

describe("blockers, confirmation and titles", () => {
  it("picks the first blocker and knows when warnings need a confirmation", () => {
    const blocked = check({}, { ok: false, blockers: [gf({ element_id: "7" }), gf()] });
    expect(firstBlocker(blocked)?.element_id).toBe("7");
    expect(firstBlocker(check())).toBeNull();
    expect(needsConfirm(check({}, { warnings: [gf({ level: "warning" })] }))).toBe(true);
    expect(needsConfirm(blocked)).toBe(false);
    expect(needsConfirm(null)).toBe(false);
  });
  it("names elements in the gate's sentences and titles its kinds", () => {
    const ix = {
      line: new Map([[12, { line_id: 12, from_bus: 1, to_bus: 2, voltage_kv: 132 }]]), trafo: new Map(), bus: new Map(), gen: new Map(),
      place: new Map([[1, "Boston"], [2, "Spalding"]]), lineNames: new Map([[12, "Boston to Spalding 132 kV"]]),
    } as never;
    expect(gateText(gf(), ix)).toContain("Boston to Spalding 132 kV newly over its rating");
    expect(gateText(gf(), null)).toContain("line 12");
    expect(gateTitle("behind_base")).toBe("Behind main");
    expect(gateTitle("something_new")).toBe("something new");
  });
});

const finding = (over: Partial<Finding> = {}): Finding => ({
  finding_id: "f-1", branch_id: "br-1", fingerprint: "fp", source: "engine", kind: "overload", severity: "breach", year: 2031, case: null,
  element_kind: "line", element_id: "12", value: 104, limit: 100, message: "line 12 at 104% of its rating in 2031 (worst case)", context: {},
  status: "open", note: "", evidence_kind: "result_cache", evidence_ref: "k", evidence: {}, snapshot_id: "s", engine: "e",
  first_seen_at: "t", last_seen_at: "t", acked_at: null, resolved_at: null, ...over,
});

describe("findings", () => {
  it("titles kinds, reading alerts and works from their context", () => {
    expect(findingTitle(finding())).toBe("Over its rating");
    expect(findingTitle(finding({ kind: "alert", context: { alert_kind: "firm_capacity" } }))).toBe("Demand above firm capacity");
    expect(findingTitle(finding({ kind: "work", context: { verdict: "curtailment" } }))).toBe("Planned work: Curtailment");
    expect(findingTitle(finding({ kind: "deferred", context: { grid: false } }))).toBe("Deferred at intake");
    expect(findingTitle(finding({ kind: "deferred", context: { grid: true } }))).toBe("Deferred");
  });
  it("groups plan-wide findings first, then by year, breaches first", () => {
    const groups = findingsByYear([
      finding({ finding_id: "a", year: 2032, severity: "warn", kind: "n1" }),
      finding({ finding_id: "b", year: null, kind: "deferred", severity: "warn" }),
      finding({ finding_id: "c", year: 2032, severity: "breach" }),
      finding({ finding_id: "d", year: 2030 }),
    ]);
    expect(groups.map((g) => g.year)).toEqual([null, 2030, 2032]);
    expect(groups[2].rows.map((r) => r.finding_id)).toEqual(["c", "a"]);
  });
  it("points at the element, the project, the region, or the region a bus sits in", () => {
    const model = {
      regions: [{ region_id: "boston", buses: [5, 6] }],
      lines: [{ line_id: 3, from_bus: 9, to_bus: 10 }],
    } as unknown as Model;
    const outages: Outage[] = [{ outage_id: "mw-1", element_kind: "trafo", element_id: "4", season: "Summer", year: 2030, weeks: 4, kind: "outage", work: "maintenance", repower: null, factor: null, created_at: "" } as Outage];
    expect(findingSel(finding(), model, outages)).toEqual({ kind: "line", id: 12 });
    expect(findingSel(finding({ element_kind: "project", element_id: "CR-1" }), model, outages)).toEqual({ kind: "project", id: "CR-1" });
    expect(findingSel(finding({ element_kind: "region", element_id: "boston" }), model, outages)).toEqual({ kind: "region", id: "boston" });
    expect(findingSel(finding({ element_kind: "bus", element_id: "6" }), model, outages)).toEqual({ kind: "region", id: "boston" });
    expect(findingSel(finding({ element_kind: "bus", element_id: "10" }), model, outages)).toEqual({ kind: "line", id: 3 });
    expect(findingSel(finding({ element_kind: "bus", element_id: "99" }), model, outages)).toBeNull();
    expect(findingSel(finding({ element_kind: "outage", element_id: "mw-1" }), model, outages)).toEqual({ kind: "trafo", id: 4 });
    expect(findingSel(finding({ element_kind: "gsp", element_id: "gsp" }), model, outages)).toBeNull();
  });
  it("counts the open findings by severity", () => {
    expect(openCounts([finding(), finding({ severity: "warn" }), finding({ status: "acknowledged" }), finding({ severity: "info" })])).toEqual({ open: 3, breach: 1, warn: 1 });
  });
});

describe("refusedCheck", () => {
  it("turns a refused merge's body into a check, and ignores anything else", () => {
    const verdict = { ok: false, blockers: [gf({ kind: "stale", message: "Re-run it." })], warnings: [], context: [], years_compared: [], summary: "" };
    const stale = refusedCheck({ code: "blocked", fresh: false, verdict }, null, "br-1");
    expect(stale?.fresh).toBe(false);
    expect(stale?.stale_reasons).toEqual(["Re-run it."]);
    const warned = refusedCheck({ code: "warnings_unacknowledged", fresh: true, verdict: { ...verdict, ok: true, blockers: [] } }, check(), "br-1");
    expect(warned?.requires_acknowledgement).toBe(true);
    expect(warned?.into).toBe("main");
    expect(refusedCheck("branch is 'merged', not open", null, "br-1")).toBeNull();
    expect(refusedCheck({ code: "blocked" }, null, "br-1")).toBeNull();
  });
});
