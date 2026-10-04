import { describe, expect, it } from "vitest";

import type { Model, OptimizeResult, Outage, OutageStudy, YearResult } from "../types";
import { indexModel } from "./derive";
import {
  INITIAL_DRAFT,
  curtailedName,
  draftBody,
  draftHint,
  outageChipTag,
  outageLine,
  outageTag,
  repoweredNotes,
  stepFactor,
  windowSummary,
  windowView,
  windowsByYear,
} from "./maintenance";
import { item } from "./test-fixtures";

const model: Model = {
  buses: [
    { bus_id: 1, name: "BOSTON 33kV MAIN1", vn_kv: 33, lon: 0, lat: 53 },
    { bus_id: 2, name: "BICKER FEN 132kV", vn_kv: 132, lon: -0.2, lat: 52.9 },
    { bus_id: 3, name: "KIRTON 33kV", vn_kv: 33, lon: -0.05, lat: 52.9 },
  ],
  lines: [
    { line_id: 10, line_name: "BOS-BKF", rating_a: 600, voltage_kv: 132, from_bus: 1, to_bus: 2, from_lon: 0, from_lat: 53, to_lon: -0.2, to_lat: 52.9 },
    { line_id: 11, line_name: "KIR-BOS", rating_a: 400, voltage_kv: 33, from_bus: 3, to_bus: 1, from_lon: -0.05, from_lat: 52.9, to_lon: 0, to_lat: 53 },
  ],
  transformers: [
    { trafo_id: 5, name: "T5", sn_mva: 45, hv_bus: 2, lv_bus: 1, hv_kv: 132, lv_kv: 33, hv_name: "BICKER FEN 132kV", hv_lon: -0.2, hv_lat: 52.9, lv_lon: 0, lv_lat: 53 },
  ],
  loads: [],
  generators: [{ request_id: "EX-3000", bus_id: 2, rating_mw: 50, technology: "wind", applicant: "Wind farm", lon: -0.2, lat: 52.9 }],
};
const ix = indexModel(model);

const out = (over: Partial<Outage> = {}): Outage => ({
  outage_id: "o", element_kind: "line", element_id: "10", season: "Summer", year: 2030, weeks: 4, kind: "outage",
  work: "maintenance", repower: null, factor: null, ...over,
});

const study = (over: Partial<OutageStudy> = {}): OutageStudy => ({
  outage_id: "o", year: 2030, cases: ["summer_min"], ok: true, violations: [], worst_line_loading_pct: 71, worst_trafo_loading_pct: 40,
  gsp_export_mw: 0, message: "", work: "maintenance", with_ids: [], verdict: "feasible", demand_at_risk_mw: 0, curtailment: [],
  curtailed_mw: 0, n1_during: null, after: "the element returns as it was", ...over,
});

const year = (y: number, studies: OutageStudy[]): YearResult => ({
  year: y, growth: 1, energised: [], accepted: [], worst_line_loading_pct: 50, worst_trafo_loading_pct: 40, min_vm_pu: 0.97,
  max_vm_pu: 1.03, overloaded_line_ids: [], line_loading: {}, bus_vm: {}, voltage_violation_bus_ids: [], gsp_export_mw: 200,
  gsp_import_mw: 0, gsp_limit_mw: 527, n1_cases: ["winter_peak"], n1_screened: 30, n1_violations: [], trafo_loading: {}, outage_studies: studies,
});

const result = (studied: string[], studies: OutageStudy[] = []): OptimizeResult => ({
  params: { growth_2030: 1.08, growth_2035: 1.35, scenario: "ht", w_readiness: 0.5, w_need: 0.35, w_strategic: 0.15 },
  run_key: "k",
  queue: [], phases: {}, years: studies.length ? { "2030": year(2030, studies) } : {}, years_total: 10,
  studied: { outage_ids: studied, reinforcements: [], schedule: {} }, justification: "", snapshot_id: "s", branch_id: "br",
});

const ctx = (r: OptimizeResult | null, outages: Outage[] = [out()]) => ({ result: r, ix, outages, queue: [item({ request_id: "CR-2060", applicant: "Fen Solar" })] });

