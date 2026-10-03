import { describe, expect, it } from "vitest";

import { C } from "../theme";
import type { Diff, Outage, WorkDelta, YearDelta } from "../types";
import {
  deltaTag,
  diffColor,
  diffMapFor,
  flaggedYears,
  verdictOnBranch,
  verdictOnMain,
  workTitle,
  worksInOrder,
  yearDeltaFor,
  yearEffect,
} from "./diff";

const yd = (over: Partial<YearDelta> = {}): YearDelta => ({
  year: 2032, worst_line_base: 90, worst_line_head: 90, worst_line_delta: 0, worst_trafo_base: 80, worst_trafo_head: 80,
  worst_trafo_delta: 0, min_vm_delta: 0, max_vm_delta: 0, gsp_export_base: 200, gsp_export_head: 200, gsp_export_delta: 0,
  gsp_limit_mw: 527, n1_findings_base: 3, n1_findings_head: 3, n1_findings_delta: 0, n1_new: [], n1_cleared: [],
  newly_overloaded_line_ids: [], cleared_line_ids: [], newly_overloaded_trafo_ids: [], cleared_trafo_ids: [],
  top_line_deltas: [], top_trafo_deltas: [], energised_only_head: [], energised_only_base: [], ...over,
});

const work = (over: Partial<WorkDelta> = {}): WorkDelta => ({
  outage_id: "mw-1", year: 2032, work: "maintenance", with_ids: [], verdict_on_main: "feasible", verdict_on_branch: "curtailment",
  curtailed_mw_main: 0, curtailed_mw_branch: 40, demand_at_risk_mw_main: 0, demand_at_risk_mw_branch: 0, change: "worse",
  consequence: "Feasible on main, but needs 40.0 MW of curtailment on this branch.", message: "", ...over,
});

const diff = (over: Partial<Diff> = {}): Diff => ({
  base_label: "", head_label: "", headline: {}, projects: [], phases: [], years: {}, works: [], base_branch: "main",
  head_branch: "br-1", narration: "", ...over,
});

const names = { line: (id: number) => `Line ${id}`, trafo: (id: number) => `T${id}` };

describe("year-aware diff", () => {
  it("picks the viewed year's delta, or null when it is not solved on both plans", () => {
    const d = diff({ years: { "2032": yd() } });
    expect(yearDeltaFor(d, 2032)?.year).toBe(2032);
    expect(yearDeltaFor(d, 2033)).toBeNull();
    expect(yearDeltaFor(null, 2032)).toBeNull();
  });

  it("maps changed lines and transformers for the map, skipping noise", () => {
    const m = diffMapFor(yd({
      top_line_deltas: [
        { element_id: 1, base_pct: 90, head_pct: 104, delta: 14, crossed: "newly_overloaded" },
        { element_id: 2, base_pct: 40, head_pct: 40.2, delta: 0.2, crossed: "unchanged" },
      ],
      top_trafo_deltas: [{ element_id: 7, base_pct: 50, head_pct: 60, delta: 10, crossed: "worsened" }],
    }));
    expect([...m.lines.keys()]).toEqual([1]);
    expect(m.trafos.get(7)).toEqual({ delta: 10, head: 60 });
    expect(deltaTag(m.lines.get(1)!)).toBe("+14% · 104%");
    expect(deltaTag({ delta: -6.4, head: 50 })).toBe("-6%");
    expect(diffColor(m.lines.get(1)!)).toBe(C.red);
    expect(diffColor(m.trafos.get(7)!)).toBe(C.amber);
    expect(diffMapFor(null).lines.size).toBe(0);
  });

  it("says what changes in the year, naming lines and transformers", () => {
    const items = yearEffect(yd({
      newly_overloaded_line_ids: [1],
      cleared_trafo_ids: [7],
      top_line_deltas: [{ element_id: 1, base_pct: 90, head_pct: 104, delta: 14, crossed: "newly_overloaded" }],
      top_trafo_deltas: [{ element_id: 8, base_pct: 50, head_pct: 92, delta: 42, crossed: "worsened" }],
      gsp_export_delta: 93, gsp_export_head: 293, n1_findings_delta: 2, n1_findings_head: 5, energised_only_head: ["ECR-1"],
    }), names);
    const text = items.map((x) => x.text);
    expect(text).toContain("Line 1 newly over 100% in 2032 (90% to 104%).");
    expect(text).toContain("T7 back within its rating in 2032.");
    expect(text).toContain("T8 rises from 50% to 92% in 2032.");
    expect(text).toContain("Peak GSP export rises from 200 to 293 MW (limit 527 MW).");
    expect(text).toContain("The N-1 screen finds 2 second-fault problems more (3 to 5).");
    expect(text).toContain("In service on this branch only: ECR-1.");
    expect(items[0].tone).toBe("bad");
    expect(items.find((x) => x.text.startsWith("T7"))?.tone).toBe("good");
    expect(text.every((t) => !t.includes("—"))).toBe(true); // no em-dashes in UI copy
    expect(yearEffect(yd(), names)).toEqual([]);
  });

  it("flags years with a new overload, more N-1 findings or a window made worse", () => {
    const d = diff({
      years: { "2029": yd({ year: 2029, newly_overloaded_trafo_ids: [3] }), "2030": yd({ year: 2030 }), "2031": yd({ year: 2031, n1_findings_delta: 1 }) },
      works: [work({ year: 2033 }), work({ outage_id: "mw-2", year: 2034, change: "better" })],
    });
    expect([...flaggedYears(d)].sort()).toEqual([2029, 2031, 2033]);
    expect(flaggedYears(null).size).toBe(0);
  });
});

describe("planned works in the diff", () => {
  it("states each verdict with its MW", () => {
    const w = work();
    expect(verdictOnMain(w)).toBe("Feasible");
    expect(verdictOnBranch(w)).toBe("Curtailment 40 MW");
    expect(verdictOnMain(work({ verdict_on_main: null }))).toBe("Not studied");
    expect(verdictOnBranch(work({ verdict_on_branch: "demand_at_risk", demand_at_risk_mw_branch: 12.34 }))).toBe("Demand at risk 12.3 MW");
  });

  it("lists the viewed year's windows first, then the ones made worse", () => {
    const ws = [work({ outage_id: "a", year: 2029, change: "unchanged" }), work({ outage_id: "b", year: 2034, change: "worse" }), work({ outage_id: "c", year: 2031, change: "better" })];
    expect(worksInOrder(ws, 2031).map((w) => w.outage_id)).toEqual(["c", "b", "a"]);
  });

  it("titles a window by its work and element", () => {
    const o: Outage = { outage_id: "mw-1", element_kind: "gen", element_id: "EX-9", season: "Summer", year: 2032, weeks: 4, kind: "outage", work: "maintenance", repower: null, factor: null };
    expect(workTitle(work({ work: "repowering" }), o, null)).toBe("Repowering · gen EX-9");
    expect(workTitle(work(), undefined, null)).toBe("Maintenance · mw-1");
  });
});
