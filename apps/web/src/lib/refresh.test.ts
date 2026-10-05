import { describe, expect, it } from "vitest";

import { mergeQuiet } from "./refresh";

describe("refresh policy", () => {
  it("keeps a coalesced run quiet only if every request was quiet", () => {
    expect(mergeQuiet(true, true)).toBe(true);
    expect(mergeQuiet(true, false)).toBe(false);
    expect(mergeQuiet(undefined, true)).toBe(true); // nothing waiting: the new request decides
    expect(mergeQuiet(undefined, undefined)).toBe(false); // a plain Run is never quiet
    expect(mergeQuiet(true, undefined)).toBe(false);
    expect(mergeQuiet(false, true)).toBe(false);
  });
});