describe("draftBody", () => {
  const sel = { kind: "line" as const, id: 10 };
  it("sends only the fields each work takes", () => {
    expect(draftBody(sel, { ...INITIAL_DRAFT, kind: "derate" })).toMatchObject({ work: "maintenance", kind: "derate", repower: null, factor: null, element_id: "10" });
    expect(draftBody(sel, { ...INITIAL_DRAFT, work: "replacement", kind: "derate" })).toMatchObject({ work: "replacement", kind: "outage", repower: null, factor: null });
    expect(draftBody(sel, { ...INITIAL_DRAFT, work: "repowering", repower: "uprate", factor: 1.75 })).toMatchObject({ kind: "outage", repower: "uprate", factor: 1.75 });
    expect(draftBody(sel, { ...INITIAL_DRAFT, work: "repowering", repower: "add_parallel", factor: 1.75 })).toMatchObject({ repower: "add_parallel", factor: null });
  });
  it("steps the uprate factor in quarters between 1.25x and 4x", () => {
    expect(stepFactor(1.5, 1)).toBe(1.75);
    expect(stepFactor(1.25, -1)).toBe(1.25);
    expect(stepFactor(4, 1)).toBe(4);
  });
  it("hints what is studied and what happens after, per work", () => {
    expect(draftHint({ ...INITIAL_DRAFT, season: "Winter" }, "line")).toBe("Studied at winter peak with the branch demand profile. Studied out of service during the window. Back as it was after it.");
    expect(draftHint({ ...INITIAL_DRAFT, work: "repowering", factor: 2, year: 2029 }, "line")).toContain("From 2030 the later years are solved with it back at 2x its rating");
    expect(draftHint({ ...INITIAL_DRAFT, work: "repowering", repower: "add_parallel" }, "gen")).toContain("back with a second unit");
    expect(draftHint({ ...INITIAL_DRAFT, work: "repowering", year: 2035 }, "line")).toContain("after the last plan year");
  });
});

describe("tags and lines", () => {
  it("reads the work on the map, the roadmap and in a row", () => {
    expect(outageTag(out())).toBe("OUT · Summer");
    expect(outageTag(out({ kind: "derate" }))).toBe("50% · Summer");
    expect(outageTag(out({ work: "repowering", repower: "uprate", factor: 1.5 }))).toBe("REPOWER · Summer");
    expect(outageChipTag(out({ work: "replacement" }))).toBe("RPL");
    expect(outageLine(out({ work: "repowering", repower: "uprate", factor: 1.5 }))).toBe("Summer 2030 · 4 weeks · repowering, uprate to 1.5x");
    expect(outageLine(out({ work: "repowering", repower: "add_parallel", element_kind: "gen" }))).toContain("add a second unit");
  });
});

