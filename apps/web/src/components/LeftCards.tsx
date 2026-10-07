// Top-left: the result stamp (which profile the shown result was solved on, how many years are in, whether it is out
// of date, and a run that failed or stopped, with a Retry) and the readings for the selected year. Below 1100px wide
// they collapse into one pill.

import { Info, X } from "@phosphor-icons/react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { GRID_LOAD_HINT, gridLoadText } from "../lib/boot";
import { alertSummary } from "../lib/demand";
import { GSP_NEAR_LIMIT, ZOOM_ELEMENT, ZOOM_REGION, gspTicks, n1Counts, voltageCase, worstElement } from "../lib/derive";
import type { Layout } from "../lib/layout";
import { assumptionGroups, assumptionText } from "../lib/projects";
import { runButton } from "../lib/runStages";
import { C, caseLabel, fmtMw } from "../theme";
import { Gauge, ProfileGlyph } from "./ui";

export type LeftCardsPlanner = PlannerSlice<
  "assumptions" | "boundary" | "model" | "modelError" | "modelLoading" | "outages" | "plan" | "result" | "resultAt" | "showAssumptions" | "showBoundary" | "warehouseStale" | "year",
  "focusSel" | "retryLoad" | "run" | "setLayer" | "showLimits" | "toggleBoundary" | "toggleAssumptions",
  "exact" | "ix" | "profile" | "resultProfile" | "run" | "stale" | "yr" | "caps" | "synthetic"
>;

type RunButton = ReturnType<typeof runButton>;

