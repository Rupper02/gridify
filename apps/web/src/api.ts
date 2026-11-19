// Typed client for the Gridify API (apps/api). Every call goes to `BASE`.

import type {
  Assumption,
  Boundary,
  Branch,
  Connection,
  ConnectionDraft,
  Forecasts,
  Job,
  Model,
  PlanDiff,
  PlanPayload,
  RegistryItem,
  RunComparison,
  RunGrid,
  RunInfo,
  RunSummary,
} from "./types";

// 127.0.0.1, not localhost: uvicorn listens on IPv4 only, and the browser tried ::1 first on every new connection
export const BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://127.0.0.1:8000";

/** A failed call: the status and the API's `detail` (a string, or a structured body). */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: unknown,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** A failed call's reason for a toast or the stamp: the API's detail when it answered, else that it may be down. */
export const failureText = (e: unknown): string => (e instanceof Error ? e.message : "check the API is running");

/** A read the API refused because the branch has not run for what it holds (`retry: false`) or the engine was busy
 * (`retry: true`): 409 `{code: "not_solved"}`. */
export const notSolved = (e: unknown): { retry: boolean } | null => {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const d = e.detail as { code?: unknown; retry?: unknown } | null;
  return d?.code === "not_solved" ? { retry: !!d.retry } : null;
};

async function errorOf(r: Response): Promise<ApiError> {
  const fallback = `${r.status} ${r.statusText}`;
  try {
    const d = ((await r.json()) as { detail?: unknown }).detail;
    if (d == null) return new ApiError(r.status, null, fallback);
    if (typeof d === "string") return new ApiError(r.status, d, d);
    if (Array.isArray(d)) return new ApiError(r.status, d, d.map((x) => (x as { msg?: string }).msg ?? JSON.stringify(x)).join("; "));
    const msg = (d as { message?: unknown }).message;
    return new ApiError(r.status, d, typeof msg === "string" ? msg : JSON.stringify(d));
  } catch {
    return new ApiError(r.status, null, fallback);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let r: Response;
  try {
    r = await fetch(`${BASE}${path}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error(`the API at ${BASE} did not answer: is it running?`);
  }
  if (!r.ok) throw await errorOf(r);
  return (await r.json()) as T;
}

const get = <T>(path: string) => call<T>("GET", path);
const post = <T>(path: string, body: unknown = {}) => call<T>("POST", path, body);

/** A run that ended without a result: cancelled by the planner, or stopped by the API (`message`: its reason). */
export class RunCancelled extends Error {}

const sleep = (ms: number) => new Promise((res) => window.setTimeout(res, ms));
const POLL_MS = 600;
const YEAR_POLL_MS = 3000; // a year takes minutes: a poll every few seconds is plenty

export interface RunHandlers {
  onStart?: (jobId: string) => void;
  onProgress?: (stage: string, fraction: number) => void;
  onPartial?: (p: PlanPayload) => void;
  /** Still wanted: a run that is no longer the planner's stops polling (the job is cancelled by the caller). */
  wanted?: () => boolean;
}

export const api = {
  getModel: () => get<Model>("/model"),
  getBoundary: () => get<Boundary | null>("/boundary"),
  getForecasts: () => get<Forecasts>("/forecasts"),
  getAssumptions: () => get<Assumption[]>("/assumptions"),
  getRegistry: () => get<RegistryItem[]>("/registry"),

  /** The measured and grown years: the catalogue, a run's summary, one element's month-by-hour grid (read-only). */
  listRuns: () => get<RunInfo[]>("/runs"),
  getRun: (runId: string) => get<RunSummary>(`/runs/${runId}`),
  getRunGrid: (runId: string, kind: "line" | "trafo" | "bus", id: number) => get<RunGrid>(`/runs/${runId}/grid/${kind}/${id}`),
  getRunCompare: (runId: string) => get<RunComparison>(`/runs/${runId}/compare`),

  /** Run a branch's year (about 16 minutes) as a background job and follow it: progress, then the run it made. */
  async runYear(bid: string, year: number, pathway: string, h: RunHandlers = {}): Promise<{ run_id: string; before: string }> {
    let job = await post<Job>(`/branches/${bid}/year-run`, { year, pathway });
    h.onStart?.(job.job_id);
    while (job.status === "queued" || job.status === "running") {
      await sleep(YEAR_POLL_MS);
      if (h.wanted && !h.wanted()) throw new RunCancelled();
      job = await get<Job>(`/jobs/${job.job_id}?with_result=false`);
      h.onProgress?.(job.stage, job.fraction);
    }
    if (job.status === "cancelled") throw new RunCancelled(job.reason ?? "");
    if (job.status === "failed") throw new Error(job.error ?? "the year run failed");
    const done = await get<Job & { result: { run_id: string; before: string } | null }>(`/jobs/${job.job_id}`);
    if (!done.result) throw new Error("the year run finished without a result");
    return done.result;
  },

  listBranches: () => get<{ branches: Branch[] }>("/branches").then((r) => r.branches),
  createBranch: (name: string, fromBranch: string) => post<Branch>("/branches", { name, from_branch: fromBranch }),
  setProfile: (bid: string, scenario: string) => post<Branch>(`/branches/${bid}/profile`, { scenario }),
  merge: (bid: string) => post<{ merged: string; into: string }>(`/branches/${bid}/merge`),
  discard: (bid: string) => post<{ discarded: string }>(`/branches/${bid}/discard`),

  listConnections: (bid: string) => get<Connection[]>(`/branches/${bid}/connections`),
  addConnection: (bid: string, body: ConnectionDraft) => post<Connection>(`/branches/${bid}/connections`, body),
  changeConnection: (bid: string, rid: string, body: Partial<ConnectionDraft>) => call<Connection>("PATCH", `/branches/${bid}/connections/${rid}`, body),
  removeConnection: (bid: string, rid: string) => call<{ removed: string }>("DELETE", `/branches/${bid}/connections/${rid}`),

  /** The branch's result for what it holds now; `not_solved` (409) until it has run. */
  getResult: (bid: string) => get<PlanPayload>(`/branches/${bid}/result`),
  getDiff: (bid: string) => get<PlanDiff>(`/branches/${bid}/diff`),
  cancelJob: (jobId: string) => post<Job>(`/jobs/${jobId}/cancel`),

  /** Run a branch as a background job and follow it to its end: progress and the years as they land. */
  async runBranch(bid: string, viewYear: number | null, h: RunHandlers = {}): Promise<PlanPayload> {
    let job = await post<Job>(`/branches/${bid}/run`, { view_year: viewYear });
    h.onStart?.(job.job_id);
    let seen = -1;
    while (job.status === "queued" || job.status === "running") {
      await sleep(POLL_MS);
      if (h.wanted && !h.wanted()) throw new RunCancelled();
      job = await get<Job>(`/jobs/${job.job_id}?partial=true&with_result=false&since=${seen}`);
      h.onProgress?.(job.stage, job.fraction);
      if (job.partial) {
        seen = job.partial_version;
        h.onPartial?.(job.partial);
      }
    }
    if (job.status === "cancelled") throw new RunCancelled();
    if (job.status === "failed") throw new Error(job.error ?? "the run failed");
    const done = await get<Job>(`/jobs/${job.job_id}`);
    if (!done.result) throw new Error("the run finished without a result");
    return done.result;
  },
};
