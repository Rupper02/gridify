// Pure view helpers: everything here is a function of API data + UI state, with no side effects,
// so it is unit-testable without a browser or a map.

import { ORDER, ST, fmtMw, techLabel } from "../theme";
import type {
  FormState,
  Line,
  OptimizeResult,
  PhaseKey,
  PhaseResult,
  QueueItem,
  RunParams,
  Sel,
  SortKey,
  Status,
  Transformer,
} from "../types";

export const isAccepted = (x: QueueItem): boolean => x.status === "Phase1" || x.status === "Phase2";

/** GB statutory voltage band for a nominal voltage (ESQCR): ±10 % at 132 kV and above, ±6 % below. */
export const voltageBand = (kv: number | null | undefined): [number, number] => (kv != null && kv >= 132 ? [0.9, 1.1] : [0.94, 1.06]);
export const voltageBandLabel = (kv: number | null | undefined): string => {
  const [lo, hi] = voltageBand(kv);
  return `${lo.toFixed(2)}–${hi.toFixed(2)} pu`;
};

/**
 * The year a project energises in the plan: the operator's override if set, else the optimizer's
 * recommendation. Only ACCEPTED projects get a year; deferred and rejected ones can't be hosted, so
 * they stay off the timeline.
 */
export function effYearOf(x: QueueItem): number | null {
  if (!isAccepted(x)) return null;
  return x.scheduled_year != null ? x.scheduled_year : x.recommended_year;
}

export const phaseForYear = (year: number): PhaseKey => (year <= 2030 ? "2030" : "2035");

export type ProjVariant = "p1" | "p2" | "ghost" | "rej";
export interface ProjView {
  x: QueueItem;
  variant: ProjVariant;
  size: number;
  label: string;
  online: boolean;
  isNew: boolean;
  future: boolean;
  blocked: boolean;
  offRec: boolean;
  fg: string;
}

/**
 * Map/label view of the geolocated queue items for the given timeline year. Deferred projects are
 * NOT drawn: they have no year, so they would sit on the map at every year as if present. They stay
 * flagged in the Queue, the Roadmap's deferred column and the Alerts tab, and the element blocking
 * them is still highlighted (see bindingSets).
 */
export function buildProjList(q: QueueItem[], timelineYear: number): ProjView[] {
  return q
    .filter((x) => x.lon != null && x.rating_mw != null && x.status !== "Deferred")
    .map((x) => {
      const accepted = isAccepted(x);
      const eff = effYearOf(x);
      const onTimeline = accepted && eff != null;
      const future = onTimeline && eff > timelineYear;
      const isNew = onTimeline && eff === timelineYear;
      const online = onTimeline && eff <= timelineYear;
      // scheduled earlier than the grid supports = goes against the recommendation (marked on map)
      const offRec =
        accepted && x.scheduled_year != null && x.recommended_year != null && x.scheduled_year < x.recommended_year;
      const blocked = x.status === "Rejected";
      const variant: ProjVariant =
        x.status === "Rejected" ? "rej" : future ? "ghost" : x.status === "Phase1" ? "p1" : "p2";
      const size =
        x.status === "Rejected" ? 0.55 : (0.6 + (Math.sqrt(x.rating_mw ?? 0) / Math.sqrt(18)) * 0.5) * (isNew ? 1.12 : 1);
      const label = blocked
        ? `${x.request_id} · rejected`
        : future
          ? `${x.request_id} · planned ${eff}`
          : `${x.request_id} · ${fmtMw(x.rating_mw)} MW${isNew ? ` · online ${eff}` : ""}`;
      return { x, variant, size, label, online, isNew, future, blocked, offRec, fg: future ? "#1e40af" : ST[x.status].fg };
    });
}

/** Timeline roll-up: accepted projects online by the slider year, and those energising that year. */
export function timelineRollup(q: QueueItem[], timelineYear: number) {
  const accepted = q.filter(isAccepted);
  const online = accepted.filter((x) => {
    const y = effYearOf(x);
    return y != null && y <= timelineYear;
  });
  const fresh = accepted.filter((x) => effYearOf(x) === timelineYear);
  const mw = (xs: QueueItem[]) => xs.reduce((a, x) => a + (x.rating_mw ?? 0), 0);
  return { online, fresh, onlineMw: mw(online), freshMw: mw(fresh) };
}

/** Elements named as the binding constraint by any deferred project. */
export function bindingSets(q: QueueItem[]) {
  const bindLines = new Set<number>();
  const bindBuses = new Set<number>();
  q.forEach((x) => {
    const el = x.status === "Deferred" && x.reason ? x.reason.element : null;
    if (el) {
      if (el.line_id != null) bindLines.add(el.line_id);
      if (el.bus_id != null) bindBuses.add(el.bus_id);
    }
  });
  return { bindLines, bindBuses };
}

