// Typed client for the GridForge API (apps/api). Every call goes to `BASE`; engine deferral reasons
// are normalised into the single shape the UI renders everywhere (see normReason).

import type {
  BestWindowRequest,
  BestWindowResult,
  Boundary,
  Branch,
  BranchReinforcement,
  Diff,
  Finding,
  FindingCounts,
  FindingStatus,
  Forecast,
  Job,
  MergeCheck,
  Model,
  NewCandidate,
  OptimizeResult,
  Outage,
  RegistryItem,
  Suggestion,
} from "./types";
import { getMaxMw, normReason, setMaxMw } from "./lib/reasons";

export const BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

/** A failed call: the status and the API's `detail` (a string, or a structured body such as a refused merge's verdict). */
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

async function errorDetail(r: Response): Promise<{ detail: unknown; text: string }> {
  const fallback = `${r.status} ${r.statusText}`;
  try {
    const d = ((await r.json()) as { detail?: unknown }).detail;
    if (d == null) return { detail: null, text: fallback };
    if (typeof d === "string") return { detail: d, text: d };
    const msg = (d as { message?: unknown }).message;
    return { detail: d, text: typeof msg === "string" ? msg : JSON.stringify(d) };
  } catch {
    return { detail: null, text: fallback };
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    const { detail, text } = await errorDetail(r);
    throw new ApiError(r.status, detail, text);
  }
  return (await r.json()) as T;
}
const getJson = <T>(path: string) => request<T>("GET", path);
const postJson = <T>(path: string, body?: unknown) => request<T>("POST", path, body);
const del = <T>(path: string) => request<T>("DELETE", path);

// ---- reasons: see lib/reasons.ts ---------------------------------------------------------------
export { normReason } from "./lib/reasons";

function applyReasons(res: OptimizeResult): OptimizeResult {
  res.queue.forEach((q) => {
    q.reason = normReason(q.reason, q);
  });
  return res;
}
function applyDiffReasons(d: Diff): Diff {
  d.projects.forEach((p) => {
    p.head_reason = normReason(p.head_reason, p);
  });
  d.years ??= {};
  d.works ??= [];
  return d;
}

/** A run that a newer one superseded: not a failure, nothing to report. */
export class RunCancelled extends Error {
  constructor() {
    super("superseded by a newer run");
  }
}

/** What a run reports while it solves: the job's stage and fraction, and partial results. */
export interface RunProgress {
  /** The job's id as soon as it exists, so a newer run can cancel it. */
  onStart?: (jobId: string) => void;
  onProgress: (stage: string, fraction: number) => void;
  /** The queue plus the years solved so far, as soon as the engine has them. */
  onPartial?: (partial: OptimizeResult) => void;
}

// ---- endpoints ------------------------------------------------------------------------------

