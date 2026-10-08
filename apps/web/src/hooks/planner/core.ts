// The planner's state shape and the small core every planner hook shares: the state, a way to patch
// it, a ref to its latest value, the map handle and the toast. Each hook (run, branches, registry,
// selection, project edits, maintenance, agents, ask, projects) takes a `Core` plus only the other hooks' actions
// it needs.

import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";

import { HOSTING_IDLE, type HostingState } from "../../lib/capacity";
import { DEFAULT_VISIBLE, type FeatureKey, loadVisible } from "../../lib/mapFeatures";
import { INITIAL_DRAFT, type MaintDraft } from "../../lib/maintenance";
import type { Plan } from "../../lib/plan";
import { DEFAULT_PROJECT_ID, mainIdOf } from "../../lib/projects";
import { RUN_IDLE, type RunState } from "../../lib/runStages";
import type {
  AgentRun,
  AgentsStatus,
  Assumption,
  Boundary,
  Branch,
  BranchReinforcement,
  Diff,
  Finding,
  Forecast,
  Limits,
  MapLayer,
  MergeCheck,
  Model,
  OptimizeResult,
  Outage,
  Project,
  RegistryItem,
  RunNote,
  Sel,
  StepEvidence,
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

export type { MaintDraft, RunState };

/** The findings group the Limits tab's ledger opens on when another card sends the operator there (read once, then cleared). */
export type FindingsFocus = "n1";

export interface Toast {
  id: number;
  text: string;
  tone: "ok" | "warn";
}

/** How many toasts show at once (the oldest goes when a fourth arrives) and for how long. */
const MAX_TOASTS = 3;
const TOAST_MS = 3600;

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
  defaultScenario: string; // the pathway a branch is planned on unless it says otherwise (engine DEFAULT_SCENARIO)
  plan: Plan | null; // the plan's years and phases (GET /forecasts); null until the boot has read them
  boundary: Boundary | null;
  registry: RegistryItem[];
  registryLoaded: boolean;
  // branches
  branches: Branch[];
  activeBranch: string; // "" until the project's branches are in (then its main)
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
  resultAt: string; // when the shown result's run finished (HH:MM)
  run: RunState; // where the branch's run stands (lib/runStages.ts); useRun is its only writer
  editedAt: number; // when the branch's inputs last changed (ms): a run requested before it is outdated

  // review
  diff: Diff | null;
  diffMode: boolean;
  diffError: string | null; // why the comparison with the parent could not load (Review offers a Retry)
  mergeCheck: MergeCheck | null; // the gate's verdict for the active branch (null until checked)
  gateError: string | null; // why the gate's verdict could not load (Review offers a Retry)
  findings: Finding[]; // the active branch's findings ledger
  limits: Limits | null; // what limits the active branch: the engine's reduction of its last run (null until read)
  limitsError: string | null; // why it could not be read (the Limits tab offers a Retry)
  hosting: HostingState; // the room to connect at each substation today (the Capacity tab, the Headroom layer)
  // the agents
  agents: AgentsStatus | null; // the project's agents: starting, idle, running or paused; polled
  agentRuns: AgentRun[]; // the project's agent runs, newest first (read while the Review tab shows: the note's "writing" line)
  threads: Thread[]; // the project's conversations
  thread: ThreadView | null; // the open conversation
  trace: TraceEvent[]; // the reply being streamed, as events
  note: RunNote | null; // the engineer's note on the active branch's run (null until written, or once the run moved on)
  study: StepEvidence | null; // the evidence drawer: a recorded step and the study behind it
  // view
  tab: Tab;
  sideOpen: boolean;
  leftFolded: boolean; // the left card is its "Solved" line (and any warning) alone
  dockFolded: boolean; // the roadmap is its header line alone (layout gives the map the room back)
  findingsFocus: FindingsFocus | null; // the findings group the Limits tab's ledger expands on opening (the readings' N-1 stat sets it)
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
  toasts: Toast[]; // newest last
}

