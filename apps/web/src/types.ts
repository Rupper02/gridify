// Wire types for the GridForge API (apps/api) and the planner's own view types.

export type Status = "Phase1" | "Phase2" | "Deferred" | "Rejected";
/** Engine technology ids (see theme.TECH for labels, icons and study treatment). */
export type Tech = "solar" | "wind" | "battery" | "hybrid" | "gas" | "gas_engine" | "biomass" | "electrolyser" | "demand";
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
  from_bus?: number;
  to_bus?: number;
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
  import_mw?: number | null;
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

/** What one planned outage does to its year's network (engine: network.study_outage). */
export interface OutageStudy {
  outage_id: string;
  year: number;
  cases: string[];
  ok: boolean;
  violations: RawReason[];
  worst_line_loading_pct: number;
  worst_trafo_loading_pct: number;
  gsp_export_mw: number;
  message: string;
}

/** The plan as it stands in one year (engine: years.evaluate_year). */
export interface YearResult extends PhaseResult {
  year: number;
  growth: number;
  energised: string[];
  trafo_loading: Record<string, number>;
  outage_studies: OutageStudy[];
}

export interface Studied {
  outage_ids: string[];
  reinforcements: { kind: string; element_id: number; action: string; factor: number }[];
  schedule: Record<string, number>;
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
  /** Every year of the plan, filled progressively while a run is solving. */
  years: Record<string, YearResult>;
  years_total: number;
  studied: Studied;
  justification: string;
  snapshot_id: string;
  branch_id: string;
}

export interface Forecast {
  id: string;
  label: string;
  short: string;
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
  import_mw?: number | null;
  readiness_score: number;
  strategic_fit?: number;
  readiness_rationale?: string;
  status: "valid" | "rejected";
  review_reasons?: string;
  commissioning_year?: number | null;
  branch_id?: string;
}

export interface NewCandidate {
  applicant: string;
  bus_id: number;
  technology: Tech;
  rating_mw: number;
  import_mw: number | null;
  readiness_score: number;
  readiness_rationale: string;
  commissioning_year: number | null;
  branch_id: string;
}

/** A planned maintenance window on a branch (API: /branches/{id}/outages). */
export type Season = "Spring" | "Summer" | "Autumn" | "Winter";
export type ElementKind = "line" | "trafo" | "gen";
export interface Outage {
  outage_id: string;
  element_kind: ElementKind;
  element_id: string;
  season: Season;
  year: number;
  weeks: number;
  kind: "outage" | "derate";
  created_at?: string;
}

/** A simulated reinforcement proposed on a branch (API: /branches/{id}/reinforcements). */
export interface BranchReinforcement {
  reinforcement_id: string;
  kind: string;
  element_id: number;
  action: string;
  factor: number;
  label: string;
  created_at?: string;
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

export type Change = "accelerated" | "slipped" | "moved_up" | "moved_down" | "added" | "dropped" | "unchanged";
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
export type Crossed = "newly_overloaded" | "cleared" | "worsened" | "eased" | "unchanged";
export interface LineDelta {
  line_id: number;
  base_pct: number;
  head_pct: number;
  delta: number;
  crossed: Crossed;
}
/** One line's or transformer's loading in a plan year, main vs the branch (engine: diff.LoadingDelta). */
export interface LoadingDelta {
  element_id: number;
  base_pct: number | null;
  head_pct: number | null;
  delta: number;
  crossed: Crossed;
}
/** An N-1 finding as the engine reports it (outage lost, limit broken). */
export interface N1Finding {
  outage_type: string;
  outage_id: number | string;
  outage_name?: string;
  type: string;
  element_id: number | null;
  value?: number | null;
  message: string;
}
/** The network effect of the branch in one plan year (engine: diff.YearDelta). */
export interface YearDelta {
  year: number;
  worst_line_base: number;
  worst_line_head: number;
  worst_line_delta: number;
  worst_trafo_base: number;
  worst_trafo_head: number;
  worst_trafo_delta: number;
  min_vm_delta: number;
  max_vm_delta: number;
  gsp_export_base: number;
  gsp_export_head: number;
  gsp_export_delta: number;
  gsp_limit_mw: number | null;
  n1_findings_base: number;
  n1_findings_head: number;
  n1_findings_delta: number;
  n1_new: N1Finding[];
  n1_cleared: N1Finding[];
  newly_overloaded_line_ids: number[];
  cleared_line_ids: number[];
  newly_overloaded_trafo_ids: number[];
  cleared_trafo_ids: number[];
  top_line_deltas: LoadingDelta[];
  top_trafo_deltas: LoadingDelta[];
  energised_only_head: string[];
  energised_only_base: string[];
}
export type WorkVerdict = "feasible" | "curtailment" | "demand_at_risk" | "not_feasible";
export type WorkChange = "worse" | "better" | "unchanged" | "unstudied";
/** One of the branch's planned works windows, studied on main's plan and on the branch's (engine: diff.WorkDelta). */
export interface WorkDelta {
  outage_id: string;
  year: number;
  work: string;
  with_ids: string[];
  verdict_on_main: WorkVerdict | null;
  verdict_on_branch: WorkVerdict;
  curtailed_mw_main: number | null;
  curtailed_mw_branch: number;
  demand_at_risk_mw_main: number | null;
  demand_at_risk_mw_branch: number;
  change: WorkChange;
  consequence: string;
  message: string;
}
export interface PhaseDelta {
  phase: string;
  worst_line_delta: number;
  worst_trafo_delta: number;
  min_vm_delta: number;
  max_vm_delta: number;
  newly_overloaded_line_ids: number[];
  cleared_line_ids: number[];
  top_line_deltas: LineDelta[];
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
  /** Every plan year solved on both runs, keyed by year. */
  years: Record<string, YearDelta>;
  /** The branch's planned works: verdict on main's plan vs the branch's. */
  works: WorkDelta[];
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

/** What can be clicked on the map: a project opens the project card, the rest the element card. */
export type Sel =
  | { kind: "project"; id: string }
  | { kind: "line"; id: number }
  | { kind: "trafo"; id: number }
  | { kind: "gen"; id: string };
export type ElementSel = Exclude<Sel, { kind: "project" }>;
export type Tab = "copilot" | "queue" | "outages" | "review";
export type MapLayer = "flow" | "loading" | "voltage";

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
  has_partial?: boolean;
  partial?: OptimizeResult | null;
  result?: OptimizeResult | null;
  error?: string | null;
}
