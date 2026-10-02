import type { Planner } from "../hooks/usePlanner";
import { lineMva, loadPct, trafoRatio, trafoSub, vmAt } from "../lib/derive";
import { ST, fmtMw, techLabel } from "../theme";
import type { PhaseKey, QueueItem } from "../types";

interface Row {
  k: string;
  v: string;
  color?: string;
}

const pctColor = (v: number | null) => (v == null ? "#9ca3af" : v > 100 ? "#f87171" : v > 90 ? "#fbbf24" : "#f9fafb");
const vColor = (v: number | null) => (v == null ? "#9ca3af" : v > 1.1 || v < 0.9 ? "#f87171" : "#f9fafb");
const PHASES: PhaseKey[] = ["2030", "2035"];

export function Tooltip({ planner, bindLines, busProjects }: { planner: Planner; bindLines: Set<number>; busProjects: Record<number, QueueItem[]> }) {
  const { s, derived } = planner;
  const { q, qById, eg30, eg35 } = derived;
  const hov = s.hover;
  const m = s.model;
  const r = s.result;
  if (!hov || !m) return null;

  let title = "";
  let rows: Row[] = [];
  if (hov.kind === "line") {
    const l = m.lines.find((x) => x.line_id === hov.id);
    if (l) {
      title = l.line_name;
      rows = [
        { k: "Voltage", v: l.voltage_kv ? `${+l.voltage_kv} kV` : "—" },
        { k: "Rating", v: `${l.rating_a} A · ${lineMva(l)}` },
        { k: "Length", v: `${l.length_km != null ? l.length_km.toFixed(2) : "—"} km` },
      ];
      if (l.in_service === false) rows.push({ k: "State", v: "Open point" });
      else
        PHASES.forEach((p) => {
          const v = loadPct(r, p, l.line_id);
          rows.push({ k: `Loading ${p}`, v: v == null ? "—" : `${v.toFixed(0)}%`, color: pctColor(v) });
        });
      if (bindLines.has(l.line_id))
        rows.push({ k: "Binds", v: q.filter((x) => x.reason?.element?.line_id === l.line_id).map((x) => x.request_id).join(", "), color: "#fbbf24" });
    }
  }
  if (hov.kind === "bus") {
    const id = Number(hov.id);
    const ps = busProjects[id] ?? [];
    const bb = m.buses.find((x) => x.bus_id === id);
    title = `Bus ${id}`;
    rows = [{ k: "Voltage level", v: bb?.vn_kv != null ? `${bb.vn_kv} kV` : "—" }];
    PHASES.forEach((p) => {
      const v = vmAt(r, p, id);
      rows.push({ k: `V ${p}`, v: v == null ? "—" : `${v.toFixed(3)} pu`, color: vColor(v) });
    });
    if (ps.length) rows.push({ k: "Projects", v: ps.map((x) => x.request_id).join(", ") });
    if (s.pickMode) rows.push({ k: "", v: "Click to select", color: "#93c5fd" });
  }
  if (hov.kind === "project") {
    const x = qById[String(hov.id)];
    if (x) {
      title = x.request_id;
      rows = [
        { k: "Applicant", v: x.applicant || "—" },
        { k: "Status", v: ST[x.status].label, color: { Phase1: "#86efac", Phase2: "#93c5fd", Deferred: "#fcd34d", Rejected: "#d1d5db" }[x.status] },
        { k: "Capacity", v: `${techLabel(x.technology) ?? "—"} · ${fmtMw(x.rating_mw)} MW` },
        { k: "Bus", v: String(x.bus_id) },
      ];
      if (x.reason) rows.push({ k: "Reason", v: x.reason.message.length > 34 ? x.reason.message.slice(0, 33) + "…" : x.reason.message, color: "#fcd34d" });
    }
  }
  if (hov.kind === "load") {
    const l = m.loads.find((x) => x.load_id === hov.id);
    if (l) {
      title = `Load at bus ${l.bus_id}`;
      rows = [
        { k: "Base demand", v: `${l.p_mw.toFixed(2)} MW` },
        { k: "2030", v: `${(l.p_mw * eg30).toFixed(2)} MW` },
        { k: "2035", v: `${(l.p_mw * eg35).toFixed(2)} MW` },
      ];
    }
  }
  if (hov.kind === "trafo") {
    const t = m.transformers.find((x) => x.trafo_id === hov.id);
    if (t) {
      title = `${trafoSub(t)} transformer`;
      rows = [{ k: "Rating", v: `${fmtMw(t.sn_mva)} MVA` }, { k: "Ratio", v: trafoRatio(t) }, { k: "Vector group", v: t.name || "—" }];
    }
  }
  if (hov.kind === "existing") {
    const g = (m.generators ?? []).find((x) => x.request_id === hov.id);
    if (g) {
      title = g.applicant || g.request_id;
      rows = [
        { k: "", v: "Existing connection", color: "#cbd5e1" },
        { k: "Technology", v: techLabel(g.technology) ?? g.technology ?? "—" },
        { k: "Capacity", v: `${fmtMw(g.rating_mw)} MW` },
        { k: "Bus", v: String(g.bus_id) },
      ];
    }
  }
  if (!title) return null;
  const x = s.mouse.x > s.size.w - 240 ? s.mouse.x - 226 : s.mouse.x + 14;
  const y = Math.min(s.mouse.y + 14, s.size.h - 150);
  return (
    <div className="tip" style={{ left: x, top: y }}>
      <div className="title">{title}</div>
      <div className="kv">
        {rows.map((row, i) => (
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
