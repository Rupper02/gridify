import { describe, expect, it, vi } from "vitest";

import { DEFAULT_VISIBLE, lineFeature, loadVisible, saveVisible } from "./mapFeatures";

describe("map features", () => {
  it("puts every circuit in a voltage band", () => {
    expect([132, 400, 33, 66, 11, 0.4].map(lineFeature)).toEqual(["lines132", "lines132", "lines33", "lines33", "linesLow", "linesLow"]);
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
