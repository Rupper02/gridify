// Capacity: how strong the branch's grid is. When each element needs reinforcement, year by year (the engine's binding
// set: the first plan year it goes over, or comes near, its limit, the case, the first-order margin and the kind of
// works that relieves it), and the room to connect at each substation today (the engine's hosting-capacity study,
// measured when the operator asks). The map's Headroom layer draws both; a row sets the year and shows the element.

import { PlugsConnected } from "@phosphor-icons/react";

import type { PlannerSlice } from "../hooks/planner/slice";
import {
  type HostingState,
  NEED,
  type NeedYear,
  type Room,
  type SiteRoom,
  gspOver,
  holdCounts,
  leverText,
  marginText,
  needOf,
  needTimeline,
  roomColor,
  roomText,
} from "../lib/capacity";
import { type ModelIndex, ZOOM_ELEMENT, nameElements, plural } from "../lib/derive";
import { bindingSel, worstText } from "../lib/limits";
import { C, caseLabel, fmtMw } from "../theme";
import type { ElementBinding, Limits, Model, Sel, YearResult } from "../types";

export type CapacityTabPlanner = PlannerSlice<
  "hosting" | "limits" | "limitsError" | "model" | "result" | "year",
  "focusSel" | "loadHosting" | "measureHosting" | "setYear",
  "branch" | "ix" | "onMain" | "rooms" | "run" | "stale"
>;

type Open = (sel: Sel | null, year: number | null) => void;

const KIND_LABEL: Record<ElementBinding["kind"], string> = { line: "circuit", trafo: "transformer", bus: "busbar" };