export function LeftCards({ planner, layout }: { planner: LeftCardsPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const { yr, stale, resultProfile, profile, run } = derived;
  const limit = yr?.gsp_limit_mw ?? s.boundary?.export_limit_mw ?? null;
  const gsp = yr?.converged === false ? null : (yr?.gsp_export_mw ?? null); // a year that did not solve has no figures
  const gspHot = gsp != null && limit ? gsp / limit > GSP_NEAR_LIMIT : false;
  const runBtn = runButton(run, stale.stale, profile?.label ?? "", !!s.model); // plain until the profile is known
  // out of date, unless a run that will include the change is on its way (or the last one did not finish: Retry covers both)
  const showStale = stale.stale && !run.inProgress && !run.problem;

  if (layout.narrow) {
    return (
      <div className="narrow-pill glass" style={{ borderColor: showStale || run.problem ? "rgba(255,195,107,0.45)" : undefined }}>
        {resultProfile && <ProfileGlyph bars={resultProfile.bars} />}
        <span style={{ fontSize: 12, fontWeight: 600 }}>{resultProfile ? `${resultProfile.label} result` : (gridLoadText(!!s.model, s.modelLoading, s.modelError) ?? "No run yet")}</span>
        <span className="mono" style={{ fontSize: 11, color: gspHot ? C.amber : C.ink2 }}>
          GSP {gsp != null ? Math.round(gsp) : "–"}/{limit != null ? Math.round(limit) : "–"}
        </span>
        {run.quiet && <span style={{ fontSize: 11, color: C.mute }}>updating…</span>}
        {showStale && (
          <button className="btn warn" style={{ height: 24, fontSize: 11 }} onClick={() => void actions.run({ restart: stale.stale })} disabled={runBtn.disabled} title={runBtn.title}>
            Out of date · re-run
          </button>
        )}
        {run.problem && (
          <button className="btn warn" style={{ height: 24, fontSize: 11 }} onClick={() => void actions.run({ restart: stale.stale })} disabled={runBtn.disabled} title={run.problem}>
            {run.roadmap} · retry
          </button>
        )}
      </div>
    );
  }

  const reserve = layout.showDock ? layout.dockPx + 88 : 88;
  return (
    <div className="left-col" style={{ maxHeight: `calc(100% - ${reserve}px)` }}>
      <ResultStamp planner={planner} runBtn={runBtn} showStale={showStale} />
      {layout.showReadings && s.result && <Readings planner={planner} gsp={gsp} limit={limit} gspHot={gspHot} compact={layout.compactReadings} />}
      {s.showBoundary && s.boundary && <BoundaryCard planner={planner} />}
    </div>
  );
}

function ResultStamp({ planner, runBtn, showStale }: { planner: LeftCardsPlanner; runBtn: RunButton; showStale: boolean }) {
  const { s, actions, derived } = planner;
  const { stale, resultProfile, run: st, caps, synthetic } = derived;
  const n = s.outages.length;
  const settled = !st.inProgress && !st.problem; // the stamp adds what it knows only to a finished run's line
  const sub =
    gridLoadText(!!s.model, s.modelLoading, s.modelError) ??
    (settled ? `${st.label}${n ? ` · ${n} planned outage${n > 1 ? "s" : ""}` : ""}${caps.summer_case ? "" : " · winter peak only"}` : st.label);
  return (
    <div className="card glass">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>Simulation result</span>
        <span className="mono" style={{ fontSize: 10.5, color: C.mute }}>{!s.plan ? "" : s.resultAt ? `run ${s.resultAt} · ${s.year}` : String(s.year)}</span>
      </div>
      <div className="stamp">
        {resultProfile && <ProfileGlyph bars={resultProfile.bars} big />}
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.25 }}>
          {/* no profile is known before the branch is in: only the loading text, no "Custom" */}
          {resultProfile ? (
            <>
              <span style={{ fontSize: 15, fontWeight: 600 }}>{resultProfile.label} demand</span>
              <span style={{ fontSize: 11, color: C.mute }}>{sub}</span>
            </>
          ) : (
            <span style={{ fontSize: 12.5, fontWeight: 600, color: C.ink2 }}>{sub}</span>
          )}
        </div>
      </div>
      {showStale && (
        <div className="box amber">
          <span style={{ fontSize: 12, color: C.amberInk, lineHeight: 1.4, textWrap: "pretty" }}>{stale.text}</span>
          <button className="btn warn" style={{ alignSelf: "flex-start" }} onClick={() => void actions.run({ restart: stale.stale })} disabled={runBtn.disabled} title={runBtn.title}>
            {runBtn.label}
          </button>
        </div>
      )}
      {st.problem && (
        <div className="box amber" role="alert">
          <span style={{ fontSize: 12, color: C.amberInk, lineHeight: 1.4, textWrap: "pretty" }}>{st.problem}</span>
          <button className="btn warn" style={{ alignSelf: "flex-start" }} onClick={() => void actions.run({ restart: stale.stale })} disabled={runBtn.disabled} title={runBtn.title}>
            Retry
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
      {s.warehouseStale && <span className="synthetic-tag">Read while the pipeline was writing a new warehouse version: what you see is the previous version. Reload the page to read the new one.</span>}
      <button className="assume-btn" onClick={() => void actions.toggleAssumptions()} aria-expanded={s.showAssumptions}>
        <Info size={12} />
        {s.showAssumptions ? "Hide what the model assumes" : "What the model assumes"}
      </button>
      {s.showAssumptions && (
        <div className="assume-list">
          {!s.assumptions && <span className="mute" style={{ fontSize: 11.5 }}>Loading…</span>}
          {s.assumptions && !s.assumptions.length && <span className="mute" style={{ fontSize: 11.5 }}>Nothing recorded.</span>}
          {/* one section per source; the file's gaps (what the import could not provide) open first */}
          {s.assumptions && assumptionGroups(s.assumptions).map((g) => (
            <details key={g.source} className="assume-group" open={g.source === "file"}>
              <summary>
                {g.label}
                <span className="mono fcount">{g.rows.length}</span>
              </summary>
              {g.rows.map((a) => (
                <span key={a.key} style={{ fontSize: 11, color: C.ink2, lineHeight: 1.4, textWrap: "pretty" }}>· {assumptionText(a)}</span>
              ))}
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

function Readings({ planner, gsp, limit, gspHot, compact }: { planner: LeftCardsPlanner; gsp: number | null; limit: number | null; gspHot: boolean; compact: boolean }) {
  const { s, actions, derived } = planner;
  const { yr, ix, exact } = derived;
  const n1 = n1Counts(yr);
  const { note } = derived.run;
  const worst = worstElement(yr, ix);
  const vcase = voltageCase(yr); // the study case the lowest voltage comes from
  const sgt = s.boundary?.sgt_count;
  const sgtMw = s.boundary && sgt ? s.boundary.export_limit_mw / sgt : null;
  return (
    <div className="card glass" style={{ gap: 14 }}>
      {derived.caps.boundary && ( // a grid with no boundary has no export reading to show
      <button className="gsp-btn" onClick={actions.toggleBoundary} title="Beyond the GSP: limits and transmission projects">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <span style={{ fontSize: 11.5, color: C.mute }}>GSP export</span>
          <span className="mono" style={{ fontSize: 13, fontWeight: 600, color: gspHot ? C.amber : C.ink }}>
            {gsp != null ? fmtMw(gsp) : "–"} / {limit != null ? fmtMw(limit) : "–"} MW
          </span>
        </div>
        <Gauge ticks={gspTicks(gsp ?? 0, limit)} />
        <span style={{ fontSize: 10.5, color: C.mute2 }}>
          {yr?.gsp_case ? `At ${caseLabel(yr.gsp_case)}` : "Worst case"}{sgt && sgtMw ? ` · ${sgt} × ${fmtMw(sgtMw)} MW SGTs` : ""}
          {!exact && yr ? ` · showing ${yr.year} until ${s.year} is solved` : ""}
        </span>
      </button>
      )}
      {yr?.converged === false ? (
        <div className="notice red" role="status">
          <b>The power flow does not converge in {yr.year}.</b> The engine has no figures for this year: no loadings, voltages
          or N-1 results to read. Check the model (the Limits tab's findings list each year that fails) before trusting a plan on it.
        </div>
      ) : (
      <div className={`readings${compact ? " compact" : ""}`}>
        <button
          className="reading reading-btn"
          onClick={() => worst && actions.focusSel(worst.sel, ZOOM_ELEMENT)}
          disabled={!worst}
          title={worst ? `Show the ${worst.name} on the map` : undefined}
        >
          <span className="k">Worst element</span>
          <span className="v" style={{ color: worst ? (worst.pct > 100 ? C.red : worst.pct > 90 ? C.amber : C.ink) : C.ink }}>
            {worst ? `${Math.round(worst.pct)}%` : "–"}
          </span>
          <span className="n">{worst ? `${worst.name}${worst.at ? ` · at ${caseLabel(worst.at)}` : ""}` : "not solved yet"}</span>
        </button>
        <div className="reading">
          <span className="k">Voltage band</span>
          <span className="v">{yr ? yr.min_vm_pu.toFixed(3) : "–"}</span>
          <span className="n">
            to {yr ? yr.max_vm_pu.toFixed(3) : "–"} pu · {yr?.voltage_violation_bus_ids.length ? `${yr.voltage_violation_bus_ids.length} outside band` : "limits by level"}
            {vcase ? ` · lowest at ${caseLabel(vcase)}` : ""}
          </span>
        </div>
        <div className="reading">
          <span className="k">Peak demand</span>
          <span className="v">×{yr ? yr.growth.toFixed(2) : "–"}</span>
          <span className="n">vs today, by {yr?.year ?? s.year}</span>
        </div>
        {/* "12 of 27 outages": opens the Limits tab's findings on the N-1 group, as the worst element flies to its element */}
        <button
          className="reading reading-btn"
          onClick={() => actions.showLimits("n1")}
          disabled={!yr?.n1_screened}
          title={yr?.n1_screened ? "Open the N-1 findings" : undefined}
        >
          <span className="k">N-1 screen</span>
          <span className="v" style={{ color: yr?.n1_violations.length ? C.amber : C.ink }}>
            {yr ? (yr.n1_screened ? `${n1.outages} of ${yr.n1_screened}` : "none") : "–"}
          </span>
          <span className="n">
            {yr && !yr.n1_screened
              ? "no line or transformer is in the N-1 scope: not studied"
              : `outages breach a limit${n1.breaches ? ` (${n1.breaches} ${n1.breaches === 1 ? "finding" : "findings"})` : ""}, screened${yr?.n1_cases?.length ? ` at ${yr.n1_cases.map(caseLabel).join(" and ")}` : ""}, reported only`}
          </span>
        </button>
      </div>
      )}
      {yr?.alerts && <CustomerAlerts planner={planner} />}
      {note && <span style={{ fontSize: 10.5, color: C.mute2 }}>{note}</span>}
    </div>
  );
}

/** One line: the year's demand-side alerts by level; opens the Demand layer on the worst region. */
function CustomerAlerts({ planner }: { planner: LeftCardsPlanner }) {
  const { actions, derived } = planner;
  const { breach, warn, worst } = alertSummary(derived.yr);
  const open = () => {
    actions.setLayer("demand");
    if (worst) actions.focusSel({ kind: "region", id: worst }, ZOOM_REGION);
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
