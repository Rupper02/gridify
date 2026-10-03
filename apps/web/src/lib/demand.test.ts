import { describe, expect, it } from "vitest";

import type { Alert, Model, Region, RegionYear, YearResult } from "../types";
import {
  P2_CLASS,
  REGION_STATE,
  alertSummary,
  alertTitle,
  alertsFor,
  classMeaning,
  firmFill,
  haloRadius,
  labelOrder,
  outagePhrase,
  regionCentroid,
  regionFeatures,
  regionFigure,
  regionLevels,
  regionRows,
  LEVEL_LINE,
  regionSites,
} from "./demand";

const region = (over: Partial<Region>): Region => ({
  region_id: "R1", name: "Alpha", bsp: "BSP", level: "primary", buses: [1], firm_mw: 20, firm_mva: 21, base_demand_mw: 10,
  peak_demand_mw: 12, p2_class: "C", ...over,
});
const ry = (over: Partial<RegionYear>): RegionYear => ({
  region_id: "R1", name: "Alpha", bsp: "BSP", demand_mw: 15, modelled_mw: 14, firm_mw: 20, headroom_mw: 5, p2_class: "C",
  n1_at_risk_mw: 0, n1_outage: null, voltage_violation_bus_ids: [], worst_vm_pu: 1.0, worst_vm_limit_pu: 0.94,
  demand_room_mw: 5, ...over,
});
const alert = (over: Partial<Alert>): Alert => ({
  kind: "firm_capacity", level: "warn", region_id: "R1", year: 2030, value: 1, limit: 1, message: "", ...over,
});
const year = (regions: RegionYear[], alerts: Alert[]): YearResult => ({ year: 2030, regions, alerts }) as unknown as YearResult;
const buses = [
  { bus_id: 1, name: "A", vn_kv: 33, lon: 0, lat: 52 },
  { bus_id: 2, name: "A11", vn_kv: 11, lon: 0, lat: 52 },
  { bus_id: 3, name: "B", vn_kv: 33, lon: 1, lat: 53 },
];
const model = (regions: Region[]): Model => ({ buses, lines: [], transformers: [], loads: [], generators: [], regions });

describe("regionLevels", () => {
  it("keeps the worst level per region, whatever the order", () => {
    const m = regionLevels([alert({ level: "breach" }), alert({ level: "warn" }), alert({ region_id: "R2", level: "warn" })]);
    expect(m.get("R1")).toBe("breach");
    expect(m.get("R2")).toBe("warn");
    expect(regionLevels(undefined).size).toBe(0);
  });
});

describe("regionRows", () => {
  it("is unsolved before a run, using today's peak", () => {
    const [r] = regionRows(model([region({})]), null);
    expect(r.state).toBe("unsolved");
    expect(r.demand_mw).toBe(12);
    expect(r.year).toBeNull();
  });
  it("overlays the year's figures and colours by the worst alert", () => {
    const rows = regionRows(
      model([region({}), region({ region_id: "R2", buses: [3] }), region({ region_id: "R3", buses: [] })]),
      year([ry({}), ry({ region_id: "R2", demand_mw: 30 })], [alert({ level: "breach" })]),
    );
    expect(rows.map((r) => r.region_id)).toEqual(["R1", "R2"]); // no buses: not drawable
    expect(rows[0].state).toBe("breach");
    expect(rows[0].demand_mw).toBe(15);
    expect(rows[1].state).toBe("ok");
  });
  it("handles a model without regions", () => {
    expect(regionRows({}, null)).toEqual([]);
    expect(regionRows(null, null)).toEqual([]);
  });
});

describe("alertSummary", () => {
  it("counts by level and picks the region with the most breaches", () => {
    const yr = year(
      [ry({}), ry({ region_id: "R2" })],
      [alert({ level: "breach", region_id: "R2" }), alert({ level: "warn" }), alert({ level: "warn" }), alert({ level: "warn", region_id: "R2", kind: "headroom" })],
    );
    expect(alertSummary(yr)).toEqual({ breach: 1, warn: 3, worst: "R2" });
  });
  it("breaks ties on the least headroom", () => {
    const yr = year([ry({ headroom_mw: 4 }), ry({ region_id: "R2", headroom_mw: -2 })], [alert({}), alert({ region_id: "R2" })]);
    expect(alertSummary(yr).worst).toBe("R2");
  });
  it("is empty without a year", () => {
    expect(alertSummary(null)).toEqual({ breach: 0, warn: 0, worst: null });
  });
  it("filters a region's alerts", () => {
    const yr = year([], [alert({}), alert({ region_id: "R2" })]);
    expect(alertsFor(yr, "R2")).toHaveLength(1);
  });
});

