import { describe, expect, it } from "vitest";

import type { Model, WindowOption, YearResult } from "../types";
import { indexModel } from "./derive";
import {
  elementSuggestions,
  factorFromText,
  findElement,
  maintAnswer,
  maintSlots,
  outageBody,
  rangeFromText,
  scheduledOn,
  searchProgress,
  searchRequest,
  startMaint,
  weeksFromText,
  windowFromText,
  windowLine,
  withWindows,
  workFromText,
} from "./maintCopilot";
import type { MaintCtx } from "./maintCopilot";

const bus = (bus_id: number, name: string, vn_kv: number) => ({ bus_id, name, vn_kv, lon: 0, lat: 52 });
const model: Model = {
  buses: [bus(1, "BOSTON 132kV", 132), bus(2, "SPALDING 132kV", 132), bus(3, "BOSTON 33kV", 33)],
  lines: [
    { line_id: 16, line_name: "", rating_a: 500, voltage_kv: 132, from_bus: 1, to_bus: 2, from_lon: 0, from_lat: 0, to_lon: 0, to_lat: 0 },
    { line_id: 4, line_name: "", rating_a: 300, voltage_kv: 33, from_bus: 3, to_bus: 3, from_lon: 0, from_lat: 0, to_lon: 0, to_lat: 0 },
  ],
  transformers: [{ trafo_id: 30, name: "BOSTON T1", sn_mva: 90, hv_bus: 1, lv_bus: 3, hv_kv: 132, lv_kv: 33, hv_name: "BOSTON 132kV", hv_lon: 0, hv_lat: 0, lv_lon: 0, lv_lat: 0 }],
  loads: [],
  generators: [{ request_id: "EX-3000", bus_id: 3, rating_mw: 20, technology: "solar", applicant: "Fen Solar", lon: 0, lat: 0 }],
};
const ix = indexModel(model);
const yr = { line_loading: { 16: 91.2, 4: 40 }, trafo_loading: { 30: 77 } } as unknown as YearResult;
const ctx: MaintCtx = {
  branchName: "spring-works",
  suggestions: elementSuggestions(ix, yr, null),
  findElement: (t) => findElement(model, ix, t),
};
const run = (...answers: string[]) => answers.reduce((st, a) => maintAnswer(st, a, ctx), startMaint(ctx));
const last = (st: { messages: { text: string }[] }) => st.messages[st.messages.length - 1];

const opt = (over: Partial<WindowOption>): WindowOption => ({
  rank: 1, year: 2029, season: "Summer", verdict: "feasible", curtailed_mw: 0, demand_at_risk_mw: 0, n1_findings: 0,
  worst_line_loading_pct: 71.4, worst_trafo_loading_pct: 50, message: "", ...over,
});

describe("maintenance copilot: elements", () => {
  it("suggests the most loaded elements in the year, the selected one first", () => {
    expect(ctx.suggestions.map((o) => [o.kind, o.id])).toEqual([["line", "16"], ["trafo", "30"], ["line", "4"]]);
    expect(ctx.suggestions[0].label).toBe("Boston to Spalding 132 kV (line 16) · 91%");
    const withSel = elementSuggestions(ix, yr, { kind: "trafo", id: 30 });
    expect(withSel[0]).toMatchObject({ kind: "trafo", id: "30" });
    expect(withSel[0].label).toContain("(selected)");
    expect(withSel.filter((o) => o.kind === "trafo")).toHaveLength(1);
  });
  it("finds typed elements by number, id and name", () => {
    expect(findElement(model, ix, "line 16")).toMatchObject({ kind: "line", id: "16" });
    expect(findElement(model, ix, "T30")).toMatchObject({ kind: "trafo", id: "30" });
    expect(findElement(model, ix, "transformer 30")).toMatchObject({ kind: "trafo", id: "30" });
    expect(findElement(model, ix, "ex-3000")).toMatchObject({ kind: "gen", id: "EX-3000" });
    expect(findElement(model, ix, "4")).toMatchObject({ kind: "line", id: "4" });
    expect(findElement(model, ix, "Spalding")).toMatchObject({ kind: "line", id: "16" });
    expect(findElement(model, ix, "Fen Solar")).toMatchObject({ kind: "gen", id: "EX-3000" });
    expect(findElement(model, ix, "line 999")).toBeNull();
    expect(findElement(model, ix, "Atlantis")).toBeNull();
  });
});

describe("maintenance copilot: parsing", () => {
  it("reads works, factors, weeks, windows and ranges from free text", () => {
    expect(workFromText("we need to repower it")).toBe("repowering");
    expect(workFromText("Like-for-like replacement")).toBe("replacement");
    expect(workFromText("routine maintenance")).toBe("maintenance");
    expect(workFromText("paint it blue")).toBeNull();
    expect([factorFromText("1.5x"), factorFromText("x2"), factorFromText("+50%"), factorFromText("7"), factorFromText("1")]).toEqual([1.5, 2, 1.5, null, null]);
    expect([weeksFromText("6 weeks"), weeksFromText("2 months"), weeksFromText("40"), weeksFromText("soon")]).toEqual([6, 8, null, null]);
    expect(windowFromText("fall of 2031")).toEqual({ season: "Autumn", year: 2031 });
    expect(windowFromText("summer 2040")).toEqual({ season: "Summer", year: null });
    expect(rangeFromText("Find the best window")).toEqual([2026, 2035]);
    expect(rangeFromText("best window between 2031 and 2028")).toEqual([2028, 2031]);
    expect(rangeFromText("best window from 2029")).toEqual([2029, 2035]);
    expect(rangeFromText("best window before 2030")).toEqual([2026, 2030]);
  });
});

