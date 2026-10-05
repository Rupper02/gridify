import { describe, expect, it } from "vitest";
import { latestWins } from "./latest";

describe("latestWins", () => {
  it("lets only the newest load of a key apply", () => {
    const begin = latestWins();
    const older = begin("diff");
    const newer = begin("diff");
    expect(older()).toBe(false);
    expect(newer()).toBe(true);
  });
  it("keeps keys independent", () => {
    const begin = latestWins();
    const diff = begin("diff");
    begin("mergeCheck");
    expect(diff()).toBe(true);
  });
});
