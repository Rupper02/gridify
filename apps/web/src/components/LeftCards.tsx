// Top-left: one card. A stamp line (when the shown result was solved and on which profile, or where the run stands),
// the boxes that earn their space only when something is wrong (out of date, a run that failed or stopped, the grid
// not loaded), then five readings for the selected year, each a figure with one label and a click-through: the GSP
// export against its limit, the binding element with the MW of room left, the voltage range against the band, the
// N-1 outages that breach, the customer alerts. Below 1100px wide it collapses into one pill.

import { Info, X } from "@phosphor-icons/react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { GRID_LOAD_HINT, gridLoadText } from "../lib/boot";
import { alertSummary } from "../lib/demand";
import { GSP_NEAR_LIMIT, ZOOM_REGION, gspTicks, n1Counts, voltageCase, worstElement } from "../lib/derive";
import type { Layout } from "../lib/layout";
import { assumptionGroups, assumptionText } from "../lib/projects";
import { runButton } from "../lib/runStages";
import { C, caseLabel, fmtMw } from "../theme";
import type { ElementBinding } from "../types";
import { Gauge, Hint, ProfileGlyph } from "./ui";

export type LeftCardsPlanner = PlannerSlice<
  "assumptions" | "boundary" | "limits" | "model" | "modelError" | "modelLoading" | "plan" | "result" | "resultAt" | "showAssumptions" | "showBoundary" | "warehouseStale" | "year",
  "focusSel" | "retryLoad" | "run" | "setLayer" | "showLimits" | "toggleBoundary" | "toggleAssumptions",
  "exact" | "ix" | "profile" | "resultProfile" | "run" | "stale" | "yr" | "caps" | "synthetic"
>;

type RunButton = ReturnType<typeof runButton>;

/** What each reading means, for a reader who has never met the term. */
const HINTS = {
  gsp: "The Grid Supply Point is where this distribution network meets the transmission grid. Export is the power flowing up through it when local generation exceeds local demand; the limit is what its supergrid transformers and the transmission connection allow. The gap between the two is the room for new generation on the whole network.",
  binding: "The line or transformer closest to its thermal rating this year: the first thing that would overload if more power flowed, so it sets the ceiling for new connections near it. \"Room\" is how many more MW it can carry before it reaches its rating (a first-order estimate; the Limits tab has the detail).",
  voltage: "The lowest and highest busbar voltages, in per unit of nominal (1.000 = nominal). Each voltage level has a statutory band it must stay inside; outside it, customers' equipment is at risk and a connection that causes it is refused.",
  n1: "The security test: every line and transformer on the 132 kV backbone is taken out one at a time, and the network must still carry its load within limits. The figure counts the single outages, of all those studied, that would overload something or cut off demand. Reported for the engineer; it does not by itself refuse a connection.",
  alerts: "Demand groups (substations) checked against their firm capacity and security of supply (Engineering Recommendation P2/8): a warning when a group's demand comes close to what it can be supplied with one transformer out, a breach when it is over.",
};

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
      <div className="card glass" style={{ gap: 12 }}>
        <StampLine planner={planner} />
        <Problems planner={planner} runBtn={runBtn} showStale={showStale} />
        {layout.showReadings && s.result && <Readings planner={planner} gsp={gsp} limit={limit} gspHot={gspHot} compact={layout.compactReadings} />}
        <Assumptions planner={planner} />
      </div>
      {s.showBoundary && s.boundary && <BoundaryCard planner={planner} />}
    </div>
  );
}

/** One line: "Solved 21:24 · Standard" for a settled result, or where the run stands; the profile glyph beside it. */
function StampLine({ planner }: { planner: LeftCardsPlanner }) {
  const { s, derived } = planner;
  const { resultProfile, run: st } = derived;
  const loading = gridLoadText(!!s.model, s.modelLoading, s.modelError);
  const settled = !st.inProgress && !st.problem && s.result;
  const text = loading ?? (settled ? `Solved ${s.resultAt || ""}` : st.label);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }} title={settled ? st.label : undefined}>
      {resultProfile && <ProfileGlyph bars={resultProfile.bars} />}
      <span className="ellipsis" style={{ fontSize: 12.5, fontWeight: 600, minWidth: 0 }}>{text}</span>
      {resultProfile && <span className="mono" style={{ marginLeft: "auto", fontSize: 10.5, color: C.mute, flex: "none" }}>{resultProfile.label}</span>}
    </div>
  );
}

