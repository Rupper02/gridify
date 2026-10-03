// Top-left: the result stamp (which profile the shown result was solved on, how many years are in,
// and whether it is out of date) and the readings for the selected year. Below 1100px wide they
// collapse into one pill.

import { X } from "@phosphor-icons/react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { alertSummary } from "../lib/demand";
import { gspTicks, worstElement } from "../lib/derive";
import type { Layout } from "../lib/layout";
import { C, fmtMw } from "../theme";
import { Gauge, ProfileGlyph } from "./ui";

export type LeftCardsPlanner = PlannerSlice<
  "boundary" | "outages" | "refreshing" | "result" | "resultAt" | "running" | "showBoundary" | "solving" | "year",
  "focusSel" | "run" | "setLayer" | "toggleBoundary",
  "exact" | "ix" | "profile" | "resultProfile" | "stale" | "yearsSolved" | "yearsTotal" | "yr"
>;

export function LeftCards({ planner, layout }: { planner: LeftCardsPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const { yr, ix, stale, resultProfile, profile } = derived;
  const limit = yr?.gsp_limit_mw ?? s.boundary?.export_limit_mw ?? null;
  const gsp = yr?.gsp_export_mw ?? null;
  const gspHot = gsp != null && limit ? gsp / limit > 0.9 : false;
  const runLabel = `${stale.stale ? "Re-run" : "Run"} on ${profile.label}`;
  const showStale = stale.stale && !s.refreshing; // an automatic refresh is already on its way

  const worst = worstElement(yr, ix);
  const vMin = yr?.min_vm_pu.toFixed(3) ?? "–";
  const vMax = yr?.max_vm_pu.toFixed(3) ?? "–";
  const worstPct = worst ? Math.round(worst.pct) : null;
  
  if (layout.narrow) {
    const computing = s.refreshing || s.running;
    const winterImport = yr?.gsp_import_winter_mw !== undefined ? yr.gsp_import_winter_mw : null;
    const summerImport = yr?.gsp_import_summer_mw !== undefined ? Math.max(0, yr.gsp_import_summer_mw) : null;
    const winterLimit = s.boundary?.import_limit_mw.winter ?? null;
    const summerLimit = s.boundary?.import_limit_mw.summer ?? null;
    const winterHot = winterImport != null && winterLimit && winterImport > 0 ? winterImport / winterLimit > 0.9 : false;
    const summerHot = summerImport != null && summerLimit && summerImport > 0 ? summerImport / summerLimit > 0.9 : false;
    
    // Voltage with each case's own voltage (treat 0 as no data)
    const hasWinterVoltage = !!(yr?.min_vm_winter && yr?.max_vm_winter);
    const hasSummerVoltage = !!(yr?.min_vm_summer && yr?.max_vm_summer);
    const vDisplay = computing ? "..." : hasWinterVoltage && hasSummerVoltage && yr
      ? `${yr.min_vm_winter!.toFixed(3)}(W)–${yr.max_vm_winter!.toFixed(3)}(W) ${yr.min_vm_summer!.toFixed(3)}(S)–${yr.max_vm_summer!.toFixed(3)}(S)`
      : `${vMin}–${vMax}`;
    
    // Worst element with season or both percentages
    const worstDisplay = computing ? "..." : !worst ? "–" :
      worst.winterPct !== null && worst.summerPct !== null ? `W${Math.round(worst.winterPct)}% S${Math.round(worst.summerPct)}%` :
      worst.case && worst.winterPct !== null && worst.case === "winter peak" ? `${Math.round(worst.winterPct)}% (W)` :
      worst.case && worst.summerPct !== null && worst.case === "summer min" ? `${Math.round(worst.summerPct)}% (S)` :
      `${worstPct}%`;
    
    return (
      <div className="narrow-pill glass" style={{ borderColor: showStale ? "rgba(255,195,107,0.45)" : undefined }}>
        <ProfileGlyph bars={resultProfile.bars} />
        <span style={{ fontSize: 12, fontWeight: 600 }}>{resultProfile.label} result</span>
        <span className="mono" style={{ fontSize: 11, color: computing ? C.mute2 : gspHot ? C.amber : C.ink2 }}>
          Export{yr?.gsp_export_case ? ` (${yr.gsp_export_case === "winter_peak" ? "W" : "S"})` : ""} {computing ? "..." : gsp != null ? Math.round(gsp) : "–"}/{limit != null ? Math.round(limit) : "–"}
        </span>
        <span className="mono" style={{ fontSize: 11, color: computing ? C.mute2 : winterHot ? C.amber : C.ink2 }}>
          W.import {computing ? "..." : winterImport != null ? Math.round(winterImport) : "–"}/2×160.1
        </span>
        <span className="mono" style={{ fontSize: 11, color: computing ? C.mute2 : summerHot ? C.amber : C.ink2 }}>
          S.import {computing ? "..." : summerImport != null ? Math.round(summerImport) : "–"}/2×110.8
        </span>
        <span className="mono" style={{ fontSize: 11, color: computing ? C.mute2 : C.ink2 }}>
          V {vDisplay}
        </span>
        {worst && worst.winterPct !== null && worst.summerPct !== null ? (
          <>
            <span className="mono" style={{ fontSize: 11, color: computing ? C.mute2 : worst.winterPct > 100 ? C.red : worst.winterPct > 90 ? C.amber : C.ink2 }}>
              W.worst {computing ? "..." : `${Math.round(worst.winterPct)}%`}
            </span>
            <span className="mono" style={{ fontSize: 11, color: computing ? C.mute2 : worst.summerPct > 100 ? C.red : worst.summerPct > 90 ? C.amber : C.ink2 }}>
              S.worst {computing ? "..." : `${Math.round(worst.summerPct)}%`}
            </span>
          </>
        ) : (
          <span className="mono" style={{ fontSize: 11, color: computing ? C.mute2 : worstPct && worstPct > 100 ? C.red : worstPct && worstPct > 90 ? C.amber : C.ink2 }}>
            Worst {worstDisplay}
          </span>
        )}
        {computing && <span style={{ fontSize: 11, color: C.mute }}>updating…</span>}
        {showStale && (
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
      {!layout.showReadings && s.result && <CompactReadings planner={planner} gsp={gsp} limit={limit} gspHot={gspHot} worst={worst} vMin={vMin} vMax={vMax} worstPct={worstPct} />}
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
    : s.refreshing
      ? "Updating the years your edit touches…"
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
      {stale.stale && !s.refreshing && (
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
  const computing = s.refreshing || s.running;
  
  // Winter and summer imports with their distinct limits
  // Treat undefined as no data; 0 is valid (summer case exporting = 0 import)
  const winterImport = yr?.gsp_import_winter_mw !== undefined ? yr.gsp_import_winter_mw : null;
  const summerImport = yr?.gsp_import_summer_mw !== undefined ? Math.max(0, yr.gsp_import_summer_mw) : null;
  const winterLimit = s.boundary?.import_limit_mw.winter ?? null;
  const summerLimit = s.boundary?.import_limit_mw.summer ?? null;
  const winterHot = winterImport != null && winterLimit && winterImport > 0 ? winterImport / winterLimit > 0.9 : false;
  const summerHot = summerImport != null && summerLimit && summerImport > 0 ? summerImport / summerLimit > 0.9 : false;
  
  // Voltage range with season attribution - show each case's own voltage
  // Treat 0 as no data (0 voltage is impossible)
  const hasWinterVoltage = !!(yr?.min_vm_winter && yr?.max_vm_winter);
  const hasSummerVoltage = !!(yr?.min_vm_summer && yr?.max_vm_summer);
  // Determine the overall envelope extremes and which case each came from
  const overallMin = yr?.min_vm_pu ?? 0;
  const overallMax = yr?.max_vm_pu ?? 0;
  const minFromWinter = hasWinterVoltage && yr && yr.min_vm_winter! <= (yr.min_vm_summer ?? Infinity);
  const minFromSummer = hasSummerVoltage && yr && yr.min_vm_summer! < (yr.min_vm_winter ?? Infinity);
  const maxFromWinter = hasWinterVoltage && yr && yr.max_vm_winter! >= (yr.max_vm_summer ?? -Infinity);
  const maxFromSummer = hasSummerVoltage && yr && yr.max_vm_summer! > (yr.max_vm_winter ?? -Infinity);
  
  return (
    <div className="card glass" style={{ gap: 14 }}>
      <button className="gsp-btn" onClick={actions.toggleBoundary} title="Beyond the GSP: limits and transmission projects">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <span style={{ fontSize: 11.5, color: C.mute }}>
            GSP export{yr?.gsp_export_case ? ` · ${yr.gsp_export_case === "winter_peak" ? "winter" : "summer"}` : ""}
          </span>
          <span className="mono" style={{ fontSize: 13, fontWeight: 600, color: computing ? C.mute2 : gspHot ? C.amber : C.ink }}>
            {computing ? "..." : gsp != null ? fmtMw(gsp) : "–"} / {limit != null ? fmtMw(limit) : "–"} MW
          </span>
        </div>
        <Gauge ticks={computing ? [] : gspTicks(gsp ?? 0, limit)} />
        <span style={{ fontSize: 10.5, color: C.mute2 }}>
          {sgt && sgtMw ? `${sgt} × ${fmtMw(sgtMw)} MW SGTs` : ""}
          {!exact && yr ? (sgt && sgtMw ? " · " : "") + `showing ${yr.year} until ${s.year} is solved` : ""}
        </span>
      </button>
      
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <span style={{ fontSize: 11.5, color: C.mute }}>Winter import</span>
          <span className="mono" style={{ fontSize: 13, fontWeight: 600, color: computing ? C.mute2 : winterHot ? C.amber : C.ink }}>
            {computing ? "..." : winterImport != null ? fmtMw(winterImport) : "–"} / 2×160.1 MW
          </span>
        </div>
        <Gauge ticks={computing ? [] : gspTicks(winterImport ?? 0, winterLimit)} />
        
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginTop: 6 }}>
          <span style={{ fontSize: 11.5, color: C.mute }}>Summer import</span>
          <span className="mono" style={{ fontSize: 13, fontWeight: 600, color: computing ? C.mute2 : summerHot ? C.amber : C.ink }}>
            {computing ? "..." : summerImport != null ? `${fmtMw(summerImport)} / 2×110.8` : "–"} MW
          </span>
        </div>
        <Gauge ticks={computing ? [] : gspTicks(summerImport ?? 0, summerLimit)} />
      </div>
      
      <div className="readings">
        {worst && worst.winterPct !== null && worst.summerPct !== null ? (
          <>
            <div className="reading">
              <span className="k">Worst winter</span>
              <span className="v" style={{ color: computing ? C.mute2 : worst.winterPct > 100 ? C.red : worst.winterPct > 90 ? C.amber : C.ink }}>
                {computing ? "..." : `${Math.round(worst.winterPct)}%`}
              </span>
              <span className="n">{worst.winterName}</span>
            </div>
            <div className="reading">
              <span className="k">Worst summer</span>
              <span className="v" style={{ color: computing ? C.mute2 : worst.summerPct > 100 ? C.red : worst.summerPct > 90 ? C.amber : C.ink }}>
                {computing ? "..." : `${Math.round(worst.summerPct)}%`}
              </span>
              <span className="n">{worst.summerName}</span>
            </div>
          </>
        ) : (
          <button
            className="reading reading-btn"
            onClick={() => worst && actions.focusSel(worst.sel, 2.4)}
            disabled={!worst}
            title={worst ? `Show the ${worst.name} on the map` : undefined}
          >
            <span className="k">Worst element</span>
            <span className="v" style={{ color: computing ? C.mute2 : worst ? (worst.pct > 100 ? C.red : worst.pct > 90 ? C.amber : C.ink) : C.ink }}>
              {computing ? "..." : worst ? `${Math.round(worst.pct)}%` : "–"}
            </span>
            <span className="n">
              {computing ? "computing" : !worst ? "not solved yet" : worst.name}
            </span>
          </button>
        )}
        <div className="reading">
          <span className="k">Voltage band</span>
          {hasWinterVoltage && hasSummerVoltage && yr ? (
            <>
              <span className="v">{yr.min_vm_winter!.toFixed(3)} (W)</span>
              <span className="n">to {yr.max_vm_winter!.toFixed(3)} pu (W) · {yr.min_vm_summer!.toFixed(3)} (S) to {yr.max_vm_summer!.toFixed(3)} pu (S)</span>
            </>
          ) : (
            <>
              <span className="v">{computing ? "..." : yr ? yr.min_vm_pu.toFixed(3) : "–"}</span>
              <span className="n">
                {computing ? "computing" : <>to {yr ? yr.max_vm_pu.toFixed(3) : "–"} pu · {yr?.voltage_violation_bus_ids.length ? `${yr.voltage_violation_bus_ids.length} outside band` : "statutory bands"}</>}
              </span>
            </>
          )}
        </div>
        <div className="reading">
          <span className="k">Peak demand</span>
          <span className="v">×{computing ? "..." : yr ? yr.growth.toFixed(2) : "–"}</span>
          <span className="n">vs today, by {yr?.year ?? s.year}</span>
        </div>
        <div className="reading">
          <span className="k">N-1 findings</span>
          <span className="v" style={{ color: computing ? C.mute2 : yr?.n1_violations.length ? C.amber : C.ink }}>
            {computing ? "..." : yr ? `${yr.n1_violations.length} / ${yr.n1_screened}` : "–"}
          </span>
          <span className="n">132 kV outages screened, reported only</span>
        </div>
      </div>
      {yr?.alerts && <CustomerAlerts planner={planner} />}
      {s.solving && !s.running && <span style={{ fontSize: 10.5, color: C.mute2 }}>Solving the remaining years in the background.</span>}
    </div>
  );
}

/** Compact readings for short windows (< 760px tall): critical stats in a minimal card. */
function CompactReadings({ planner, gsp, limit, gspHot, worst, vMin, vMax, worstPct }: {
  planner: LeftCardsPlanner;
  gsp: number | null;
  limit: number | null;
  gspHot: boolean;
  worst: ReturnType<typeof worstElement>;
  vMin: string;
  vMax: string;
  worstPct: number | null;
}) {
  const { s, derived } = planner;
  const { yr } = derived;
  const computing = s.refreshing || s.running;
  
  const winterImport = yr?.gsp_import_winter_mw !== undefined ? yr.gsp_import_winter_mw : null;
  const summerImport = yr?.gsp_import_summer_mw !== undefined ? Math.max(0, yr.gsp_import_summer_mw) : null;
  const winterLimit = s.boundary?.import_limit_mw.winter ?? null;
  const summerLimit = s.boundary?.import_limit_mw.summer ?? null;
  const winterHot = winterImport != null && winterLimit && winterImport > 0 ? winterImport / winterLimit > 0.9 : false;
  const summerHot = summerImport != null && summerLimit && summerImport > 0 ? summerImport / summerLimit > 0.9 : false;
  
  // Voltage range with each case's own voltage (treat 0 as no data)
  const hasWinterVoltage = !!(yr?.min_vm_winter && yr?.max_vm_winter);
  const hasSummerVoltage = !!(yr?.min_vm_summer && yr?.max_vm_summer);
  // Show winter and summer voltages separately when both available
  const vDisplay = computing ? "..." : hasWinterVoltage && hasSummerVoltage && yr
    ? `${yr.min_vm_winter!.toFixed(3)}(W)–${yr.max_vm_winter!.toFixed(3)}(W) ${yr.min_vm_summer!.toFixed(3)}(S)–${yr.max_vm_summer!.toFixed(3)}(S)`
    : `${vMin}–${vMax}`;
  
  return (
    <div className="card glass" style={{ padding: "8px 12px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "6px 12px", fontSize: 11 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ color: C.mute }}>
            GSP export{yr?.gsp_export_case ? ` (${yr.gsp_export_case === "winter_peak" ? "W" : "S"})` : ""}
          </span>
          <span className="mono" style={{ fontWeight: 600, color: computing ? C.mute2 : gspHot ? C.amber : C.ink }}>
            {computing ? "..." : gsp != null && limit != null ? `${Math.round(gsp)} / ${Math.round(limit)}` : "–"}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ color: C.mute }}>Winter import</span>
          <span className="mono" style={{ fontWeight: 600, color: computing ? C.mute2 : winterHot ? C.amber : C.ink }}>
            {computing ? "..." : winterImport != null ? `${Math.round(winterImport)} / 2×160.1` : "–"}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ color: C.mute }}>Summer import</span>
          <span className="mono" style={{ fontWeight: 600, color: computing ? C.mute2 : summerHot ? C.amber : C.ink }}>
            {computing ? "..." : summerImport != null ? `${Math.round(summerImport)} / 2×110.8` : "–"}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ color: C.mute }}>Voltage</span>
          <span className="mono" style={{ fontWeight: 600, color: computing ? C.mute2 : C.ink, fontSize: 10 }}>
            {vDisplay}
          </span>
        </div>
        {worst && worst.winterPct !== null && worst.summerPct !== null ? (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ color: C.mute }}>Worst winter</span>
              <span className="mono" style={{ fontWeight: 600, color: computing ? C.mute2 : worst.winterPct > 100 ? C.red : worst.winterPct > 90 ? C.amber : C.ink }}>
                {computing ? "..." : `${Math.round(worst.winterPct)}%`}
              </span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ color: C.mute }}>Worst summer</span>
              <span className="mono" style={{ fontWeight: 600, color: computing ? C.mute2 : worst.summerPct > 100 ? C.red : worst.summerPct > 90 ? C.amber : C.ink }}>
                {computing ? "..." : `${Math.round(worst.summerPct)}%`}
              </span>
            </div>
          </>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ color: C.mute }}>Worst</span>
            <span className="mono" style={{ fontWeight: 600, color: computing ? C.mute2 : worstPct && worstPct > 100 ? C.red : worstPct && worstPct > 90 ? C.amber : C.ink }}>
              {computing ? "..." : !worst ? "–" :
                worst.case && worst.winterPct !== null && worst.case === "winter peak" ? `${Math.round(worst.winterPct)}%(W)` :
                worst.case && worst.summerPct !== null && worst.case === "summer min" ? `${Math.round(worst.summerPct)}%(S)` :
                worstPct != null ? `${worstPct}%` : "–"
              }
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

/** One line: the year's demand-side alerts by level; opens the Demand layer on the worst region. */
function CustomerAlerts({ planner }: { planner: LeftCardsPlanner }) {
  const { actions, derived } = planner;
  const { breach, warn, worst } = alertSummary(derived.yr);
  const open = () => {
    actions.setLayer("demand");
    if (worst) actions.focusSel({ kind: "region", id: worst }, 1.6);
  };
  return (
    <button className="cust-alerts" onClick={open} title={worst ? "Show the worst demand region on the map" : "Show the demand regions on the map"}>
      <span className="k">Customer alerts</span>
      {breach + warn === 0 ? (
        <span className="mono" style={{ color: C.greenInk }}>none</span>
      ) : (
        <span className="mono">
          {breach > 0 && <span style={{ color: C.red }}>{breach} breach</span>}
          {breach > 0 && warn > 0 && <span style={{ color: C.mute2 }}> · </span>}
          {warn > 0 && <span style={{ color: C.amber }}>{warn} warn</span>}
        </span>
      )}
    </button>
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
