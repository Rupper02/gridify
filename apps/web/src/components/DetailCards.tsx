// The detail cards over the map. A project opens the project card (details, energisation year with
// recommend-then-override, the binding constraint and "What would it take?"); a line, transformer or
// existing generator opens the element card (rating, loading in the year, its maintenance windows and
// the form to schedule one).

import { Intersect, Lightbulb, LineSegment, Trash, Wrench, X } from "@phosphor-icons/react";
import type { CSSProperties, ReactNode } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { busLabel, effYearOf, elementInfo, headlineMw, nameElements, outageImpact, seasonHint } from "../lib/derive";
import type { Layout } from "../lib/layout";
import { C, ST, TECH, fmtMw, isTech, loadColor, techLabel, tint } from "../theme";
import type { ElementSel, QueueItem, RegistryItem, Season } from "../types";
import { Stepper, TechIcon } from "./ui";

export type DetailCardsPlanner = PlannerSlice<
  "diffMode" | "maintDraft" | "outages" | "result" | "sel" | "sideOpen" | "year",
  "removeOutage" | "scheduleOutage" | "select" | "setDraft" | "setSchedule" | "startRecs",
  "branch" | "branchOnly" | "hue" | "ix" | "onMain" | "prelim" | "qById" | "yr"
>;

function cardPos(planner: DetailCardsPlanner, layout: Layout): CSSProperties {
  const { s } = planner;
  const top = s.diffMode ? (layout.narrow ? 160 : 118) : layout.narrow ? 110 : s.sideOpen ? 68 : 114;
  const reserve = layout.showDock ? layout.dockPx + 20 : 14;
  return { top, right: s.sideOpen ? layout.sideW + 128 : 150, maxHeight: `calc(100% - ${top + reserve}px)` };
}

export function DetailCards({ planner, layout }: { planner: DetailCardsPlanner; layout: Layout }) {
  const sel = planner.s.sel;
  if (!sel) return null;
  if (sel.kind === "project") return <ProjectCard planner={planner} layout={layout} id={sel.id} />;
  return <ElementCard planner={planner} layout={layout} sel={sel} />;
}

const CardHead = ({ icon, iconBg, title, sub, mono, onClose }: { icon: ReactNode; iconBg: string; title: string; sub: string; mono?: boolean; onClose: () => void }) => (
  <div className="head">
    <span className="ic" style={{ background: iconBg }}>{icon}</span>
    <div style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1, lineHeight: 1.3 }}>
      <span className={mono ? "mono" : ""} style={{ fontSize: mono ? 15 : 13.5, fontWeight: 600, textWrap: "pretty" }}>{title}</span>
      <span className="ellipsis" style={{ fontSize: mono ? 12 : 11, color: mono ? C.ink2 : C.mute, fontFamily: mono ? undefined : "var(--mono)" }}>{sub}</span>
    </div>
    <button className="icon-btn" onClick={onClose} aria-label="Close">
      <X size={12} />
    </button>
  </div>
);

