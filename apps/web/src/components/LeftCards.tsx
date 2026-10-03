// Top-left: the result stamp (which profile the shown result was solved on, how many years are in,
// and whether it is out of date) and the readings for the selected year. Below 1100px wide they
// collapse into one pill.

import { X } from "@phosphor-icons/react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { gspTicks, worstElement } from "../lib/derive";
import type { Layout } from "../lib/layout";
import { C, fmtMw } from "../theme";
import { Gauge, ProfileGlyph } from "./ui";

export type LeftCardsPlanner = PlannerSlice<
  "boundary" | "outages" | "result" | "resultAt" | "running" | "showBoundary" | "solving" | "year",
  "focusSel" | "run" | "toggleBoundary",
  "exact" | "ix" | "profile" | "resultProfile" | "stale" | "yearsSolved" | "yearsTotal" | "yr"
>;

export function LeftCards({ planner, layout }: { planner: LeftCardsPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const { yr, stale, resultProfile, profile } = derived;
  const limit = yr?.gsp_limit_mw ?? s.boundary?.export_limit_mw ?? null;
  const gsp = yr?.gsp_export_mw ?? null;
  const gspHot = gsp != null && limit ? gsp / limit > 0.9 : false;
  const runLabel = `${stale.stale ? "Re-run" : "Run"} on ${profile.label}`;

  if (layout.narrow) {
    return (
      <div className="narrow-pill glass" style={{ borderColor: stale.stale ? "rgba(255,195,107,0.45)" : undefined }}>
        <ProfileGlyph bars={resultProfile.bars} />
        <span style={{ fontSize: 12, fontWeight: 600 }}>{resultProfile.label} result</span>
        <span className="mono" style={{ fontSize: 11, color: gspHot ? C.amber : C.ink2 }}>
          GSP {gsp != null ? Math.round(gsp) : "–"}/{limit != null ? Math.round(limit) : "–"}
        </span>
        {stale.stale && (
          <button className="btn warn" style={{ height: 24, fontSize: 11 }} onClick={() => void actions.run()}>
            Out of date · re-run
          </button>
        )}
      </div>
    );
  }

  const reserve = layout.showDock ? layout.dockPx + 88 : 88;
  return (
    <div className="left-col" style={{ maxHeight: `calc(100% - ${reserve}px)` }}>
      <ResultStamp planner={planner} runLabel={runLabel} />
      {layout.showReadings && s.result && <Readings planner={planner} gsp={gsp} limit={limit} gspHot={gspHot} />}
      {s.showBoundary && s.boundary && <BoundaryCard planner={planner} />}
    </div>
  );
}

function ResultStamp({ planner, runLabel }: { planner: LeftCardsPlanner; runLabel: string }) {
  const { s, actions, derived } = planner;
  const { stale, resultProfile, yearsSolved, yearsTotal } = derived;
  const n = s.outages.length;
  const sub = !s.result
    ? "No run yet"
    : yearsSolved < yearsTotal
      ? `Solving years · ${yearsSolved} of ${yearsTotal} in`
      : `All years solved${n ? ` · ${n} planned outage${n > 1 ? "s" : ""}` : ""}`;
  return (
    <div className="card glass">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>Simulation result</span>
        <span className="mono" style={{ fontSize: 10.5, color: C.mute }}>{s.resultAt ? `run ${s.resultAt} · ${s.year}` : String(s.year)}</span>
      </div>
      <div className="stamp">
        <ProfileGlyph bars={resultProfile.bars} big />
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.25 }}>
          <span style={{ fontSize: 15, fontWeight: 600 }}>{resultProfile.label} demand</span>
          <span style={{ fontSize: 11, color: C.mute }}>{sub}</span>
        </div>
      </div>
      {stale.stale && (
        <div className="box amber">
          <span style={{ fontSize: 12, color: C.amberInk, lineHeight: 1.4, textWrap: "pretty" }}>{stale.text}</span>
          <button className="btn warn" style={{ alignSelf: "flex-start" }} onClick={() => void actions.run()} disabled={s.running}>
            {runLabel}
          </button>
        </div>
      )}
    </div>
  );
}