/** The boxes that earn their space only when something is wrong: out of date, a run that did not finish, the grid not
 * loaded; and the two tags a reader must know about the picture (a synthetic layout, a warehouse mid-write). */
function Problems({ planner, runBtn, showStale }: { planner: LeftCardsPlanner; runBtn: RunButton; showStale: boolean }) {
  const { s, actions, derived } = planner;
  const { stale, run: st, synthetic } = derived;
  return (
    <>
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
    </>
  );
}

/** The binding element in the Limits reading (`analysis.limits`) that is the viewed year's worst element, if read. */
function bindingOf(planner: LeftCardsPlanner, kind: "line" | "trafo", id: number): ElementBinding | null {
  return planner.s.limits?.binding.find((b) => b.kind === kind && b.element_id === id) ?? null;
}

function Readings({ planner, gsp, limit, gspHot, compact }: { planner: LeftCardsPlanner; gsp: number | null; limit: number | null; gspHot: boolean; compact: boolean }) {
  const { s, actions, derived } = planner;
  const { yr, ix, exact } = derived;
  const n1 = n1Counts(yr);
  const { note } = derived.run;
  const worst = worstElement(yr, ix);
  const binding = worst && (worst.sel.kind === "line" || worst.sel.kind === "trafo") ? bindingOf(planner, worst.sel.kind, Number(worst.sel.id)) : null;
  const room = binding?.headroom_mw ?? null; // the MW left at the element's worst year, first-order (the Limits tab says more)
  const since = binding?.first_breach_year ?? binding?.first_near_year ?? null;
  const vcase = voltageCase(yr);
  const outside = yr?.voltage_violation_bus_ids.length ?? 0;
  const sgt = s.boundary?.sgt_count;
  const sgtMw = s.boundary && sgt ? s.boundary.export_limit_mw / sgt : null;
  const gspTitle = `Export up through the GSP against its limit${yr?.gsp_case ? `, at ${caseLabel(yr.gsp_case)}` : ""}${sgt && sgtMw ? `; ${sgt} × ${fmtMw(sgtMw)} MW supergrid transformers` : ""}. Beyond the GSP: limits and transmission projects.`;
  return (
    <>
      {derived.caps.boundary && ( // a grid with no boundary has no export reading to show
      <button className="gsp-btn" onClick={actions.toggleBoundary} title={gspTitle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <span className="k" style={{ fontSize: 11.5, color: C.mute }}>GSP export <Hint tip={HINTS.gsp} /></span>
          <span className="mono" style={{ fontSize: 13, fontWeight: 600, color: gspHot ? C.amber : C.ink, whiteSpace: "nowrap" }}>
            {gsp != null ? fmtMw(gsp) : "–"} / {limit != null ? fmtMw(limit) : "–"} MW
          </span>
        </div>
        <Gauge ticks={gspTicks(gsp ?? 0, limit)} />
        {(yr?.gsp_case || (!exact && yr)) && (
          <span style={{ fontSize: 10.5, color: C.mute2 }}>
            {yr?.gsp_case ? `at ${caseLabel(yr.gsp_case)}` : ""}{!exact && yr ? `${yr.gsp_case ? " · " : ""}showing ${yr.year} until ${s.year} is solved` : ""}
          </span>
        )}
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
          onClick={() => actions.showLimits()}
          disabled={!worst}
          title={worst ? `${worst.name}: ${Math.round(worst.pct)}% of its rating${worst.at ? ` at ${caseLabel(worst.at)}` : ""} in ${yr?.year}${room != null ? `; ${room} MW of room at its worst year, first-order` : ""}. Open the Limits tab.` : undefined}
        >
          <span className="k">Binding element <Hint tip={HINTS.binding} /></span>
          <span className="v" style={{ color: worst ? (worst.pct > 100 ? C.red : worst.pct > 90 ? C.amber : C.ink) : C.ink }}>
            {!worst ? "–" : room != null ? `${room} MW room` : `${Math.round(worst.pct)}%`}
          </span>
          <span className="n">{worst ? `${worst.name}${room != null ? ` · ${Math.round(worst.pct)}%` : ""}${since ? ` · ${binding?.first_breach_year ? "breaches" : "near"} from ${since}` : ""}` : "not solved yet"}</span>
        </button>
        <div className="reading" title={`The lowest and highest busbar voltages in ${yr?.year ?? s.year} against the statutory band at each level${vcase ? `; the lowest at ${caseLabel(vcase)}` : ""}.`}>
          <span className="k">Voltage <Hint tip={HINTS.voltage} /></span>
          <span className="v" style={{ color: outside ? C.amber : C.ink }}>{yr ? `${yr.min_vm_pu.toFixed(3)}–${yr.max_vm_pu.toFixed(3)}` : "–"}</span>
          <span className="n">{yr ? (outside ? `${outside} bus${outside === 1 ? "" : "es"} out of band` : "pu · within band") : ""}</span>
        </div>
        {/* "12 of 27 outages": opens the Limits tab's findings on the N-1 group */}
        <button
          className="reading reading-btn"
          onClick={() => actions.showLimits("n1")}
          disabled={!yr?.n1_screened}
          title={yr?.n1_screened ? `Single outages whose post-fault state breaches a limit or strands demand${n1.breaches ? ` (${n1.breaches} findings)` : ""}${yr.n1_cases?.length ? `, screened at ${yr.n1_cases.map(caseLabel).join(" and ")}` : ""}; reported, never a connection gate. Open the N-1 causes.` : "No line or transformer is in the N-1 scope: not studied"}
        >
          <span className="k">N-1 <Hint tip={HINTS.n1} /></span>
          <span className="v" style={{ color: yr?.n1_violations.length ? C.amber : C.ink }}>
            {yr ? (yr.n1_screened ? `${n1.outages} of ${yr.n1_screened}` : "none") : "–"}
          </span>
          <span className="n">{yr && !yr.n1_screened ? "not in scope" : "outages breach a limit"}</span>
        </button>
        {yr?.alerts && <CustomerAlerts planner={planner} />}
      </div>
      )}
      {note && <span style={{ fontSize: 10.5, color: C.mute2 }}>{note}</span>}
    </>
  );
}

/** The year's demand-side alerts by level, as a reading; opens the Demand layer on the worst region. */
function CustomerAlerts({ planner }: { planner: LeftCardsPlanner }) {
  const { actions, derived } = planner;
  const { breach, warn, worst } = alertSummary(derived.yr);
  const open = () => {
    actions.setLayer("demand");
    if (worst) actions.focusSel({ kind: "region", id: worst }, ZOOM_REGION);
  };
  const total = breach + warn;
  return (
    <button className="reading reading-btn" onClick={open} title={worst ? "Demand groups whose firm capacity or N-1 cover the plan tests (P2/8). Show the worst on the map." : "Show the demand regions on the map"}>
      <span className="k">Customer alerts <Hint tip={HINTS.alerts} /></span>
      <span className="v" style={{ color: breach ? C.red : warn ? C.amber : C.greenInk }}>{total ? String(total) : "none"}</span>
      <span className="n">{total ? [breach ? `${breach} breach${breach === 1 ? "" : "es"}` : "", warn ? `${warn} warning${warn === 1 ? "" : "s"}` : ""].filter(Boolean).join(" · ") : "firm capacity holds"}</span>
    </button>
  );
}

/** What the model assumes, as a small link that opens the list (every project has assumptions, NGED's included). */
function Assumptions({ planner }: { planner: LeftCardsPlanner }) {
  const { s, actions } = planner;
  return (
    <>
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
    </>
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
