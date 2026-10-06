// Typed client for the GridForge API (apps/api). Every call goes to `BASE`; engine deferral reasons
// are normalised into the single shape the UI renders everywhere (see normReason).

import type {
  AgentRun,
  AgentsStatus,
  Approval,
  Assumption,
  Boundary,
  Branch,
  BranchReinforcement,
  Control,
  Diff,
  Finding,
  FindingCounts,
  FindingStatus,
  FileInspection,
  ImportFormats,
  Forecast,
  Horizon,
  Job,
  MergeCheck,
  Model,
  OptimizeResult,
  Outage,
  Project,
  RebasePick,
  RebasePreview,
  RegistryItem,
  Review,
  StepEvidence,
  Thread,
  ThreadView,
  TraceEvent,
} from "./types";
import { planOf } from "./lib/plan";
import { normReason } from "./lib/reasons";

// 127.0.0.1, not localhost: uvicorn listens on IPv4 only, and the browser tried ::1 first on every new connection
export const BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://127.0.0.1:8000";

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

/** A failed call's reason for a toast or a stamp: the API's detail when it answered, else that it may be down. */
export const failureText = (e: unknown): string => (e instanceof Error ? e.message : "check the API is running");

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

/** Told, after each response that read the pipeline's warehouse, whether it was the last version rather than the
 * current one (the pipeline was writing a new one: `X-Warehouse-Stale`). One listener: the planner's. */
let warehouseListener: ((stale: boolean) => void) | null = null;
export const onWarehouse = (fn: ((stale: boolean) => void) | null): void => {
  warehouseListener = fn;
};

/** A response's JSON, or the API's refusal as an ApiError (its status and `detail`). */
async function parse<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const { detail, text } = await errorDetail(r);
    throw new ApiError(r.status, detail, text);
  }
  return (await r.json()) as T;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.ok && r.headers.get("X-Warehouse-Snapshot")) warehouseListener?.(r.headers.get("X-Warehouse-Stale") === "1");
  return parse<T>(r);
}
const getJson = <T>(path: string) => request<T>("GET", path);
const postJson = <T>(path: string, body?: unknown) => request<T>("POST", path, body);
const del = <T>(path: string) => request<T>("DELETE", path);
const patchJson = <T>(path: string, body: unknown) => request<T>("PATCH", path, body);

/** A multipart POST (a file plus fields); errors as `request` reports them. */
async function postForm<T>(path: string, form: FormData): Promise<T> {
  return parse<T>(await fetch(`${BASE}${path}`, { method: "POST", body: form }));
}

/** How often a job is polled: while it waits for the solver, and while it solves (a year takes seconds; the
 * poll is cheap once it carries `since`, but the solver shares one process with the API). */
