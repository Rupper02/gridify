import { describe, expect, it, vi } from "vitest";

import { DEFAULT_VISIBLE, FEATURE_KEYS, lineFeature, loadVisible, onlyFeature, saveVisible, shows, toggleFeature, withFeature } from "./mapFeatures";

describe("map features", () => {
  it("shows everything but the demand groups by default", () => {
    expect(DEFAULT_VISIBLE).toEqual(FEATURE_KEYS.filter((k) => k !== "demand"));
  });
  it("toggles one kind, keeping the registry's order", () => {
    const off = toggleFeature(DEFAULT_VISIBLE, "transformers");
    expect(shows(off, "transformers")).toBe(false);
    expect(toggleFeature(off, "transformers")).toEqual(DEFAULT_VISIBLE);
  });
  it("focuses on one kind, and asking again brings the defaults back", () => {
    expect(onlyFeature(DEFAULT_VISIBLE, "generation")).toEqual(["generation"]);
    expect(onlyFeature(["generation"], "generation")).toEqual(DEFAULT_VISIBLE);
  });
  it("turns a feature on for a layer that needs it, without touching the rest", () => {
    const v = withFeature(["lines132"], "demand");
    expect(v).toEqual(["lines132", "demand"]);
    expect(withFeature(v, "demand")).toEqual(v);
  });
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
