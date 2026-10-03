import { describe, expect, it } from "vitest";

import { normReason } from "./api";

describe("normReason", () => {
  it("turns a line overload into a grid reason with the binding line and a next step", () => {
    const r = normReason({ type: "line", element_id: 115, value: 157.2, message: "line 115 overloaded at 157% of its rating at winter peak demand", case: "winter_peak" })!;
    expect(r.kind).toBe("grid");
    expect(r.element).toEqual({ line_id: 115 });
    expect(r.short).toBe("Overloads line 115 to 157%: a grid limit, not the project");
    expect(r.why).toContain("overload line 115 to 157% (limit 100%)");
    expect(r.why).toContain("This bites at winter peak demand.");
    expect(r.caseLabel).toBe("winter peak");
    expect(r.action).toContain("Reinforce line 115");
  });

  it("tells voltage rise from voltage sag by the value", () => {
    const high = normReason({ type: "voltage", element_id: 155, value: 1.112, message: "" })!;
    expect(high.short).toContain("Too much export");
    expect(high.element).toEqual({ bus_id: 155 });
    const low = normReason({ type: "voltage", element_id: 7, value: 0.88, message: "" })!;
    expect(low.short).toContain("sags to 0.880 pu");
  });

  it("explains the GSP boundary without pointing at a local element, and keeps the summer-minimum note", () => {
    const r = normReason({ type: "gsp", value: 540.4, message: "Bicker Fen GSP would export 540 MW to the transmission system at summer minimum demand — above its 527 MW export limit", case: "summer_min" })!;
    expect(r.kind).toBe("grid");
    expect(r.element).toBeNull();
    expect(r.short).toBe("GSP export limit: the region would push 540 MW up to transmission");
    expect(r.why).toContain("sunny, low-demand day");
    expect(r.why).not.toContain("This bites at"); // the case note is not appended twice
    expect(r.action).toContain("No local reinforcement fixes this");
  });

  it("classifies intake rejections from the engine's message", () => {
    expect(normReason({ type: "rejected", message: "connection point bus 999 is not in the network model" }, { bus_id: 999 })!.short).toBe("Connection point not in the network model");
    expect(normReason({ type: "rejected", message: "rating is out of range" }, { rating_mw: 500 })!.why).toContain("(500 MW) is above the 300 MW");
    expect(normReason({ type: "rejected", message: "missing rating" })!.short).toBe("Incomplete application");
    expect(normReason({ type: "non_convergent", message: "power flow did not converge at winter peak demand" })!.short).toBe("Can't be assessed yet");
  });

  it("is idempotent on an already-normalised reason and null-safe", () => {
    const once = normReason({ type: "trafo", element_id: 36, value: 105, message: "" })!;
    const twice = normReason(once)!;
    expect(twice.short).toBe(once.short);
    expect(normReason(null)).toBeNull();
  });
});
