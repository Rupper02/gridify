// The year view (measured and grown years, GET /runs): the run selector, the run's limits, the worst elements, the busbars
// out of band and the substations above firm capacity (the side panel's "Year runs" tab); and, for the selected line,
// transformer or busbar, its figures and a month-by-hour grid of when it is over (a section of the detail card).
// On a branch, the tab also runs the branch's year (a job of about 16 minutes) and shows what it changes against its
// "before", the catalogued grown year of the same year and pathway, first.

import { useEffect, useState } from "react";

import { api, failureText } from "../api";
import type { Planner } from "../hooks/usePlanner";
import { HOURS_STEPS } from "../lib/geo";
import { busName, lineName, trafoName } from "../lib/model";
import { C, loadColor } from "../theme";
import type { RunComparison, RunElement, RunGrid } from "../types";

const hrs = (h: number): string => `${h >= 100 ? Math.round(h).toLocaleString() : Math.round(h * 10) / 10} h`;
const when = (t: string): string => new Date(t.replace(" ", "T")).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

/** An element's label in the year view: whether its flow agrees with the source's model, and how far it is from it. */
function Label({ e }: { e: RunElement }) {
  const color = !e.finding ? C.mute2 : e.label.startsWith("flow agrees") ? C.greenInk : e.label.startsWith("flow differs") ? C.amber : C.mute;
  const off = e.offset_mw != null ? ` (${e.offset_mw > 0 ? "+" : ""}${e.offset_mw} MW, ${Math.abs(e.offset_pct ?? 0)}% of rating)` : "";
  const judged = e.label_year != null ? `Agreement judged on the ${e.label_year} measured year` : undefined;
  return <span style={{ color, fontSize: 11 }} title={judged}>{e.label}{off}</span>;
}

/** On a branch: run its year on a catalogued grown year, with the job's progress. */
function BranchYear({ planner }: { planner: Planner }) {
  const { s, actions } = planner;
  const { branch } = planner.derived;
  const bases = (s.runs ?? []).filter((x) => x.base && x.available);
  const [base, setBase] = useState("");
  const pick = bases.find((x) => x.run_id === base) ?? bases[0];
  const yr = s.yearRun;
  const mine = yr.kind !== "idle" && yr.branchId === s.activeBranch;
  if (!branch || !pick) return null;
  return (
    <div className="qgroup">
      <div className="qhead"><b style={{ fontSize: 12 }}>This branch through a whole year</b></div>
      <span className="mute" style={{ fontSize: 11, lineHeight: 1.45 }}>
        The connections on "{branch.name}" that are in service by the year, added to a grown year half-hour by
        half-hour, and compared with that year without them. About 20 minutes on the API's one worker; a branch already
        run for what it holds opens at once. Solving any branch's plan years stops it, so an edit never waits behind it.
      </span>
      <div style={{ display: "flex", gap: 6 }}>
        <select className="search" value={pick.run_id} onChange={(e) => setBase(e.target.value)} aria-label="Year to run the branch on" disabled={yr.kind === "running"}>
          {bases.map((x) => <option key={x.run_id} value={x.run_id}>{x.label.replace(" (grown)", "")}</option>)}
        </select>
        {yr.kind === "running" ? (
          <button className="btn ghost" onClick={() => actions.cancelYearRun()}>Stop</button>
        ) : (
          <button className="btn" onClick={() => void actions.runYear(pick.run_id)}>Run the year</button>
        )}
      </div>
      {yr.kind === "running" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span className="mono" style={{ fontSize: 11 }}>{mine ? "" : "another branch: "}{yr.stage}</span>
          <div style={{ height: 4, borderRadius: 2, background: "rgba(255,255,255,0.08)" }}>
            <div style={{ height: 4, borderRadius: 2, width: `${Math.round(yr.fraction * 100)}%`, background: C.amber }} />
          </div>
        </div>
      )}
      {yr.kind === "failed" && mine && <span style={{ color: C.redInk, fontSize: 11.5 }}>{yr.error}</span>}
      {yr.kind === "stopped" && mine && <span className="notice" style={{ fontSize: 11.5 }}>The year run was {yr.reason}.</span>}
    </div>
  );
}

