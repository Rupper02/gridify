import { describe, expect, it } from "vitest";

import type { Finding, GateFinding, MergeCheck, Model, Outage } from "../types";
import { findingSel, gateState, refusedCheck } from "./gate";

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
const settled = { inProgress: false, problem: null };
const solving = { inProgress: true, problem: null };

describe("gateState", () => {
  it("follows the branch, the run, the client's staleness, then the server's verdict", () => {
    expect(gateState(null, fresh, false, settled).state).toBe("closed");
    expect(gateState(check(), fresh, true, solving).state).toBe("checking");
    expect(gateState(null, fresh, true, settled).state).toBe("checking");
    expect(gateState(null, fresh, true, settled, "timed out").state).toBe("failed");
    const unfinished = gateState(check(), fresh, true, { inProgress: false, problem: "The run failed: boom" });
    expect(unfinished.state).toBe("unfinished");
    expect(unfinished.headline).toContain("did not finish");
    const s = gateState(check(), { stale: true, text: "An energisation year changed." }, true, settled);
    expect(s.state).toBe("stale");
    expect(s.headline).toContain("energisation year");
    const srv = gateState(check({ fresh: false, stale_reasons: ["the plan years have not been solved"] }), fresh, true, settled);
    expect(srv.state).toBe("stale");
    expect(srv.headline).toContain("plan years");
  });
  it("is blocked, warnings or ready by the verdict and words the count", () => {
    const b = gateState(check({}, { ok: false, blockers: [gf(), gf({ element_id: "13" })] }), fresh, true, settled);
    expect(b.state).toBe("blocked");
    expect(b.headline).toBe("Blocked: 2 problems this branch introduces.");
    const w = gateState(check({}, { warnings: [gf({ kind: "against_recommendation", level: "warning" })] }), fresh, true, settled);
    expect(w.state).toBe("warnings");
    expect(w.headline).toContain("1 warning to acknowledge");
    expect(gateState(check(), fresh, true, settled)).toEqual({ state: "ready", headline: "Ready to merge: no new problem in any plan year." });
  });
});


const finding = (over: Partial<Finding> = {}): Finding => ({
  finding_id: "f-1", branch_id: "br-1", fingerprint: "fp", source: "engine", kind: "overload", severity: "breach", year: 2031, case: null,
  element_kind: "line", element_id: "12", value: 104, limit: 100, message: "line 12 at 104% of its rating in 2031 (worst case)", context: {},
  status: "open", note: "", evidence_kind: "result_cache", evidence_ref: "k", evidence: {}, snapshot_id: "s", engine: "e",
  first_seen_at: "t", last_seen_at: "t", acked_at: null, resolved_at: null, ...over,
});

describe("findings", () => {
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
});

describe("refusedCheck", () => {
  it("turns a refused merge's body into a check, and ignores anything else", () => {
    const verdict = { ok: false, blockers: [gf({ kind: "stale", message: "Re-run it." })], warnings: [], context: [], years_compared: [], summary: "" };
    const stale = refusedCheck({ code: "blocked", fresh: false, verdict }, null, "br-1", "br-0");
    expect(stale?.fresh).toBe(false);
    expect(stale?.stale_reasons).toEqual(["Re-run it."]);
    const warned = refusedCheck({ code: "warnings_unacknowledged", fresh: true, verdict: { ...verdict, ok: true, blockers: [] } }, check(), "br-1", "br-0");
    expect(warned?.requires_acknowledgement).toBe(true);
    expect(warned?.into).toBe("main");
    expect(refusedCheck("branch is 'merged', not open", null, "br-1", "br-0")).toBeNull();
    expect(refusedCheck({ code: "blocked" }, null, "br-1", "br-0")).toBeNull();
  });
});
