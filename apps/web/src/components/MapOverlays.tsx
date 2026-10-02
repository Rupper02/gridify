import type { PlannerSlice, WithPatch } from "../hooks/planner/slice";

import { timelineRollup } from "../lib/derive";
import { fmtMw } from "../theme";

export type TimelineBoxPlanner = PlannerSlice<"timelineYear", never, "phase"> & WithPatch;
type GspFiguresPlanner = PlannerSlice<"boundary", never, "ph">;
export type StatsBarPlanner = PlannerSlice<
  "result" | "model" | "timelineYear" | "boundary" | "showBoundary",
  never,
  "ph" | "q" | "eg30" | "eg35" | "phase"
> &
  WithPatch;
export type BoundaryCardPlanner = PlannerSlice<"boundary" | "timelineYear", never, "ph"> & WithPatch;

export function TimelineBox({ planner }: { planner: TimelineBoxPlanner }) {
  const { s, patch, derived } = planner;
  const y = s.timelineYear;
  const label = y <= 2026 ? "as-is today" : derived.phase === "2030" ? "Clean Power lens" : "Strategic lens";
  const fg = y <= 2026 ? "#0d9488" : derived.phase === "2030" ? "#16a34a" : "#2563eb";
  return (
    <div className="row" style={{ gap: 10 }}>
      <div className="timeline-box">
        <div className="row" style={{ alignItems: "baseline", justifyContent: "space-between", gap: 10 }}>
          <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.07em", color: "var(--mute)" }}>TIMELINE</span>
          <span>
            <b className="mono" style={{ fontSize: 15, fontWeight: 700 }}>{y}</b>{" "}
            <span style={{ fontSize: 10.5, color: fg, fontWeight: 600 }}>{label}</span>
          </span>
        </div>
        <input type="range" min={2026} max={2035} step={1} value={y} onChange={(e) => patch({ timelineYear: +e.target.value })} />
        <div className="mono" style={{ display: "flex", justifyContent: "space-between", fontSize: 8.5, color: "var(--mute2)" }}>
          <span>2026 · today</span>
          <span>2035</span>
        </div>
      </div>
    </div>
  );
}

/** Worst-case GSP exchange for the phase in view, against its export limit. */
function gspFigures(planner: GspFiguresPlanner) {
  const { s, derived } = planner;
  const ph = derived.ph;
  const B = s.boundary;
  const lim = ph && ph.gsp_limit_mw != null ? ph.gsp_limit_mw : B?.export_limit_mw ?? null;
  const exp = ph ? Math.round(ph.gsp_export_mw || 0) : null;
  const imp = ph ? Math.round(ph.gsp_import_mw || 0) : 0;
  const util = lim && exp != null ? exp / lim : 0;
  const fg = util > 1 ? "#dc2626" : util > 0.9 ? "#b45309" : "var(--ink)";
  return { lim, exp, imp, util, fg };
}

export function StatsBar({ planner }: { planner: StatsBarPlanner }) {
  const { s, patch, derived } = planner;
  const { ph, q, eg30, eg35, phase } = derived;
  const r = s.result;
  const growth = phase === "2030" ? eg30 : eg35;
  const tl = timelineRollup(q, s.timelineYear);
  const { lim, exp, imp, fg } = gspFigures(planner);
  const gens = s.model?.generators ?? [];
  return (
    <div className="stats">
      <span>Demand <b>×{growth.toFixed(2)}</b></span>
      <span>Existing fleet <b style={{ color: "#0d9488" }}>{s.model ? `${gens.length} · ${fmtMw(gens.reduce((a, g) => a + (g.rating_mw || 0), 0))} MW` : "—"}</b></span>
      <span>Online by {s.timelineYear} <b>{r ? `${tl.online.length} · ${fmtMw(tl.onlineMw)} MW` : "—"}</b></span>
      <span>New in {s.timelineYear} <b style={{ color: r && tl.fresh.length ? "#b45309" : "var(--mute2)" }}>{r && tl.fresh.length ? `+${tl.fresh.length} · ${fmtMw(tl.freshMw)} MW` : "—"}</b></span>
      <span
        className="link"
        title={lim ? `Worst-case power pushed up through the GSP to the transmission system, against the ${Math.round(lim)} MW it can take. Click for what's beyond the GSP.` : "Worst-case power exchanged with the transmission system at the GSP."}
        onClick={() => patch({ showBoundary: !s.showBoundary })}
      >
        GSP → transmission <b style={{ color: fg }}>{exp == null ? "—" : exp > 0 ? `${exp}${lim ? ` / ${Math.round(lim)}` : ""} MW export` : `${imp} MW import`}</b>{" "}
        <span style={{ color: "var(--blue)", fontSize: 10.5 }}>{s.boundary ? (s.showBoundary ? "▴" : "▾") : ""}</span>
      </span>
      <span>Worst line <b style={{ color: ph && ph.worst_line_loading_pct > 100 ? "#dc2626" : "var(--ink)" }}>{ph ? `${ph.worst_line_loading_pct.toFixed(0)}%` : "—"}</b></span>
      <span>Voltage <b>{ph ? `${ph.min_vm_pu.toFixed(3)}–${ph.max_vm_pu.toFixed(3)} pu` : "—"}</b></span>
      <span title="Single-outage screen of the 132 kV backbone at winter peak: outages that overload something, breach a voltage band or island demand. Reported, not a connection gate.">
        N-1 <b style={{ color: ph && ph.n1_violations?.length ? "#c2410c" : "var(--ink)" }}>{ph ? `${ph.n1_violations?.length ?? 0} / ${ph.n1_screened ?? 0}` : "—"}</b>
      </span>
    </div>
  );
}