function ProjectCard({ planner, layout, id }: { planner: DetailCardsPlanner; layout: Layout; id: string }) {
  const { s, actions, derived } = planner;
  const x: QueueItem | undefined = derived.qById[id];
  const pre: RegistryItem | undefined = derived.prelim.find((p) => p.request_id === id);
  if (!x && !pre) return null;
  const item = (x ?? pre)!;
  const st = ST[x ? x.status : "Prelim"];
  const onlyHere = derived.branchOnly.has(id) && !derived.onMain;
  const importOnly = isTech(item.technology) && TECH[item.technology].importOnly;
  const rec = x?.recommended_year ?? null;
  const eff = x ? effYearOf(x) : null;
  const recText = !rec || eff == null ? "" : eff < rec ? `Earlier than recommended (${rec})` : eff > rec ? `Later than recommended (${rec})` : "Recommended by the optimiser";
  const recColor = !rec || eff == null ? C.mute : eff < rec ? C.amber : eff > rec ? C.mute : C.greenInk;
  const ready = Math.round((item.readiness_score ?? 0) * 100);
  return (
    <div className="detail glass" style={{ ...cardPos(planner, layout), width: 296, borderColor: onlyHere ? tint(derived.hue, "80") : undefined }}>
      <CardHead
        icon={<TechIcon tech={item.technology} size={18} color={st.c} />}
        iconBg={tint(st.c, "22")}
        title={id}
        sub={item.applicant || techLabel(item.technology)}
        mono
        onClose={() => actions.select(null)}
      />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        <span className="chip" style={{ background: tint(st.c, "22"), color: st.c }}>{st.long}</span>
        {onlyHere && <span className="chip" style={{ border: `1px solid ${derived.hue}`, color: derived.hue }}>only on {derived.branch?.name}</span>}
        {x?.against_recommendation && <span className="chip" style={{ background: "rgba(255,195,107,0.16)", color: C.amberInk }}>against the recommendation</span>}
      </div>
      <div className="kv">
        <span>Technology</span><span>{techLabel(item.technology)}</span>
        <span>{importOnly ? "Import" : "Export"}</span>
        <span className="mono">{fmtMw(headlineMw(item))} MW{!importOnly && (item.import_mw ?? 0) > 0 && TECH[item.technology as keyof typeof TECH]?.imports ? ` · imports ${fmtMw(item.import_mw)}` : ""}</span>
        <span>Connection</span><span className="mono">{derived.ix ? busLabel(derived.ix, item.bus_id) : `Bus ${item.bus_id}`}</span>
        <span>Rank</span><span className="mono">{x ? (x.rank != null ? `#${x.rank}` : "unranked") : "unranked"}</span>
        <span>Readiness</span><span className="mono">{ready}%</span>
        <span>Study treatment</span><span style={{ color: C.ink2 }}>{isTech(item.technology) ? TECH[item.technology].treatment : "Firm in both cases"}</span>
      </div>
      {x && eff != null && (
        <div className="box dark">
          <span style={{ fontSize: 11.5, color: C.mute }}>Energisation year</span>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Stepper value={eff} label="energisation year" onDec={() => void actions.setSchedule(id, eff - 1)} onInc={() => void actions.setSchedule(id, eff + 1)} />
            <span style={{ marginLeft: "auto", fontSize: 11, textAlign: "right", lineHeight: 1.35, color: recColor }}>{recText}</span>
          </div>
          {x.scheduled_year != null && !derived.onMain && (
            <button className="btn ghost" style={{ height: 24, padding: 0, alignSelf: "flex-start", fontSize: 11 }} onClick={() => void actions.setSchedule(id, null)}>
              Back to the recommendation
            </button>
          )}
        </div>
      )}
      {pre && !x && (
        <div className="box dark">
          <span style={{ fontSize: 12, color: C.ink2, lineHeight: 1.45 }}>
            Preliminary: not simulated yet. Requested {pre.commissioning_year ?? "no year"}. Run to rank it and get a recommended year.
          </span>
        </div>
      )}
      {x && (x.status === "Deferred" || x.status === "Rejected") && x.reason && (
        <div className="box amber">
          <span style={{ fontSize: 11, fontWeight: 600, color: C.amber }}>{x.status === "Rejected" ? "Rejected at intake" : "Binding constraint"}</span>
          <span style={{ fontSize: 12, color: C.amberInk, lineHeight: 1.45 }}>{nameElements(x.reason.why, derived.ix)}</span>
          <span style={{ fontSize: 11.5, color: C.ink2, lineHeight: 1.45 }}>{nameElements(x.reason.action, derived.ix)}</span>
          {x.status === "Deferred" && (
            <button className="btn warn sq" style={{ alignSelf: "flex-start" }} onClick={() => actions.startRecs(id)}>
              <Lightbulb size={13} />
              What would it take?
            </button>
          )}
        </div>
      )}
    </div>
  );
}

const SEASONS: Season[] = ["Spring", "Summer", "Autumn", "Winter"];
const WEEKS = [2, 4, 6, 8];