export function CapacityTab({ planner }: { planner: CapacityTabPlanner }) {
  const { s, actions, derived } = planner;
  const where = derived.onMain ? "main" : derived.branch?.name;
  const l = s.limits;
  const open: Open = (sel, year) => {
    if (year != null) actions.setYear(year);
    if (sel) actions.focusSel(sel, ZOOM_ELEMENT);
  };
  return (
    <div className="scroll" style={{ padding: "4px 14px 16px", gap: 12 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>How strong {where} is</span>
        {l && s.model ? (
          <span style={{ fontSize: 12, color: C.ink2, lineHeight: 1.45 }}>{strengthLine(l, s.model)}</span>
        ) : (
          <span style={{ fontSize: 12, color: C.mute, lineHeight: 1.45 }}>
            {s.limitsError ?? (derived.run.inProgress ? "Solving the plan; the reinforcement timeline appears once every year is in." : "When each element needs reinforcement, and the room to connect at each substation.")}
          </span>
        )}
      </div>
      {derived.stale.stale && !derived.run.inProgress && <div className="notice amber">The result is out of date; this is its last run.</div>}
      {l && <Timeline l={l} years={s.result?.years} year={s.year} model={s.model} onOpen={open} />}
      <RoomToConnect h={s.hosting} rooms={derived.rooms} ix={derived.ix} onMeasure={() => void actions.measureHosting()} onRetry={() => void actions.loadHosting()} onOpen={open} />
    </div>
  );
}

/** "4 elements go over a limit in the plan, the first in 2033 · 12 more come near one · 70 of 78 circuits and 38 of 44
 * transformers hold through 2035". */
function strengthLine(l: Limits, m: Model): string {
  const over = l.binding.filter((b) => b.first_breach_year != null);
  const near = l.binding.filter((b) => b.first_breach_year == null && b.first_near_year != null);
  const first = Math.min(...over.map((b) => b.first_breach_year!));
  const h = holdCounts(m, l);
  const end = l.years[l.years.length - 1];
  return [
    over.length ? `${plural(over.length, "element")} go${over.length === 1 ? "es" : ""} over a limit in the plan, the first in ${first}` : "No element goes over a limit in any plan year",
    near.length ? `${near.length} more come${near.length === 1 ? "s" : ""} near one` : "",
    `${h.linesHold} of ${h.lines} circuits and ${h.trafosHold} of ${h.trafos} transformers hold through ${end}`,
  ]
    .filter(Boolean)
    .join(" · ");
}

// ---- when it needs reinforcement ----------------------------------------------------------------
function Timeline({ l, years, year, model, onOpen }: { l: Limits; years: Record<string, YearResult> | undefined; year: number; model: Model | null; onOpen: Open }) {
  const groups = needTimeline(l);
  const gsp = gspOver(years);
  if (gsp && !groups.some((g) => g.year === gsp.year)) groups.push({ year: gsp.year, breach: [], near: [] });
  groups.sort((a, b) => a.year - b.year);
  return (
    <section className="lsec">
      <span className="lsec-title">When it needs reinforcement</span>
      {!groups.length && <span className="mute" style={{ fontSize: 12 }}>Nothing goes over or near a limit in any plan year.</span>}
      {groups.map((g: NeedYear) => (
        <div key={g.year} className="need-year">
          <span className={`need-year-head mono${g.year <= year ? " past" : ""}`}>{g.year}{g.year === l.years[0] ? " · today" : ""}</span>
          {gsp?.year === g.year && (
            <div className="lrow">
              <span className="sev-dot" style={{ background: NEED[gsp.year <= year ? "now" : "later"].c }} />
              <span className="ellipsis" style={{ fontSize: 12.5, fontWeight: 600 }}>GSP export</span>
              <span className="chip kind">boundary</span>
              <span className="lfacts">
                <b className="mono" style={{ color: C.red }}>{fmtMw(gsp.export_mw)} of {fmtMw(gsp.limit_mw)} MW{gsp.case ? ` at ${caseLabel(gsp.case)}` : ""}</b>
                <span>needs more export capacity at the GSP: transmission works</span>
              </span>
            </div>
          )}
          {[...g.breach, ...g.near].map((b) => <NeedRow key={`${b.kind}:${b.element_id}`} b={b} year={year} model={model} onOpen={onOpen} />)}
        </div>
      ))}
    </section>
  );
}

/** One element in the year it first goes over (or near) its limit: its worst figure and case, the first-order margin,
 * what would relieve it, the outages that breach it and the projects it holds back. */
function NeedRow({ b, year, model, onOpen }: { b: ElementBinding; year: number; model: Model | null; onOpen: Open }) {
  const n = needOf(b, year);
  const at = b.first_breach_year ?? b.first_near_year;
  const margin = marginText(b);
  return (
    <div className="lrow">
      <span className="sev-dot" style={{ background: NEED[n].c }} title={NEED[n].label} />
      <button className="frow-main" onClick={() => onOpen(bindingSel(b, model), at)} title={`Show it on the map in ${at}`}>
        <span className="ellipsis" style={{ fontSize: 12.5, fontWeight: 600 }}>{b.name}</span>
        <span className="chip kind">{KIND_LABEL[b.kind]}</span>
      </button>
      <span />
      <span className="lfacts">
        <b className="mono" style={{ color: b.first_breach_year != null ? C.red : NEED.near.c }}>{worstText(b)}</b>
        {margin && <span>{margin}</span>}
        <span>{b.first_breach_year != null ? "needs" : "if it grows:"} {leverText(b)}</span>
        {b.n1_outages > 0 && <span>{plural(b.n1_outages, "outage")} breach{b.n1_outages === 1 ? "es" : ""} it</span>}
      </span>
      {b.holds_back.length > 0 && (
        <span className="chips">
          {b.holds_back.map((id) => (
            <span key={id} className="chip hold">holds back {id}</span>
          ))}
        </span>
      )}
    </div>
  );
}

// ---- the room to connect today ------------------------------------------------------------------
function RoomToConnect({ h, rooms, ix, onMeasure, onRetry, onOpen }: { h: HostingState; rooms: Map<string, SiteRoom>; ix: ModelIndex | null; onMeasure: () => void; onRetry: () => void; onOpen: Open }) {
  const sites = [...rooms.values()].sort((a, b) => (b.gen?.mw ?? -1) - (a.gen?.mw ?? -1) || (b.dem?.mw ?? -1) - (a.dem?.mw ?? -1));
  const n = h.export?.items.length ?? h.import?.items.length ?? 0;
  return (
    <section className="lsec">
      <span className="lsec-title">Room to connect today</span>
      <span style={{ fontSize: 11.5, color: C.mute, lineHeight: 1.45 }}>
        A firm connection probed in 5 MW steps at each substation's busbars on today's network (the branch's reinforcements, not its projects or demand growth): generation at summer minimum, demand at winter peak, as a DNO's headroom map publishes them. Each substation shows its best busbar.
      </span>
      {h.status === "failed" && (
        <span className="notice amber" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="grow">Could not measure the room: {h.error}</span>
          <button className="btn" onClick={onRetry}>Retry</button>
        </span>
      )}
      {(h.status === "idle" || h.status === "reading") && <span className="mute" style={{ fontSize: 12 }}>Reading the room…</span>}
      {h.status === "absent" && (
        <button className="btn" style={{ alignSelf: "flex-start" }} onClick={onMeasure}>
          <PlugsConnected size={13} />
          Measure the room (a few minutes; kept for every branch with the same reinforcements)
        </button>
      )}
      {h.status === "measuring" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span className="mono" style={{ fontSize: 11, color: C.mute }}>{h.stage || "starting"}</span>
          <span style={{ height: 4, borderRadius: 2, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
            <span style={{ display: "block", height: "100%", width: `${Math.round(h.fraction * 100)}%`, background: C.accent }} />
          </span>
        </div>
      )}
      {h.status === "ready" && (
        <span className="mono" style={{ fontSize: 11, color: C.mute }}>
          {plural(sites.length, "substation")} · {plural(n, "busbar")} probed
        </span>
      )}
      {sites.map((x) => (
        <button key={x.name} className="cause-row link" onClick={() => onOpen({ kind: "trafo", id: x.trafo }, null)} title="Show the substation on the map">
          <span style={{ display: "flex", alignItems: "baseline", gap: 10, minWidth: 0 }}>
            <span className="ellipsis grow" style={{ fontSize: 12.5, fontWeight: 600 }}>{x.name}</span>
            <RoomFigure label="gen" r={x.gen} />
            <RoomFigure label="demand" r={x.dem} />
          </span>
          {[x.gen && !x.gen.capped && `generation: ${nameElements(x.gen.why, ix)}`, x.dem && !x.dem.capped && `demand: ${nameElements(x.dem.why, ix)}`]
            .filter(Boolean)
            .map((t) => (
              <span key={t as string} style={{ fontSize: 11, color: C.mute, lineHeight: 1.4 }}>then {t}</span>
            ))}
        </button>
      ))}
    </section>
  );
}

function RoomFigure({ label, r }: { label: string; r: Room | null }) {
  if (!r) return null;
  return (
    <span className="mono" style={{ fontSize: 11.5, whiteSpace: "nowrap", color: C.mute }}>
      {label} <b style={{ color: roomColor(r.mw) }}>{roomText(r)} MW</b> <span style={{ fontSize: 10.5 }}>{+r.kv} kV</span>
    </span>
  );
}
