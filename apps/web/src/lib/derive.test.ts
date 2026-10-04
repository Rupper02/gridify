import { describe, expect, it } from "vitest";

import type { Branch, Model, OptimizeResult, Outage, RegistryItem, YearResult } from "../types";
import {
  branchHue,
  busPlace,
  changedProjects,
  effYearOf,
  gspTicks,
  indexModel,
  lineName,
  nameElements,
  preliminaryOf,
  queueGroups,
  roadmapYears,
  staleness,
  worstElement,
  yearResultFor,
} from "./derive";
import { item } from "./test-fixtures";


const year = (y: number, over: Partial<YearResult> = {}): YearResult => ({
  year: y, growth: 1, energised: [], accepted: [], worst_line_loading_pct: 50, worst_trafo_loading_pct: 40, min_vm_pu: 0.97,
  max_vm_pu: 1.03, overloaded_line_ids: [], line_loading: {}, bus_vm: {}, voltage_violation_bus_ids: [], gsp_export_mw: 200,
  gsp_import_mw: 0, gsp_limit_mw: 527, n1_cases: ["winter_peak"], n1_screened: 30, n1_violations: [], trafo_loading: {}, outage_studies: [], ...over,
});

const result = (over: Partial<OptimizeResult> = {}): OptimizeResult => ({
  params: { growth_2030: 1.08, growth_2035: 1.35, scenario: "ht", w_readiness: 0.5, w_need: 0.35, w_strategic: 0.15 },
  run_key: "k",
  queue: [], phases: {}, years: {}, years_total: 10, studied: { outage_ids: [], reinforcements: [], schedule: {} },
  justification: "", snapshot_id: "s", branch_id: "br", ...over,
});