const POLL_QUEUED_MS = 400;
const POLL_RUNNING_MS = 1000;

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
  // projects: the grids planned on, each with its own main; the built-in one is NGED's
  listProjects: async () => (await getJson<{ projects: Project[] }>("/projects")).projects ?? [],
  /** Import a grid as a project: the file, a name and the limits the operator knows (strings, as typed). */
  importProject: (file: File, name: string, limits: Record<string, string>) => {
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("name", name);
    Object.entries(limits).forEach(([k, v]) => form.append(k, v));
    return postForm<Project>("/projects", form);
  },
  deleteProject: (pid: string) => del<{ project_id: string; deleted: boolean }>(`/projects/${pid}`),
  /** The source kinds (labels, the extensions the import form offers) and the upload size limit. */
  importFormats: () => getJson<ImportFormats>("/projects/formats"),
  /** A file's voltage levels before it is imported (what the import form's study basis asks about); nothing is stored. */
  inspectFile: (file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return postForm<FileInspection>("/projects/inspect", form);
  },
  /** The demand pathways a project runs on: the FES pathways, or the forecast entered at import. */
  getProjectForecasts: async (pid: string) => (await getJson<{ forecasts?: Forecast[] }>(`/projects/${pid}/forecasts`)).forecasts ?? [],
  getAssumptions: (pid: string) => getJson<{ project_id: string; assumptions: Assumption[] }>(`/projects/${pid}/assumptions`),
  getModel: (pid: string) => getJson<Model>(`/projects/${pid}/model`),
  /** A branch's projects as stored (added by hand, pulled from the registry, or an agent's approved proposal): what its next run ranks. */
  listCandidates: (id: string) => getJson<RegistryItem[]>(`/branches/${id}/candidates`),
  getRegistry: (pid: string) => getJson<RegistryItem[]>(`/projects/${pid}/registry`),
  addFromRegistry: (branchId: string, requestId: string) =>
    postJson<RegistryItem>(`/branches/${branchId}/registry`, { request_id: requestId }),
  /** Change a project on a branch (its control mode, here); answers with the stored row. */
  changeCandidate: (branchId: string, requestId: string, changes: { control: Control }) =>
    patchJson<RegistryItem>(`/branches/${branchId}/candidates/${requestId}`, changes),
  /** Persist the operator's energisation year for a project on a branch (null = follow the recommendation). */
  setSchedule: (branchId: string, requestId: string, year: number | null) =>
    postJson<{ branch_id: string; request_id: string; scheduled_year: number | null }>(
      `/branches/${branchId}/schedule`,
      { request_id: requestId, year },
    ),
  /** Store a branch's demand profile (scenario + growth). The next run uses it. */
  updateScenario: (branchId: string, scenario: string, growth_2030: number, growth_2035: number) =>
    postJson<Branch>(`/branches/${branchId}/scenario`, { scenario, growth_2030, growth_2035 }),
  /** The built-in demand pathways (fixed growth multipliers per pathway), and the plan's years and phases. */
  getForecasts: async () => {
    const r = await getJson<{ default: string; forecasts?: Forecast[]; plan_years: number[]; horizons: Horizon[] }>("/forecasts");
    // `defaultScenario`: the engine's DEFAULT_SCENARIO, the pathway a branch is planned on unless it says otherwise
    return { forecasts: Array.isArray(r.forecasts) ? r.forecasts : [], plan: planOf(r.plan_years, r.horizons), defaultScenario: r.default };
  },
  /** The project's transmission boundary (export limit, export today, the projects behind it), or null when it models none (404). */
  getBoundary: async (pid: string): Promise<Boundary | null> => {
    try {
      return await getJson<Boundary>(`/projects/${pid}/boundary`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  },

  // branches ("git for grids"). A branch = a demand profile + the projects, outages and
  // reinforcements added on it.
  createBranch: (body: { name: string; from_branch: string; scenario?: string }) => postJson<Branch>("/branches", body),
  listBranches: async (pid: string) => (await getJson<{ branches: Branch[] }>(`/projects/${pid}/branches`)).branches ?? [],
  /**
   * Run a branch as a background job: the queue first, then every year of the plan with
   * `view_year` first. Partial results are handed over as they land.
   */
  runBranchJob: async (id: string, opts: { with_justification?: boolean; view_year?: number | null }, p: RunProgress): Promise<OptimizeResult> => {
    let job = await postJson<Job>(`/branches/${id}/optimize/jobs`, opts);
    p.onStart?.(job.job_id);
    // the partial result (the queue plus every year solved so far) is large and re-serialised per poll: the poll
    // names the version it has (`since`) and the API sends a partial only when it has a newer one
    let seen: number | null = null;
    while (job.status === "queued" || job.status === "running") {
      p.onProgress(job.stage, job.fraction);
      if (job.partial && p.onPartial) {
        seen = job.partial_version ?? null;
        p.onPartial(applyReasons(job.partial));
      }
      await new Promise((r) => setTimeout(r, job.status === "queued" ? POLL_QUEUED_MS : POLL_RUNNING_MS));
      job = await getJson<Job>(`/jobs/${job.job_id}?partial=${p.onPartial ? "true" : "false"}${seen != null ? `&since=${seen}` : ""}`);
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
  /** The merge gate's verdict for a branch against its parent. Read-only. */
  mergeCheck: (id: string) => getJson<MergeCheck>(`/branches/${id}/merge-check`),
  /** Merge through the gate: a 409 ApiError carries `{code, message, verdict}`; warnings need `acknowledge`. */
  mergeBranch: (id: string, opts: { into: string; acknowledge?: boolean }) =>
    postJson<Branch>(`/branches/${id}/merge`, { into: opts.into, acknowledge: !!opts.acknowledge }),
  discardBranch: (id: string) => postJson<Branch>(`/branches/${id}/discard`),
  /** What rebasing a branch onto its parent as it is now would do (writes nothing). */
  rebasePreview: (id: string) => getJson<RebasePreview>(`/branches/${id}/rebase`),
  /** Rebase with the operator's pick for every conflict; a 409 means a pick is missing or the parent moved again. */
  rebaseBranch: (id: string, picks: Record<string, RebasePick>) => postJson<{ branch: Branch; taken: number }>(`/branches/${id}/rebase`, { picks }),
  /** The findings ledger: what the branch's last run found, with the counts per status. */
  listFindings: (id: string) => getJson<{ branch_id: string; counts: FindingCounts; findings: Finding[] }>(`/branches/${id}/findings`),
  setFindingStatus: (findingId: string, status: FindingStatus, note = "") => postJson<Finding>(`/findings/${findingId}/ack`, { status, note }),

  // planned maintenance and simulated reinforcements on a branch
  listOutages: async (id: string) => (await getJson<{ outages: Outage[] }>(`/branches/${id}/outages`)).outages ?? [],
  addOutage: (id: string, o: Omit<Outage, "outage_id" | "created_at">) => postJson<Outage>(`/branches/${id}/outages`, o),
  removeOutage: (id: string, outageId: string) => del<{ removed: boolean }>(`/branches/${id}/outages/${outageId}`),
  listReinforcements: async (id: string) =>
    (await getJson<{ reinforcements: BranchReinforcement[] }>(`/branches/${id}/reinforcements`)).reinforcements ?? [],
  removeReinforcement: (id: string, rid: string) => del<{ removed: boolean }>(`/branches/${id}/reinforcements/${rid}`),

  // the agents: status and the pause switch, conversations with a streamed reply, approvals, reviews, evidence
  agentsStatus: (pid: string) => getJson<AgentsStatus>(`/projects/${pid}/agents`),
  pauseAgents: (pid: string) => postJson<AgentsStatus>(`/projects/${pid}/agents/pause`, { reason: "operator" }),
  resumeAgents: (pid: string) => postJson<AgentsStatus>(`/projects/${pid}/agents/resume`),
  /** The project's agent runs, newest first (the API caps them at 50). */
  listAgentRuns: async (pid: string) => (await getJson<{ runs?: AgentRun[] }>(`/projects/${pid}/agents/runs`)).runs ?? [],
  listThreads: async (pid: string) => (await getJson<{ threads: Thread[] }>(`/projects/${pid}/threads`)).threads ?? [],
  createThread: (pid: string, branchId: string | null, title: string) => postJson<Thread>(`/projects/${pid}/threads`, { branch_id: branchId, title }),
  getThread: (pid: string, tid: string) => getJson<ThreadView>(`/projects/${pid}/threads/${tid}`),
  /** Ask: the question is stored, a reply queued and its workflow started; stream the reply by `reply_id`. */
  postMessage: (pid: string, tid: string, content: string) =>
    postJson<{ message_id: string; reply_id: string; workflow_id: string | null; paused: boolean }>(`/projects/${pid}/threads/${tid}/messages`, { content }),
  /**
   * Follow a reply as server-sent events (tokens, tool calls with their step ids, results, the final
   * message). The browser reconnects by itself with the last event id; `onDrop` is told each time so
   * the caller can stop once the reply has settled. Returns the function that closes the stream.
   */
  streamReply: (pid: string, tid: string, messageId: string, h: { onEvent: (ev: TraceEvent) => void; onEnd: () => void; onDrop?: () => void }): (() => void) => {
    const es = new EventSource(`${BASE}/projects/${pid}/threads/${tid}/stream?message_id=${encodeURIComponent(messageId)}`);
    let ended = false;
    const end = () => {
      if (ended) return;
      ended = true;
      es.close();
      h.onEnd();
    };
    for (const kind of ["token", "tool_call", "tool_result", "progress", "cite", "final", "error"]) {
      es.addEventListener(kind, (e) => {
        if (!(e instanceof MessageEvent)) return; // the browser's own error event, not the server's
        const ev = JSON.parse(e.data as string) as TraceEvent;
        h.onEvent(ev);
        if (ev.t === "final" || ev.t === "error") end();
      });
    }
    es.onerror = (e) => {
      if (!(e instanceof MessageEvent)) h.onDrop?.();
    };
    return end;
  },
  /** Stop the reply on its way in a thread: marked cancelled at once, its workflow cancelled at its next step. */
  cancelReply: (pid: string, tid: string) => postJson<{ thread_id: string; message_id: string; status: "cancelled" }>(`/projects/${pid}/threads/${tid}/cancel`),
  /** Decide a proposal. The answer continues once every proposal of its reply is decided; until then `waiting_for` lists the open ones. */
  decideApproval: (pid: string, aid: string, decision: "approve" | "deny", note = "") =>
    postJson<Approval & { workflow_id: string | null; waiting_for: string[] }>(`/projects/${pid}/approvals/${aid}`, { decision, note }),
  /** The reviewer's current comment on a branch. */
  listReviews: async (branchId: string) => (await getJson<{ reviews: Review[] }>(`/branches/${branchId}/reviews`)).reviews ?? [],
  /** The evidence behind a step an agent cited. */
  stepEvidence: (pid: string, stepId: string) => getJson<StepEvidence>(`/projects/${pid}/agents/steps/${encodeURIComponent(stepId)}`),
};

