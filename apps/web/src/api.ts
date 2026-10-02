// Typed client for the GridForge API (apps/api). Every call goes to `BASE`; engine deferral reasons
// are normalised into the single shape the UI renders everywhere (see normReason).

import type {
  Boundary,
  Branch,
  Diff,
  Forecast,
  Model,
  NewCandidate,
  OptimizeResult,
  RawReason,
  Reason,
  RegistryItem,
  Suggestion,
} from "./types";

export const BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

// intake cap used in reason text until /forecasts tells us the engine's real value
let maxMw = 300;

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

// ---- reasons --------------------------------------------------------------------------------

// Which planning study case a grid limit bites in, so the operator knows WHEN it's a problem.
const CASE_WHY: Record<string, string> = {
  summer_min:
    " This bites at summer minimum demand — a sunny, low-demand day when little local load is there to soak up the export and the wires are on their lower summer rating.",
  winter_peak: " This bites at winter peak demand.",
};

interface ReasonContext {
  bus_id?: number | null;
  rating_mw?: number | null;
}

/**
 * Normalise an engine reason ({type, element_id, value, message, case}) into
 * {kind, element, short, why (plain English), action (what to do next)}.
 */
export function normReason(reason: RawReason | Reason | null | undefined, item?: ReasonContext): Reason | null {
  if (!reason) return null;
  const out = normReasonCore(reason, item ?? {});
  // (a GSP reason already names its case in the message, and explains it itself)
  if (out.kind === "grid" && reason.type !== "gsp" && reason.case && CASE_WHY[reason.case]) {
    out.why = `${out.why}${CASE_WHY[reason.case]}`;
    out.caseLabel = reason.case === "summer_min" ? "summer minimum" : "winter peak";
  }
  return out;
}