function ElementCard({ planner, layout, sel }: { planner: DetailCardsPlanner; layout: Layout; sel: ElementSel }) {
  const { s, actions, derived } = planner;
  const { ix } = derived;
  if (!ix) return null;
  const info = elementInfo(sel, ix, derived.yr, s.year);
  if (!info) return null;
  const d = s.maintDraft;
  const windows = s.outages.filter((o) => o.element_kind === sel.kind && o.element_id === String(sel.id));
  const Icon = sel.kind === "line" ? LineSegment : Intersect;
  return (
    <div className="detail glass" style={{ ...cardPos(planner, layout), width: 308, borderColor: "rgba(255,255,255,0.16)" }}>
      <CardHead
        icon={sel.kind === "gen" ? <TechIcon tech={ix.gen.get(sel.id)?.technology} size={18} color={C.line132} /> : <Icon size={18} color={C.line132} />}
        iconBg="rgba(255,255,255,0.08)"
        title={info.name}
        sub={info.kindLabel}
        onClose={() => actions.select(null)}
      />
      <div className="kv">
        <span>Rating</span><span className="mono">{info.rating}</span>
        <span>{info.loadLabel}</span><span className="mono" style={{ color: info.loadPct != null ? loadColor(info.loadPct) : C.ink }}>{info.load}</span>
      </div>
      {windows.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 600 }}>Scheduled on {derived.onMain ? "main" : derived.branch?.name}</span>
          {windows.map((o) => {
            const imp = outageImpact(o, s.result, ix);
            return (
              <div key={o.outage_id} className="mrow">
                <Wrench size={13} color={C.line132} />
                <span className="ellipsis" style={{ fontSize: 12 }}>{o.season} {o.year} · {o.weeks} wk · {o.kind}</span>
                {!derived.onMain ? (
                  <button className="icon-btn sm" onClick={() => void actions.removeOutage(o.outage_id)} title="Remove" aria-label="Remove outage">
                    <Trash size={12} />
                  </button>
                ) : <span />}
                <span className="imp" style={{ color: imp.c }}>{imp.text}</span>
              </div>
            );
          })}
        </div>
      )}
      <div className="box dark" style={{ gap: 10, padding: 12 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>Schedule maintenance</span>
        <div className="form-row">
          <span className="lbl">Season</span>
          <div className="opts">
            {SEASONS.map((x) => (
              <button key={x} className={`pill-opt${d.season === x ? " on" : ""}`} onClick={() => actions.setDraft({ season: x })}>{x}</button>
            ))}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: C.mute, flex: 1 }}>Year</span>
          <Stepper small value={d.year} label="year" onDec={() => actions.setDraft({ year: Math.max(2026, d.year - 1) })} onInc={() => actions.setDraft({ year: Math.min(2035, d.year + 1) })} />
        </div>
        <div className="form-row">
          <span className="lbl">Duration</span>
          <div className="opts">
            {WEEKS.map((w) => (
              <button key={w} className={`pill-opt${d.weeks === w ? " on" : ""}`} onClick={() => actions.setDraft({ weeks: w })}>{w} weeks</button>
            ))}
          </div>
        </div>
        <div className="form-row">
          <span className="lbl">Type</span>
          <div className="opts">
            <button className={`pill-opt${d.kind === "outage" ? " on" : ""}`} onClick={() => actions.setDraft({ kind: "outage" })}>Full outage</button>
            <button className={`pill-opt${d.kind === "derate" ? " on" : ""}`} onClick={() => actions.setDraft({ kind: "derate" })}>Derate to 50%</button>
          </div>
        </div>
        <span style={{ fontSize: 11, color: C.mute2, lineHeight: 1.4 }}>{seasonHint(d.season)}</span>
        <button className="btn primary sm" style={{ justifyContent: "center", height: 34 }} onClick={() => void actions.scheduleOutage(sel)}>
          <Wrench size={13} weight="bold" />
          {derived.onMain ? "Open a branch and schedule" : `Schedule on ${derived.branch?.name}`}
        </button>
      </div>
    </div>
  );
}
