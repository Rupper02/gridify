// The planner's state shape and the small core every planner hook shares: the state, a way to patch
// it, a ref to its latest value, the map handle and the toast. Each hook (run, branches, registry,
// selection, project edits, maintenance, agents, ask, projects) takes a `Core` plus only the other hooks' actions
// it needs.

import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";

import { DEFAULT_VISIBLE, type FeatureKey, loadVisible } from "../../lib/mapFeatures";
import { INITIAL_DRAFT, type MaintDraft } from "../../lib/maintenance";
import type { Plan } from "../../lib/plan";
import { DEFAULT_PROJECT_ID } from "../../lib/projects";
import type {
  AgentsStatus,
  Assumption,
  Boundary,
  Branch,
  BranchReinforcement,
  Diff,
  Finding,
  FindingCounts,
  Forecast,
  MapLayer,
  MergeCheck,
  Model,
  OptimizeResult,
  Outage,
  Project,
  RegistryItem,
  Review,
  Sel,
  Status,
  StepEvidence,
  Suggestion,
  Tab,
  Thread,
  ThreadView,
  TraceEvent,
} from "../../types";

export interface MapApi {
  fit(anim: boolean): void;
  zoomBy(d: number): void;
  focusOn(ll: [number, number] | null, kMin?: number): void;
}

/** The Ask tab's conversation view: open (a thread, or a new one before its first question), the composer's draft, a request in flight. */
export interface ChatState {
  open: boolean;
  input: string;
  busy: boolean;
}

export type { MaintDraft };

export interface PlannerState {
  // projects: the grids planned on; the active one owns the model, the branches and the result below
  projects: Project[];
  projectId: string;
  projectsOpen: boolean; // the projects screen (list, import)
  assumptions: Assumption[] | null; // what the active project's model assumes (loaded on demand)
  showAssumptions: boolean;
  // data
  model: Model | null;
  modelLoading: boolean; // the active project's grid (model + branches) is on its way
  modelError: string | null; // why it could not load (the stamp says so, with a Retry)
  warehouseStale: boolean; // the last warehouse read was its previous version: the pipeline was writing a new one
  forecasts: Forecast[];
  plan: Plan | null; // the plan's years and phases (GET /forecasts); null until the boot has read them
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
  /** The branch's projects as stored (added by hand, pulled from the registry, or proposed by an agent and approved). */
  candidates: RegistryItem[];
  /** Projects added per branch since its last run (shown as Preliminary until a run includes them). */
  added: Record<string, RegistryItem[]>;
  // the run
  result: OptimizeResult | null;
  resultAt: string; // when the shown result was solved (HH:MM)
  prevStatus: Record<string, Status>;
  running: boolean; // the overlay: until the queue and the viewed year are in
  solving: boolean; // the job is still solving the remaining years in the background
  refreshing: boolean; // an automatic refresh after a cheap edit is pending or running (no overlay)
  stage: string;
  fraction: number;
  runId: number;
  // review
  diff: Diff | null;
  diffMode: boolean;
  suggestions: Suggestion[] | null;
  mergeCheck: MergeCheck | null; // the gate's verdict for the active branch (null until checked)
  findings: Finding[]; // the active branch's findings ledger
  findingCounts: FindingCounts | null;
  // the agents
  agents: AgentsStatus | null; // the project's agents: off (no key), idle, running or paused; polled
  threads: Thread[]; // the project's conversations (Ask the model, the health thread)
  thread: ThreadView | null; // the open conversation
  trace: TraceEvent[]; // the reply being streamed, as events
  reviews: Review[]; // the reviewer's comments on the active branch
  study: StepEvidence | null; // the evidence drawer: a recorded step and the study behind it
  // view
  tab: Tab;
  sideOpen: boolean;
  layer: MapLayer;
  /** The kinds of element the map shows (lib/mapFeatures.ts). */
  visible: FeatureKey[];
  showMenuOpen: boolean;
  showDeferred: boolean;
  legendOpen: boolean;
  showBoundary: boolean;
  year: number; // the viewed plan year; the boot opens on the end of Phase 1
  sel: Sel | null;
  maintDraft: MaintDraft;
  chat: ChatState;
  toast: { text: string; tone: "ok" | "warn" } | null;
}

export const EMPTY_CHAT: ChatState = { open: false, input: "", busy: false };

export const INITIAL: PlannerState = {
  projects: [], projectId: DEFAULT_PROJECT_ID, projectsOpen: false, assumptions: null, showAssumptions: false,
  model: null, modelLoading: true, modelError: null, warehouseStale: false, forecasts: [], plan: null, maxMw: 300, boundary: null, registry: [], registryLoaded: false,
  branches: [], branchesLoaded: false, activeBranch: "main", menuOpen: false,
  outages: [], reinforcements: [], candidates: [], added: {},
  result: null, resultAt: "", prevStatus: {}, running: false, solving: false, refreshing: false, stage: "", fraction: 0, runId: 0,
  diff: null, diffMode: false, suggestions: null, mergeCheck: null, findings: [], findingCounts: null,
  agents: null, threads: [], thread: null, trace: [], reviews: [], study: null,
  tab: "ask", sideOpen: true, layer: "flow", visible: [...DEFAULT_VISIBLE], showMenuOpen: false, showDeferred: false, legendOpen: false, showBoundary: false,
  year: 0, sel: null, // set from the plan at boot; nothing shows a year before then
  maintDraft: INITIAL_DRAFT,
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

/** Create the planner state and its core. */
export function useCore(): { s: PlannerState; core: Core } {
  const [s, setS] = useState<PlannerState>(() => ({ ...INITIAL, visible: loadVisible() }));
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