function Readings({ planner, gsp, limit, gspHot }: { planner: LeftCardsPlanner; gsp: number | null; limit: number | null; gspHot: boolean }) {
  const { s, actions, derived } = planner;
  const { yr, ix, exact } = derived;
  const worst = worstElement(yr, ix);
  const sgt = s.boundary?.sgt_count;
  const sgtMw = s.boundary && sgt ? s.boundary.export_limit_mw / sgt : null;
  return (
    <div className="card glass" style={{ gap: 14 }}>
      <button className="gsp-btn" onClick={actions.toggleBoundary} title="Beyond the GSP: limits and transmission projects">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <span style={{ fontSize: 11.5, color: C.mute }}>GSP export</span>
          <span className="mono" style={{ fontSize: 13, fontWeight: 600, color: gspHot ? C.amber : C.ink }}>
            {gsp != null ? fmtMw(gsp) : "–"} / {limit != null ? fmtMw(limit) : "–"} MW
          </span>
        </div>
        <Gauge ticks={gspTicks(gsp ?? 0, limit)} />
        <span style={{ fontSize: 10.5, color: C.mute2 }}>
          Worst case{sgt && sgtMw ? ` · ${sgt} × ${fmtMw(sgtMw)} MW SGTs` : ""}
          {!exact && yr ? ` · showing ${yr.year} until ${s.year} is solved` : ""}
        </span>
      </button>
      <div className="readings">
        <button
          className="reading reading-btn"
          onClick={() => worst && actions.focusSel(worst.sel, 2.4)}
          disabled={!worst}
          title={worst ? `Show the ${worst.name} on the map` : undefined}
        >
          <span className="k">Worst element</span>
          <span className="v" style={{ color: worst ? (worst.pct > 100 ? C.red : worst.pct > 90 ? C.amber : C.ink) : C.ink }}>
            {worst ? `${Math.round(worst.pct)}%` : "–"}
          </span>
          <span className="n">{worst?.name ?? "not solved yet"}</span>
        </button>
        <div className="reading">
          <span className="k">Voltage band</span>
          <span className="v">{yr ? yr.min_vm_pu.toFixed(3) : "–"}</span>
          <span className="n">to {yr ? yr.max_vm_pu.toFixed(3) : "–"} pu · {yr?.voltage_violation_bus_ids.length ? `${yr.voltage_violation_bus_ids.length} outside band` : "statutory bands"}</span>
        </div>
        <div className="reading">
          <span className="k">Peak demand</span>
          <span className="v">×{yr ? yr.growth.toFixed(2) : "–"}</span>
          <span className="n">vs today, by {yr?.year ?? s.year}</span>
        </div>
        <div className="reading">
          <span className="k">N-1 findings</span>
          <span className="v" style={{ color: yr?.n1_violations.length ? C.amber : C.ink }}>
            {yr ? `${yr.n1_violations.length} / ${yr.n1_screened}` : "–"}
          </span>
          <span className="n">132 kV outages screened, reported only</span>
        </div>
      </div>
      {s.solving && !s.running && <span style={{ fontSize: 10.5, color: C.mute2 }}>Solving the remaining years in the background.</span>}
    </div>
  );
}

function BoundaryCard({ planner }: { planner: LeftCardsPlanner }) {
  const { s, actions, derived } = planner;
  const b = s.boundary!;
  const yr = derived.yr;
  return (
    <div className="card glass boundary-card">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, flex: 1 }}>Beyond the GSP</span>
        <button className="icon-btn" onClick={actions.toggleBoundary} aria-label="Close">
          <X size={12} />
        </button>
      </div>
      <div className="rows">
        <span className="mute">Export limit</span>
        <span className="mono">{fmtMw(b.export_limit_mw)} MW</span>
        <span className="mute">Firm (one SGT out)</span>
        <span className="mono">{fmtMw(b.firm_export_mw)} MW</span>
        <span className="mute">Export today</span>
        <span className="mono">{fmtMw(b.export_today_mw)} MW</span>
        <span className="mute">Export in {yr?.year ?? s.year}</span>
        <span className="mono">{yr ? `${fmtMw(yr.gsp_export_mw)} MW` : "–"}</span>
      </div>
      <span className="mute" style={{ fontSize: 11.5 }}>
        {b.gsp_name} already exports this region's surplus generation up to transmission, so its supergrid transformers fill first. The export
        sign convention is assumed; fault levels and the 400 kV network are not modelled.
      </span>
      {b.transmission_projects.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 11.5, fontWeight: 600 }}>Transmission projects behind it</span>
          {b.transmission_projects.map((t) => (
            <span key={t.name} style={{ display: "flex", gap: 6, fontSize: 11 }}>
              <span className="grow ellipsis">{t.name}</span>
              <span className="mono mute">{fmtMw(t.mw)} MW · {t.year}</span>
            </span>
          ))}
        </div>
      )}
      <span className="mute-2" style={{ fontSize: 10.5 }}>Source: {b.source}</span>
    </div>
  );
}