export function busProjectsOf(q: QueueItem[]): Record<number, QueueItem[]> {
  const out: Record<number, QueueItem[]> = {};
  q.forEach((x) => {
    if (x.bus_id != null) (out[x.bus_id] = out[x.bus_id] ?? []).push(x);
  });
  return out;
}

/** The element the selected project is blocked by, if any (for highlighting). */
export function selectedElement(sel: Sel | null, qById: Record<string, QueueItem>) {
  const selQ = sel && sel.kind === "project" ? qById[sel.id] : null;
  return { selQ: selQ ?? null, selEl: selQ?.reason?.element ?? null };
}

// ---- real ratings/voltages from the model (no assumed feeder voltage) --------------------------
/** A transformer's substation is its HV busbar name minus the voltage/bay suffix. */
export const trafoSub = (t: Transformer): string =>
  String(t.hv_name || t.name || `T${t.trafo_id}`).replace(/\s*\d+(\.\d+)?\s*kV.*$/i, "").trim();
export const trafoRatio = (t: Transformer): string => (t.hv_kv && t.lv_kv ? `${+t.hv_kv} / ${+t.lv_kv} kV` : "—");
/** Capacity of a line = √3 · V · I. */
export const lineMva = (l: Line): string =>
  l.voltage_kv ? `${((Math.sqrt(3) * l.voltage_kv * l.rating_a) / 1000).toFixed(1)} MVA` : "—";

export const loadPct = (r: OptimizeResult | null, p: PhaseKey, id: number): number | null =>
  r?.phases[p]?.line_loading?.[id] ?? null;
export const vmAt = (r: OptimizeResult | null, p: PhaseKey, id: number): number | null =>
  r?.phases[p]?.bus_vm?.[id] ?? null;

// ---- queue table ----------------------------------------------------------------------------
export function filterSortQueue(
  q: QueueItem[],
  filter: "All" | Status,
  query: string,
  sortKey: SortKey,
  sortDir: 1 | -1,
): QueueItem[] {
  const needle = query.toLowerCase();
  const filtered = q.filter(
    (x) =>
      (filter === "All" || x.status === filter) &&
      (!needle || `${x.request_id} ${x.applicant || ""} bus ${x.bus_id} ${x.technology}`.toLowerCase().includes(needle)),
  );
  const keyFn: Record<SortKey, (x: QueueItem) => number | string> = {
    rank: (x) => (x.rank == null ? 999 : x.rank),
    id: (x) => x.request_id,
    mw: (x) => x.rating_mw ?? -1,
    ready: (x) => x.readiness_score,
    status: (x) => ORDER[x.status] * 1000 + (x.rank || 999),
  };
  const k = keyFn[sortKey];
  return [...filtered].sort((a, b) => {
    const A = k(a);
    const B = k(b);
    return (A < B ? -1 : A > B ? 1 : 0) * sortDir;
  });
}

export const sumMw = (xs: { rating_mw: number | null }[]): number => xs.reduce((a, b) => a + (b.rating_mw ?? 0), 0);
export const byStatus = (q: QueueItem[], st: Status): QueueItem[] => q.filter((x) => x.status === st);

// ---- alerts ---------------------------------------------------------------------------------
export interface AlertItem {
  key: string;
  title: string;
  meta: string;
  tag: string;
  fg: string;
  target?: { kind: "line" | "bus"; id: number };
  project?: string;
}
export interface AlertGroup {
  key: "viol" | "n1" | "dg" | "watch" | "dr" | "rj";
  label: string;
  color: string;
  fg: string;
  items: AlertItem[];
}

