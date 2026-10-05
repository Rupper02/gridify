import { describe, expect, it } from "vitest";

import { BOOT_RETRY_MS, retryable, retrying } from "./boot";

const failing = (status?: number) => async (): Promise<string> => {
  throw status === undefined ? new TypeError("Failed to fetch") : Object.assign(new Error(`${status}`), { status });
};

describe("boot retries", () => {
  it("retries a network error or a 5xx, never a refusal", () => {
    expect(retryable(new TypeError("Failed to fetch"))).toBe(true);
    expect(retryable({ status: 503 })).toBe(true);
    expect(retryable({ status: 404 })).toBe(false);
    expect(retryable({ status: 410 })).toBe(false);
  });

  it("pauses longer each time and resolves once the call succeeds", async () => {
    const slept: number[] = [];
    let calls = 0;
    const out = await retrying(
      async () => {
        calls++;
        if (calls < 3) throw new TypeError("Failed to fetch");
        return "grid";
      },
      { sleep: async (ms) => void slept.push(ms) },
    );
    expect(out).toBe("grid");
    expect(calls).toBe(3);
    expect(slept).toEqual(BOOT_RETRY_MS.slice(0, 2));
  });

  it("throws the last failure once the pauses are used up", async () => {
    const slept: number[] = [];
    await expect(retrying(failing(), { sleep: async (ms) => void slept.push(ms) })).rejects.toThrow("Failed to fetch");
    expect(slept).toEqual([...BOOT_RETRY_MS]);
  });

  it("gives up at once on a refusal, or when the caller no longer wants the answer", async () => {
    let calls = 0;
    const counted = (status?: number) => async () => {
      calls++;
      return failing(status)();
    };
    await expect(retrying(counted(404), { sleep: async () => {} })).rejects.toThrow("404");
    expect(calls).toBe(1);
    calls = 0;
    await expect(retrying(counted(), { shouldRetry: () => false, sleep: async () => {} })).rejects.toThrow("Failed to fetch");
    expect(calls).toBe(1);
  });
});

