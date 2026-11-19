// The API's shapes, as the planner reads them (gridify_optimizer.types and the API's payloads).

// ---- the grid ---------------------------------------------------------------------------------
export interface Bus {
  bus_id: number;
  name: string;
  vn_kv: number;
  lon: number;
  lat: number;
  /** Where it is, by name (the engine's `naming`). */
  place?: string;
  /** The voltage band the engine judges this bus against. */
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
  /** Null where the LTDS gives no length. */
  length_km?: number | null;
  /** False: an open point (in the model, carrying nothing). */
  in_service: boolean;
}
export interface Transformer {
  trafo_id: number;
  name: string;
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
  name: string;
  snapshot_id: string;
  buses: Bus[];
  lines: Line[];
  transformers: Transformer[];
  loads: Load[];
  generators: Generator[];
}

/** GET /forecasts: the plan's years and the largest connection a branch can place. */
export interface Forecasts {
  plan_years: number[];
  max_connection_mw: number;
}

export interface Assumption {
  key: string;
  message: string;
  source: string;
  element_kind: string | null;
  count: number | null;
}

// ---- branches and connections ------------------------------------------------------------------
export interface Branch {
  branch_id: string;
  name: string;
  parent_id: string | null;
  scenario: string;
  growth_2030: number;
  growth_2035: number;
  status: "open" | "merged" | "discarded";
  created_at: string;
  merged_at: string | null;
  n_connections: number;
}

export type Tech = "solar" | "wind" | "battery" | "hybrid" | "gas" | "gas_engine" | "biomass" | "electrolyser" | "demand" | "other";

export interface Control {
  mode: "pf" | "voltage";
  pf?: number | null;
  absorbing?: boolean;
  vm_pu?: number | null;
  q_range_pf?: number | null;
}

/** A connection placed on a branch, energising in `year`. */
export interface Connection {
  request_id: string;
  name: string | null;
  bus_id: number;
  technology: string;
  rating_mw: number;
  import_mw: number | null;
  control: Control | null;
  year: number;
  source: "manual" | "registry" | "carried";
  created_at: string;
}
/** The fields a new connection is placed with. */
export interface ConnectionDraft {
  from_registry?: string;
  name?: string | null;
  bus_id?: number;
  technology?: string;
  rating_mw?: number | null;
  import_mw?: number | null;
  year?: number;
}

/** A not-yet-built project the registry publishes (GET /registry). */
export interface RegistryItem {
  request_id: string;
  name: string;
  bus_id: number | null;
  technology: string | null;
  rating_mw: number | null;
  import_mw: number | null;
  year: number | null;
  note: string;
  complete: boolean;
  review_reasons: string;
}

// ---- results -------------------------------------------------------------------------------------
export type Case = "winter_peak" | "summer_min";

/** One limit breached in a solve. */
export interface Reason {
  type: "voltage" | "line" | "trafo" | "gsp" | "gsp_import" | "non_convergent" | "voltage_collapse" | string;
  element_id: number | null;
  value: number | null;
  limit: number | null;
  message: string;
  case: Case | null;
}

export interface YearResult {
  year: number;
  growth: number;
  energised: string[];
  converged: boolean;
  worst_line_loading_pct: number;
  worst_trafo_loading_pct: number;
  min_vm_pu: number;
  max_vm_pu: number;
  overloaded_line_ids: number[];
  line_loading: Record<string, number>;
  trafo_loading: Record<string, number>;
  bus_vm: Record<string, number>;
  voltage_violation_bus_ids: number[];
  gsp_export_mw: number;
  gsp_import_mw: number;
  gsp_limit_mw: number | null;
  gsp_case: Case | null;
  /** case -> {lines, trafos, buses}: which case set each element's envelope figure. */
  envelope_case: Record<string, Partial<Record<"lines" | "trafos" | "buses", number[]>>>;
  violations: Reason[];
}

export interface PlanParams {
  scenario: string;
  growth_2030: number;
  growth_2035: number;
}

/** A branch's run (POST /branches/{id}/run, GET /branches/{id}/result). */
export interface PlanPayload {
  branch_id: string;
  run_key: string;
  params: PlanParams;
  years: Record<string, YearResult>;
}

export interface Job {
  job_id: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  stage: string;
  fraction: number;
  error: string | null;
  /** why it was stopped, when the API stopped it */
  reason: string | null;
  has_partial: boolean;
  partial_version: number;
  partial?: PlanPayload | null;
  result?: PlanPayload | null;
}

