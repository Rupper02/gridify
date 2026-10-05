import { describe, expect, it, vi } from "vitest";

import { DEFAULT_VISIBLE, featureLabel, lineFeature, lineTiers, loadVisible, saveVisible } from "./mapFeatures";

describe("map features", () => {
  it("puts every circuit in a tier of the grid's own voltages, named by them", () => {
    const t = lineTiers([132, 33, 11, 0.4, 132]);
    expect([132, 33, 11, 0.4].map((kv) => lineFeature(kv, t))).toEqual(["linesHigh", "linesMid", "linesLow", "linesLow"]);
    expect(["linesHigh", "linesMid", "linesLow"].map((k) => featureLabel(k as never, t))).toEqual(["132 kV lines", "33 kV lines", "Below 33 kV"]);
    // a one-level grid has one line feature
    expect(["linesHigh", "linesMid", "linesLow"].map((k) => featureLabel(k as never, lineTiers([345])))).toEqual(["345 kV lines", null, null]);
  });
});

describe("remembered map features", () => {
  const mem = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => mem.get(k) ?? null,
    setItem: (k: string, v: string) => void mem.set(k, v),
    removeItem: (k: string) => void mem.delete(k),
  });
  it("starts from the defaults when nothing, garbage or an empty choice is saved", () => {
    for (const v of [null, "not json", "[]", '["gone"]']) {
      if (v === null) localStorage.removeItem("gridforge.mapFeatures");
      else localStorage.setItem("gridforge.mapFeatures", v);
      expect(loadVisible()).toEqual(DEFAULT_VISIBLE);
    }
    saveVisible(["generation"]);
    expect(loadVisible()).toEqual(["generation"]);
  });
});
