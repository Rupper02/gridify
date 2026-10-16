// The left column: the result stamp (solved, solving, failed with a Retry) and the viewed year's readings: the worst
// line and transformer, the voltage range, the GSP's export against its limit, what breaches, demand growth. Then what
// the model assumes, on request.

import { ArrowClockwise, CheckCircle, Info, Warning } from "@phosphor-icons/react";

import type { Planner } from "../hooks/usePlanner";
import { caseOf, lineName, trafoName } from "../lib/model";
import { C, caseLabel, loadColor, profileLabel } from "../theme";
import { Gauge, Hint } from "./ui";

const GSP_TICKS = 24;

function gspTicks(exportMw: number, limit: number | null): string[] {
  if (!limit) return Array(GSP_TICKS).fill("rgba(255,255,255,0.1)");
  const lit = Math.round((Math.min(exportMw, limit * 1.2) / limit) * GSP_TICKS);
  return Array.from({ length: GSP_TICKS }, (_, i) => (i < lit ? (exportMw > limit ? C.red : exportMw > 0.9 * limit ? C.amber : C.accent) : "rgba(255,255,255,0.1)"));
}

export function LeftCards({ planner, compact }: { planner: Planner; compact: boolean }) {
  const { s, actions, derived } = planner;
  const { yr, ix, exact } = derived;
  const run = s.run;
  const worstLine = yr && Object.entries(yr.line_loading).reduce<[string, number] | null>((a, e) => (!a || e[1] > a[1] ? e : a), null);
  const worstTrafo = yr && Object.entries(yr.trafo_loading).reduce<[string, number] | null>((a, e) => (!a || e[1] > a[1] ? e : a), null);
  const breaches = yr?.violations.length ?? 0;
  return (
    <div className="left-col">
      <div className="card glass">
        <div className="stamp">
          {run.kind === "running" ? (
            <span className="grow" style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <b style={{ fontSize: 12.5 }}>Solving · {Math.round(run.fraction * 100)}%</b>
              <span className="mute ellipsis" style={{ fontSize: 11 }}>{run.stage}</span>
            </span>
          ) : run.kind === "failed" ? (
            <>
              <Warning size={16} color={C.amber} />
              <span className="grow" style={{ fontSize: 11.5, color: C.amberInk }}>The run failed: {run.error}</span>
              <button className="icon-btn" onClick={() => void actions.run()} title="Retry">
                <ArrowClockwise size={14} />
              </button>
            </>
          ) : s.bootError ? (
            <>
              <Warning size={16} color={C.amber} />
              <span className="grow" style={{ fontSize: 11.5, color: C.amberInk }}>{s.bootError}</span>
              <button className="icon-btn" onClick={() => void actions.boot()} title="Retry">
                <ArrowClockwise size={14} />
              </button>
            </>
          ) : s.result ? (
            <>
              <CheckCircle size={16} color={C.phase1} />
              <span className="grow" style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                <b style={{ fontSize: 12.5 }}>Solved {s.resultAt === "cached" ? "(cached)" : s.resultAt}</b>
                <span className="mute" style={{ fontSize: 11 }}>{profileLabel(s.result.params.scenario)} demand · AC power flow, two cases</span>
              </span>
            </>
          ) : (
            <span className="mute" style={{ fontSize: 12 }}>{s.model ? "Waiting for the first run…" : "Loading the grid…"}</span>
          )}
        </div>

        {yr && (
          <>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <b className="mono" style={{ fontSize: 15 }}>{s.year}</b>
              <span className="mute" style={{ fontSize: 11 }}>
                demand ×{yr.growth.toFixed(2)} of today{!exact && " · this year is still solving"}
              </span>
            </div>
            <div className={`readings${compact ? " compact" : ""}`}>
              <button className="reading-btn" onClick={() => worstLine && actions.select({ kind: "line", id: +worstLine[0] })}>
                <span className="reading">
                  <span className="k">Worst line <Hint tip="The most loaded circuit against its thermal rating, in the worse of the two study cases (winter peak at winter ratings, summer minimum at summer ratings)." /></span>
                  <span className="v" style={{ color: loadColor(yr.worst_line_loading_pct) }}>{Math.round(yr.worst_line_loading_pct)}%</span>
                  <span className="n ellipsis">{worstLine && ix ? `${lineName(ix, +worstLine[0])} · ${caseLabel(caseOf(yr, "lines", +worstLine[0]))}` : "–"}</span>
                </span>
              </button>
              <button className="reading-btn" onClick={() => worstTrafo && actions.select({ kind: "trafo", id: +worstTrafo[0] })}>
                <span className="reading">
                  <span className="k">Worst transformer</span>
                  <span className="v" style={{ color: loadColor(yr.worst_trafo_loading_pct) }}>{Math.round(yr.worst_trafo_loading_pct)}%</span>
                  <span className="n ellipsis">{worstTrafo && ix ? `${trafoName(ix, +worstTrafo[0])} · ${caseLabel(caseOf(yr, "trafos", +worstTrafo[0]))}` : "–"}</span>
                </span>
              </button>
              <span className="reading">
                <span className="k">Voltage range <Hint tip="The lowest and highest busbar voltage after the tap changers settle. The statutory band is ±10% at 132 kV and ±6% below it." /></span>
                <span className="v">{yr.min_vm_pu.toFixed(3)}–{yr.max_vm_pu.toFixed(3)}</span>
                <span className="n">pu · {yr.voltage_violation_bus_ids.length} bus{yr.voltage_violation_bus_ids.length === 1 ? "" : "es"} out of band</span>
              </span>
              <button className="reading-btn" onClick={() => actions.setTab("limits")}>
                <span className="reading">
                  <span className="k">Breaches</span>
                  <span className="v" style={{ color: breaches ? C.red : C.phase1 }}>{yr.converged ? breaches : "no solution"}</span>
                  <span className="n">{breaches ? "see Limits" : "every limit holds"}</span>
                </span>
              </button>
            </div>
            <div className="gsp-btn">
              <span style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
                <span className="mute">GSP export to transmission</span>
                <span className="mono">
                  {Math.round(yr.gsp_export_mw)}
                  {yr.gsp_limit_mw ? ` / ${Math.round(yr.gsp_limit_mw)}` : ""} MW
                </span>
              </span>
              <Gauge ticks={gspTicks(yr.gsp_export_mw, yr.gsp_limit_mw)} />
              <span className="mute-2" style={{ fontSize: 10.5 }}>
                at {caseLabel(yr.gsp_case)} · import at peak {Math.round(yr.gsp_import_mw)} MW
              </span>
            </div>
          </>
        )}

        <button className="btn ghost" style={{ justifyContent: "flex-start", padding: 0 }} onClick={() => void actions.toggleAssumptions()}>
          <Info size={13} /> What the model assumes
        </button>
        {s.showAssumptions && (
          <div className="box dark" style={{ fontSize: 11.5, lineHeight: 1.45, maxHeight: 260, overflowY: "auto" }}>
            {(s.assumptions ?? []).map((a) => (
              <span key={a.key}>
                {a.message}
                {a.count ? <span className="mute"> ({a.count} {a.element_kind ?? "elements"})</span> : null}
              </span>
            ))}
            {!s.assumptions && <span className="mute">Loading…</span>}
          </div>
        )}
      </div>
    </div>
  );
}