export const EMPTY_CHAT: ChatState = { open: false, input: "", busy: false };

/** What belongs to one branch's view: reset on every switch (select, open, merge, discard, a project switch). */
export const BRANCH_FRESH: Partial<PlannerState> = {
  diff: null, diffMode: false, diffError: null, mergeCheck: null, gateError: null, findings: [], limits: null, limitsError: null, hosting: HOSTING_IDLE, note: null, thread: null, trace: [], study: null, sel: null,
  outages: [], reinforcements: [], candidates: [], chat: EMPTY_CHAT,
};

export const INITIAL: PlannerState = {
  projects: [], projectId: DEFAULT_PROJECT_ID, projectsOpen: false, assumptions: null, showAssumptions: false,
  model: null, modelLoading: true, modelError: null, warehouseStale: false, forecasts: [], defaultScenario: "", plan: null, boundary: null, registry: [], registryLoaded: false,
  branches: [], activeBranch: "", menuOpen: false,
  outages: [], reinforcements: [], candidates: [], added: {},
  result: null, resultAt: "", run: RUN_IDLE, editedAt: 0,
  diff: null, diffMode: false, diffError: null, mergeCheck: null, gateError: null, findings: [], limits: null, limitsError: null, hosting: HOSTING_IDLE,
  agents: null, agentRuns: [], threads: [], thread: null, trace: [], note: null, study: null,
  tab: "ask", sideOpen: true, dockFolded: false, leftFolded: false, findingsFocus: null, layer: "flow", visible: [...DEFAULT_VISIBLE], showMenuOpen: false, showDeferred: false, legendOpen: false, showBoundary: false,
  year: 0, sel: null, // set from the plan at boot; nothing shows a year before then
  maintDraft: INITIAL_DRAFT,
  chat: EMPTY_CHAT,
  toasts: [],
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

/** The branch (the active one unless named) when it can be edited; on main (the plan of record, read-only) a toast says so and null. */
export function editableBranch({ ref, toastMsg }: Pick<Core, "ref" | "toastMsg">, what: string, bid = ref.current.activeBranch): string | null {
  const st = ref.current;
  if (bid && bid !== mainIdOf(st.projects, st.projectId)) return bid;
  toastMsg(`main is read-only. Open a branch to ${what}.`, "warn");
  return null;
}

/** Create the planner state and its core. */
export function useCore(): { s: PlannerState; core: Core } {
  const [s, setS] = useState<PlannerState>(() => ({ ...INITIAL, visible: loadVisible() }));
  const ref = useRef(s);
  // `ref.current` is the planner's state of record and `patch` writes it synchronously: an async flow that patches and
  // then reads the ref in the same tick (a run started right after the branch landed) sees what it just wrote. React's
  // own updater would run only when it renders (eagerly only while nothing else is queued), which left the ref stale.
  const patch = useCallback(
    (p: Patch) => {
      const next = { ...ref.current, ...(typeof p === "function" ? p(ref.current) : p) };
      ref.current = next;
      setS(next);
    },
    [],
  );
  const mapApi = useRef<MapApi | null>(null);
  const toastSeq = useRef(0);
  const toastTimers = useRef<number[]>([]);

  // a short queue, so a merge's, a switch's and a run's messages in quick succession all get read
  const toastMsg = useCallback(
    (text: string, tone: "ok" | "warn" = "ok") => {
      const id = ++toastSeq.current;
      patch((st) => ({ toasts: [...st.toasts, { id, text, tone }].slice(-MAX_TOASTS) }));
      toastTimers.current.push(window.setTimeout(() => patch((st) => ({ toasts: st.toasts.filter((t) => t.id !== id) })), TOAST_MS));
    },
    [patch],
  );
  useEffect(() => () => toastTimers.current.forEach((t) => window.clearTimeout(t)), []);

  return { s, core: { patch, ref, mapApi, toastMsg } };
}
