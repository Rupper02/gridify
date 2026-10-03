// The planner's state shape and the small core every planner hook shares: the state, a way to patch
// it, a ref to its latest value, the map handle and the toast. Each hook (run, branches, registry,
// selection, project edits, maintenance, copilot) takes a `Core` plus only the other hooks' actions
// it needs.

import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";

import type { ChatMsg, Intake } from "../../lib/intake";
import type {
  Boundary,
  Branch,
  BranchReinforcement,
  Diff,
  Forecast,
  MapLayer,
  Model,
  OptimizeResult,
  Outage,
  RegistryItem,
  Season,
  Sel,
  Status,
  Suggestion,
  Tab,
} from "../../types";

export interface MapApi {
  fit(anim: boolean): void;
  zoomBy(d: number): void;
  focusOn(ll: [number, number] | null, kMin?: number): void;
}

/** A Recommendations message: text, plus the engine's levers when it has them. */
export interface RecMsg {
  user: boolean;
  text: string;
  levers?: Suggestion[];
  action?: "run";
  loading?: boolean;
}

export interface ChatState {
  mode: "project" | "recs" | null;
  intake: Intake | null;
  recs: RecMsg[];
  input: string;
  busy: boolean;
  /** Chats started on this branch in this session, newest first. */
  recent: { mode: "project" | "recs"; title: string; at: string }[];
}

export interface MaintDraft {
  season: Season;
  year: number;
  weeks: number;
  kind: "outage" | "derate";
}

export interface PlannerState {
  // data
  model: Model | null;
  forecasts: Forecast[];
  maxMw: number;
  boundary: Boundary | null;
  registry: RegistryItem[];
  registryLoaded: boolean;
  // branches
  branches: Branch[];
  branchesLoaded: boolean;
  activeBranch: string;
  menuOpen: boolean;
  // the branch's own proposals beyond projects
  outages: Outage[];
  reinforcements: BranchReinforcement[];
  /** Projects added per branch since its last run (shown as Preliminary until a run includes them). */
  added: Record<string, RegistryItem[]>;
  // the run
  result: OptimizeResult | null;
  resultAt: string; // when the shown result was solved (HH:MM)
  prevStatus: Record<string, Status>;
  running: boolean; // the overlay: until the queue and the viewed year are in
  solving: boolean; // the job is still solving the remaining years in the background
  stage: string;
  fraction: number;
  runId: number;
  // review
  diff: Diff | null;
  diffMode: boolean;
  suggestions: Suggestion[] | null;
  // view
  tab: Tab;
  sideOpen: boolean;
  layer: MapLayer;
  showDeferred: boolean;
  legendOpen: boolean;
  showBoundary: boolean;
  year: number;
  sel: Sel | null;
  maintDraft: MaintDraft;
  chat: ChatState;
  toast: { text: string; tone: "ok" | "warn" } | null;
}

export const EMPTY_CHAT: ChatState = { mode: null, intake: null, recs: [], input: "", busy: false, recent: [] };

export const INITIAL: PlannerState = {
  model: null, forecasts: [], maxMw: 300, boundary: null, registry: [], registryLoaded: false,
  branches: [], branchesLoaded: false, activeBranch: "main", menuOpen: false,
  outages: [], reinforcements: [], added: {},
  result: null, resultAt: "", prevStatus: {}, running: false, solving: false, stage: "", fraction: 0, runId: 0,
  diff: null, diffMode: false, suggestions: null,
  tab: "copilot", sideOpen: true, layer: "flow", showDeferred: false, legendOpen: false, showBoundary: false,
  year: 2030, sel: null,
  maintDraft: { season: "Summer", year: 2029, weeks: 4, kind: "outage" },
  chat: EMPTY_CHAT,
  toast: null,
};

export type Patch = Partial<PlannerState> | ((st: PlannerState) => Partial<PlannerState>);

/** What a hook needs from the planner: patch the state, read its latest value, drive the map, toast. */
export interface Core {
  patch: (p: Patch) => void;
  /** The latest state, for async flows that must not read a stale closure. */
  ref: MutableRefObject<PlannerState>;
  mapApi: MutableRefObject<MapApi | null>;
  toastMsg: (t: string, tone?: "ok" | "warn") => void;
}

export type { ChatMsg };

/** Create the planner state and its core. */
export function useCore(): { s: PlannerState; core: Core } {
  const [s, setS] = useState<PlannerState>(INITIAL);
  const ref = useRef(s);
  ref.current = s;
  const patch = useCallback(
    (p: Patch) =>
      setS((st) => {
        const next = { ...st, ...(typeof p === "function" ? p(st) : p) };
        ref.current = next; // async flows read the latest state before React re-renders
        return next;
      }),
    [],
  );
  const mapApi = useRef<MapApi | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);

  const toastMsg = useCallback(
    (text: string, tone: "ok" | "warn" = "ok") => {
      window.clearTimeout(toastTimer.current);
      patch({ toast: { text, tone } });
      toastTimer.current = window.setTimeout(() => patch({ toast: null }), 3600);
    },
    [patch],
  );
  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  return { s, core: { patch, ref, mapApi, toastMsg } };
}