export const api = {
  getModel: () => getJson<Model>("/model"),
  addCandidate: (c: NewCandidate) => postJson<RegistryItem>("/optimize/candidates", c),
  getRegistry: () => getJson<RegistryItem[]>("/registry"),
  addFromRegistry: (branchId: string, requestId: string) =>
    postJson<RegistryItem>(`/branches/${branchId}/registry`, { request_id: requestId }),
  /** Persist the operator's energisation year for a project on a branch (null = follow the recommendation). */
  setSchedule: (branchId: string, requestId: string, year: number | null) =>
    postJson<{ branch_id: string; request_id: string; scheduled_year: number | null }>(
      `/branches/${branchId}/schedule`,
      { request_id: requestId, year },
    ),
  /** Store a branch's demand profile (scenario + growth). The next run uses it. */
  updateScenario: (branchId: string, scenario: string, growth_2030: number, growth_2035: number) =>
    postJson<Branch>(`/branches/${branchId}/scenario`, { scenario, growth_2030, growth_2035 }),
  /** NESO FES 2025 demand pathways (fixed growth multipliers per pathway) and the intake cap. */
  getForecasts: async () => {
    const r = await getJson<{ forecasts?: Forecast[]; max_connection_mw?: number }>("/forecasts");
    if (r.max_connection_mw) setMaxMw(r.max_connection_mw);
    return { forecasts: Array.isArray(r.forecasts) ? r.forecasts : [], maxMw: r.max_connection_mw ?? getMaxMw() };
  },
  /** The GSP boundary: export/import limits to transmission + the transmission projects behind it. */
  getBoundary: async (): Promise<Boundary | null> => {
    try {
      return await getJson<Boundary>("/boundary");
    } catch {
      return null;
    }
  },

  // branches ("git for grids"). A branch = a demand profile + the projects, outages and
  // reinforcements added on it.
  createBranch: (body: { name: string; from_branch: string; scenario: string }) => postJson<Branch>("/branches", body),
  listBranches: async () => (await getJson<{ branches: Branch[] }>("/branches")).branches ?? [],
  /**
   * Run a branch as a background job: the queue first, then every year of the plan with
   * `view_year` first. Partial results are handed over as they land.
   */
  runBranchJob: async (id: string, opts: { with_justification?: boolean; view_year?: number | null }, p: RunProgress): Promise<OptimizeResult> => {
    let job = await postJson<Job>(`/branches/${id}/optimize/jobs`, opts);
    p.onStart?.(job.job_id);
    let seenYears = -1;
    while (job.status === "queued" || job.status === "running") {
      p.onProgress(job.stage, job.fraction);
      if (job.partial && p.onPartial) {
        const n = Object.keys(job.partial.years ?? {}).length;
        if (n !== seenYears) {
          seenYears = n;
          p.onPartial(applyReasons(job.partial));
        }
      }
      await new Promise((r) => setTimeout(r, job.status === "queued" ? 400 : 600));
      job = await getJson<Job>(`/jobs/${job.job_id}?partial=${p.onPartial ? "true" : "false"}`);
    }
    if (job.status === "cancelled") throw new RunCancelled();
    if (job.status !== "done" || !job.result) throw new Error(job.error ?? "the run failed");
    p.onProgress("done", 1);
    return applyReasons(job.result);
  },
  /** Stop a job a newer run supersedes (what it already solved stays cached on the API). */
  cancelJob: (jobId: string) => postJson<Job>(`/jobs/${jobId}/cancel`),
  diffBranch: async (id: string, opts?: { with_narration?: boolean }) =>
    applyDiffReasons(await getJson<Diff>(`/branches/${id}/diff${opts?.with_narration ? "?with_narration=1" : ""}`)),
  /** The merge gate's verdict for a branch against `into` (default its parent). Read-only. */
  mergeCheck: (id: string, into?: string) => getJson<MergeCheck>(`/branches/${id}/merge-check${into ? `?into=${encodeURIComponent(into)}` : ""}`),
  /** Merge through the gate: a 409 ApiError carries `{code, message, verdict}`; warnings need `acknowledge`. */
  mergeBranch: (id: string, opts: { into?: string; acknowledge?: boolean } = {}) =>
    postJson<Branch>(`/branches/${id}/merge`, { into: opts.into ?? "main", acknowledge: !!opts.acknowledge }),
  discardBranch: (id: string) => postJson<Branch>(`/branches/${id}/discard`),
  /** The findings ledger: what the branch's last run found, with the counts per status. */
  listFindings: (id: string, opts?: { status?: FindingStatus; year?: number }) => {
    const p = new URLSearchParams();
    if (opts?.status) p.set("status", opts.status);
    if (opts?.year != null) p.set("year", String(opts.year));
    const qs = p.toString() ? `?${p}` : "";
    return getJson<{ branch_id: string; counts: FindingCounts; findings: Finding[] }>(`/branches/${id}/findings${qs}`);
  },
  setFindingStatus: (findingId: string, status: FindingStatus, note = "") => postJson<Finding>(`/findings/${findingId}/ack`, { status, note }),
  /** The copilot's levers: for the branch's deferred projects, or for one of them (`request_id`). */
  getSuggestions: async (id: string, opts?: { limit?: number; with_narration?: boolean; request_id?: string }) => {
    const p = new URLSearchParams();
    if (opts?.limit) p.set("limit", String(opts.limit));
    if (opts?.with_narration) p.set("with_narration", "1");
    if (opts?.request_id) p.set("request_id", opts.request_id);
    const qs = p.toString() ? `?${p}` : "";
    return (await getJson<{ suggestions: Suggestion[] }>(`/branches/${id}/suggestions${qs}`)).suggestions ?? [];
  },

  // planned maintenance and simulated reinforcements on a branch
  listOutages: async (id: string) => (await getJson<{ outages: Outage[] }>(`/branches/${id}/outages`)).outages ?? [],
  addOutage: (id: string, o: Omit<Outage, "outage_id" | "created_at">) => postJson<Outage>(`/branches/${id}/outages`, o),
  removeOutage: (id: string, outageId: string) => del<{ removed: boolean }>(`/branches/${id}/outages/${outageId}`),
  /** The best window for a planned work, as a background job (progress per year studied). */
  bestWindowJob: async (id: string, body: BestWindowRequest, onProgress: (stage: string, fraction: number) => void): Promise<BestWindowResult> => {
    let job = await postJson<Job<BestWindowResult>>(`/branches/${id}/works/best-window`, body);
    while (job.status === "queued" || job.status === "running") {
      onProgress(job.stage, job.fraction);
      await new Promise((r) => setTimeout(r, job.status === "queued" ? 400 : 700));
      job = await getJson<Job<BestWindowResult>>(`/jobs/${job.job_id}`);
    }
    if (job.status !== "done" || !job.result) throw new Error(job.error ?? "the window search failed");
    return job.result;
  },
  listReinforcements: async (id: string) =>
    (await getJson<{ reinforcements: BranchReinforcement[] }>(`/branches/${id}/reinforcements`)).reinforcements ?? [],
  addReinforcement: (id: string, r: Omit<BranchReinforcement, "reinforcement_id" | "created_at">) =>
    postJson<BranchReinforcement>(`/branches/${id}/reinforcements`, r),
  removeReinforcement: (id: string, rid: string) => del<{ removed: boolean }>(`/branches/${id}/reinforcements/${rid}`),
};

export type Api = typeof api;