export function BoundaryCard({ planner }: { planner: BoundaryCardPlanner }) {
  const { s, patch } = planner;
  const B = s.boundary!;
  const { lim, exp, fg } = gspFigures(planner);
  return (
    <div className="boundary">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
        <span className="caps">Beyond the GSP · {B.gsp_name}</span>
        <button className="btn plain" style={{ fontSize: 14, color: "var(--mute2)" }} onClick={() => patch({ showBoundary: false })}>×</button>
      </div>
      <div className="kv" style={{ marginTop: 8 }}>
        <span className="k">Export limit</span><span className="v">{Math.round(B.export_limit_mw)} MW ({B.sgt_count} SGTs)</span>
        <span className="k">Firm (one SGT out)</span><span className="v">{Math.round(B.firm_export_mw)} MW</span>
        <span className="k">Export today</span><span className="v">{Math.round(B.export_today_mw)} MW</span>
        <span className="k">In {s.timelineYear}</span><span className="v" style={{ color: fg }}>{exp == null ? "run the simulation" : `${exp} of ${Math.round(lim ?? 0)} MW`}</span>
      </div>
      <div className="pretty" style={{ marginTop: 9, fontSize: 11.5, color: "var(--ink3)" }}>
        This region already generates more than it uses, so new generation flows <b>up</b> through the supergrid transformers into the transmission system. That boundary — not the local wires — is what fills up first.
      </div>
      <div className="caps" style={{ marginTop: 10, fontWeight: 700, letterSpacing: "0.07em", color: "var(--mute)" }}>Transmission projects at Bicker Fen</div>
      {B.transmission_projects.map((p) => {
        const built = p.status === "Built";
        // only what exists today is in the network; a not-yet-built project at the GSP is an OPTIONAL
        // registry project like any other: it counts only once you add it to a branch
        const tag = p.registry_id
          ? `Not built yet — would connect at the GSP and flow through our supergrid transformers. Optional: add ${p.registry_id} from the registry.`
          : built
            ? "In service at 400 kV — bypasses this network, but uses transmission capacity out of Lincolnshire"
            : "Planned at 400 kV — bypasses this network, but would compete for the same transmission capacity";
        return (
          <div key={p.name} style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "6px 0", borderTop: "1px solid #f3f4f6" }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600, color: "var(--ink)" }}>{p.name}</div>
              <div style={{ fontSize: 11, color: "var(--mute)" }}>{p.type} · {p.status} · {built ? `in service since ${p.year}` : `contracted date ${p.year}`}</div>
              <div style={{ fontSize: 11, color: p.registry_id ? "#b45309" : "var(--mute)", marginTop: 1 }}>{tag}</div>
            </div>
            <span className="mono" style={{ fontWeight: 600, whiteSpace: "nowrap", color: built ? "var(--ink)" : "var(--mute2)" }}>{fmtMw(p.mw)} MW</span>
          </div>
        );
      })}
      <div className="pretty" style={{ marginTop: 8, fontSize: 10.5, color: "var(--mute2)" }}>
        Sources: {B.source}; NESO TEC &amp; Interconnector registers. Not modelled: the 400 kV network itself and fault levels (published ratings are ambiguous).
      </div>
    </div>
  );
}
