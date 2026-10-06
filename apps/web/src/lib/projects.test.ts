import { describe, expect, it } from "vitest";

import type { Assumption, ImportReport, Project } from "../types";
import { assumptionGroups, assumptionText, limitsFromForm, mainIdOf, projectOf, reportLines } from "./projects";

const project = (over: Partial<Project> = {}): Project => ({
  project_id: "prj-1", name: "IEEE 9-bus", source_kind: "pandapower_json", snapshot_id: "abc", created_at: "2026-10-03T10:00:00Z", main_id: "prj-1-main",
  builtin: false, file_name: "case9.json", meta: null, report: null,
  capabilities: { boundary: false, regions: false, registry: false, editions: false, summer_case: false, crs: "synthetic" }, ...over,
});

describe("projects", () => {
  it("knows each project's plan of record and falls back to main", () => {
    const ps = [project({ project_id: "nged-bickerfen", main_id: "main", builtin: true }), project()];
    expect(mainIdOf(ps, "nged-bickerfen")).toBe("main");
    expect(mainIdOf(ps, "prj-1")).toBe("prj-1-main");
    expect(mainIdOf([], "anything")).toBe("");
    expect(projectOf(ps, "prj-1")?.name).toBe("IEEE 9-bus");
    expect(projectOf(ps, "nope")).toBeNull();
  });
  it("reads an import report into lines", () => {
    const r: ImportReport = {
      ok: true, errors: [], warnings: ["the network has 2 separate parts, each with its own infeed or out of service", "the base case already breaks a limit: line 3 at 104%"],
      counts: { buses: 9, lines: 9, transformers: 0, loads: 3, generators: 2, slacks: 1 }, islands: 2, converged: true, feasible: false, reason: "line 3 at 104%", cases: ["winter_peak"], assumptions: [],
    };
    const lines = reportLines(r);
    expect(lines[0]).toEqual({ tone: "good", text: "9 buses · 9 lines · 0 transformers · 3 loads · 2 generators" });
    expect(lines.map((l) => l.tone)).toEqual(["good", "warn", "warn", "warn", "warn"]);
    expect(lines.some((l) => l.text.includes("winter peak only"))).toBe(true);
    expect(reportLines(null)).toEqual([]);
    expect(reportLines({ ...r, ok: false, converged: false, errors: ["no slack"], cases: [] })[0].tone).toBe("bad");
  });
  it("groups assumptions by source and words them with their counts", () => {
    const rows: Assumption[] = [
      { key: "unrated_lines", message: "Lines the file left unrated", source: "file", element_kind: "line", count: 2, element_ids: [0, 4] },
      { key: "gsp_limit_entered", message: "Export limit entered", source: "operator-entered", element_kind: null, count: null, element_ids: [] },
      { key: "gb_voltage_bands", message: "GB bands assumed", source: "engine-default", element_kind: null, count: null, element_ids: [] },
    ];
    const groups = assumptionGroups(rows);
    expect(groups.map((g) => [g.label, g.rows.length])).toEqual([["Not in the file", 1], ["Entered at import", 1], ["Planning assumption", 1]]);
    expect(assumptionText(rows[0])).toBe("Lines the file left unrated (2 lines)");
    expect(assumptionText(rows[2])).toBe("GB bands assumed");
  });
  it("keeps only the limits that were entered and rejects a non-number", () => {
    expect(limitsFromForm({ gsp_export_limit_mw: " 527 ", gsp_name: "Bicker Fen", min_demand_factor: "", summer_rating_ratio: "" })).toEqual({ limits: { gsp_export_limit_mw: "527", gsp_name: "Bicker Fen" }, error: null });
    expect(limitsFromForm({ min_demand_factor: "half" }).error).toContain("must be a number");
    expect(limitsFromForm({})).toEqual({ limits: {}, error: null });
  });
});
