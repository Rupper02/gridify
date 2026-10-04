// Top-left: the result stamp (which profile the shown result was solved on, how many years are in,
// and whether it is out of date) and the readings for the selected year. Below 1100px wide they
// collapse into one pill.

import { Info, X } from "@phosphor-icons/react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { GRID_LOAD_HINT, gridLoadText } from "../lib/boot";
import { alertSummary } from "../lib/demand";
import { gspTicks, worstElement } from "../lib/derive";
import type { Layout } from "../lib/layout";
import { assumptionGroups, assumptionText } from "../lib/projects";
import { C, caseLabel, fmtMw } from "../theme";
import { Gauge, ProfileGlyph } from "./ui";

export type LeftCardsPlanner = PlannerSlice<
  "assumptions" | "boundary" | "model" | "modelError" | "modelLoading" | "outages" | "refreshing" | "result" | "resultAt" | "running" | "showAssumptions" | "showBoundary" | "solving" | "year",
  "focusSel" | "retryLoad" | "run" | "setLayer" | "toggleBoundary" | "toggleAssumptions",
  "exact" | "ix" | "profile" | "resultProfile" | "stale" | "yearsSolved" | "yearsTotal" | "yr" | "caps" | "synthetic"
>;

export function LeftCards({ planner, layout }: { planner: LeftCardsPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const { yr, stale, resultProfile, profile } = derived;
  const limit = yr?.gsp_limit_mw ?? s.boundary?.export_limit_mw ?? null;
  const gsp = yr?.gsp_export_mw ?? null;
  const gspHot = gsp != null && limit ? gsp / limit > 0.9 : false;
  const runLabel = `${stale.stale ? "Re-run" : "Run"} on ${profile.label}`;
  const showStale = stale.stale && !s.refreshing; // an automatic refresh is already on its way

  if (layout.narrow) {
    return (
      <div className="narrow-pill glass" style={{ borderColor: showStale ? "rgba(255,195,107,0.45)" : undefined }}>
        <ProfileGlyph bars={resultProfile.bars} />
        <span style={{ fontSize: 12, fontWeight: 600 }}>{resultProfile.label} result</span>
        <span className="mono" style={{ fontSize: 11, color: gspHot ? C.amber : C.ink2 }}>
          GSP {gsp != null ? Math.round(gsp) : "–"}/{limit != null ? Math.round(limit) : "–"}
        </span>
        {s.refreshing && <span style={{ fontSize: 11, color: C.mute }}>updating…</span>}
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
      {s.showBoundary && s.boundary && <BoundaryCard planner={planner} />}
    </div>
  );
}

function ResultStamp({ planner, runLabel }: { planner: LeftCardsPlanner; runLabel: string }) {
  const { s, actions, derived } = planner;
  const { stale, resultProfile, yearsSolved, yearsTotal, caps, synthetic } = derived;
  const n = s.outages.length;
  const sub =
    gridLoadText(!!s.model, s.modelLoading, s.modelError) ??
    (!s.result
      ? "No run yet"
      : s.refreshing
        ? "Updating the years your edit touches…"
        : yearsSolved < yearsTotal
          ? `Solving years · ${yearsSolved} of ${yearsTotal} in`
          : `All years solved${n ? ` · ${n} planned outage${n > 1 ? "s" : ""}` : ""}${caps.summer_case ? "" : " · winter peak only"}`);
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
      {s.modelError && (
        <div className="box amber">
          <span style={{ fontSize: 12, color: C.amberInk, lineHeight: 1.4, textWrap: "pretty" }}>{GRID_LOAD_HINT}</span>
          <button className="btn warn" style={{ alignSelf: "flex-start" }} onClick={() => void actions.retryLoad()} disabled={s.modelLoading}>
            Retry
          </button>
        </div>
      )}
      {synthetic && <span className="synthetic-tag">Synthetic layout: the file has no coordinates, so the buses are laid out, not placed.</span>}
      <button className="assume-btn" onClick={() => void actions.toggleAssumptions()} aria-expanded={s.showAssumptions}>
        <Info size={12} />
        {s.showAssumptions ? "Hide what the model assumes" : "What the model assumes"}
      </button>
      {s.showAssumptions && (
        <div className="assume-list">
          {!s.assumptions && <span className="mute" style={{ fontSize: 11.5 }}>Loading…</span>}
          {s.assumptions && !s.assumptions.length && <span className="mute" style={{ fontSize: 11.5 }}>Nothing recorded.</span>}
          {s.assumptions && assumptionGroups(s.assumptions).map((g) => (
            <div key={g.source} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: C.mute, letterSpacing: "0.02em" }}>{g.label}</span>
              {g.rows.map((a) => (
                <span key={a.key} style={{ fontSize: 11, color: C.ink2, lineHeight: 1.4, textWrap: "pretty" }}>· {assumptionText(a)}</span>
              ))}
            </div>
          ))}
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
          <span className="n">132 kV outages screened{yr?.n1_cases?.length ? ` at ${yr.n1_cases.map(caseLabel).join(" and ")}` : ""}, reported only</span>
        </div>
      </div>
      {yr?.alerts && <CustomerAlerts planner={planner} />}
      {s.solving && !s.running && <span style={{ fontSize: 10.5, color: C.mute2 }}>Solving the remaining years in the background.</span>}
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
