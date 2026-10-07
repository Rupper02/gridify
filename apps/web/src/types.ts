// Wire types for the GridForge API (apps/api) and the planner's own view types.

export type Status = "Phase1" | "Phase2" | "Deferred" | "Rejected";
/** Engine technology ids (see theme.TECH for labels, icons and study treatment). */
export type Tech = "solar" | "wind" | "battery" | "hybrid" | "gas" | "gas_engine" | "biomass" | "electrolyser" | "demand" | "other";
export type PhaseKey = string;

export interface Bus {
  bus_id: number;
  name: string;
  vn_kv: number;
  lon: number;
  lat: number;
  /** Where it is, by name (the engine's `naming`, the same the agents use); absent on an older model. */
  place?: string;
  /** The voltage band the engine judges this bus against: the grid's own limits at its level (`network.voltage_limits`). */
  vmin_pu: number;
  vmax_pu: number;
}
export interface Line {
  line_id: number;
  line_name: string;
  /** What people call it (the engine's `naming`): the places it joins, parallel circuits numbered. */
  display_name?: string;
  rating_a: number;
  voltage_kv: number;
  from_bus?: number;
  to_bus?: number;
  from_lon: number;
  from_lat: number;
  to_lon: number;
  to_lat: number;
  length_km?: number;
  /** False: an open point (in the model, carrying nothing). */
  in_service: boolean;
}
export interface Transformer {
  trafo_id: number;
  name: string;
  /** What people call it (the engine's `naming`): its substation and ratio, parallel units numbered. */
  display_name?: string;
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
  /** `wgs84` when the positions are real; `synthetic` when the file carried none and this is a layout. */
  crs?: "wgs84" | "synthetic";
}

/** A demand group's level: a primary substation (or a customer's own connection), or a bulk supply
 * point over the primaries it feeds (its demand is theirs, never counted twice). */
export type RegionLevel = "primary" | "bsp";

/** A demand group (one LTDS Table 3 row: a primary, or a BSP's own 33 kV group), GET /model. */
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
export type ReasonKind = "grid" | "intake";
/** The engine reason, normalised for the UI: what kind of block, which element, why, what to do. */
export interface Reason extends RawReason {
  kind: ReasonKind;
  element: { line_id?: number; bus_id?: number } | null;
  short: string;
  why: string;
  action: string;
}

