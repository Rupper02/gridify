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
  /** The demand group (LTDS Table 3 row) this load belongs to; absent on an older warehouse. */
  region_id?: string | null;
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
  /** The demand groups as they stand today (before growth); empty on a warehouse that predates them. */
  regions?: Region[];
}

/** A demand group (one LTDS Table 3 row: a primary, or a BSP's own 33 kV group), GET /model. */
/** A demand group's level: a primary substation (or a customer's own connection), or a bulk supply
 * point over the primaries it feeds (its demand is theirs, never counted twice). */
export type RegionLevel = "primary" | "bsp";

export interface Region {
  region_id: string;
  name: string;
  bsp: string;
  level: RegionLevel;
  /** Where it sits: its loads' buses (a primary) or the BSP's own busbars. */
  buses: number[];
  firm_mw: number;
  firm_mva: number | null;
  base_demand_mw: number;
  peak_demand_mw: number;
  p2_class: string;
}

/** One demand group in one plan year, judged by a simplified P2/8-style check (engine: demand.py). */
export interface RegionYear {
  region_id: string;
  name: string;
  bsp: string;
  demand_mw: number;
  modelled_mw: number;
  firm_mw: number;
  headroom_mw: number;
  p2_class: string;
  n1_at_risk_mw: number;
  /** The single 132 kV outage that strands the most demand, e.g. "line 13". */
  n1_outage: string | null;
  voltage_violation_bus_ids: number[];
  worst_vm_pu: number | null;
  worst_vm_limit_pu: number | null;
  /** First-order (≈) room for new demand: min(firm headroom, winter transformer spare). */
  demand_room_mw: number | null;
}

export type AlertKind = "firm_capacity" | "n1_stranded" | "voltage" | "headroom";
export type AlertLevel = "warn" | "breach";
/** A demand-side warning for one group in one year (engine: demand.ALERT_CHECKS). */
export interface Alert {
  kind: AlertKind | string;
  level: AlertLevel;
  region_id: string;
  year: number;
  value: number | null;
  limit: number | null;
  message: string;
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
  /** Islanded findings: the buses the outage cuts off. */
  islanded_bus_ids?: number[];
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
  work: Work;
  /** The other windows of the same season and year, studied together with this one. */
  with_ids: string[];
  verdict: Verdict;
  demand_at_risk_mw: number;
  /** Generation constrained to hold the limits ("curtailment" only; a first-order estimate). */
  curtailment: Curtailment[];
  curtailed_mw: number;
  /** The N-1 screen with the window in place (informational); null when the year had no screen. */
  n1_during: N1During | null;
  /** What the work leaves behind once the window is over. */
  after: string;
}

export type Verdict = "feasible" | "curtailment" | "demand_at_risk" | "not_feasible";
/** Generation constrained during a window: a fleet id (EX-...) or a project request id. */
export interface Curtailment {
  id: string;
  name: string; // its technology
  mw: number;
  case: string;
}
/** The N-1 screen of the backbone with a window in place (informational, never a gate). */
export interface N1During {
  cases: string[];
  screened: number;
  findings: number;
  second_fault_at_risk_mw: number;
  worst: string;
}

/** The plan as it stands in one year (engine: years.evaluate_year). */
export interface YearResult extends PhaseResult {
  converged?: boolean; // false when a study case did not converge that year
  year: number;
  growth: number;
  energised: string[];
  trafo_loading: Record<string, number>;
  outage_studies: OutageStudy[];
  /** The demand side: every demand group this year, and its alerts (breaches first). */
  regions?: RegionYear[];
  alerts?: Alert[];
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
  /** The identity of this result's physics (the plan-years cache key): what a review or an agent event refers to. */
  run_key: string;
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
  /** What the window is for: maintenance returns the element as it was, replacement like-for-like,
   * repowering with a new capability from the following year (the queue run does not see it). */
  work: Work;
  repower: Repower | null; // repowering only
  factor: number | null; // repowering by uprate only: the rating multiplier (1 < factor <= 4)
  created_at?: string;
}

