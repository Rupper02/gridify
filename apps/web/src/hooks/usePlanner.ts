// The planner controller: one state object (mirroring the API + the view), the actions that drive it, what is derived
// from it, and a handle to the map. Components are functions of what this returns; they never write state.
//
// A run is explicit and single: `run()` starts a background job for the active branch (every plan year, the viewed
// year first) and follows it; a newer request supersedes it. An edit (a connection, the demand profile) re-runs the
// branch by itself after a short debounce, so the map always catches up with what the branch holds.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MutableRefObject } from "react";

import { RunCancelled, api, failureText, notSolved } from "../api";
import { type DiffMap, diffMapFor } from "../lib/geo";
import { type FeatureKey, lineTiers, loadVisible, onlyFeature, saveVisible, toggleFeature } from "../lib/mapFeatures";
import { indexModel, limiters } from "../lib/model";
import { BRANCH_HUES, MAIN_HUE } from "../theme";
import type {
  Assumption,
  Boundary,
  Branch,
  Connection,
  ConnectionDraft,
  Forecasts,
  MapLayer,
  Model,
  PlanDiff,
  PlanPayload,
  RegistryItem,
  Sel,
  Tab,
  YearResult,
} from "../types";

export const MAIN_ID = "main";

export interface MapApi {
  fit(anim: boolean): void;
  zoomBy(d: number): void;
  focusOn(ll: [number, number] | null): void;
}

export type RunState =
  | { kind: "idle" }
  | { kind: "running"; branchId: string; stage: string; fraction: number }
  | { kind: "failed"; branchId: string; error: string };

export interface Toast {
  id: number;
  text: string;
  tone: "ok" | "warn";
}

export interface PlannerState {
  model: Model | null;
  bootError: string | null;
  forecasts: Forecasts | null;
  boundary: Boundary | null;
  assumptions: Assumption[] | null;
  showAssumptions: boolean;
  registry: RegistryItem[] | null;
  branches: Branch[];
  activeBranch: string;
  connections: Connection[];
  result: PlanPayload | null;
  resultAt: string;
  run: RunState;
  diff: PlanDiff | null;
  diffError: string | null;
  year: number;
  layer: MapLayer;
  visible: FeatureKey[];
  sel: Sel | null;
  tab: Tab;
  sideOpen: boolean;
  menuOpen: boolean;
  toasts: Toast[];
}

const INITIAL: PlannerState = {
  model: null, bootError: null, forecasts: null, boundary: null, assumptions: null, showAssumptions: false, registry: null,
  branches: [], activeBranch: "", connections: [], result: null, resultAt: "", run: { kind: "idle" }, diff: null, diffError: null,
  year: 0, layer: "flow", visible: [], sel: null, tab: "connections", sideOpen: true, menuOpen: false, toasts: [],
};

const hhmm = () => new Date().toTimeString().slice(0, 5);
const sleep = (ms: number) => new Promise((r) => window.setTimeout(r, ms));
const EDIT_DEBOUNCE_MS = 700;
const DIFF_RETRY_MS = 3000;
const DIFF_RETRIES = 10;
const TOAST_MS = 3600;

/** The branch's hue: main is silver; the other branches take the hues in creation order. */
export function branchHue(branches: Branch[], id: string): string {
  if (!id || id === MAIN_ID) return MAIN_HUE;
  const others = branches.filter((b) => b.branch_id !== MAIN_ID).sort((a, b) => a.created_at.localeCompare(b.created_at));
  const i = others.findIndex((b) => b.branch_id === id);
  return BRANCH_HUES[(i < 0 ? 0 : i) % BRANCH_HUES.length];
}

/** The stored result for a year; while a run is still solving, the nearest year already solved. */
function yearOf(r: PlanPayload | null, year: number): { yr: YearResult | null; exact: boolean } {
  if (!r) return { yr: null, exact: false };
  const hit = r.years[String(year)];
  if (hit) return { yr: hit, exact: true };
  const solved = Object.keys(r.years).map(Number);
  if (!solved.length) return { yr: null, exact: false };
  const near = solved.reduce((a, b) => (Math.abs(b - year) < Math.abs(a - year) ? b : a));
  return { yr: r.years[String(near)], exact: false };
}

