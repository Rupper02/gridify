// The card for the selected map element: a connection application (with its energisation-year
// stepper), a line, a bus or a transformer.

import type { Planner } from "../hooks/usePlanner";
import { lineMva, loadPct, trafoRatio, trafoSub, vmAt, voltageBandLabel } from "../lib/derive";
import { ST, fmtMw, techLabel } from "../theme";
import type { QueueItem } from "../types";

interface Row {
  k: string;
  v: string;
  color?: string;
}
interface Note {
  label: string;
  body: string;
  next?: string;
  bg: string;
  bd: string;
  fg: string;
  labelFg: string;
}
interface Detail {
  kind: string;
  title: string;
  subtitle: string;
  chip?: { label: string; bg: string; fg: string };
  rows: Row[];
  note?: Note;
  action?: { label: string; onClick: () => void };
  schedule?: {
    can: boolean;
    rec: number | null;
    eff: number | null;
    overridden: boolean;
    warn: string;
    rid: string;
  };
}

interface Props {
  planner: Planner;
  selQ: QueueItem | null;
  over: Set<number>;
  vv: Set<number>;
  busProjects: Record<number, QueueItem[]>;
}

export function DetailCard({ planner, selQ, over, vv, busProjects }: Props) {
  const { s, patch, actions, derived } = planner;
  const { q, phase, eg30, eg35 } = derived;
  const sel = s.sel;
  const m = s.model;
  const r = s.result;
  if (!sel || !m || !r) return null;
  const growth = phase === "2030" ? eg30 : eg35;
  let d: Detail | null = null;

  if (sel.kind === "project" && selQ) {
    const x = selQ;
    const st = ST[x.status];
    d = {
      kind: "Connection application",
      title: x.request_id,
      subtitle: x.applicant || "",
      chip: { label: st.label, bg: st.bg, fg: st.fg },
      rows: [
        { k: "Technology", v: techLabel(x.technology) ?? "—" },
        { k: "Capacity", v: `${fmtMw(x.rating_mw)} MW` },
        { k: "Point of connection", v: x.bus_id != null ? `Bus ${x.bus_id}` : "—" },
        { k: "Queue rank", v: x.rank != null ? `#${x.rank}` : "—" },
        { k: "Readiness", v: `${Math.round(x.readiness_score * 100)}%` },
        { k: "Grid need", v: x.grid_need ? x.grid_need.toFixed(2) : "—" },
        { k: "Rank score", v: x.rank_score != null ? x.rank_score.toFixed(3) : "—" },
      ],
    };
    if (x.reason) {
      const rk = x.reason.kind;
      const label =
        rk === "grid"
          ? x.status === "Deferred" ? "Ready — but the grid here can’t take it yet" : "Grid constraint"
          : rk === "readiness" ? "Not developed enough yet" : rk === "phased" ? "Held to 2035" : "Can’t be assessed yet";
      const warm =
        rk === "phased"
          ? { bg: "#eff6ff", bd: "#bfdbfe", fg: "#1e40af", labelFg: "#2563eb" }
          : rk === "intake"
            ? { bg: "#f9fafb", bd: "#e5e7eb", fg: "#4b5563", labelFg: "#6b7280" }
            : { bg: "#fffbeb", bd: "#fde68a", fg: "#92400e", labelFg: "#b45309" };
      d.note = { label, body: x.reason.why || x.reason.message, next: x.reason.action || undefined, ...warm };
      if (x.reason.element) d.action = { label: "Zoom to the binding constraint", onClick: () => actions.selectProject(x.request_id, true) };
    } else if (x.status === "Phase1" || x.status === "Phase2") {
      d.note = {
        label: "No binding constraint",
        body: x.status === "Phase1" ? "Clears thermal and voltage limits under both 2030 and 2035 demand." : "Clears network limits under 2035 demand; readiness supports 2035 delivery.",
        bg: st.soft, bd: st.bd, fg: st.fg, labelFg: st.c,
      };
    }
    // energisation scheduling: the optimizer recommends a year; the operator confirms/overrides it
    const can = x.status === "Phase1" || x.status === "Phase2";
    const rec = x.recommended_year;
    const ov = x.scheduled_year;
    const eff = can ? (ov != null ? ov : rec) : null;
    let warn = "";
    if (!can)
      warn = x.status === "Rejected"
        ? "Rejected at intake — fix the application before it can be scheduled."
        : "Deferred — it can’t connect until the grid is reinforced. Open Review → Copilot for the unblock.";
    else if (ov != null && rec != null && ov < rec) warn = `Earlier than the grid supports — recommended ${rec}. Marked as against the recommendation.`;
    d.schedule = { can, rec, eff, overridden: can && ov != null && ov !== rec, warn, rid: x.request_id };
  }

  if (sel.kind === "line") {
    const l = m.lines.find((x) => x.line_id === sel.id);
    if (l) {
      const binds = q.filter((x) => x.reason?.element?.line_id === l.line_id);
      const v30 = loadPct(r, "2030", l.line_id);
      const v35 = loadPct(r, "2035", l.line_id);
      const isO = over.has(l.line_id);
      d = {
        kind: "Line",
        title: l.line_name,
        subtitle: l.in_service === false ? "Normally-open point" : l.voltage_kv ? `${+l.voltage_kv} kV circuit` : "Circuit",
        chip: isO || binds.length ? { label: isO ? `Overloaded · ${phase}` : "Binding constraint", bg: isO ? "#fee2e2" : "#fef3c7", fg: isO ? "#991b1b" : "#92400e" } : undefined,
        rows: [
          { k: "Thermal rating", v: `${l.rating_a} A` },
          { k: "Capacity", v: lineMva(l) },
          { k: "Length", v: `${(l.length_km || 0).toFixed(2)} km` },
          { k: "Loading 2030", v: v30 == null ? "—" : `${v30.toFixed(1)}%`, color: v30 != null && v30 > 100 ? "#dc2626" : undefined },
          { k: "Loading 2035", v: v35 == null ? "—" : `${v35.toFixed(1)}%`, color: v35 != null && v35 > 100 ? "#dc2626" : undefined },
        ],
      };
      if (binds.length)
        d.note = { label: "Holding back", body: binds.map((x) => `${x.request_id} (${fmtMw(x.rating_mw)} MW) — ${x.reason!.short || x.reason!.message}`).join(" · "), bg: "#fffbeb", bd: "#fde68a", fg: "#92400e", labelFg: "#b45309" };
      else if (isO)
        d.note = { label: "Demand-driven overload", body: `Load growth to ×${growth.toFixed(2)} pushes this section past its rating. Local generation or reinforcement would relieve it.`, bg: "#fef2f2", bd: "#fecaca", fg: "#991b1b", labelFg: "#dc2626" };
    }
  }

  if (sel.kind === "bus") {
    const ps = busProjects[sel.id] ?? [];
    const b = m.buses.find((x) => x.bus_id === sel.id);
    const v30 = vmAt(r, "2030", sel.id);
    const v35 = vmAt(r, "2035", sel.id);
    d = {
      kind: "Bus",
      title: `Bus ${sel.id}`,
      subtitle: b?.vn_kv != null ? `${b.vn_kv} kV node` : "Network node",
      chip: vv.has(sel.id) ? { label: "Voltage breach", bg: "#fee2e2", fg: "#991b1b" } : undefined,
      rows: [
        { k: "Statutory band", v: voltageBandLabel(b?.vn_kv) },
        { k: "Voltage 2030", v: v30 == null ? "—" : `${v30.toFixed(3)} pu` },
        { k: "Voltage 2035", v: v35 == null ? "—" : `${v35.toFixed(3)} pu` },
        { k: "Projects here", v: ps.length ? ps.map((x) => x.request_id).join(", ") : "None" },
      ],
      action: { label: "New application at this bus", onClick: () => actions.newApplicationAt(sel.id) },
    };
  }

  if (sel.kind === "trafo") {
    const t = m.transformers.find((x) => x.trafo_id === sel.id);
    if (t)
      d = {
        kind: (t.hv_kv || 0) >= 132 ? "Grid / bulk supply transformer" : "Primary substation transformer",
        title: trafoSub(t),
        subtitle: `HV bus ${t.hv_bus ?? "—"} → LV bus ${t.lv_bus ?? "—"}`,
        rows: [{ k: "Rating", v: `${fmtMw(t.sn_mva)} MVA` }, { k: "Ratio", v: trafoRatio(t) }, { k: "Vector group", v: t.name || "—" }],
      };
  }

  if (!d) return null;
  const sc = d.schedule;
  return (
    <div className="detail" onMouseDown={(e) => e.stopPropagation()}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="caps">{d.kind}</div>
          <div className="title">{d.title}</div>
          <div className="ellipsis" title={d.subtitle} style={{ fontSize: 12, color: "var(--mute)", marginTop: 1 }}>{d.subtitle}</div>
        </div>
        <button className="btn icon" onClick={() => patch({ sel: null })}>×</button>
      </div>
      {d.chip && (
        <div style={{ marginTop: 10 }}>
          <span className="chip" style={{ background: d.chip.bg, color: d.chip.fg, fontSize: 11.5, padding: "3px 8px" }}>{d.chip.label}</span>
        </div>
      )}
      <div className="kv">
        {d.rows.map((row) => (
          <RowView key={row.k} row={row} />
        ))}
      </div>
      {d.note && (
        <div className="note" style={{ background: d.note.bg, borderColor: d.note.bd }}>
          <div className="label" style={{ color: d.note.labelFg }}>{d.note.label}</div>
          <div className="body pretty" style={{ color: d.note.fg }}>{d.note.body}</div>
          {d.note.next && (
            <div className="next pretty" style={{ color: d.note.fg, borderTopColor: d.note.bd }}>
              <span style={{ fontWeight: 700 }}>What to do →</span> {d.note.next}
            </div>
          )}
        </div>
      )}
      {sc && (
        <div className="sched">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
            <span className="caps" style={{ fontWeight: 700, color: "var(--mute)" }}>Energisation year</span>
            <span style={{ fontSize: 11, color: "var(--mute)" }}>
              recommended <b className="mono" style={{ color: "var(--ink)" }}>{sc.rec != null ? sc.rec : "not schedulable"}</b>
            </span>
          </div>
          {sc.can && (
            <div className="row" style={{ marginTop: 8 }}>
              <button className="step" onClick={() => void actions.setSchedule(sc.rid, (sc.eff ?? sc.rec ?? 2030) - 1)}>−</button>
              <span className="year">{sc.eff != null ? sc.eff : "—"}</span>
              <button className="step" onClick={() => void actions.setSchedule(sc.rid, (sc.eff ?? sc.rec ?? 2030) + 1)}>+</button>
              {sc.overridden && (
                <button className="btn plain" style={{ marginLeft: 2, padding: "0 8px", height: 28, borderRadius: 6, fontSize: 11.5, fontWeight: 600, color: "var(--blue)" }} onClick={() => void actions.setSchedule(sc.rid, null)}>
                  ↺ recommended
                </button>
              )}
            </div>
          )}
          {sc.warn && <div className="pretty" style={{ marginTop: 8, fontSize: 12, color: "#b45309" }}>⚠ {sc.warn}</div>}
        </div>
      )}
      {d.action && (
        <button className="btn" style={{ marginTop: 10, width: "100%", height: 30, fontSize: 12 }} onClick={d.action.onClick}>{d.action.label}</button>
      )}
    </div>
  );
}

function RowView({ row }: { row: Row }) {
  return (
    <>
      <span className="k">{row.k}</span>
      <span className="v" style={{ color: row.color ?? "var(--ink)" }}>{row.v}</span>
    </>
  );
}
