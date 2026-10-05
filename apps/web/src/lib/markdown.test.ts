import { describe, expect, it } from "vitest";
import { citeSteps, citedStep } from "./markdown";

describe("citeSteps", () => {
  it("turns step citations into numbered links and resolves 'same step'", () => {
    const out = citeSteps("Phase 1 is 0 [step answer:ask:m1:toolu_a]. Next, 4.3 MW [same step].");
    expect(out).toBe("Phase 1 is 0 [1](#cite:answer%3Aask%3Am1%3Atoolu_a). Next, 4.3 MW [2](#cite:answer%3Aask%3Am1%3Atoolu_a).");
  });
  it("leaves text without citations alone", () => {
    expect(citeSteps("**bold** text")).toBe("**bold** text");
  });
  it("reads the id back and ignores other links", () => {
    expect(citedStep("#cite:answer%3Aa")).toBe("answer:a");
    expect(citedStep("https://x.y")).toBeNull();
  });
});
