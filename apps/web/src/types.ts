// Wire types for the GridForge API (apps/api) and the planner's own view types.

export type Status = "Phase1" | "Phase2" | "Deferred" | "Rejected";
export type Tech = "solar" | "wind" | "battery";
// PhaseKey can be "2030", "2035", or any year string for year-scoped studies
export type PhaseKey = string;

export interface Bus {
  bus_id: number;
  name: string;
  vn_kv: number;
  lon: number;
  lat: number;
}
export interface Line {
  line_id: number;
  line_name: string;
  rating_a: number;
  voltage_kv: number;
  from_lon: number;
  from_lat: number;
  to_lon: number;
  to_lat: number;
  length_km?: number;
  in_service?: boolean;
}
export interface Transformer {
  trafo_id: number;
  name: string;
  sn_mva: number;
  hv_bus: number;
  lv_bus: number;
  hv_kv: number;
  lv_kv: number;
  hv_name: string;
  hv_lon: number;
  hv_lat: number;
  lv_lon: number;
  lv_lat: number;
}
export interface Load {
  load_id: number;
  bus_id: number;
  p_mw: number;
  lon: number;
  lat: number;
}
export interface Generator {
  request_id: string;
  bus_id: number;
  rating_mw: number;
  technology: string;
  applicant: string;
  lon: number;
  lat: number;
}
export interface Model {
  buses: Bus[];
  lines: Line[];
  transformers: Transformer[];
  loads: Load[];
  generators: Generator[];
}

/** A deferral/rejection reason as the engine emits it. */
export interface RawReason {
  type: string;
  element_id?: number | null;
  value?: number | null;
  limit?: number | null; // the limit breached (pu for voltage, % for thermal, MW for the GSP)
  message: string;
  case?: string | null;
}
export type ReasonKind = "grid" | "readiness" | "phased" | "intake";
/** The engine reason, normalised for the UI: what kind of block, which element, why, what to do. */
export interface Reason extends RawReason {
  kind: ReasonKind;
  element: { line_id?: number; bus_id?: number } | null;
  short: string;
  why: string;
  action: string;
  caseLabel?: string;
}

export interface QueueItem {
  rank: number | null;
  request_id: string;
  bus_id: number | null;
  technology: string | null;
  rating_mw: number | null;
  readiness_score: number;
  strategic_fit: number;
  grid_need: number;
  rank_score: number | null;
  status: Status;
  reason: Reason | null;
  commissioning_year: number | null;
  recommended_year: number | null;
  worst_line_loading_pct: number | null;
  readiness_rationale: string;
  lon: number | null;
  lat: number | null;
  applicant: string;
  scheduled_year: number | null;
  against_recommendation: boolean;
}

export interface PhaseResult {
  accepted: string[];
  worst_line_loading_pct: number;
  worst_trafo_loading_pct: number;
  min_vm_pu: number;
  max_vm_pu: number;
  overloaded_line_ids: number[];
  line_loading: Record<string, number>;
  bus_vm: Record<string, number>;
  voltage_violation_bus_ids: number[];
  gsp_export_mw: number;
  gsp_import_mw: number;
  gsp_limit_mw: number | null;
  n1_screened: number;
  n1_violations: N1Violation[];
}

/** One finding of the single-outage (N-1) screen of the 132 kV backbone. */
export interface N1Violation {
  outage_type: "line" | "trafo";
  outage_id: number;
  outage_name: string;
  type: string; // "line" | "trafo" | "voltage" | "islanded" | "non_convergent"
  element_id: number | null;
  value: number | null;
  message: string;
}

export interface OptimizeResult {
  params: {
    growth_2030: number;
    growth_2035: number;
    scenario: string;
    w_readiness: number;
    w_need: number;
    w_strategic: number;
  };
  queue: QueueItem[];
  phases: Record<PhaseKey, PhaseResult>;
  justification: string;
  snapshot_id: string;
  branch_id: string;
}

export interface Forecast {
  id: string;
  label: string;
  description: string;
  growth_2030: number;
  growth_2035: number;
  source: string;
  cited: boolean;
}