export function usePlanner() {
  const [s, setS] = useState<PlannerState>(() => ({ ...INITIAL, visible: loadVisible() }));
  const ref = useRef(s);
  // `ref.current` is the state of record and `patch` writes it synchronously, so an async flow that patches and then
  // reads the ref in the same tick sees what it just wrote
  const patch = useCallback((p: Partial<PlannerState> | ((st: PlannerState) => Partial<PlannerState>)) => {
    const next = { ...ref.current, ...(typeof p === "function" ? p(ref.current) : p) };
    ref.current = next;
    setS(next);
  }, []);
  const mapApi = useRef<MapApi | null>(null) as MutableRefObject<MapApi | null>;
  const toastSeq = useRef(0);
  const toast = useCallback((text: string, tone: "ok" | "warn" = "ok") => {
    const id = ++toastSeq.current;
    patch((st) => ({ toasts: [...st.toasts, { id, text, tone }].slice(-3) }));
    window.setTimeout(() => patch((st) => ({ toasts: st.toasts.filter((t) => t.id !== id) })), TOAST_MS);
  }, [patch]);

  // ---- the run ---------------------------------------------------------------------------------------------
  const runSeq = useRef(0);
  const jobRef = useRef<string | null>(null);
  const debounce = useRef<number | undefined>(undefined);

  const loadDiff = useCallback(async (bid: string) => {
    if (bid === MAIN_ID) return patch({ diff: null, diffError: null });
    patch({ diff: null, diffError: null });
    for (let i = 0; i < DIFF_RETRIES; i++) {
      try {
        const d = await api.getDiff(bid);
        if (ref.current.activeBranch === bid) patch({ diff: d });
        return;
      } catch (e) {
        const ns = notSolved(e);
        if (!ns?.retry) {
          if (ref.current.activeBranch === bid && !ns) patch({ diffError: failureText(e) });
          return;
        }
        await sleep(DIFF_RETRY_MS); // the engine was busy: ask again
        if (ref.current.activeBranch !== bid) return;
      }
    }
    patch({ diffError: "the engine stayed busy: try again in a moment" });
  }, [patch]);

  const run = useCallback(async () => {
    window.clearTimeout(debounce.current);
    const bid = ref.current.activeBranch;
    if (!bid) return;
    const token = ++runSeq.current;
    if (jobRef.current) void api.cancelJob(jobRef.current).catch(() => {});
    jobRef.current = null;
    const mine = () => runSeq.current === token;
    patch({ run: { kind: "running", branchId: bid, stage: "queued", fraction: 0 }, diff: null, diffError: null });
    try {
      const res = await api.runBranch(bid, ref.current.year || null, {
        wanted: mine,
        onStart: (id) => (jobRef.current = id),
        onProgress: (stage, fraction) => mine() && patch({ run: { kind: "running", branchId: bid, stage, fraction } }),
        // the years already on screen stay until their re-solved versions land
        onPartial: (p) => mine() && patch((st) => ({ result: { ...p, years: { ...(st.result?.branch_id === bid ? st.result.years : {}), ...p.years } } })),
      });
      if (!mine()) return;
      jobRef.current = null;
      patch({ result: res, resultAt: hhmm(), run: { kind: "idle" } });
      void loadDiff(bid);
    } catch (e) {
      if (!mine() || e instanceof RunCancelled) return;
      patch({ run: { kind: "failed", branchId: bid, error: failureText(e) } });
    }
  }, [loadDiff, patch]);

  /** Re-run after an edit, once the burst of edits settles. */
  const runSoon = useCallback(() => {
    window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(() => void run(), EDIT_DEBOUNCE_MS);
  }, [run]);
  useEffect(() => () => window.clearTimeout(debounce.current), []);

  // ---- branches ----------------------------------------------------------------------------------------------
  const refreshBranches = useCallback(async () => {
    try {
      patch({ branches: await api.listBranches() });
    } catch (e) {
      toast(`Could not list the branches: ${failureText(e)}`, "warn");
    }
  }, [patch, toast]);

  const loadConnections = useCallback(async (bid: string) => {
    const conns = await api.listConnections(bid);
    if (ref.current.activeBranch === bid) patch({ connections: conns });
  }, [patch]);

  /** Show a branch: its connections, then its result (cached) or a run when it has none for what it holds. */
  const openBranch = useCallback(async (bid: string) => {
    runSeq.current++; // whatever was running belonged to the branch being left
    if (jobRef.current) void api.cancelJob(jobRef.current).catch(() => {});
    jobRef.current = null;
    window.clearTimeout(debounce.current);
    patch({ activeBranch: bid, connections: [], result: null, diff: null, diffError: null, sel: null, menuOpen: false, run: { kind: "idle" },
      tab: bid === MAIN_ID && ref.current.tab === "compare" ? "connections" : ref.current.tab });
    try {
      await loadConnections(bid);
      const res = await api.getResult(bid);
      if (ref.current.activeBranch !== bid) return;
      patch({ result: res, resultAt: "cached" });
      void loadDiff(bid);
    } catch (e) {
      if (notSolved(e)) void run();
      else toast(failureText(e), "warn");
    }
  }, [loadConnections, loadDiff, patch, run, toast]);

  /** The branch an edit goes on: the active one, or on main (read-only) a new branch opened for it. */
  const editable = useCallback(async (): Promise<string | null> => {
    const st = ref.current;
    if (st.activeBranch && st.activeBranch !== MAIN_ID) return st.activeBranch;
    try {
      const n = st.branches.filter((b) => b.branch_id !== MAIN_ID).length + 1;
      const b = await api.createBranch(`draft-${n}`, MAIN_ID);
      await refreshBranches();
      patch({ activeBranch: b.branch_id, result: ref.current.result, diff: null, sel: ref.current.sel });
      await loadConnections(b.branch_id);
      toast(`main is read-only: opened branch ${b.name} for this change`);
      return b.branch_id;
    } catch (e) {
      toast(`Could not open a branch: ${failureText(e)}`, "warn");
      return null;
    }
  }, [loadConnections, patch, refreshBranches, toast]);

  // ---- the boot ----------------------------------------------------------------------------------------------
  const boot = useCallback(async () => {
    patch({ bootError: null });
    let lastErr: unknown = null;
    for (let i = 0; i < 6; i++) {
      try {
        const [model, forecasts, branches] = await Promise.all([api.getModel(), api.getForecasts(), api.listBranches()]);
        patch({ model, forecasts, branches, year: forecasts.plan_years[0] });
        void api.getBoundary().then((boundary) => patch({ boundary })).catch(() => {});
        await openBranch(MAIN_ID);
        return;
      } catch (e) {
        lastErr = e;
        await sleep(1500 * (i + 1)); // the API may still be starting
      }
    }
    patch({ bootError: failureText(lastErr) });
  }, [openBranch, patch]);
  const booted = useRef(false);
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    void boot();
  }, [boot]);

  // ---- actions -----------------------------------------------------------------------------------------------
  const actions = useMemo(() => {
    const edited = async (bid: string) => {
      await Promise.all([loadConnections(bid), refreshBranches()]);
      runSoon();
    };
    return {
      boot,
      run,
      openBranch,
      loadDiff,
      toast,
      async createBranch(name: string) {
        try {
          const b = await api.createBranch(name, ref.current.activeBranch || MAIN_ID);
          await refreshBranches();
          await openBranch(b.branch_id);
          toast(`Branch ${b.name} opened`);
        } catch (e) {
          toast(`Could not open the branch: ${failureText(e)}`, "warn");
        }
      },
      async merge() {
        const bid = ref.current.activeBranch;
        try {
          const r = await api.merge(bid);
          await refreshBranches();
          await openBranch(r.into);
          toast(`Merged into ${r.into === MAIN_ID ? "main" : r.into}`);
        } catch (e) {
          toast(`Could not merge: ${failureText(e)}`, "warn");
        }
      },
      async discard() {
        const bid = ref.current.activeBranch;
        const parent = ref.current.branches.find((b) => b.branch_id === bid)?.parent_id ?? MAIN_ID;
        try {
          await api.discard(bid);
          await refreshBranches();
          await openBranch(parent);
          toast("Branch discarded");
        } catch (e) {
          toast(`Could not discard: ${failureText(e)}`, "warn");
        }
      },
      async setProfile(scenario: string) {
        const bid = ref.current.activeBranch;
        try {
          await api.setProfile(bid, scenario);
          await refreshBranches();
          void run();
        } catch (e) {
          toast(`Could not change the demand profile: ${failureText(e)}`, "warn");
        }
      },
      async addConnection(draft: ConnectionDraft) {
        const bid = await editable();
        if (!bid) return false;
        try {
          const c = await api.addConnection(bid, draft);
          await edited(bid);
          patch({ sel: { kind: "connection", id: c.request_id }, tab: "connections" });
          return true;
        } catch (e) {
          toast(failureText(e), "warn");
          return false;
        }
      },
      async changeConnection(rid: string, change: Partial<ConnectionDraft>) {
        const bid = ref.current.activeBranch;
        try {
          await api.changeConnection(bid, rid, change);
          await edited(bid);
        } catch (e) {
          toast(failureText(e), "warn");
        }
      },
      async removeConnection(rid: string) {
        const bid = ref.current.activeBranch;
        try {
          await api.removeConnection(bid, rid);
          if (ref.current.sel?.kind === "connection" && ref.current.sel.id === rid) patch({ sel: null });
          await edited(bid);
        } catch (e) {
          toast(failureText(e), "warn");
        }
      },
      async loadRegistry() {
        if (ref.current.registry) return;
        try {
          patch({ registry: await api.getRegistry() });
        } catch (e) {
          toast(`Could not read the registry: ${failureText(e)}`, "warn");
        }
      },
      async toggleAssumptions() {
        const show = !ref.current.showAssumptions;
        patch({ showAssumptions: show });
        if (show && !ref.current.assumptions) {
          try {
            patch({ assumptions: await api.getAssumptions() });
          } catch (e) {
            toast(failureText(e), "warn");
          }
        }
      },
      select(sel: Sel | null) {
        patch({ sel });
      },
      setYear(year: number) {
        patch({ year });
      },
      setLayer(layer: MapLayer) {
        patch({ layer });
      },
      setTab(tab: Tab) {
        patch({ tab, sideOpen: true });
      },
      toggleSide() {
        patch((st) => ({ sideOpen: !st.sideOpen }));
      },
      toggleMenu(open?: boolean) {
        patch((st) => ({ menuOpen: open ?? !st.menuOpen }));
      },
      toggleFeature(k: FeatureKey) {
        const visible = toggleFeature(ref.current.visible, k);
        saveVisible(visible);
        patch({ visible });
      },
      onlyFeature(k: FeatureKey) {
        const visible = onlyFeature(ref.current.visible, k);
        saveVisible(visible);
        patch({ visible });
      },
    };
  }, [boot, editable, loadConnections, loadDiff, openBranch, patch, refreshBranches, run, runSoon, toast]);

  // ---- derived -------------------------------------------------------------------------------------------------
  const ix = useMemo(() => (s.model ? indexModel(s.model) : null), [s.model]);
  const tiers = useMemo(() => lineTiers((s.model?.lines ?? []).map((l) => l.voltage_kv)), [s.model]);
  const { yr, exact } = useMemo(() => yearOf(s.result, s.year), [s.result, s.year]);
  const branch = s.branches.find((b) => b.branch_id === s.activeBranch) ?? null;
  const onMain = !s.activeBranch || s.activeBranch === MAIN_ID; // before the branches load, the planner opens on main
  const compare = !onMain && s.tab === "compare" && !!s.diff;
  const diffMap: DiffMap | null = useMemo(() => (compare ? diffMapFor(s.diff?.years[String(s.year)] ?? null) : null), [compare, s.diff, s.year]);
  const limits = useMemo(() => limiters(s.result?.years ?? {}), [s.result]);
  const derived = {
    ix,
    tiers,
    yr,
    exact,
    branch,
    onMain,
    compare,
    diffMap,
    limits,
    hue: branchHue(s.branches, s.activeBranch),
    years: s.forecasts?.plan_years ?? [],
    running: s.run.kind === "running",
  };

  return { s, actions, derived, mapApi };
}

export type Planner = ReturnType<typeof usePlanner>;