describe("geometry", () => {
  const at = new Map(buses.map((b) => [b.bus_id, b]));
  it("merges buses on one site and averages the sites", () => {
    expect(regionSites([1, 2, 3, 99], at)).toEqual([[0, 52], [1, 53]]);
    expect(regionCentroid([1, 2, 3], at)).toEqual([0.5, 52.5]);
    expect(regionCentroid([99], at)).toBeNull();
  });
  it("draws one halo per site, severe regions last, selection flagged", () => {
    const fs = regionFeatures(
      model([region({ buses: [1, 2] }), region({ region_id: "R2", buses: [3] })]),
      year([ry({}), ry({ region_id: "R2" })], [alert({ level: "breach" })]),
      { kind: "region", id: "R2" },
    );
    expect(fs.map((f) => f.properties?.id)).toEqual(["R2", "R1"]);
    expect(fs[1].properties?.color).toBe(REGION_STATE.breach.c);
    expect(fs[0].properties?.sel).toBe(1);
  });
  it("grows the halo with demand, sub-linearly", () => {
    expect(haloRadius(100)).toBeGreaterThan(haloRadius(10));
    expect(haloRadius(400) - haloRadius(0)).toBeLessThan(4 * (haloRadius(100) - haloRadius(0)));
    expect(haloRadius(-5)).toBe(haloRadius(0));
  });
});

describe("outagePhrase", () => {
  it("words the engine's outage ids for nameElements", () => {
    expect(outagePhrase("trafo 4")).toBe("transformer 4");
    expect(outagePhrase("line 13")).toBe("line 13");
    expect(outagePhrase(null)).toBe("");
  });
});

describe("wording", () => {
  it("explains every engine class, and admits an unknown one", () => {
    ["A", "B", "C", "D", "E", "F"].forEach((c) => expect(P2_CLASS[c].meaning.length).toBeGreaterThan(10));
    expect(classMeaning("Z")).toMatch(/not recognised/);
  });
  it("titles alert kinds, with a fallback", () => {
    expect(alertTitle("n1_stranded")).toMatch(/one outage/);
    expect(alertTitle("new_check")).toBe("new check");
  });
  it("writes the map figure, and says when there is no firm figure", () => {
    expect(regionFigure({ demand_mw: 15.04, firm_mw: 20, p2_class: "C" })).toBe("15.0 / 20.0 MW · C");
    expect(regionFigure({ demand_mw: 0.5, firm_mw: 0, p2_class: "A" })).toMatch(/no firm figure/);
  });
  it("fills the firm bar and flags demand above it", () => {
    expect(firmFill(10, 20)).toMatchObject({ frac: 0.5, over: false });
    expect(firmFill(30, 20)).toMatchObject({ frac: 1, over: true });
    expect(firmFill(5, 0).frac).toBe(0);
  });
  it("labels breaches first", () => {
    const rows = regionRows(model([region({}), region({ region_id: "R2", buses: [3] })]), year([ry({}), ry({ region_id: "R2" })], [alert({ region_id: "R2", level: "breach" })]));
    expect(labelOrder(rows)[0].region_id).toBe("R2");
  });
  it("leaves unlabelled a group with no firm figure and no alert", () => {
    const rows = regionRows(model([region({ firm_mw: 0 }), region({ region_id: "R2", buses: [3], firm_mw: 0 })]), year([ry({ firm_mw: 0 }), ry({ region_id: "R2", firm_mw: 0 })], [alert({ region_id: "R2" })]));
    expect(labelOrder(rows).map((r) => r.region_id)).toEqual(["R2"]);
  });
});

describe("region levels", () => {
  it("says what kind of group a region is", () => {
    expect(LEVEL_LINE.primary({ bsp: "Sleaford" })).toBe("Sleaford BSP · demand group");
    expect(LEVEL_LINE.bsp({ bsp: "Sleaford" })).toBe("BSP · every primary it feeds");
  });
});
