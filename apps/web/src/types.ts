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
  length_km?: number;
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

/** GET /boundary: the GSP's export limit to transmission and today's export. */
export interface Boundary {
  gsp_name: string;
  export_limit_mw: number;
  firm_export_mw?: number;
  export_today_mw: number;
  [k: string]: unknown;
}

export interface Pathway {
  id: string;
  label: string;
  short: string;
  description: string;
  source: string;
  curve: Record<string, number> | null;
}
/** GET /forecasts. */
export interface Forecasts {
  default: string;
  forecasts: Pathway[];
  plan_years: number[];
  max_connection_mw: number;
  import_only_techs: string[];
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
  type: "voltage" | "line" | "trafo" | "gsp" | "non_convergent" | string;
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
  snapshot_id: string;
  params: PlanParams;
  connections: (Connection & { lon: number | null; lat: number | null })[];
  years: Record<string, YearResult>;
}

export interface Job {
  job_id: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  stage: string;
  fraction: number;
  error: string | null;
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

// ---- the planner's view ------------------------------------------------------------------------------
export type MapLayer = "flow" | "loading" | "voltage";
export type Tab = "connections" | "limits" | "compare";

/** What is selected on the map or in a list. */
export type Sel =
  | { kind: "line"; id: number }
  | { kind: "trafo"; id: number }
  | { kind: "bus"; id: number }
  | { kind: "gen"; id: string }
  | { kind: "connection"; id: string };