// ---- the comparison --------------------------------------------------------------------------------
export interface LoadingDelta {
  element_id: number;
  base_pct: number | null;
  head_pct: number | null;
  delta: number;
  crossed: "newly_overloaded" | "cleared" | "worsened" | "eased" | "unchanged";
}
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
  violations_base: number;
  violations_head: number;
  new_violations: Reason[];
  cleared_violations: Reason[];
  newly_overloaded_line_ids: number[];
  cleared_line_ids: number[];
  newly_overloaded_trafo_ids: number[];
  cleared_trafo_ids: number[];
  top_line_deltas: LoadingDelta[];
  top_trafo_deltas: LoadingDelta[];
  energised_only_head: string[];
  energised_only_base: string[];
}
export interface PlanDiff {
  base: string;
  headline: {
    years_compared: number;
    years_with_new_violations: number;
    years_with_cleared_violations: number;
    first_year_with_new_violations: number | null;
    worst_line_delta: number;
    gsp_export_delta: number;
  };
  years: Record<string, YearDelta>;
}

// ---- measured and grown years (GET /runs): the year view ------------------------------------------------
export interface RunInfo {
  run_id: string;
  label: string;
  kind: "measured" | "grown";
  year: number;
  pathway: string | null;
  available: boolean;
  make: string;
  limits: string;
  /** a grown year a branch's year can be run on (and compared with) */
  base: boolean;
  /** a branch's year: the catalogued run it is compared with, and the branch it was run for */
  before: string | null;
  branch_id: string | null;
}

export interface RunElement {
  kind: "line" | "trafo";
  element_id: number;
  peak_pct: number;
  peak_at: string;
  h80: number;
  h90: number;
  h100: number;
  label: string;
  offset_mw: number | null;
  offset_pct: number | null;
  finding: boolean;
  label_year: number | null; // the measured year the agreement label was judged on
}

export interface RunBus {
  bus_id: number;
  hours_outside: number;
  vmin_pu: number;
  vmax_pu: number;
  finding: boolean;
}

export interface RunSubstation {
  name: string;
  bus_id: number;
  firm_mva: number;
  peak_mva: number;
  peak_at: string;
  hours_above_firm: number;
}

export interface RunSummary {
  info: RunInfo;
  half_hours: number;
  solved: number;
  collapsed: number; // of the half-hours not solved, those whose solution was a voltage collapse
  fingerprint: string;
  elements: RunElement[];
  buses: RunBus[];
  substations: RunSubstation[];
  check: string;
}

export interface RunGrid {
  run_id: string;
  kind: "line" | "trafo" | "bus";
  element_id: number;
  /** hours over, per month (rows, January first) and hour of day (columns, 00:00 first) */
  hours: number[][];
}

/** One line or transformer whose year changes with a branch. */
export interface RunChange {
  kind: "line" | "trafo";
  element_id: number;
  peak_before: number;
  peak_after: number;
  h90_before: number;
  h90_after: number;
  h100_before: number;
  h100_after: number;
}

/** A branch's year against its "before" (GET /runs/{id}/compare). */
export interface RunComparison {
  run_id: string;
  before: string;
  year: number;
  in_service: string[];
  voltage_control_at_unity: string[];
  on_slack: string[];
  storage: string[];
  output_peak_mw: number;
  output_energy_gwh: number;
  changed: RunChange[];
  /** the energy above rating on the element the branch puts over for longest: a crude first indication */
  worst: { kind: "line" | "trafo"; element_id: number; hours_above: number; mvah_above: number; largest_mva_above: number } | null;
  /** [bus_id, hours outside before, after] */
  buses: [number, number, number][];
  /** [substation, hours above firm before, after] */
  substations: [string, number, number][];
  export_peak_mw: [number, number];
  import_peak_mw: [number, number];
}

/** A branch's year being solved: the job's progress in the driver's own terms. */
export type YearRunState =
  | { kind: "idle" }
  | { kind: "running"; branchId: string; base: string; stage: string; fraction: number }
  | { kind: "failed"; branchId: string; error: string }
  /** the API stopped it, saying why (a plan run never waits behind a year) */
  | { kind: "stopped"; branchId: string; reason: string };

/** How the year view colours lines and transformers: hours above rating, or peak loading. */
export type RunMetric = "hours" | "peak";

// ---- the planner's view ------------------------------------------------------------------------------
export type MapLayer = "flow" | "loading" | "voltage" | "hours";
export type Tab = "connections" | "limits" | "compare" | "runs";

/** What is selected on the map or in a list. */
export type Sel =
  | { kind: "line"; id: number }
  | { kind: "trafo"; id: number }
  | { kind: "bus"; id: number }
  | { kind: "gen"; id: string }
  | { kind: "connection"; id: string };