export type BranchStatus = "open" | "merged" | "discarded";
export interface Branch {
  branch_id: string;
  name: string;
  parent_id: string | null;
  scenario: string;
  growth_2030: number;
  growth_2035: number;
  status: BranchStatus;
  created_at: string;
  merged_at: string | null;
  n_added: number;
}

/** A registry (projected) project, or a project added to a branch, as the API shapes it. */
export interface RegistryItem {
  request_id: string;
  applicant: string;
  bus_id: number | null;
  technology: string | null;
  rating_mw: number | null;
  readiness_score: number;
  strategic_fit?: number;
  readiness_rationale?: string;
  status: "valid" | "rejected";
  review_reasons?: string;
  commissioning_year?: number | null;
  branch_id?: string;
  manual?: boolean;
}

export interface NewCandidate {
  applicant: string;
  bus_id: number;
  technology: Tech;
  rating_mw: number;
  readiness_score: number;
  readiness_rationale: string;
  branch_id: string;
  manual?: boolean;
}

export interface TransmissionProject {
  name: string;
  mw: number;
  type: string;
  status: string;
  year: number;
  at: string;
  source: string;
  registry_id: string | null;
}
export interface Boundary {
  gsp_name: string;
  sgt_count: number;
  export_limit_mw: number;
  firm_export_mw: number;
  import_limit_mw: { winter: number; summer: number };
  source: string;
  export_today_mw: number;
  transmission_projects: TransmissionProject[];
}

export type Change =
  | "accelerated"
  | "slipped"
  | "moved_up"
  | "moved_down"
  | "added"
  | "dropped"
  | "unchanged";
export interface ProjectDelta {
  request_id: string;
  technology: string | null;
  rating_mw: number | null;
  bus_id: number | null;
  base_status: Status | null;
  head_status: Status | null;
  base_rank: number | null;
  head_rank: number | null;
  rank_delta: number | null;
  change: Change;
  head_reason: Reason | null;
}
export interface PhaseDelta {
  phase: string;
  worst_line_delta: number;
  worst_trafo_delta: number;
  min_vm_delta: number;
  max_vm_delta: number;
  newly_overloaded_line_ids: number[];
  cleared_line_ids: number[];
  mw_connected_base: number;
  mw_connected_head: number;
  mw_connected_delta: number;
}
export interface Diff {
  base_label: string;
  head_label: string;
  headline: Record<string, number>;
  projects: ProjectDelta[];
  phases: PhaseDelta[];
  base_branch: string;
  head_branch: string;
  narration: string;
}

export interface Suggestion {
  target_type: string;
  target_element_id: number;
  action: string;
  reinforcements: { kind: string; element_id: number; action: string; factor: number }[];
  connects_target: boolean;
  freed_mw_2030: number;
  freed_mw_2035: number;
  newly_connected_project_ids: string[];
  blocked_project_ids: string[];
  extra_solves: number;
  caveat: string;
  narration: string;
}

// ---- view types ---------------------------------------------------------------------------

export type HitKind = "project" | "existing" | "trafo" | "bus" | "load" | "line";
export interface Hit {
  kind: HitKind;
  id: number | string;
}
export type Sel =
  | { kind: "project"; id: string }
  | { kind: "line"; id: number }
  | { kind: "bus"; id: number }
  | { kind: "trafo"; id: number };
export type Tab = "queue" | "alerts" | "compare";
export type SortKey = "rank" | "id" | "mw" | "ready" | "status";

export interface FormState {
  name: string;
  tech: Tech;
  mw: string;
  bus: string;
  land: boolean;
  planning: boolean;
  finance: boolean;
  readiness: number;
}

/** A background engine run (POST /branches/{id}/optimize/jobs, GET /jobs/{id}). */
export interface Job {
  job_id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed";
  stage: string;
  fraction: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  elapsed_ms: number;
  result?: OptimizeResult | null;
  error?: string | null;
}

export interface RunParams {
  g30: number;
  g35: number;
  scenario: string;
  branch: string;
  n: number;
}