function normReasonCore(reason: RawReason | Reason, it: ReasonContext): Reason {
  const t = reason.type;
  const val = typeof reason.value === "number" ? reason.value : null;
  const msg = reason.message || "";
  const prior = (reason as Partial<Reason>).element ?? null;
  const eid: number | null =
    reason.element_id != null
      ? reason.element_id
      : prior
        ? (prior.line_id ?? prior.bus_id ?? null)
        : null;
  const pct = val != null ? Math.round(val) : null;
  const base = { ...reason, message: msg, value: val };

  if (t === "gsp") {
    // the transmission boundary: no distribution-side reinforcement can fix this
    const mw = val != null ? Math.round(val) : null;
    return {
      ...base,
      kind: "grid",
      element: null,
      short: `GSP export limit — the region would push ${mw != null ? `${mw} MW` : "too much"} up to transmission`,
      why: `${msg ? msg.charAt(0).toUpperCase() + msg.slice(1) + "." : "The GSP would export more than the transmission boundary allows."}${
        reason.case === "summer_min"
          ? " That's a sunny, low-demand day — the most generation and the least local load at the same time."
          : ""
      } The bottleneck isn't in the local network — it's the supergrid transformers and transmission network above the GSP, which already carry this region's surplus generation out.`,
      action:
        "No local reinforcement fixes this. Options: wait for transmission (NESO) reinforcement, take a flexible / non-firm connection that's curtailed at export peaks, pair it with storage to shift export, or site it under a GSP with headroom.",
    };
  }
  if (t === "line" || t === "line_overload") {
    return {
      ...base,
      kind: "grid",
      element: { line_id: eid ?? undefined },
      short: `Overloads line ${eid}${pct != null ? ` to ${pct}%` : ""} — a grid limit, not the project`,
      why: `Connecting this would overload line ${eid}${pct != null ? ` to ${pct}% (limit 100%)` : ""}. The wires between here and the rest of the grid are the bottleneck — the project itself is fine.`,
      action: `Reinforce line ${eid} (add a parallel circuit) — open Review ▸ Suggestions for the exact plan and the MW it frees — or hold this project to 2035.`,
    };
  }
  if (t === "trafo" || t === "trafo_overload") {
    return {
      ...base,
      kind: "grid",
      element: null,
      short: `Overloads transformer ${eid}${pct != null ? ` to ${pct}%` : ""}`,
      why: `Connecting this would overload transformer ${eid}${pct != null ? ` to ${pct}% (limit 100%)` : ""} — the primary substation can't pass this much power.`,
      action: `Uprate or reinforce transformer ${eid} — see Review ▸ Suggestions — or hold this project to 2035.`,
    };
  }
  if (t === "voltage" || t === "voltage_high" || t === "voltage_low") {
    const high = t === "voltage_high" || (t === "voltage" && val != null && val > 1.0);
    if (high) {
      return {
        ...base,
        kind: "grid",
        element: { bus_id: eid ?? undefined },
        short: `Too much export — bus ${eid} rises to ${val != null ? val.toFixed(3) : "?"} pu (limit 1.10)`,
        why: `This much generation can't be absorbed here: it would push the voltage at bus ${eid}${val != null ? ` to ${val.toFixed(3)} pu` : ""}, above the 1.10 limit. The local network is too weak for this much export.`,
        action: `Reinforce the feeder or add reactive support at bus ${eid} — see Review ▸ Suggestions — or site a smaller project at this bus.`,
      };
    }
    return {
      ...base,
      kind: "grid",
      element: { bus_id: eid ?? undefined },
      short: `Bus ${eid} sags to ${val != null ? val.toFixed(3) : "?"} pu (limit 0.90)`,
      why: `Voltage at bus ${eid}${val != null ? ` drops to ${val.toFixed(3)} pu` : ""}, below the 0.90 limit — the network is too weak here under this demand.`,
      action: `Reinforce the feeder to bus ${eid} — see Review ▸ Suggestions — or hold this project to 2035.`,
    };
  }
  if (t === "readiness") {
    return {
      ...base,
      kind: "readiness",
      element: null,
      short: "Not developed enough yet",
      why:
        msg ||
        "The project isn't developed enough yet (land rights, planning consent, grid-connection agreement or financing).",
      action: "Resubmit once land, planning and financing progress — the grid can take it; the project isn't ready.",
    };
  }
  if (t === "phased") {
    return {
      ...base,
      kind: "phased",
      element: prior,
      short: msg,
      why: msg,
      action: "No action needed — it connects in 2035 as demand grows and headroom opens.",
    };
  }
  // rejected / intake / non_convergent
  const m = msg.toLowerCase();
  let short: string;
  let why: string;
  let action: string;
  if (m.includes("not in") || m.includes("does not exist") || (m.includes("bus") && !m.includes("busbar"))) {
    short = "Connection point not in the network model";
    why = `The point of connection${it.bus_id != null ? ` (bus ${it.bus_id})` : ""} isn't in this network model, so it can't be assessed.`;
    action =
      "Pick a real connection point: in + Add project, choose a bus from the dropdown or click “Map” to pick one on the network.";
  } else if (m.includes("rating") && (m.includes("exceed") || m.includes("range") || m.includes("cap"))) {
    short = `Capacity over the ${maxMw} MW connection cap`;
    why = `The requested capacity${it.rating_mw != null ? ` (${it.rating_mw} MW)` : ""} is above the ${maxMw} MW connection cap for this network.`;
    action = `Reduce the capacity to ≤ ${maxMw} MW, split it across sites, or connect at a higher-voltage point.`;
  } else if (m.includes("missing") || m.includes("capacity")) {
    short = "Incomplete application";
    why = msg || "The application is missing required details.";
    action = "Complete the missing fields (capacity, point of connection, technology) in + Add project and resubmit.";
  } else {
    short = "Can't be assessed yet";
    why = msg || "This application can't be assessed yet.";
    action = "Complete the application details and resubmit.";
  }
  return { ...base, kind: "intake", element: null, short, why, action };
}

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
    if (r.max_connection_mw) maxMw = r.max_connection_mw;
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
        maxMw = r.max_connection_mw;
        return r.max_connection_mw;
      }
    } catch {
      /* fall back to the default cap */
    }
    return maxMw;
  },

  // branches ("git for grids") + unblock suggestions. A branch = a scenario (demand pathway) + the projects added on it.
  createBranch: (body: { name: string; from_branch: string; scenario: string }) => postJson<Branch>("/branches", body),
  listBranches: async () => (await getJson<{ branches: Branch[] }>("/branches")).branches ?? [],
  optimizeBranch: async (id: string, opts?: { with_justification?: boolean }) =>
    applyReasons(await postJson<OptimizeResult>(`/branches/${id}/optimize`, opts ?? {})),
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