export function alertGroupsFor(r: OptimizeResult | null, eg30: number, eg35: number): AlertGroup[] {
  const groups: AlertGroup[] = [];
  if (!r) return groups;
  const q = r.queue;
  const viol: AlertItem[] = [];
  (["2030", "2035"] as PhaseKey[]).forEach((p) => {
    const P: PhaseResult = r.phases[p];
    const g = p === "2030" ? eg30 : eg35;
    P.overloaded_line_ids.forEach((id) =>
      viol.push({
        key: `o${p}${id}`,
        title: `Line ${id} overloaded · ${P.line_loading?.[id] != null ? P.line_loading[id].toFixed(0) : ">100"}%`,
        meta: `Demand ×${g.toFixed(2)} exceeds thermal rating with the ${p} plan connected`,
        tag: p,
        fg: "#991b1b",
        target: { kind: "line", id },
      }),
    );
    (P.voltage_violation_bus_ids ?? []).forEach((id) =>
      viol.push({
        key: `v${p}${id}`,
        title: `Voltage breach at bus ${id}`,
        meta: `${P.bus_vm?.[id] != null ? P.bus_vm[id].toFixed(3) : ""} pu outside its statutory band`,
        tag: p,
        fg: "#991b1b",
        target: { kind: "bus", id },
      }),
    );
  });
  if (viol.length) groups.push({ key: "viol", label: "Network violations", color: "#dc2626", fg: "#991b1b", items: viol });

  // single-outage screen of the 132 kV backbone (informational, not a connection gate)
  const n1: AlertItem[] = [];
  (["2030", "2035"] as PhaseKey[]).forEach((p) => {
    (r.phases[p].n1_violations ?? []).forEach((v) =>
      n1.push({
        key: `n1${p}${v.outage_type}${v.outage_id}${v.type}`,
        title: `${v.outage_type === "trafo" ? "Transformer" : "Line"} ${v.outage_id} out → ${v.type === "islanded" ? `${v.value ?? "?"} MW islanded` : v.type === "voltage" ? `bus ${v.element_id} at ${v.value ?? "?"} pu` : v.type === "non_convergent" ? "no solution" : `${v.type} ${v.element_id} at ${v.value ?? "?"}%`}`,
        meta: v.message,
        tag: `N-1 · ${p}`,
        fg: "#7c2d12",
        target: v.type === "voltage" && v.element_id != null ? { kind: "bus", id: v.element_id } : v.outage_type === "line" ? { kind: "line", id: v.outage_id } : undefined,
      }),
    );
  });
  if (n1.length) groups.push({ key: "n1", label: "N-1: one circuit out", color: "#ea580c", fg: "#7c2d12", items: n1 });

  const dg = byStatus(q, "Deferred")
    .filter((x) => x.reason?.kind === "grid")
    .map<AlertItem>((x) => ({
      key: x.request_id,
      title: `${x.request_id} — ${x.reason!.short}`,
      meta: `${x.applicant} · ${techLabel(x.technology) ?? "—"} ${fmtMw(x.rating_mw)} MW · readiness ${Math.round(x.readiness_score * 100)}%`,
      tag: `bus ${x.bus_id}`,
      fg: "#92400e",
      project: x.request_id,
    }));
  if (dg.length) groups.push({ key: "dg", label: "Deferred by grid constraint", color: "#d97706", fg: "#92400e", items: dg });

  const watch: AlertItem[] = [];
  (["2030", "2035"] as PhaseKey[]).forEach((p) => {
    const L = r.phases[p].line_loading ?? {};
    Object.entries(L)
      .filter(([, v]) => v > 88 && v <= 100)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 2)
      .forEach(([id, v]) =>
        watch.push({
          key: `w${p}${id}`,
          title: `Line ${id} at ${v.toFixed(0)}%`,
          meta: "Within 12% of thermal rating — little headroom left",
          tag: p,
          fg: "#374151",
          target: { kind: "line", id: +id },
        }),
      );
  });
  if (watch.length) groups.push({ key: "watch", label: "Approaching limits", color: "#6b7280", fg: "#374151", items: watch });

  const dr = byStatus(q, "Deferred")
    .filter((x) => x.reason?.kind === "readiness")
    .map<AlertItem>((x) => ({
      key: x.request_id,
      title: `${x.request_id} deferred — not ready`,
      meta: x.reason!.why || x.reason!.message,
      tag: `bus ${x.bus_id}`,
      fg: "#92400e",
      project: x.request_id,
    }));
  if (dr.length) groups.push({ key: "dr", label: "Deferred on readiness", color: "#fcd34d", fg: "#92400e", items: dr });

  const rj = byStatus(q, "Rejected").map<AlertItem>((x) => ({
    key: x.request_id,
    title: `${x.request_id} rejected at intake`,
    meta: x.reason ? x.reason.why || x.reason.message : "Rejected at intake",
    tag: "intake",
    fg: "#4b5563",
    project: x.request_id,
  }));
  if (rj.length) groups.push({ key: "rj", label: "Intake rejections", color: "#9ca3af", fg: "#4b5563", items: rj });
  return groups;
}

export const violationCount = (groups: AlertGroup[]): number =>
  groups.filter((g) => g.key === "viol" || g.key === "dg").reduce((a, g) => a + g.items.length, 0);

// ---- misc -----------------------------------------------------------------------------------
export function isStale(lp: RunParams | null, activeBranch: string, eg30: number, eg35: number, n: number): boolean {
  return !!lp && (lp.branch !== (activeBranch || "main") || lp.g30 !== eg30 || lp.g35 !== eg35 || lp.n !== n);
}

/** Readiness from the ticked evidence: a 0.1 floor plus the evidence weights (land .3, planning .35, finance .25). */
export const readyFromForm = (f: Pick<FormState, "land" | "planning" | "finance">): number =>
  +(0.1 + (f.land ? 0.3 : 0) + (f.planning ? 0.35 : 0) + (f.finance ? 0.25 : 0)).toFixed(2);