describe("windowView", () => {
  it("says not studied until a run covers it, and solving until its year lands", () => {
    expect(windowView(out(), ctx(result([])))).toMatchObject({ state: "unstudied", chip: null, lines: ["Not studied yet. Re-run to see the effect."] });
    expect(windowView(out(), ctx(result(["o"])))).toMatchObject({ state: "solving", chip: null });
  });
  it("reads a feasible window with its worst loadings and the N-1 screen during it", () => {
    const v = windowView(out(), ctx(result(["o"], [study({ n1_during: { cases: ["winter_peak"], screened: 12, findings: 0, violations: [], second_fault_at_risk_mw: 0, worst: "" } })])));
    expect(v.chip).toEqual({ label: "Feasible", c: "#5ee6a8" });
    expect(v.lines[0]).toBe("Within limits in summer min. Worst line 71%, worst transformer 40%.");
    expect(v.lines[1]).toBe("A second fault during the window: 12 faults screened, none breaches a limit.");
  });
  it("names curtailed fleet generators and projects with MW and case, and the breach it clears", () => {
    const s = study({
      ok: false, verdict: "curtailment",
      violations: [{ type: "line", element_id: 11, value: 118, limit: 100, message: "", case: "summer_min" }],
      curtailment: [{ id: "EX-3000", name: "wind", mw: 12, case: "summer_min" }, { id: "CR-2060", name: "solar", mw: 5.5, case: "summer_min" }],
    });
    const v = windowView(out(), ctx(result(["o"], [s])));
    expect(v.chip?.label).toBe("Curtailment");
    expect(v.lines[0]).toBe("Holds the limits if generation is constrained: Wind farm (EX-3000) by 12 MW at summer min, Fen Solar (CR-2060) by 5.5 MW at summer min.");
    expect(v.lines[1]).toBe("Summer min: Kirton to Boston 33 kV reaches 118%.");
  });
  it("reads demand at risk, the windows studied with it, a second fault and what a repowering leaves", () => {
    const other = out({ outage_id: "p", element_kind: "trafo", element_id: "5" });
    const s = study({
      ok: false, verdict: "demand_at_risk", demand_at_risk_mw: 14.2, with_ids: ["p"], work: "repowering",
      n1_during: {
        cases: ["summer_min"], screened: 10, findings: 2, second_fault_at_risk_mw: 30, worst: "line 10 out as well cuts off another 30.0 MW at summer minimum demand",
        violations: [
          { outage_type: "line", outage_id: 10, outage_name: "", case: "summer_min", type: "islanded", element_id: 1, value: 31, message: "line 10 out islands 31.0 MW of demand at 2 bus(es) at summer minimum demand" },
          { outage_type: "line", outage_id: 10, outage_name: "", case: "summer_min", type: "line", element_id: 11, value: 150, message: "line 11 overloaded at 150% of its summer rating at summer minimum demand" },
        ],
      },
      after: "from 2031, line 10 comes back at 1.5x its rating",
    });
    const o = out({ work: "repowering", repower: "uprate", factor: 1.5 });
    const v = windowView(o, ctx(result(["o"], [s]), [o, other]));
    expect(v.chip?.label).toBe("Demand at risk");
    expect(v.lines).toEqual([
      "14.2 MW of demand at risk during the window.",
      "Studied together with the other summer 2030 work: Bicker Fen 132/33 kV transformer (full outage).",
      "A second fault during the window: 2 findings, 30 MW at risk.",
      "Boston to Bicker Fen 132 kV out islands 31.0 MW of demand at 2 bus(es) at summer minimum demand.",
      "Boston to Bicker Fen 132 kV out as well: Kirton to Boston 33 kV overloaded at 150% of its summer rating at summer minimum demand.",
      "After the window: from 2031, Boston to Bicker Fen 132 kV comes back at 1.5x its rating.",
    ]);
  });
  it("falls back to a name by technology for an unknown id", () => {
    expect(curtailedName({ id: "EX-9", name: "solar" }, ix, [])).toBe("Solar PV EX-9");
  });
});

describe("the outages tab and the element card", () => {
  it("groups windows by year and season, and sums them up by verdict", () => {
    const a = out({ outage_id: "a", season: "Autumn" });
    const b = out({ outage_id: "b", season: "Winter" });
    const c = out({ outage_id: "c", year: 2028 });
    expect(windowsByYear([a, b, c]).map((g) => `${g.year}:${g.rows.map((r) => r.outage_id).join("")}`)).toEqual(["2028:c", "2030:ba"]);
    const r = result(["a", "b"], [study({ outage_id: "a", verdict: "curtailment" }), study({ outage_id: "b", verdict: "demand_at_risk" })]);
    expect(windowSummary([a, b, c], r)).toBe("3 windows · 1 needs curtailment · 1 puts demand at risk · 1 not studied yet");
    expect(windowSummary([a], null)).toBe("1 window · 1 not studied yet");
  });
  it("notes a repowering from the year after its window", () => {
    const o = out({ year: 2029, work: "repowering", repower: "uprate", factor: 2 });
    expect(repoweredNotes({ kind: "line", id: 10 }, [o], 2029)).toEqual([]);
    expect(repoweredNotes({ kind: "line", id: 10 }, [o], 2031)).toEqual(["Repowered in 2029: back at 2x its rating from 2030."]);
    expect(repoweredNotes({ kind: "line", id: 11 }, [o], 2031)).toEqual([]);
  });
});
