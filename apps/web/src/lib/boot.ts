// Booting the planner. The grid arrives in steps (the projects, then the model and branches, then the
// run and the boundary card), and each step is told to the operator rather than assumed: the result
// stamp says the grid is loading, and a step that fails is retried with a growing pause, since the
// usual cause is an API still starting or restarting under --reload, then shown with a Retry.

/** Pauses between attempts; once the last one is used up, the failure is shown. */
export const BOOT_RETRY_MS: readonly number[] = [1000, 2000, 4000, 8000];

export const GRID_LOAD_HINT =
  "The API did not answer in time. If it is still starting, give it a moment; if it is not running, start it (pnpm --filter @gridforge/api dev). Then retry.";

/** Worth another try: a network error or a server-side failure (5xx). A refusal (4xx) is final. */
export function retryable(e: unknown): boolean {
  const status = (e as { status?: unknown } | null)?.status;
  return typeof status !== "number" || status >= 500;
}

export interface RetryOptions {
  delays?: readonly number[];
  /** Whether to try again after this failure (and whether anyone still wants the answer). */
  shouldRetry?: (e: unknown) => boolean;
  sleep?: (ms: number) => Promise<void>;
}

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Run `fn`; after a failure pause for the next entry of `delays` and try again while `shouldRetry` says so. The last failure is thrown. */
export async function retrying<T>(fn: () => Promise<T>, { delays = BOOT_RETRY_MS, shouldRetry = retryable, sleep = wait }: RetryOptions = {}): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn();
    } catch (e) {
      if (attempt >= delays.length || !shouldRetry(e)) throw e;
      await sleep(delays[attempt]);
    }
  }
}

/** What the result stamp says while the grid is not there: that it is loading, or why it failed. Null once the model is in. */
export function gridLoadText(hasModel: boolean, loading: boolean, error: string | null): string | null {
  if (error) return `Could not load the grid: ${error}`;
  if (!hasModel && loading) return "Loading the grid…";
  return null;
}