/** A branch's year against its "before": the elements it changes, longest increase first, each with the branch's own
 * study-case figure beside it, and the MVAh above rating on the worst. */
function Comparison({ planner, c }: { planner: Planner; c: RunComparison }) {
  const { s, actions } = planner;
  const { ix } = planner.derived;
  const before = s.runs?.find((x) => x.run_id === c.before);
  const plan = s.result?.years[String(c.year)] ?? null;
  const name = (kind: "line" | "trafo", id: number) => (ix ? (kind === "line" ? lineName(ix, id) : trafoName(ix, id)) : `${kind} ${id}`);
  const study = (kind: "line" | "trafo", id: number) => (plan ? (kind === "line" ? plan.line_loading : plan.trafo_loading)[String(id)] : undefined);
  const up = c.changed.filter((x) => x.h100_after > x.h100_before).length;
  return (
    <div className="qgroup">
      <div className="qhead"><span className="sw" style={{ background: C.red }} /><b style={{ fontSize: 12 }}>What the branch changes</b><span className="fcount">{up}</span></div>
      <span className="mute" style={{ fontSize: 11, lineHeight: 1.45 }}>
        Against {before?.label ?? c.before}: {c.in_service.join(", ")} in service, up to {c.output_peak_mw} MW,
        {" "}{c.output_energy_gwh} GWh in the year.
      </span>
      {c.on_slack.length > 0 && <div className="notice" style={{ fontSize: 11 }}>{c.on_slack.join(", ")} connect{c.on_slack.length === 1 ? "s" : ""} at the slack bus: in this model it moves only the GSP exchange and loads no circuit.</div>}
      {c.storage.length > 0 && <div className="notice" style={{ fontSize: 11 }}>{c.storage.join(", ")} follow{c.storage.length === 1 ? "s" : ""} a placeholder battery rule; the study-case figure beside each element is the worst case.</div>}
      {c.voltage_control_at_unity.length > 0 && <span className="mute" style={{ fontSize: 11 }}>Run at unity power factor, not voltage control: {c.voltage_control_at_unity.join(", ")}.</span>}
      {c.worst && (
        <span style={{ fontSize: 11.5, lineHeight: 1.45 }}>
          <b>{name(c.worst.kind, c.worst.element_id)}</b>: about {Math.round(c.worst.mvah_above).toLocaleString()} MVAh above its rating in
          the year, up to {c.worst.largest_mva_above} MVA at once. A crude first indication of the export that would have to be
          held back (MVA on one circuit, not MW at the project; one weather year).
        </span>
      )}
      {c.changed.length === 0 && <span className="mute" style={{ fontSize: 11.5 }}>No line or transformer changes by more than 5 points or any hour over rating.</span>}
      {c.changed.slice(0, 15).map((x) => {
        const sc = study(x.kind, x.element_id);
        return (
          <button key={`${x.kind}${x.element_id}`} className="qrow" style={{ gridTemplateColumns: "minmax(0, 1fr) auto" }} onClick={() => actions.select({ kind: x.kind, id: x.element_id })}>
            <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
              <b className="ellipsis" style={{ fontSize: 12 }}>{name(x.kind, x.element_id)}</b>
              <span className="mute" style={{ fontSize: 11 }}>
                peak {Math.round(x.peak_before)}% → {Math.round(x.peak_after)}%{sc != null ? ` · study cases ${Math.round(sc)}%` : ""}
              </span>
            </span>
            <span className="mono" style={{ fontSize: 11, color: x.h100_after > 0 ? C.redInk : C.amber, textAlign: "right" }}>
              {hrs(x.h100_before)} → {hrs(x.h100_after)}<br /><span className="mute-2">over rating</span>
            </span>
          </button>
        );
      })}
      {!plan && <span className="mute-2" style={{ fontSize: 10.5 }}>Run the branch's plan years to see its study-case figure beside each element.</span>}
      <span className="mute" style={{ fontSize: 11 }}>
        GSP export peak {c.export_peak_mw[0]} → {c.export_peak_mw[1]} MW, import peak {c.import_peak_mw[0]} → {c.import_peak_mw[1]} MW
        (the engine's GSP flow; Ash Farm, at the slack bus, is not in it).
      </span>
      {c.buses.length > 0 && <span className="mute" style={{ fontSize: 11 }}>Busbars out of band: {c.buses.map(([b, x, y]) => `${ix ? busName(ix, b) : b} ${hrs(x)} → ${hrs(y)}`).join("; ")}.</span>}
      {c.substations.length > 0 && <span className="mute" style={{ fontSize: 11 }}>Above firm capacity: {c.substations.map(([n, x, y]) => `${n} ${hrs(x)} → ${hrs(y)}`).join("; ")}.</span>}
    </div>
  );
}

export function RunsTab({ planner }: { planner: Planner }) {
  const { s, actions } = planner;
  const { ix, onMain } = planner.derived;
  const [showLimits, setShowLimits] = useState(false);
  useEffect(() => {
    void actions.openRuns();
  }, [actions]);
  const r = s.runSummary;
  const info = s.runs?.find((x) => x.run_id === s.runId) ?? (r?.info.run_id === s.runId ? r.info : undefined);
  const listed = (s.runs ?? []).some((x) => x.run_id === s.runId);
  const name = (e: RunElement) => (ix ? (e.kind === "line" ? lineName(ix, e.element_id) : trafoName(ix, e.element_id)) : `${e.kind} ${e.element_id}`);
  const worst = r ? r.elements.filter((e) => e.h100 > 0 || e.h90 > 0).slice(0, 25) : [];
  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <b style={{ fontSize: 13 }}>Year runs</b>
        <span className="mute" style={{ fontSize: 11.5, lineHeight: 1.45 }}>
          A whole year, half-hour by half-hour, through the same power flow: where and when lines and transformers run over
          their rating. Pick "Over rating" in the header to colour the map by it.
        </span>
        <select className="search" value={s.runId} onChange={(e) => void actions.setRun(e.target.value)} aria-label="Year run">
          {(s.runs ?? []).map((x) => (
            <option key={x.run_id} value={x.run_id}>{x.label}{x.available ? "" : " (no file)"}</option>
          ))}
          {!listed && info && <option value={info.run_id}>{info.label}</option>}
        </select>
        <div style={{ display: "flex", gap: 6 }}>
          {(["hours", "peak"] as const).map((m) => (
            <button key={m} className={`btn${s.runMetric === m ? "" : " ghost"}`} onClick={() => actions.setRunMetric(m)}>
              {m === "hours" ? "Hours over rating" : "Peak loading"}
            </button>
          ))}
          {s.layer !== "hours" && <button className="btn ghost" onClick={() => actions.setLayer("hours")}>Show on map</button>}
        </div>
      </div>
      {!onMain && <BranchYear planner={planner} />}
      {info && !info.available && (
        <div className="notice">
          This run has no file yet. Make it (about 16 minutes, one core), then reload:
          <code style={{ display: "block", marginTop: 6, fontSize: 10.5, whiteSpace: "pre-wrap" }}>{info.make}</code>
        </div>
      )}
      {info?.available && (
        <div className="notice" style={{ fontSize: 11.5, lineHeight: 1.45 }}>
          <button className="btn ghost" style={{ height: "auto", padding: 0, fontSize: 11.5 }} onClick={() => setShowLimits((v) => !v)}>
            {showLimits ? "Hide" : "What these numbers can and cannot tell you"}
          </button>
          {showLimits && <div style={{ marginTop: 6 }}>{info.limits}</div>}
        </div>
      )}
      {s.runLoading && <span className="mute">Reading the run…</span>}
      {r && r.info.run_id === s.runId && (
        <>
          {s.runCompare?.run_id === s.runId && <Comparison planner={planner} c={s.runCompare} />}
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <b style={{ fontSize: 12 }}>On the map ({s.runMetric === "hours" ? "hours above rating" : "peak loading"})</b>
            {s.runMetric === "hours" ? (
              <span className="mute" style={{ fontSize: 11, lineHeight: 1.6 }}>
                Red, thicker for longer: {HOURS_STEPS.map((x) => x.label).join(" · ")}. Amber: at or above 90% at some point,
                never over. Grey: input unreliable, not a finding. Red rings: busbars out of band. Amber rings: substations
                above firm capacity.
              </span>
            ) : (
              <span className="mute" style={{ fontSize: 11 }}>The loading colours of the Loading layer, at each element's peak in the year.</span>
            )}
          </div>
          <div className="qgroup">
            <div className="qhead"><span className="sw" style={{ background: C.red }} /><b style={{ fontSize: 12 }}>Over rating, longest first</b><span className="fcount">{r.elements.filter((e) => e.h100 > 0).length}</span></div>
            {worst.length === 0 && <span className="mute" style={{ fontSize: 11.5 }}>Nothing reaches 90% of its rating in this run.</span>}
            {worst.map((e) => (
              <button key={`${e.kind}${e.element_id}`} className="qrow" style={{ gridTemplateColumns: "minmax(0, 1fr) auto", opacity: e.finding ? 1 : 0.6 }}
                onClick={() => actions.select({ kind: e.kind, id: e.element_id })}>
                <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                  <b className="ellipsis" style={{ fontSize: 12 }}>{name(e)}</b>
                  <Label e={e} />
                </span>
                <span className="mono" style={{ fontSize: 11, color: e.h100 > 0 ? C.redInk : C.amber, textAlign: "right" }}>
                  {e.h100 > 0 ? hrs(e.h100) : `${Math.round(e.peak_pct)}%`}<br /><span className="mute-2">peak {Math.round(e.peak_pct)}%</span>
                </span>
              </button>
            ))}
          </div>
          <div className="qgroup">
            <div className="qhead"><span className="sw" style={{ background: C.red }} /><b style={{ fontSize: 12 }}>Busbars out of band</b><span className="fcount">{r.buses.length}</span></div>
            {r.buses.length === 0 && <span className="mute" style={{ fontSize: 11.5 }}>Every busbar stays in its statutory band.</span>}
            {r.buses.map((b) => (
              <button key={b.bus_id} className="qrow" style={{ gridTemplateColumns: "minmax(0, 1fr) auto", opacity: b.finding ? 1 : 0.6 }} onClick={() => actions.select({ kind: "bus", id: b.bus_id })}>
                <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                  <b className="ellipsis" style={{ fontSize: 12 }}>{ix ? busName(ix, b.bus_id) : `bus ${b.bus_id}`}</b>
                  <span className="mute" style={{ fontSize: 11 }}>{b.vmin_pu.toFixed(3)} to {b.vmax_pu.toFixed(3)} pu{b.finding ? "" : " · input unreliable, not a finding"}</span>
                </span>
                <span className="mono" style={{ fontSize: 11, color: C.redInk }}>{hrs(b.hours_outside)}</span>
              </button>
            ))}
          </div>
          <div className="qgroup">
            <div className="qhead"><span className="sw" style={{ background: C.amber }} /><b style={{ fontSize: 12 }}>Above firm capacity</b><span className="fcount">{r.substations.length}</span></div>
            <span className="mute" style={{ fontSize: 11, lineHeight: 1.45 }}>
              Firm capacity is what a substation carries after losing one transformer; above it, an outage leaves a shortfall.
              Two halves of one site are shown against each half's firm capacity, which overstates their hours. Primary
              (33/11 kV) substations only; the 132/33 kV substations are in the firm-capacity report.
            </span>
            {r.substations.map((x) => (
              <button key={x.name} className="qrow" style={{ gridTemplateColumns: "minmax(0, 1fr) auto" }} onClick={() => actions.select({ kind: "bus", id: x.bus_id })}>
                <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                  <b className="ellipsis" style={{ fontSize: 12 }}>{x.name}</b>
                  <span className="mute" style={{ fontSize: 11 }}>peak {x.peak_mva} MVA against {x.firm_mva} MVA, {when(x.peak_at)}</span>
                </span>
                <span className="mono" style={{ fontSize: 11, color: C.amber }}>{hrs(x.hours_above_firm)}</span>
              </button>
            ))}
          </div>
          <span className="mute-2" style={{ fontSize: 10.5 }}>
            {r.solved.toLocaleString()} of {r.half_hours.toLocaleString()} half-hours solved
            {r.solved < r.half_hours && ` (${r.collapsed.toLocaleString()} a voltage collapse, ${(r.half_hours - r.solved - r.collapsed).toLocaleString()} did not converge)`} · engine {r.fingerprint}
          </span>
        </>
      )}
    </>
  );
}

/** The selected element in the year view: its run figures and a month-by-hour grid of when it is over. */
export function RunDetail({ planner }: { planner: Planner }) {
  const { s } = planner;
  const r = s.runSummary;
  const sel = s.sel;
  const [grid, setGrid] = useState<RunGrid | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const kind = sel?.kind === "line" || sel?.kind === "trafo" || sel?.kind === "bus" ? sel.kind : null;
  const id = kind && sel && typeof sel.id === "number" ? sel.id : null;
  useEffect(() => {
    setGrid(null);
    setErr(null);
    if (!r || !kind || id == null) return;
    let live = true;
    api.getRunGrid(r.info.run_id, kind, id).then((g) => live && setGrid(g), (e) => live && setErr(failureText(e)));
    return () => {
      live = false;
    };
  }, [r, kind, id]);
  if (!r || !kind || id == null) return null;
  const e = kind === "bus" ? null : r.elements.find((x) => x.kind === kind && x.element_id === id);
  const b = kind === "bus" ? r.buses.find((x) => x.bus_id === id) : null;
  const max = grid ? Math.max(0.5, ...grid.hours.flat()) : 1;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: 8 }}>
      <b style={{ fontSize: 12 }}>{r.info.label}</b>
      {e && (
        <>
          <Label e={e} />
          <div className="kv">
            <span>Peak</span><span className="mono" style={{ color: loadColor(e.peak_pct) }}>{e.peak_pct}% · {when(e.peak_at)}</span>
            <span>At or above 80%</span><span className="mono">{hrs(e.h80)}</span>
            <span>At or above 90%</span><span className="mono">{hrs(e.h90)}</span>
            <span>Above rating</span><span className="mono" style={{ color: e.h100 > 0 ? C.redInk : undefined }}>{hrs(e.h100)}</span>
          </div>
        </>
      )}
      {kind === "bus" && (
        <span className="mono" style={{ fontSize: 11.5 }}>
          {b ? `outside its band ${hrs(b.hours_outside)} · ${b.vmin_pu.toFixed(3)} to ${b.vmax_pu.toFixed(3)} pu${b.finding ? "" : " · input unreliable, not a finding"}` : "inside its band all year"}
        </span>
      )}
      {err && <span className="mute">{err}</span>}
      {grid && grid.hours.flat().some((h) => h > 0) && (
        <div>
          <span className="mute" style={{ fontSize: 10.5 }}>When it is over: months down, hours of day across (00 to 23)</span>
          <div style={{ display: "grid", gridTemplateColumns: "12px repeat(24, 1fr)", gap: 1, marginTop: 4 }}>
            {grid.hours.map((row, m) => [
              <span key={`m${m}`} className="mute-2" style={{ fontSize: 9, lineHeight: "9px" }}>{MONTHS[m]}</span>,
              ...row.map((h, k) => (
                <span key={`${m}-${k}`} title={`${MONTHS[m]} ${String(k).padStart(2, "0")}:00 · ${h} h`}
                  style={{ height: 9, borderRadius: 1, background: h > 0 ? C.red : "rgba(255,255,255,0.05)", opacity: h > 0 ? 0.25 + 0.75 * (h / max) : 1 }} />
              )),
            ])}
          </div>
        </div>
      )}
      {grid && !grid.hours.flat().some((h) => h > 0) && <span className="mute" style={{ fontSize: 11 }}>Never over in this run.</span>}
    </div>
  );
}