/** Find the best window for a planned work (API: POST /branches/{id}/works/best-window). */
export interface BestWindowRequest {
  element_kind: ElementKind;
  element_id: string;
  work: Work;
  kind: "outage" | "derate";
  repower?: Repower | null;
  factor?: number | null;
  weeks: number;
  years?: [number, number];
  seasons?: Season[];
}
/** One ranked window (engine: windows.best_windows), studied against the plan that year. */
export interface WindowOption {
  rank: number;
  year: number;
  season: Season;
  verdict: Verdict;
  curtailed_mw: number;
  demand_at_risk_mw: number;
  /** null: not screened (outside the engine's N-1 shortlist). */
  n1_findings: number | null;
  worst_line_loading_pct: number;
  worst_trafo_loading_pct: number;
  message: string;
}
export interface BestWindowResult {
  branch_id: string;
  element_kind: ElementKind;
  element_id: string;
  work: Work;
  options: WindowOption[];
}
export type Work = "maintenance" | "repowering" | "replacement";
export type Repower = "uprate" | "add_parallel";

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
/** As OutageStudy.verdict. */
export type WorkVerdict = Verdict;
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
  /** What merging replaces in the base: the planned works and reinforcements it adds and removes. */
  on_merge?: OnMerge;
  base_branch: string;
  head_branch: string;
  narration: string;
}

