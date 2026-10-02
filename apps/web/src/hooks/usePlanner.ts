// The planner controller: one state object (mirroring the API + UI), the actions that drive it, and
// a handle to the map. Components are pure functions of what this returns.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../api";
import { EVID } from "../theme";
import type {
  Boundary,
  Branch,
  Diff,
  Forecast,
  FormState,
  Hit,
  Model,
  OptimizeResult,
  QueueItem,
  RegistryItem,
  RunParams,
  Sel,
  SortKey,
  Status,
  Suggestion,
  Tab,
} from "../types";
import { readyFromForm } from "../lib/derive";

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

const INITIAL: PlannerState = {
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

type Patch = Partial<PlannerState> | ((st: PlannerState) => Partial<PlannerState>);

/** Values an action may need before React has applied the state it just set (e.g. the branch to run). */
interface RunOverride {
  activeBranch?: string;
  branches?: Branch[];
  forecastId?: string;
  g30?: number;
  g35?: number;
}

export function usePlanner() {
  const [s, setS] = useState<PlannerState>(INITIAL);
  const ref = useRef(s);
  ref.current = s;
  const patch = useCallback((p: Patch) => setS((st) => ({ ...st, ...(typeof p === "function" ? p(st) : p) })), []);

  const mapApi = useRef<MapApi | null>(null);
  // in-flight bookkeeping lives in refs, not React state: a coalesced re-run must see the previous
  // run finish synchronously, before React has flushed `running: false`
  const inFlight = useRef(false);
  const runAgain = useRef<RunOverride | null>(null);
  const stepTimer = useRef<number | undefined>(undefined);
  const toastTimer = useRef<number | undefined>(undefined);

  const toastMsg = useCallback(
    (t: string) => {
      window.clearTimeout(toastTimer.current);
      patch({ toast: t });
      toastTimer.current = window.setTimeout(() => patch({ toast: null }), 3200);
    },
    [patch],
  );

  const refreshBranches = useCallback(async () => {
    try {
      const branches = await api.listBranches();
      patch({ branches, branchesLoaded: true });
      return branches;
    } catch {
      return null;
    }
  }, [patch]);

  const ensureBranches = useCallback(async () => {
    if (ref.current.branchesLoaded) return;
    try {
      const branches = await api.listBranches();
      patch({ branches, branchesLoaded: true });
    } catch {
      toastMsg("Could not load branches — check the API is running.");
    }
  }, [patch, toastMsg]);

  /**
   * Run the plan for the active branch. A run already in flight (several registry adds in a row, a
   * branch switch) is never dropped: it is coalesced into ONE re-run when the current one finishes.
   */
  const run = useCallback(
    async (over: RunOverride = {}) => {
      const st = ref.current;
      if (inFlight.current) {
        runAgain.current = { ...(runAgain.current ?? {}), ...over };
        return;
      }
      inFlight.current = true;
      const prev = st.result;
      const prevStatus: Record<string, Status> = prev ? Object.fromEntries(prev.queue.map((q) => [q.request_id, q.status])) : {};
      // The view follows the active branch: main runs the plan of record (existing fleet, empty
      // queue); a branch runs its own scenario + the projects pulled onto it.
      const bid = over.activeBranch ?? st.activeBranch;
      const onBranch = !!bid && bid !== "main";
      const branches = over.branches ?? st.branches;
      const br = onBranch ? branches.find((b) => b.branch_id === bid) : undefined;
      const g30 = br ? br.growth_2030 : (over.g30 ?? st.g30);
      const g35 = br ? br.growth_2035 : (over.g35 ?? st.g35);
      const scenario = br ? br.scenario : (over.forecastId ?? st.forecastId);
      const params: RunParams = { g30, g35, scenario, branch: onBranch ? bid : "main", n: st.cands.length };
      patch({ running: true, step: 0, stage: "queued", hover: null });
      window.clearInterval(stepTimer.current);
      // every run is a background job on the API; its stage + fraction drive the overlay. A run that
      // has happened before (same branch, same inputs, same engine) is served from the durable cache
      // and finishes at once. The main branch still carries the header's forecast choice.
      const onProgress = (stage: string, fraction: number) => patch({ stage, step: Math.min(5, Math.floor(fraction * 5 + 1e-9)) });
      let res: OptimizeResult;
      let cands: RegistryItem[];
      try {
        res = onBranch || scenario === st.forecastId
          ? await api.runBranchJob(bid || "main", { with_justification: true }, onProgress)
          : await api.optimize({ scenario, growth_2030: g30, growth_2035: g35, with_justification: true });
        cands = await api.getCandidates();
      } catch (e) {
        window.clearInterval(stepTimer.current);
        inFlight.current = false;
        runAgain.current = null;
        patch({ running: false, step: 0, stage: "" });
        toastMsg(`The simulation failed: ${e instanceof Error ? e.message : "check the API is running"}`);
        return;
      }
      const inQueue = new Set(res.queue.map((x) => x.request_id));
      patch((x) => ({
        runId: x.runId + 1,
        // registry adds that this run now reflects are no longer "pending"
        pendingAdds: Object.fromEntries(Object.entries(x.pendingAdds).filter(([id]) => !inQueue.has(id))) as Record<string, true>,
        result: res,
        cands,
        prevStatus,
        running: false,
        step: 5,
        stage: "",
        lastParams: params,
      }));
      inFlight.current = false;
      const again = runAgain.current;
      if (again) {
        runAgain.current = null;
        await run(again);
      }
    },
    [patch, toastMsg],
  );

  // ---- boot --------------------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [model, cands, forecasts, maxMw, boundary] = await Promise.all([
          api.getModel(), api.getCandidates(), api.getForecasts(), api.getMaxConnectionMw(), api.getBoundary(),
        ]);
        if (cancelled) return;
        // growth is fixed per pathway (no sliders): sync g30/g35 to the default forecast's cited values
        const def = forecasts.find((f) => f.id === ref.current.forecastId) ?? forecasts[0];
        const over: RunOverride = def ? { forecastId: def.id, g30: def.growth_2030, g35: def.growth_2035 } : {};
        patch({ model, cands, forecasts, maxMw, boundary, ...over });
        mapApi.current?.fit(false);
        void refreshBranches();
        void run(over);
      } catch (e) {
        if (!cancelled) toastMsg(`Could not load the model: ${e instanceof Error ? e.message : "is the API running?"}`);
      }
    })();
    return () => {
      cancelled = true;
      window.clearInterval(stepTimer.current);
      window.clearTimeout(toastTimer.current);
    };
  }, [patch, refreshBranches, run, toastMsg]);

  // ---- selection + map ----------------------------------------------------------------------
  const elementPt = useCallback((t: Sel | null): [number, number] | null => {
    const m = ref.current.model;
    if (!m || !t) return null;
    if (t.kind === "bus") {
      const b = m.buses.find((x) => x.bus_id === t.id);
      return b ? [b.lon, b.lat] : null;
    }
    if (t.kind === "line") {
      const l = m.lines.find((x) => x.line_id === t.id);
      return l ? [(l.from_lon + l.to_lon) / 2, (l.from_lat + l.to_lat) / 2] : null;
    }
    if (t.kind === "project") {
      const q = ref.current.result?.queue.find((x) => x.request_id === t.id);
      return q && q.lon != null && q.lat != null ? [q.lon, q.lat] : null;
    }
    return null;
  }, []);

  const selectProject = useCallback(
    (id: string, zoom?: boolean) => {
      patch({ sel: { kind: "project", id } });
      const q = ref.current.result?.queue.find((x) => x.request_id === id);
      const map = mapApi.current;
      if (!map) return;
      if (zoom) {
        const el = q?.reason?.element;
        const target: Sel = el
          ? el.line_id != null
            ? { kind: "line", id: el.line_id }
            : { kind: "bus", id: el.bus_id! }
          : { kind: "project", id };
        map.focusOn(elementPt(target), 2.6);
      } else if (map.zoomedIn()) map.focusOn(elementPt({ kind: "project", id }));
    },
    [elementPt, patch],
  );

  const setForm = useCallback(
    (p: Partial<FormState>) =>
      patch((st) => {
        const f = { ...st.form, ...p };
        if ("land" in p || "planning" in p || "finance" in p) f.readiness = readyFromForm(f);
        return { form: f };
      }),
    [patch],
  );

  /** A map hit was clicked: pick a bus (in pick mode), select a project, or select an element. */
  const pick = useCallback(
    (hit: Hit | null) => {
      const st = ref.current;
      if (!hit) {
        if (!st.pickMode) patch({ sel: null });
        return;
      }
      if (st.pickMode) {
        if (hit.kind === "bus") {
          setForm({ bus: String(hit.id) });
          patch({ pickMode: false });
        }
        return;
      }
      if (hit.kind === "load" || hit.kind === "existing") return;
      if (hit.kind === "project") return selectProject(String(hit.id));
      patch({ sel: { kind: hit.kind, id: Number(hit.id) } as Sel });
    },
    [patch, selectProject, setForm],
  );

  const focusSel = useCallback(
    (target: Sel, kMin = 2.8) => {
      patch({ sel: target });
      mapApi.current?.focusOn(elementPt(target), kMin);
    },
    [elementPt, patch],
  );

  // ---- branches ("git for grids") ------------------------------------------------------------
  /** Switch the active branch: the whole view (map, Queue, tiles, roadmap) follows it. */
  const selectBranch = useCallback(
    (id: string) => {
      if (id === ref.current.activeBranch) return;
      patch({ activeBranch: id, diff: null, suggestions: null, sel: null, pendingAdds: {} });
      void run({ activeBranch: id });
    },
    [patch, run],
  );

  /** Adds always target a branch (main is the plan of record). On main, auto-create + switch to one. */
  const ensureEditableBranch = useCallback(async (): Promise<string | null> => {
    const st = ref.current;
    if (st.activeBranch && st.activeBranch !== "main") return st.activeBranch;
    try {
      const b = await api.createBranch({ name: "Draft plan", from_branch: "main", scenario: st.forecastId });
      await refreshBranches();
      patch({ activeBranch: b.branch_id, showNewBranch: false, diff: null, suggestions: null });
      toastMsg(`Opened branch “${b.name}” off main — your changes stay here until you merge.`);
      return b.branch_id;
    } catch {
      toastMsg("Could not open a branch — check the API is running.");
      return null;
    }
  }, [patch, refreshBranches, toastMsg]);

  /** Pull a project from the registry onto the active branch, then re-run so it appears. */
  const addRegistryProject = useCallback(
    async (requestId: string) => {
      const branchId = await ensureEditableBranch();
      if (!branchId) return;
      // take it off the registry list straight away: the re-run that reflects it can take a while
      const setPending = (on: boolean) =>
        patch((st) => {
          const p = { ...st.pendingAdds };
          if (on) p[requestId] = true;
          else delete p[requestId];
          return { pendingAdds: p };
        });
      setPending(true);
      try {
        const row = await api.addFromRegistry(branchId, requestId);
        await refreshBranches();
        patch({ diff: null, suggestions: null });
        await run({ activeBranch: branchId });
        toastMsg(`${requestId}${row?.applicant ? ` · ${row.applicant}` : ""} added to the branch — the map and Queue update when the run finishes.`);
      } catch {
        setPending(false);
        toastMsg("Could not add that project — check the API is running.");
      }
    },
    [ensureEditableBranch, patch, refreshBranches, run, toastMsg],
  );

  const loadRegistry = useCallback(async () => {
    if (ref.current.registryLoaded) return;
    try {
      const registry = await api.getRegistry();
      patch({ registry, registryLoaded: true });
    } catch {
      toastMsg("Could not load the registry — check the API is running.");
    }
  }, [patch, toastMsg]);

  const createBranchFlow = useCallback(async () => {
    const st = ref.current;
    if (st.creatingBranch) return;
    const name = st.newBranchName.trim() || "Untitled branch";
    patch({ creatingBranch: true });
    try {
      const b = await api.createBranch({ name, from_branch: "main", scenario: st.newBranchForecast });
      const branches = await refreshBranches();
      patch({ creatingBranch: false, showNewBranch: false, newBranchName: "", activeBranch: b.branch_id, diff: null, suggestions: null });
      toastMsg(`Branch “${b.name}” created off main. Add projects, then Diff vs main.`);
      void run({ activeBranch: b.branch_id, branches: branches ?? undefined });
    } catch {
      patch({ creatingBranch: false });
      toastMsg("Could not create the branch — check the API is running.");
    }
  }, [patch, refreshBranches, run, toastMsg]);

  const runBranchDiff = useCallback(async () => {
    const st = ref.current;
    if (st.comparing || !st.activeBranch || st.activeBranch === "main") return;
    patch({ comparing: true });
    try {
      const diff = await api.diffBranch(st.activeBranch, { with_narration: true });
      patch({ diff, comparing: false });
    } catch {
      patch({ comparing: false });
      toastMsg("Diff failed — check the API is running.");
    }
  }, [patch, toastMsg]);

  const runSuggestions = useCallback(async () => {
    const st = ref.current;
    if (st.loadingSuggestions || !st.activeBranch || st.activeBranch === "main") return;
    patch({ loadingSuggestions: true });
    try {
      const suggestions = await api.getSuggestions(st.activeBranch, { with_narration: true, limit: 5 });
      patch({ suggestions, loadingSuggestions: false });
    } catch {
      patch({ loadingSuggestions: false });
      toastMsg("Suggestions failed — check the API is running.");
    }
  }, [patch, toastMsg]);

  const mergeBranchFlow = useCallback(async () => {
    const st = ref.current;
    if (!st.activeBranch || st.activeBranch === "main") return;
    try {
      await api.mergeBranch(st.activeBranch, { into: "main" });
      const branches = await refreshBranches();
      toastMsg("Branch merged into main — the new plan of record. Re-running…");
      patch({ activeBranch: "main", diff: null, suggestions: null });
      void run({ activeBranch: "main", branches: branches ?? undefined });
    } catch {
      toastMsg("Merge failed — check the API is running.");
    }
  }, [patch, refreshBranches, run, toastMsg]);

  const discardBranchFlow = useCallback(async () => {
    const st = ref.current;
    if (!st.activeBranch || st.activeBranch === "main") return;
    try {
      await api.discardBranch(st.activeBranch);
      const branches = await refreshBranches();
      patch({ activeBranch: "main", diff: null, suggestions: null });
      void run({ activeBranch: "main", branches: branches ?? undefined });
      toastMsg("Branch discarded — back on main.");
    } catch {
      toastMsg("Discard failed — check the API is running.");
    }
  }, [patch, refreshBranches, run, toastMsg]);

  // ---- energisation year --------------------------------------------------------------------
  /**
   * Set/override a project's energisation year (null = back to the optimizer's recommendation).
   * Persisted on the branch; applied optimistically, rolled back if the save fails. It doesn't change
   * accept/defer/rank: it's a planning decision on top of the verdict.
   */
  const setSchedule = useCallback(
    async (rid: string, yr: number | null) => {
      const year = yr == null ? null : Math.max(2026, Math.min(2035, yr));
      const applyYear = (val: number | null) =>
        patch((st) =>
          st.result
            ? { result: { ...st.result, queue: st.result.queue.map((it) => (it.request_id === rid ? { ...it, scheduled_year: val } : it)) } }
            : {},
        );
      const prev = ref.current.result?.queue.find((x) => x.request_id === rid)?.scheduled_year ?? null;
      applyYear(year);
      try {
        await api.setSchedule(ref.current.activeBranch || "main", rid, year);
      } catch (e) {
        applyYear(prev);
        toastMsg(`Couldn’t save the year for ${rid}: ${e instanceof Error ? e.message : "unknown error"}`);
      }
    },
    [patch, toastMsg],
  );

  // ---- add-project form ---------------------------------------------------------------------
  const formInvalid = !s.form.bus || !(+s.form.mw > 0);
  const submit = useCallback(
    async (andRun: boolean) => {
      const f = ref.current.form;
      if (!f.bus || !(+f.mw > 0)) return;
      // Every add targets a branch (main is the plan of record). On main we auto-open a branch.
      const branchId = await ensureEditableBranch();
      if (!branchId) return;
      let row: RegistryItem;
      try {
        row = await api.addCandidate({
          applicant: f.name.trim() || "Manual application",
          bus_id: +f.bus,
          technology: f.tech,
          rating_mw: +f.mw,
          readiness_score: f.readiness,
          readiness_rationale: EVID.filter((e) => f[e.k]).map((e) => e.label).join("; ") || "No evidence supplied",
          branch_id: branchId,
          manual: true,
        });
      } catch (e) {
        toastMsg(`Could not add the project: ${e instanceof Error ? e.message : "check the API is running"}`);
        return;
      }
      await refreshBranches();
      // the view follows the active branch: re-run so the project lands on the map + Queue
      patch((st) => ({ drawer: false, pickMode: false, activeBranch: branchId, suggestions: null, form: { ...st.form, name: "", bus: "" } }));
      await run({ activeBranch: branchId });
      if (andRun) selectProject(row.request_id);
      if (ref.current.diff) void runBranchDiff();
      toastMsg(`${row.request_id} added to the branch — now on the map and in the Queue.`);
    },
    [ensureEditableBranch, patch, refreshBranches, run, runBranchDiff, selectProject, toastMsg],
  );

  // ---- derived values shared by several components -------------------------------------------
  const derived = useMemo(() => {
    const onMainView = !s.activeBranch || s.activeBranch === "main";
    const activeB = onMainView ? null : (s.branches.find((b) => b.branch_id === s.activeBranch) ?? null);
    const eg30 = activeB ? activeB.growth_2030 : s.g30;
    const eg35 = activeB ? activeB.growth_2035 : s.g35;
    const phase = s.timelineYear <= 2030 ? ("2030" as const) : ("2035" as const);
    const ph = s.result ? s.result.phases[phase] : null;
    const q: QueueItem[] = s.result ? s.result.queue : [];
    const qById: Record<string, QueueItem> = Object.fromEntries(q.map((x) => [x.request_id, x]));
    const fc = s.forecasts.find((x) => x.id === s.forecastId);
    const fcEff = activeB ? (s.forecasts.find((x) => x.id === activeB.scenario) ?? fc) : fc;
    const reviewB = s.branches.find((b) => b.branch_id === s.activeBranch) ?? null;
    const hasReviewBranch = !!(reviewB && reviewB.branch_id !== "main");
    const manualIds = new Set(s.cands.filter((c) => c.manual).map((c) => c.request_id));
    return { onMainView, activeB, eg30, eg35, phase, ph, q, qById, fc, fcEff, reviewB, hasReviewBranch, manualIds };
  }, [s.activeBranch, s.branches, s.cands, s.forecastId, s.forecasts, s.g30, s.g35, s.result, s.timelineYear]);

  const actions = useMemo(
    () => ({
      run, toastMsg, selectProject, pick, focusSel, setForm, submit, setSchedule,
      selectBranch, ensureBranches, refreshBranches, addRegistryProject, loadRegistry, createBranchFlow,
      runBranchDiff, runSuggestions, mergeBranchFlow, discardBranchFlow,
      /** Header shortcut: open the Review tab with the new-branch form showing. */
      newBranchQuick: () => {
        void ensureBranches();
        patch({ tab: "compare", showNewBranch: true });
      },
      setTab: (tab: Tab) => {
        patch({ tab });
        if (tab === "compare") void ensureBranches();
      },
      onForecast: (id: string) => {
        if (ref.current.activeBranch !== "main") return;
        const x = ref.current.forecasts.find((y) => y.id === id);
        patch(x ? { forecastId: id, g30: x.growth_2030, g35: x.growth_2035 } : { forecastId: id });
      },
      toggleRegistry: () => {
        if (!ref.current.registryLoaded) void loadRegistry();
        patch((st) => ({ showRegistry: !st.showRegistry }));
      },
      zoomIn: () => mapApi.current?.zoomBy(1),
      zoomOut: () => mapApi.current?.zoomBy(-1),
      zoomFit: () => mapApi.current?.fit(true),
      newApplicationAt: (busId: number) => {
        setForm({ bus: String(busId) });
        patch({ drawer: true });
      },
    }),
    [
      addRegistryProject, createBranchFlow, discardBranchFlow, ensureBranches, focusSel, loadRegistry, mergeBranchFlow,
      patch, pick, refreshBranches, run, runBranchDiff, runSuggestions, selectBranch, selectProject, setForm,
      setSchedule, submit, toastMsg,
    ],
  );

  return { s, patch, actions, derived, mapApi, formInvalid };
}

export type Planner = ReturnType<typeof usePlanner>;