export interface QueueItem {
  rank: number | null;
  request_id: string;
  bus_id: number | null;
  technology: string | null;
  rating_mw: number | null;
  import_mw?: number | null;
  /** The control mode the run used (from the branch's stored project); null: not stated, unity power factor. */
  control?: Control | null;
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

/** One finding of the single-outage (N-1) screen of the 132 kV backbone, in one study case. */
export interface N1Violation {
  outage_type: "line" | "trafo";
  outage_id: number;
  outage_name: string;
  /** The study case the outage was screened in (islanded findings: the first case only). */
  case: string | null;
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
  /** The study cases the N-1 screen ran in (the engine's N1_CASES, those the network supports). */
  n1_cases: string[];
  n1_screened: number;
  n1_violations: N1Violation[];
  /** Every figure above is the worst of the study cases: which case set each element's (case -> ids), and the export's. */
  envelope_case?: Record<string, { lines?: number[]; trafos?: number[]; buses?: number[] }>;
  gsp_case?: string | null;
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

// "unstudied": the window's season needs a study case this grid cannot run (engine maintenance._missing)
export type Verdict = "unstudied" | "feasible" | "curtailment" | "demand_at_risk" | "not_feasible";
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
  /** The second faults the window adds, worst first (the screen's own findings, with their case). */
  violations: N1Violation[];
  second_fault_at_risk_mw: number;
  /** The worst finding in words (ids; name them with nameElements). */
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
  /** An imported grid's forecast: its multiplier on today's peak, by plan year (absent on the FES pathways). */
  curve?: Record<string, number>;
}

/** A policy horizon the engine's phases end at (config.HORIZONS: Clean Power 2030, the 2035 strategic window). */
export interface Horizon {
  year: number;
  key: string;
  label: string;
  note: string;
}

export type BranchStatus = "open" | "merged" | "discarded";
export interface Branch {
  branch_id: string;
  name: string;
  parent_id: string | null;
  /** The project the branch belongs to (every project has its own main). */
  project_id?: string | null;
  scenario: string;
  growth_2030: number;
  growth_2035: number;
  status: BranchStatus;
  created_at: string;
  merged_at: string | null;
  n_added: number;
  /** How many things (projects, works windows, reinforcements, the profile) its parent changed since an open branch was
   * opened or last rebased that it lacks: a merge would undo them, so it is rebased first. null: not known. */
  behind?: number | null;
  /** Where the branch's fork point comes from (null on a main or a closed branch). */
  fork?: ForkKind | null;
}

/** recorded when the branch was opened; rebuilt from main's merge history (an older branch; the demand profile then
 * unknown); none: no common starting point is known, so every difference is the operator's to pick. */
export type ForkKind = "recorded" | "rebuilt" | "none";

/** One difference between two states of a branch (rebase.py `Change`). */
export interface RebaseChange {
  point: string;
  element_kind: string | null;
  element_id: string | null;
  text: string;
}

export type RebasePick = "parent" | "branch" | "both";

/** Something both the parent and the branch changed: the operator picks a side (never picked for them). */
export interface RebaseConflict {
  id: string;
  element_kind: string | null;
  element_id: string | null;
  text: string;
  parent: string;
  branch: string;
  options: RebasePick[];
  /** A project's clashing fields, picked together. */
  fields: string[];
}

/** What rebasing a branch onto its parent as it is now would do (`GET /branches/{id}/rebase`). */
export interface RebasePreview {
  branch_id: string;
  onto: string;
  fork: ForkKind;
  up_to_date: boolean;
  /** How many things the parent changed that the branch lacks (one resize and the import that follows it count once). */
  n_behind: number;
  parent_changes: RebaseChange[];
  own_changes: RebaseChange[];
  behind: RebaseChange[];
  conflicts: RebaseConflict[];
}

/** How a project runs, as its connection offer sets it (types.Control): a fixed power factor, or voltage control
 * (a setpoint at its terminals within a reactive range given as a power factor at full output). */
export interface Control {
  mode: "pf" | "voltage";
  pf?: number | null;
  absorbing?: boolean;
  vm_pu?: number | null;
  q_range_pf?: number | null;
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
  status: "valid" | "incomplete";
  review_reasons?: string;
  commissioning_year?: number | null;
  branch_id?: string;
  /** How its offer runs it; null: not stated (modelled at unity power factor). */
  control?: Control | null;
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
  /** Outages with no credible post-fault steady state: one finding each, so the counts above understate them. */
  n1_collapse_base?: number;
  n1_collapse_head?: number;
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
export type WorkChange = "worse" | "better" | "unchanged" | "unstudied";
/** One of the branch's planned works windows, studied on main's plan and on the branch's (engine: diff.WorkDelta). */
export interface WorkDelta {
  outage_id: string;
  year: number;
  work: string;
  with_ids: string[];
  verdict_on_main: Verdict | null;
  verdict_on_branch: Verdict;
  curtailed_mw_main: number | null;
  curtailed_mw_branch: number;
  demand_at_risk_mw_main: number | null;
  demand_at_risk_mw_branch: number;
  /** Second faults during the window on each side; null where that side was not screened. */
  n1_findings_main: number | null;
  n1_findings_branch: number | null;
  /** Second-fault findings the branch adds during the window, worst first, and those it clears. */
  n1_new: N1Violation[];
  n1_cleared: N1Violation[];
  change: WorkChange;
  /** main schedules this window too; false = the branch adds it (its cost is new, whatever `change` says). */
  on_base: boolean;
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
export type Tab = "ask" | "queue" | "outages" | "limits" | "review";
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
  /** Counts up with every partial the job published; a poll passes the one it saw (`?since=`) and gets no copy of it. */
  partial_version?: number;
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

// ---- what limits a branch (engine limits.py, API GET /branches/{id}/limits): the engine's own reduction of a run ----
/** One plan year's envelope figure for an element, and the study case that set it. */
export interface LimitPoint {
  year: number;
  value: number;
  case: string | null;
}
/** An element that binds or comes near its limit in some plan year: its trajectory, the first years it nears and
 * breaches, the projects it holds back and the N-1 outages whose post-fault state breaches it. */
export interface ElementBinding {
  kind: "line" | "trafo" | "bus";
  element_id: number;
  name: string;
  unit: "%" | "pu";
  limit: number;
  trajectory: LimitPoint[];
  first_near_year: number | null;
  first_breach_year: number | null;
  worst: LimitPoint;
  headroom_mw: number | null;
  rating_mva: number | null;
  /** Request ids deferred with this element as their reason. */
  holds_back: string[];
  /** Distinct (outage, case) pairs whose post-fault state breaches it. */
  n1_outages: number;
  severity: "breach" | "near" | "ok";
}
/** A deferred project and the chain of what stops it, in queue order; `studied` when the engine probed what it would take. */
export interface Chain {
  request_id: string;
  technology: string | null;
  rating_mw: number | null;
  bus_id: number | null;
  reason_type: string;
  element_kind: string | null;
  element_id: number | null;
  element_name: string;
  value: number | null;
  limit: number | null;
  case: string | null;
  phase: string;
  first_near_year: number | null;
  message: string;
  fits_mw: number | null;
  chain_connects: boolean | null;
  best_move: { bus_id: number; name: string; mw: number; case: string | null } | null;
  studied: boolean;
}
/** An N-1 cause: one weak link many outages overload, an island, or an outage with no post-fault steady state. The key
 * names the element ("line:12", "voltage:19" for a bus), the island's buses or the collapsing outage. */
export interface Cluster {
  kind: "weak_link" | "island" | "collapse";
  key: string;
  label: string;
  n_rows: number;
  outages: string[];
  cases: string[];
  years: number[];
  worst: number | null;
  unit: string;
}
/** A planned works window's verdict in its year. */
export interface WorkVerdict {
  outage_id: string;
  element: string;
  year: number;
  verdict: Verdict | string;
  curtailed_mw: number;
  demand_at_risk_mw: number;
  n1_findings: number | null;
}
export interface Limits {
  years: number[];
  binding: ElementBinding[];
  chains: Chain[];
  clusters: Cluster[];
  works: WorkVerdict[];
  n1_rows: number;
  n1_pairs: number;
}

// ---- the agents (API agents/, routes /projects/{pid}/agents, threads, approvals, the run note, steps) ----
/** starting: the API's runtime is not launched yet (the key is required, so there is no "off"). */
export type AgentsState = "starting" | "idle" | "running" | "paused";
/** What the agents spent on a project: OpenRouter's billed credits (US dollars) today and in all. Shown, never a cap. */
export interface AgentsSpend {
  day: string;
  credits: number;
  tokens: number;
  solves: number;
  total_credits: number;
  paused: boolean;
  paused_reason: string;
}
export interface AgentsStatus {
  status: AgentsState;
  launched: boolean;
  paused_reason?: string;
  running: number;
  spend: AgentsSpend | null;
  last_events: { event_id: string; type: string; dedup_id: string; created_at: string; workflow_ids: string[] }[];
  models: Record<string, string>;
  project_id: string;
}
/** A conversation: the operator's ("ask", on a branch or on main). */
export interface Thread {
  thread_id: string;
  project_id: string;
  branch_id: string | null;
  title: string;
  kind: "ask" | string;
  created_at: string;
  updated_at: string | null;
}
export type MessageStatus = "queued" | "streaming" | "done" | "failed" | "awaiting_approval" | "cancelled";
export interface TraceStep {
  step_id: string;
  tool: string;
  /** The planning stage the API tagged it with (streaming.stage_of); absent on replies stored before it did. */
  stage?: TraceStage;
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
export type ApprovalStatus = "pending" | "approved" | "denied" | "applied" | "failed";
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
/** The planning stages a reply goes through: the API tags every tool event with one (streaming.STAGE_BY_TOOL_PREFIX). */
export type TraceStage = "PLAN" | "ASSEMBLE" | "RUN" | "CHECK" | "PROPOSE" | "CITE";
/** One server-sent event of a streamed reply. */
export type TraceEvent =
  | { t: "token"; text: string; seq?: number }
  | { t: "tool_call"; tool: string; stage: TraceStage; step_id: string; args: Record<string, unknown>; seq?: number }
  | { t: "tool_result"; tool: string; stage: TraceStage; step_id: string; summary: string; solves: number; seq?: number }
  | { t: "progress"; tool: string; step_id: string; stage: string; fraction: number; seq?: number }
  | { t: "cite"; stage: "CITE"; seq?: number }
  | { t: "final"; status: MessageStatus; text?: string; approvals?: string[]; flags?: string[]; seq?: number }
  | { t: "error"; message: string; seq?: number };
/** One agent run (GET /projects/{pid}/agents/runs, newest first): who ran, on what, for how long and at what cost.
 * `digest`: the one model call that writes a branch's note after a run; `answer`: a reply in a conversation. */
export type AgentRunKind = "answer" | "digest" | string;
export type AgentRunStatus = "queued" | "running" | "done" | "failed" | "skipped" | "skipped_paused" | "cancelled" | string;
export interface AgentRun {
  run_id: string;
  project_id: string;
  kind: AgentRunKind;
  agent: string;
  workflow_id: string | null;
  branch_id: string | null;
  thread_id: string | null;
  event_id: string | null;
  parent_run_id: string | null;
  status: AgentRunStatus;
  started_at: string | null;
  finished_at: string | null; // null while it runs
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_credits: number | null;
  solves: number | null;
  summary: string | null;
  error: string | null;
}
/** The engineer's note on one run of a branch (GET /branches/{id}/note): one model call restating the engine's digest
 * of the run, written a few seconds to a minute after the run lands; `superseded` once a newer run has one. */
export interface RunNote {
  note_id: string;
  branch_id: string;
  /** The physics the note is of (`OptimizeResult.run_key`): the planner tells an earlier run's note by it. */
  run_key: string;
  run_id: string;
  /** Markdown, at most 150 words, no step ids. */
  body: string;
  digest: Record<string, unknown>;
  /** Figures in the body that appear in no tool output ("figure 98765.4 appears in no tool output of this conversation"). */
  flags: string[];
  status: "current" | "superseded";
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
  /** The engine fingerprint that computed the step's cached result (null: no cached result). */
  engine: string | null;
  current_engine: string;
  /** Computed by another engine than the current one: its figures may differ from a run now. */
  stale: boolean;
}

// ---- projects (API projects.py, routes /projects) ----
/** What a project can do; the planner hides what a project cannot (no boundary card, no Demand layer, no registry). */
export interface Capabilities {
  boundary: boolean;
  regions: boolean;
  registry: boolean;
  editions: boolean;
  summer_case: boolean;
  crs: "wgs84" | "synthetic";
}
/** Something the model assumes or could not provide, stated: a builder fallback, an operator-entered limit, a gap in a file. */
export interface Assumption {
  key: string;
  message: string;
  source: "engine-default" | "operator-entered" | "file" | string;
  element_kind: string | null;
  count: number | null;
  element_ids: (number | string)[];
}
/** The import's validation: structural checks and one power flow, what can be studied, what was assumed. */
export interface ImportReport {
  ok: boolean;
  errors: string[];
  warnings: string[];
  counts: Record<string, number>;
  islands: number;
  converged: boolean;
  feasible: boolean | null;
  reason: string | null;
  cases: string[];
  assumptions: Assumption[];
}
/** A voltage level of a file about to be imported: its buses and what an N-1 screen from it down covers. */
export interface FileLevel {
  kv: number;
  buses: number;
  n1_lines: number;
  n1_trafos: number;
}
/** A named set of voltage limits the import form offers (`vmin`, `vmax` in pu, by the lowest kV they apply from). */
export interface BandPreset {
  id: string;
  label: string;
  note: string;
  bands: { min_kv: number; max_kv: number | null; vmin_pu: number; vmax_pu: number }[];
}
/** A demand pathway an import's forecast stands in for (engine `IMPORT_PATHWAYS`), named as the picker names it. */
export interface ImportPathway {
  id: string;
  label: string;
  required: boolean;
}
export interface FileInspection {
  levels: FileLevel[];
  presets: BandPreset[];
  pathways: ImportPathway[];
  /** An entered year-on-year factor is above 0 and at most this (engine `IMPORT_FORECAST_FACTOR_MAX`). */
  factor_max: number;
}
/** A grid source kind (engine `sources.SOURCES`): its label, extensions, and whether the import form offers it. */
export interface ImportFormat {
  kind: string;
  label: string;
  extensions: string[];
  offered: boolean;
}
export interface ImportFormats {
  formats: ImportFormat[];
  max_bytes: number;
}
export interface Project {
  project_id: string;
  name: string;
  source_kind: string;
  snapshot_id: string;
  created_at: string;
  main_id: string;
  builtin: boolean;
  file_name: string | null;
  meta: Record<string, unknown> | null;
  capabilities: Capabilities;
  report: ImportReport | null;
}