const model: Model = {
  buses: [
    { bus_id: 1, name: "BOSTON 33kV MAIN1", vn_kv: 33, lon: 0, lat: 53 },
    { bus_id: 2, name: "BICKER FEN 132kV", vn_kv: 132, lon: -0.2, lat: 52.9 },
    { bus_id: 3, name: "KIRTON 33kV", vn_kv: 33, lon: -0.05, lat: 52.9 },
    { bus_id: 4, name: "KIRTON 11kV", vn_kv: 11, lon: -0.05, lat: 52.9 },
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

describe("effYearOf", () => {
  it("uses the operator's year over the recommendation, and only for accepted projects", () => {
    expect(effYearOf(item({ recommended_year: 2028 }))).toBe(2028);
    expect(effYearOf(item({ recommended_year: 2028, scheduled_year: 2027 }))).toBe(2027);
    expect(effYearOf(item({ status: "Deferred", recommended_year: 2028 }))).toBeNull();
  });
});

describe("yearResultFor", () => {
  it("returns the stored year, else the nearest solved one while a run is still solving", () => {
    const r = result({ years: { "2030": year(2030), "2026": year(2026) } });
    expect(yearResultFor(r, 2030)).toMatchObject({ exact: true, yr: { year: 2030 } });
    expect(yearResultFor(r, 2029)).toMatchObject({ exact: false, yr: { year: 2030 } });
    expect(yearResultFor(r, 2027).yr?.year).toBe(2026);
    expect(yearResultFor(result(), 2030).yr).toBeNull();
  });
});

describe("branchHue", () => {
  const b = (id: string, at: string) => ({ branch_id: id, created_at: at }) as Branch;
  it("gives main silver and branches the hues in creation order", () => {
    const bs = [b("main", "0"), b("br-2", "2"), b("br-1", "1")];
    expect(branchHue(bs, "main")).toBe("#c9d6e8");
    expect(branchHue(bs, "br-1")).toBe("#7ce3ff");
    expect(branchHue(bs, "br-2")).toBe("#ff9f7a");
  });
});

describe("staleness", () => {
  const branch = { scenario: "ht" };
  const o = (id: string): Outage => ({ outage_id: id, element_kind: "line", element_id: "10", season: "Summer", year: 2029, weeks: 4, kind: "outage", work: "maintenance", repower: null, factor: null });
  it("is fresh when the result covers the branch as it stands", () => {
    expect(staleness(result(), branch, [], [], 0).stale).toBe(false);
  });
  it("flags a profile change, an unstudied outage, a reinforcement, a schedule change and preliminary projects", () => {
    expect(staleness(result(), { scenario: "ee" }, [], [], 0).text).toContain("solved on Standard demand. The branch is now set to High");
    expect(staleness(result(), branch, [o("a")], [], 0).text).toContain("1 new maintenance window has not been studied");
    expect(staleness(result({ studied: { outage_ids: ["a"], reinforcements: [], schedule: {} } }), branch, [o("a")], [], 0).stale).toBe(false);
    expect(staleness(result(), branch, [], [{ reinforcement_id: "r", kind: "gsp", element_id: 0, action: "add_parallel", factor: 2, label: "" }], 0).stale).toBe(true);
    expect(staleness(result({ queue: [item({ scheduled_year: 2030 })] }), branch, [], [], 0).text).toContain("energisation year changed");
    expect(staleness(result(), branch, [], [], 2).text).toContain("2 preliminary projects are not in this run");
  });
});

describe("queue groups and preliminary", () => {
  it("groups Preliminary, Phase 1, Phase 2, Deferred in that order, skipping empty ones", () => {
    const q = [item({ request_id: "a" }), item({ request_id: "b", status: "Deferred" })];
    const pre = [{ request_id: "CR-2060", applicant: "", bus_id: 1, technology: "battery", rating_mw: 20, readiness_score: 0.5, status: "valid" as const }];
    expect(queueGroups(q, pre).map((g) => g.g.key)).toEqual(["prelim", "Phase1", "Deferred"]);
    expect(queueGroups(q, []).find((g) => g.g.key === "Phase1")?.g.meta).toBe("1 · 10 MW");
  });
  it("treats projects added since the run as preliminary until a run includes them", () => {
    const added = [{ request_id: "a" }, { request_id: "new" }] as never[];
    expect(preliminaryOf(added, result({ queue: [item({ request_id: "a" })] })).map((x: { request_id: string }) => x.request_id)).toEqual(["new"]);
  });
});

describe("roadmapYears", () => {
  it("puts each accepted project in its energisation year, preliminary ones in their requested year, and outages", () => {
    const r = result({
      queue: [item({ request_id: "p1", recommended_year: 2028 }), item({ request_id: "p2", status: "Phase2", recommended_year: 2032, rating_mw: 30 }), item({ request_id: "d", status: "Deferred" })],
      years: { "2028": year(2028) },
    });
    const pre = [{ request_id: "pre", commissioning_year: 2029, technology: "solar" }] as never[];
    const outs: Outage[] = [{ outage_id: "o", element_kind: "line", element_id: "10", season: "Summer", year: 2029, weeks: 4, kind: "outage", work: "maintenance", repower: null, factor: null }];
    const ys = roadmapYears(r, pre, outs, new Set(["p2"]), () => "BOS-BKF");
    const y = (n: number) => ys.find((x) => x.y === n)!;
    expect(y(2028).chips.map((c) => c.id)).toEqual(["p1"]);
    expect(y(2029).chips.map((c) => `${c.kind}:${c.id}`)).toEqual(["prelim:pre", "outage:BOS-BKF"]);
    expect(y(2029).chips[1]).toMatchObject({ work: "maintenance", verdict: null }); // not studied: no verdict yet
    expect(y(2032).chips[0]).toMatchObject({ id: "p2", branchOnly: true });
    expect(y(2031).mw).toBe(10);
    expect(y(2035).mw).toBe(40);
    expect(y(2028).solved).toBe(true);
    expect(y(2029).solved).toBe(false);
  });
});

describe("naming and readings", () => {
  it("names lines by the places they join and finds the worst element", () => {
    expect(lineName(ix, 10)).toBe("Boston to Bicker Fen 132 kV");
    const w = worstElement(year(2030, { line_loading: { "10": 61, "11": 88 }, trafo_loading: { "5": 92 } }), ix);
    expect(w).toEqual({ pct: 92, name: "Bicker Fen 132/33 kV transformer", sel: { kind: "trafo", id: 5 } });
  });
  it("fills the GSP gauge, the last ticks amber", () => {
    const t = gspTicks(500, 527);
    expect(t.length).toBe(24);
    expect(t.filter((c) => c !== "rgba(255,255,255,0.09)").length).toBe(23);
    expect(t[22]).toBe("#ffc36b");
    expect(t[0]).toBe("#7ce3ff");
  });
});


describe("stored projects against the shown run", () => {
  it("counts the projects whose connection point, rating, import or year changed since the run", () => {
    const q = [item({ request_id: "A", bus_id: 1, rating_mw: 10 }), item({ request_id: "B", bus_id: 2, rating_mw: 20, commissioning_year: 2030 })];
    const row = (over: Partial<RegistryItem>): RegistryItem => ({ request_id: "A", applicant: "", bus_id: 1, technology: "solar", rating_mw: 10, readiness_score: 0.5, status: "valid", ...over });
    expect(changedProjects([row({}), row({ request_id: "B", bus_id: 2, rating_mw: 20, commissioning_year: 2030 })], q)).toBe(0);
    expect(changedProjects([row({ bus_id: 7 })], q)).toBe(1); // moved
    expect(changedProjects([row({ rating_mw: 5 }), row({ request_id: "B", bus_id: 2, rating_mw: 20, commissioning_year: 2031 })], q)).toBe(2); // resized, re-dated
    expect(changedProjects([row({ request_id: "C", bus_id: 9 })], q)).toBe(0); // not in the run: preliminary, not changed
    expect(staleness(result({ queue: q }), { scenario: "ht" }, [], [], 0, 1).text).toContain("1 project changed");
  });
});

describe("place names", () => {
  it("names a coded busbar after its neighbour, and names elements in engine text", () => {
    const m2: Model = { ...model, buses: [...model.buses, { bus_id: 9, name: "BOST1_MAIN1", vn_kv: 132, lon: 0, lat: 53 }],
      lines: [...model.lines, { line_id: 12, line_name: "X", rating_a: 600, voltage_kv: 132, from_bus: 9, to_bus: 1, from_lon: 0, from_lat: 53, to_lon: 0, to_lat: 53 }] };
    const ix2 = indexModel(m2);
    expect(busPlace(ix2, 9)).toBe("Boston");
    expect(nameElements("Overloads transformer 5 to 102%", ix2)).toBe("Overloads Bicker Fen 132/33 kV transformer to 102%");
    expect(nameElements("Overloads line 10 to 120%", ix2)).toBe("Overloads Boston to Bicker Fen 132 kV to 120%");
    expect(nameElements("bus 3 sags", ix2)).toBe("bus 3 (Kirton) sags");
    expect(nameElements("line 999 is unknown", ix2)).toBe("line 999 is unknown");
  });
});

describe("parallel circuits", () => {
  it("number circuits that share a route so lists never repeat a name", () => {
    const twin = { ...model.lines[0], line_id: 99 };
    const ix2 = indexModel({ ...model, lines: [...model.lines, twin] });
    expect(lineName(ix2, 10)).toBe("Boston to Bicker Fen 132 kV, circuit 1");
    expect(lineName(ix2, 99)).toBe("Boston to Bicker Fen 132 kV, circuit 2");
    expect(lineName(ix2, 11)).toBe("Kirton to Boston 33 kV");
  });
});
