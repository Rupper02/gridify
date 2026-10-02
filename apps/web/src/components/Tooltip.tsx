import type { PlannerSlice } from "../hooks/planner/slice";
import { lineMva, loadPct, trafoRatio, trafoSub, vmAt, voltageBand, voltageBandLabel } from "../lib/derive";
import { ST, fmtMw, techLabel } from "../theme";
import type { HitKind, Model, PhaseKey, QueueItem } from "../types";

export type TooltipPlanner = PlannerSlice<
  "hover" | "model" | "mouse" | "pickMode" | "result" | "size" | "timelineYear",
  never,
  "q" | "qById" | "phase" | "egYear"
>;

interface Row {
  k: string;
  v: string;
  color?: string;
}
interface View {
  title: string;
  rows: Row[];
}
/** Everything a tooltip builder may read; `m` is the loaded model. */
interface Ctx {
  planner: TooltipPlanner;
  m: Model;
  bindLines: Set<number>;
  busProjects: Record<number, QueueItem[]>;
}

const pctColor = (v: number | null) => (v == null ? "#9ca3af" : v > 100 ? "#f87171" : v > 90 ? "#fbbf24" : "#f9fafb");
const vColor = (v: number | null, kv?: number | null) => {
  if (v == null) return "#9ca3af";
  const [lo, hi] = voltageBand(kv);
  return v > hi || v < lo ? "#f87171" : "#f9fafb";
};

function lineTip({ planner, m, bindLines }: Ctx, id: number | string): View | null {
  const { s, derived } = planner;
  const l = m.lines.find((x) => x.line_id === id);
  if (!l) return null;
  const rows: Row[] = [
    { k: "Voltage", v: l.voltage_kv ? `${+l.voltage_kv} kV` : "—" },
    { k: "Rating", v: `${l.rating_a} A · ${lineMva(l)}` },
    { k: "Length", v: `${l.length_km != null ? l.length_km.toFixed(2) : "—"} km` },
  ];
  if (l.in_service === false) rows.push({ k: "State", v: "Open point" });
  else {
    const v = loadPct(s.result, derived.phase, l.line_id);
    rows.push({ k: `Loading ${s.timelineYear}`, v: v == null ? "—" : `${v.toFixed(0)}%`, color: pctColor(v) });
  }
  if (bindLines.has(l.line_id))
    rows.push({ k: "Binds", v: derived.q.filter((x) => x.reason?.element?.line_id === l.line_id).map((x) => x.request_id).join(", "), color: "#fbbf24" });
  return { title: l.line_name, rows };
}

function busTip({ planner, m, busProjects }: Ctx, rawId: number | string): View {
  const { s, derived } = planner;
  const id = Number(rawId);
  const ps = busProjects[id] ?? [];
  const bb = m.buses.find((x) => x.bus_id === id);
  const rows: Row[] = [{ k: "Voltage level", v: bb?.vn_kv != null ? `${bb.vn_kv} kV` : "—" }, { k: "Statutory band", v: voltageBandLabel(bb?.vn_kv) }];
  const v = vmAt(s.result, derived.phase, id);
  rows.push({ k: `V ${s.timelineYear}`, v: v == null ? "—" : `${v.toFixed(3)} pu`, color: vColor(v, bb?.vn_kv) });
  if (ps.length) rows.push({ k: "Projects", v: ps.map((x) => x.request_id).join(", ") });
  if (s.pickMode) rows.push({ k: "", v: "Click to select", color: "#93c5fd" });
  return { title: `Bus ${id}`, rows };
}

function projectTip({ planner }: Ctx, id: number | string): View | null {
  const x = planner.derived.qById[String(id)];
  if (!x) return null;
  const rows: Row[] = [
    { k: "Applicant", v: x.applicant || "—" },
    { k: "Status", v: ST[x.status].label, color: { Phase1: "#86efac", Phase2: "#93c5fd", Deferred: "#fcd34d", Rejected: "#d1d5db" }[x.status] },
    { k: "Capacity", v: `${techLabel(x.technology) ?? "—"} · ${fmtMw(x.rating_mw)} MW` },
    { k: "Bus", v: String(x.bus_id) },
  ];
  if (x.reason) rows.push({ k: "Reason", v: x.reason.message.length > 34 ? x.reason.message.slice(0, 33) + "…" : x.reason.message, color: "#fcd34d" });
  return { title: x.request_id, rows };
}

function loadTip({ planner, m }: Ctx, id: number | string): View | null {
  const { s, derived } = planner;
  const { egYear } = derived;
  const l = m.loads.find((x) => x.load_id === id);
  if (!l) return null;
  return {
    title: `Load at bus ${l.bus_id}`,
    rows: [
      { k: "Base demand", v: `${l.p_mw.toFixed(2)} MW` },
      { k: `${s.timelineYear}`, v: `${(l.p_mw * egYear).toFixed(2)} MW` },
    ],
  };
}

function trafoTip({ m }: Ctx, id: number | string): View | null {
  const t = m.transformers.find((x) => x.trafo_id === id);
  if (!t) return null;
  return {
    title: `${trafoSub(t)} transformer`,
    rows: [{ k: "Rating", v: `${fmtMw(t.sn_mva)} MVA` }, { k: "Ratio", v: trafoRatio(t) }, { k: "Vector group", v: t.name || "—" }],
  };
}

function existingTip({ m }: Ctx, id: number | string): View | null {
  const g = (m.generators ?? []).find((x) => x.request_id === id);
  if (!g) return null;
  return {
    title: g.applicant || g.request_id,
    rows: [
      { k: "", v: "Existing connection", color: "#cbd5e1" },
      { k: "Technology", v: techLabel(g.technology) ?? g.technology ?? "—" },
      { k: "Capacity", v: `${fmtMw(g.rating_mw)} MW` },
      { k: "Bus", v: String(g.bus_id) },
    ],
  };
}

/** What to show for each kind of hovered map element: a new kind is one entry (the type checks it). */
const TIPS: Record<HitKind, (ctx: Ctx, id: number | string) => View | null> = {
  line: lineTip,
  bus: busTip,
  project: projectTip,
  load: loadTip,
  trafo: trafoTip,
  existing: existingTip,
};

export function Tooltip({ planner, bindLines, busProjects }: { planner: TooltipPlanner; bindLines: Set<number>; busProjects: Record<number, QueueItem[]> }) {
  const { s } = planner;
  const hov = s.hover;
  const m = s.model;
  if (!hov || !m) return null;

  const view = TIPS[hov.kind]({ planner, m, bindLines, busProjects }, hov.id);
  if (!view?.title) return null;
  const x = s.mouse.x > s.size.w - 240 ? s.mouse.x - 226 : s.mouse.x + 14;
  const y = Math.min(s.mouse.y + 14, s.size.h - 150);
  return (
    <div className="tip" style={{ left: x, top: y }}>
      <div className="title">{view.title}</div>
      <div className="kv">
        {view.rows.map((row, i) => (
          <RowView key={i} row={row} />
        ))}
      </div>
    </div>
  );
}

function RowView({ row }: { row: Row }) {
  return (
    <>
      <span className="k">{row.k}</span>
      <span className="v mono" style={{ color: row.color ?? "#f9fafb" }}>{row.v}</span>
    </>
  );
}
