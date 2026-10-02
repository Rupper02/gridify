// Typed client for the GridForge API (apps/api). Every call goes to `BASE`; engine deferral reasons
// are normalised into the single shape the UI renders everywhere (see normReason).

import type {
  Boundary,
  Branch,
  Diff,
  Forecast,
  Job,
  Model,
  NewCandidate,
  OptimizeResult,
  RegistryItem,
  Suggestion,
} from "./types";
import { getMaxMw, normReason, setMaxMw } from "./lib/reasons";

export const BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

async function errorText(r: Response): Promise<string> {
  try {
    const j = (await r.json()) as { detail?: unknown };
    return j.detail ? String(j.detail) : `${r.status} ${r.statusText}`;
  } catch {
    return `${r.status} ${r.statusText}`;
  }
}

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(await errorText(r));
  return (await r.json()) as T;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await errorText(r));
  return (await r.json()) as T;
}

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
  return d;
}

// ---- endpoints ------------------------------------------------------------------------------

export const api = {
  getModel: () => getJson<Model>("/model"),
  getCandidates: () => getJson<RegistryItem[]>("/optimize/candidates"),
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
  optimize: async (body: { scenario: string; growth_2030: number; growth_2035: number; with_justification: boolean }) =>
    applyReasons(await postJson<OptimizeResult>("/optimize", body)),
  /** NESO FES 2025 demand pathways (fixed growth multipliers per pathway). */
  getForecasts: async () => {
    const r = await getJson<{ forecasts?: Forecast[]; max_connection_mw?: number }>("/forecasts");
    if (r.max_connection_mw) setMaxMw(r.max_connection_mw);
    return Array.isArray(r.forecasts) ? r.forecasts : [];
  },
  /** The GSP boundary: export/import limits to transmission + the transmission projects behind it. */
  getBoundary: async (): Promise<Boundary | null> => {
    try {
      return await getJson<Boundary>("/boundary");
    } catch {
      return null;
    }
  },
  getMaxConnectionMw: async (): Promise<number> => {
    try {
      const r = await getJson<{ max_connection_mw?: number }>("/forecasts");
      if (r.max_connection_mw) {
        setMaxMw(r.max_connection_mw);
        return r.max_connection_mw;
      }
    } catch {
      /* fall back to the default cap */
    }
    return getMaxMw();
  },

  // branches ("git for grids") + unblock suggestions. A branch = a scenario (demand pathway) + the projects added on it.
  createBranch: (body: { name: string; from_branch: string; scenario: string }) => postJson<Branch>("/branches", body),
  listBranches: async () => (await getJson<{ branches: Branch[] }>("/branches")).branches ?? [],
  optimizeBranch: async (id: string, opts?: { with_justification?: boolean }) =>
    applyReasons(await postJson<OptimizeResult>(`/branches/${id}/optimize`, opts ?? {})),
  /** Start a run in the background; poll `getJob` until it is done. A cached run finishes at once. */
  startOptimizeJob: (id: string, opts?: { with_justification?: boolean }) => postJson<Job>(`/branches/${id}/optimize/jobs`, opts ?? {}),
  getJob: (jobId: string) => getJson<Job>(`/jobs/${jobId}`),
  /** Run a branch as a background job, reporting stage + fraction while it runs. */
  runBranchJob: async (id: string, opts: { with_justification?: boolean }, onProgress: (stage: string, fraction: number) => void): Promise<OptimizeResult> => {
    let job = await postJson<Job>(`/branches/${id}/optimize/jobs`, opts);
    while (job.status === "queued" || job.status === "running") {
      onProgress(job.stage, job.fraction);
      await new Promise((r) => setTimeout(r, job.status === "queued" ? 400 : 700));
      job = await getJson<Job>(`/jobs/${job.job_id}`);
    }
    if (job.status !== "done" || !job.result) throw new Error(job.error ?? "the run failed");
    onProgress("done", 1);
    return applyReasons(job.result);
  },
  diffBranch: async (id: string, opts?: { with_narration?: boolean }) =>
    applyDiffReasons(await getJson<Diff>(`/branches/${id}/diff${opts?.with_narration ? "?with_narration=1" : ""}`)),
  mergeBranch: (id: string, opts?: { into: string }) => postJson<Branch>(`/branches/${id}/merge`, opts ?? { into: "main" }),
  discardBranch: (id: string) => postJson<Branch>(`/branches/${id}/discard`),
  getSuggestions: async (id: string, opts?: { limit?: number; with_narration?: boolean }) => {
    const p = new URLSearchParams();
    if (opts?.limit) p.set("limit", String(opts.limit));
    if (opts?.with_narration) p.set("with_narration", "1");
    const qs = p.toString() ? `?${p}` : "";
    return (await getJson<{ suggestions: Suggestion[] }>(`/branches/${id}/suggestions${qs}`)).suggestions ?? [];
  },
};

export type Api = typeof api;
