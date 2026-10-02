// The planner's state shape and the small core every planner hook shares: the state, a way to patch
// it, a ref to its latest value, the map handle and the toast. Each hook (run, branches, registry,
// selection, project form) takes a `Core` plus only the other hooks' actions it needs.

import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";

import type {
  Boundary,
  Branch,
  Diff,
  Forecast,
  FormState,
  Hit,
  Model,
  OptimizeResult,
  RegistryItem,
  RunParams,
  Sel,
  SortKey,
  Status,
  Suggestion,
  Tab,
} from "../../types";

export interface MapApi {
  fit(anim: boolean): void;
  zoomBy(d: number): void;
  focusOn(ll: [number, number] | null, kMin?: number): void;
  zoomedIn(): boolean;
}

export interface PlannerState {
  model: Model | null;
  cands: RegistryItem[];
  forecasts: Forecast[];
  forecastId: string;
  g30: number;
  g35: number;
  maxMw: number;
  boundary: Boundary | null;
  result: OptimizeResult | null;
  prevStatus: Record<string, Status>;
  lastParams: RunParams | null;
  running: boolean;
  step: number;
  stage: string; // what the engine is doing right now (from the job's progress)
  runId: number;
  tab: Tab;
  filter: "All" | Status;
  sortKey: SortKey;
  sortDir: 1 | -1;
  grouped: boolean;
  query: string;
  hover: Hit | null;
  mouse: { x: number; y: number };
  sel: Sel | null;
  size: { w: number; h: number };
  loadingMode: boolean;
  voltageMode: boolean;
  showLoads: boolean;
  showLabels: boolean;
  legendHidden: boolean;
  showBoundary: boolean;
  drawer: boolean;
  pickMode: boolean;
  toast: string | null;
  timelineYear: number;
  diff: Diff | null;
  comparing: boolean;
  branches: Branch[];
  branchesLoaded: boolean;
  activeBranch: string;
  showNewBranch: boolean;
  newBranchName: string;
  newBranchForecast: string;
  creatingBranch: boolean;
  registry: RegistryItem[];
  registryLoaded: boolean;
  showRegistry: boolean;
  registryQuery: string;
  pendingAdds: Record<string, true>;
  suggestions: Suggestion[] | null;
  loadingSuggestions: boolean;
  form: FormState;
}

export const INITIAL: PlannerState = {
  model: null, cands: [], forecasts: [], forecastId: "ht", g30: 1.08, g35: 1.35, maxMw: 300, boundary: null,
  result: null, prevStatus: {}, lastParams: null, running: false, step: 0, stage: "", runId: 0,
  tab: "queue", filter: "All", sortKey: "rank", sortDir: 1, grouped: false, query: "",
  hover: null, mouse: { x: 0, y: 0 }, sel: null, size: { w: 0, h: 0 },
  loadingMode: false, voltageMode: false, showLoads: true, showLabels: false, legendHidden: false, showBoundary: false,
  drawer: false, pickMode: false, toast: null, timelineYear: 2035,
  diff: null, comparing: false,
  branches: [], branchesLoaded: false, activeBranch: "main", showNewBranch: false,
  newBranchName: "", newBranchForecast: "ht", creatingBranch: false,
  registry: [], registryLoaded: false, showRegistry: false, registryQuery: "", pendingAdds: {},
  suggestions: null, loadingSuggestions: false,
  form: { name: "", tech: "solar", mw: "5", bus: "", land: true, planning: false, finance: false, readiness: 0.4 },
};

export type Patch = Partial<PlannerState> | ((st: PlannerState) => Partial<PlannerState>);

/** What a hook needs from the planner: patch the state, read its latest value, drive the map, toast. */
export interface Core {
  patch: (p: Patch) => void;
  /** The latest state, for async flows that must not read a stale closure. */
  ref: MutableRefObject<PlannerState>;
  mapApi: MutableRefObject<MapApi | null>;
  toastMsg: (t: string) => void;
}

/** Create the planner state and its core. */
export function useCore(): { s: PlannerState; core: Core } {
  const [s, setS] = useState<PlannerState>(INITIAL);
  const ref = useRef(s);
  ref.current = s;
  const patch = useCallback((p: Patch) => setS((st) => ({ ...st, ...(typeof p === "function" ? p(st) : p) })), []);
  const mapApi = useRef<MapApi | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);

  const toastMsg = useCallback(
    (t: string) => {
      window.clearTimeout(toastTimer.current);
      patch({ toast: t });
      toastTimer.current = window.setTimeout(() => patch({ toast: null }), 3200);
    },
    [patch],
  );
  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  return { s, core: { patch, ref, mapApi, toastMsg } };
}