describe("maintenance copilot: the conversation", () => {
  it("walks maintenance to a best-window search with the request the engine needs", () => {
    const st = run(ctx.suggestions[0].label, "Maintenance", "Derated to 50%", "6 weeks", "Find the best window between 2028 and 2031");
    expect(st.step).toBe("searching");
    expect(last(st)).toMatchObject({ loading: true });
    expect(searchRequest(st)).toEqual({
      element_kind: "line", element_id: "16", work: "maintenance", kind: "derate", repower: null, factor: null, weeks: 6, years: [2028, 2031],
    });
    expect(maintSlots(st).find((x) => x.key === "window")).toMatchObject({ value: "searching…", current: true });
    // a further answer while searching changes nothing
    expect(maintAnswer(st, "Summer 2029", ctx)).toBe(st);
  });
  it("asks how a repowering comes back, and the factor for an uprate", () => {
    const a = run("line 16", "Repowering");
    expect(a.step).toBe("repower");
    const b = maintAnswer(a, "Uprated", ctx);
    expect(b.step).toBe("factor");
    const c = run("line 16", "Repowering", "Uprated", "1.5x", "4");
    expect(c.step).toBe("when");
    expect(outageBody(c, "Summer", 2029)).toEqual({
      element_kind: "line", element_id: "16", work: "repowering", kind: "outage", repower: "uprate", factor: 1.5, weeks: 4, season: "Summer", year: 2029,
    });
    // "repower it with a parallel circuit" fills both answers at once; no kind or factor question
    const d = run("T30", "Repower with a parallel circuit");
    expect(d.step).toBe("weeks");
    expect(d).toMatchObject({ work: "repowering", repower: "add_parallel", kind: "outage" });
  });
  it("re-asks on answers it cannot use, and keeps the step", () => {
    const st = run("Atlantis");
    expect(st.step).toBe("element");
    expect(last(st).text).toContain("couldn't find that");
    const w = run("line 16", "Replacement", "40");
    expect(w.step).toBe("weeks");
    expect(last(w).text).toContain("between 1 and 26");
    const win = run("line 16", "Replacement", "4", "A specific season and year", "sometime");
    expect(win.step).toBe("window");
  });
  it("schedules a specific window directly, with a summary", () => {
    const st = run("line 16", "Replacement", "4", "Autumn 2030");
    expect(st).toMatchObject({ step: "done", season: "Autumn", year: 2030 });
    expect(last(st)).toMatchObject({ action: "schedule" });
    expect((last(st) as { summary?: [string, string][] }).summary).toContainEqual(["Window", "Autumn 2030"]);
    const done = scheduledOn(st, "Autumn", 2030, "spring-works", "High");
    expect(done.scheduled).toEqual(["Autumn 2030"]);
    expect(done.messages.some((m) => m.action === "schedule")).toBe(false);
    expect(last(done)).toMatchObject({ action: "run" });
    expect(last(done).text).toContain("Run on High demand");
  });
  it("shows the ranked windows from the engine, then accepts another window", () => {
    const st = searchProgress(run("line 16", "Maintenance", "Fully out", "4", "best"), "year 2029: 4 season(s)", 0.42);
    expect(last(st).text).toContain("(42%)");
    const opts = [opt({}), opt({ rank: 2, season: "Winter", verdict: "curtailment", curtailed_mw: 12.34, n1_findings: 2 })];
    const res = withWindows(st, opts, ctx);
    expect(res.step).toBe("results");
    expect(res.messages.some((m) => m.loading)).toBe(false);
    expect(last(res).text).toContain("1 of 2 windows keep every limit");
    expect((last(res) as { windows?: WindowOption[] }).windows).toHaveLength(2);
    expect(maintAnswer(res, "Spring 2031", ctx)).toMatchObject({ step: "done", season: "Spring", year: 2031 });
    expect(maintAnswer(res, "find again from 2032", ctx)).toMatchObject({ step: "searching", years: [2032, 2035] });
  });
  it("says each window in plain English from the engine's figures only", () => {
    expect(windowLine(opt({}))).toBe("Every limit holds, worst line 71%.");
    expect(windowLine(opt({ verdict: "curtailment", curtailed_mw: 12.34, n1_findings: 1 }))).toBe(
      "About 12.3 MW of generation constrained to hold the limits; 1 second-fault finding during the window.");
    expect(windowLine(opt({ verdict: "demand_at_risk", demand_at_risk_mw: 8 }))).toBe("8.0 MW of demand at risk.");
    expect(windowLine(opt({ verdict: "not_feasible" }))).toContain("stays breached");
  });
});
