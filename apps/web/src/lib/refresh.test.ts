import { describe, expect, it } from "vitest";

import { EDIT_POLICY, mergeQuiet } from "./refresh";

describe("refresh policy", () => {
  it("refreshes by itself only for edits that leave the queue's decisions alone", () => {
    expect(EDIT_POLICY.schedule.auto).toBe(true);
    expect(EDIT_POLICY.works.auto).toBe(true);
    expect(EDIT_POLICY.project.auto).toBe(false);
    expect(EDIT_POLICY.profile.auto).toBe(false);
    expect(EDIT_POLICY.reinforcement.auto).toBe(false);
  });
  it("keeps a coalesced run quiet only if every request was quiet", () => {
    expect(mergeQuiet(true, true)).toBe(true);
    expect(mergeQuiet(true, false)).toBe(false);
    expect(mergeQuiet(undefined, true)).toBe(true); // nothing waiting: the new request decides
    expect(mergeQuiet(undefined, undefined)).toBe(false); // a plain Run is never quiet
    expect(mergeQuiet(true, undefined)).toBe(false);
    expect(mergeQuiet(false, true)).toBe(false);
  });
});