export interface OnMerge {
  works_added: Outage[];
  works_removed: Outage[];
  reinforcements_added: BranchReinforcement[];
  reinforcements_removed: BranchReinforcement[];
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
  | { kind: "gen"; id: string }
  | { kind: "region"; id: string };
/** The network elements (the element card): not a project, not a demand region. */
export type ElementSel = Exclude<Sel, { kind: "project" } | { kind: "region" }>;
export type Tab = "ask" | "queue" | "outages" | "findings" | "review";
export type MapLayer = "flow" | "loading" | "voltage" | "demand";

/** A background engine run (POST /branches/{id}/optimize/jobs, GET /jobs/{id}). */
export interface Job<R = OptimizeResult> {
  job_id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  stage: string;
  fraction: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  elapsed_ms: number;
  has_partial?: boolean;
  partial?: OptimizeResult | null;
  result?: R | null;
  error?: string | null;
}

// ---- the merge gate and the findings ledger (engine gate.py / findings.py, API /merge-check, /findings) ----
export type GateLevel = "blocker" | "warning" | "info";
/** One reason the gate blocks, warns or notes; its level comes from the engine's policy table. */
export interface GateFinding {
  kind: string;
  level: GateLevel;
  year: number | null;
  case: string | null;
  element_kind: string | null;
  element_id: string | null;
  value: number | null;
  base_value: number | null;
  limit: number | null;
  message: string;
  finding_fingerprint: string | null;
}
export interface MergeVerdict {
  ok: boolean;
  blockers: GateFinding[];
  warnings: GateFinding[];
  context: GateFinding[];
  years_compared: number[];
  summary: string;
}
/** GET /branches/{id}/merge-check: may this branch merge, and on what evidence. */
export interface MergeCheck {
  branch_id: string;
  into: string;
  branch_status: BranchStatus;
  fresh: boolean;
  stale_reasons: string[];
  requires_acknowledgement: boolean;
  verdict: MergeVerdict;
  evidence: Record<string, unknown>;
  checked_at: string;
}
export type FindingSeverity = "breach" | "warn" | "info";
export type FindingStatus = "open" | "acknowledged" | "resolved";
/** One row of the findings ledger (GET /branches/{id}/findings). */
export interface Finding {
  finding_id: string;
  branch_id: string;
  fingerprint: string;
  source: "engine" | "agent" | "operator" | string;
  kind: string;
  severity: FindingSeverity;
  year: number | null;
  case: string | null;
  element_kind: string | null;
  element_id: string | null;
  value: number | null;
  limit: number | null;
  message: string;
  context: Record<string, unknown>;
  status: FindingStatus;
  note: string;
  evidence_kind: string;
  evidence_ref: string;
  evidence: Record<string, unknown>;
  snapshot_id: string | null;
  engine: string | null;
  first_seen_at: string;
  last_seen_at: string;
  acked_at: string | null;
  resolved_at: string | null;
}
export interface FindingCounts {
  open: number;
  acknowledged: number;
  resolved: number;
  breach_open: number;
  warn_open: number;
}

// ---- the agents (API agents/, routes /projects/{pid}/agents, threads, approvals, reviews, steps) ----
export type AgentsState = "off" | "idle" | "running" | "paused";
export interface AgentsBudget {
  day: string;
  credits: number;
  tokens: number;
  solves: number;
  limits: Record<string, number>;
  paused: boolean;
  paused_reason: string;
  exhausted: boolean;
}
export interface AgentsStatus {
  status: AgentsState;
  enabled: boolean;
  launched: boolean;
  reason?: string;
  paused_reason?: string;
  running: number;
  budget: AgentsBudget | null;
  last_events: { event_id: string; type: string; dedup_id: string; created_at: string; workflow_ids: string[] }[];
  models: Record<string, string>;
}
/** A conversation: the operator's ("ask", on a branch or on main) or the project's health thread. */
export interface Thread {
  thread_id: string;
  project_id: string;
  branch_id: string | null;
  title: string;
  kind: "ask" | "health" | string;
  created_at: string;
  updated_at: string | null;
}
export type MessageStatus = "queued" | "streaming" | "done" | "failed" | "awaiting_approval";
export interface TraceStep {
  step_id: string;
  tool: string;
  args: Record<string, unknown>;
  solves: number;
}
export interface MessageEvidence {
  steps: string[];
  branch_id: string | null;
  snapshot_id: string;
  engine: string;
}
export interface ThreadMessage {
  message_id: string;
  thread_id: string;
  seq: number;
  role: "user" | "assistant";
  content: string;
  status: MessageStatus;
  workflow_id: string | null;
  run_id: string | null;
  tool_trace: TraceStep[] | null;
  usage: Record<string, number | null> | null;
  cost_credits: number | null;
  /** Figures in the text that no tool of the run produced (soft: shown, never blocking). */
  flags: string[] | null;
  evidence: MessageEvidence | null;
  created_at: string;
}
export type ApprovalStatus = "pending" | "approved" | "denied" | "applied";
/** An action an answer proposed (a branch, a reinforcement, a works window), waiting for the operator. */
export interface Approval {
  approval_id: string;
  thread_id: string;
  message_id: string;
  run_id: string;
  tool: string;
  args: Record<string, unknown>;
  status: ApprovalStatus;
  note: string | null;
  decided_at: string | null;
  created_at: string;
}
export interface ThreadView extends Thread {
  messages: ThreadMessage[];
  approvals: Approval[];
}
/** The planning stages a reply goes through (the API's streaming.STAGE_BY_TOOL_PREFIX names them). */
export type TraceStage = "PLAN" | "ASSEMBLE" | "RUN" | "CHECK" | "PROPOSE" | "CITE";
/** One server-sent event of a streamed reply. */
export type TraceEvent =
  | { t: "token"; text: string; seq?: number }
  | { t: "tool_call"; tool: string; stage: TraceStage; step_id: string; args: Record<string, unknown>; seq?: number }
  | { t: "tool_result"; tool: string; step_id: string; summary: string; solves: number; seq?: number }
  | { t: "cite"; stage: "CITE"; seq?: number }
  | { t: "final"; status: MessageStatus; text?: string; approvals?: string[]; flags?: string[]; seq?: number }
  | { t: "error"; message: string; seq?: number };
/** A gate finding as the reviewer restates it: identified as the gate gave it, in the reviewer's words. */
export interface ReviewRestated {
  kind: string;
  element_id: string | null;
  fingerprint: string | null;
  restated: string;
}
export type ReviewVerdict = "blocked" | "mergeable_with_warnings" | "mergeable";
/** The reviewer's comment on one run of a branch, like a PR bot's. */
export interface Review {
  review_id: string;
  branch_id: string;
  run_key: string;
  run_id: string;
  verdict: ReviewVerdict;
  gate: { into: string; fresh: boolean; ok: boolean; summary: string; n_context: number };
  body: string;
  blockers: ReviewRestated[];
  warnings: ReviewRestated[];
  not_studied: string[];
  status: "prepared_for_review" | "superseded";
  created_at: string;
}
/** One row of a study (engine studies.STUDIES): an element and a figure, with a stable fingerprint. */
export interface StudyItem {
  index: number;
  element_kind: string;
  element_id: string;
  element_name: string;
  case: string | null;
  year: number | null;
  value: number | null;
  limit: number | null;
  unit: string;
  severity: FindingSeverity;
  message: string;
  fingerprint: string;
  extra: Record<string, unknown>;
}
export interface StudyResult {
  kind: string;
  params: Record<string, unknown>;
  items: StudyItem[];
  solves: number;
  not_studied: string[];
  summary: string;
}
/** The evidence behind a recorded step: the study it ran (re-read from the cache), stale if the engine changed. */
export interface StepEvidence {
  step: { step_id: string; run_id: string; tool: string; args: Record<string, unknown>; cache_key: string | null };
  study: StudyResult | null;
  result: unknown;
  current_engine: string;
  stale: boolean;
}
