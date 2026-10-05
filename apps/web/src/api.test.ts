import { describe, expect, it } from "vitest";

import { normReason } from "./api";

// normReason turns the engine's typed reason into what the planner shows. These tests pin what the planner relies on
// (what kind it is, which element it points at, null-safety), not the wording.
describe("normReason", () => {
  it("points a grid limit at the element that binds, and the GSP boundary at none", () => {
    const line = normReason({ type: "line", element_id: 115, value: 157.2, message: "", case: "winter_peak" })!;
    expect(line.kind).toBe("grid");
    expect(line.element).toEqual({ line_id: 115 });
    expect(line.caseLabel).toBe("winter peak");
    expect(normReason({ type: "voltage", element_id: 155, value: 1.112, message: "" })!.element).toEqual({ bus_id: 155 });
    const gsp = normReason({ type: "gsp", value: 540.4, message: "", case: "summer_min" })!;
    expect(gsp.kind).toBe("grid");
    expect(gsp.element).toBeNull();
  });

  it("tells a voltage rise from a sag, and one intake rejection from another", () => {
    expect(normReason({ type: "voltage", element_id: 1, value: 1.112, message: "" })!.short).not.toBe(normReason({ type: "voltage", element_id: 1, value: 0.88, message: "" })!.short);
    const missingBus = normReason({ type: "rejected", message: "connection point bus 999 is not in the network model" }, { bus_id: 999 })!;
    const missingRating = normReason({ type: "rejected", message: "missing rating" })!;
    expect(missingBus.short).not.toBe(missingRating.short);
  });

  it("is idempotent on an already-normalised reason and null-safe", () => {
    const once = normReason({ type: "trafo", element_id: 36, value: 105, message: "" })!;
    expect(normReason(once)!.short).toBe(once.short);
    expect(normReason(null)).toBeNull();
  });
});
