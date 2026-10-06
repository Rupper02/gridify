// The detail cards over the map. A project opens the project card (details, energisation year with
// recommend-then-override, the binding constraint and a question to the agents about its options); a
// line, transformer or existing generator opens the element card (rating, loading in the year, its
// maintenance windows and the form to schedule one).

import { Intersect, LineSegment, Sparkle, Wrench, X } from "@phosphor-icons/react";
import { type CSSProperties, type ReactNode, useState } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { busLabel, effYearOf, elementInfo, headlineMw, nameElements } from "../lib/derive";
import { cardSlot, type Layout } from "../lib/layout";
import { DERATE_PCT, PARALLEL_LABEL, WORKS, WORK_UI, draftHint, outageLine, repoweredNotes, stepFactor, verdictColor, windowView } from "../lib/maintenance";
import { type Plan, clampYear, statusTitle } from "../lib/plan";
import { type ControlForm, EMPTY_CONTROL, controlFromForm, controlText } from "../lib/projects";
import { C, ST, TECH, fmtMw, isTech, loadColor, techLabel, tint } from "../theme";
import type { Control, ElementSel, QueueItem, RegistryItem, Season } from "../types";
import { Stepper, TechIcon } from "./ui";
import { RemoveWindow, VerdictChip, WindowDetail } from "./WindowVerdict";

export type DetailCardsPlanner = PlannerSlice<
  "candidates" | "diffMode" | "maintDraft" | "outages" | "plan" | "result" | "sel" | "sideOpen" | "year",
  "askAbout" | "removeOutage" | "scheduleOutage" | "select" | "setControl" | "setDraft" | "setSchedule",
  "branch" | "branchOnly" | "hue" | "ix" | "onMain" | "prelim" | "q" | "qById" | "yr"
>;

const cardPos = (planner: DetailCardsPlanner, layout: Layout): CSSProperties => cardSlot(layout, planner.s.sideOpen, planner.s.diffMode);

export function DetailCards({ planner, layout }: { planner: DetailCardsPlanner; layout: Layout }) {
  const { sel, plan } = planner.s;
  if (!sel || !plan) return null;
  if (sel.kind === "project") return <ProjectCard planner={planner} layout={layout} plan={plan} id={sel.id} />;
  if (sel.kind === "region") return null; // RegionCard (App.tsx)
  return <ElementCard planner={planner} layout={layout} plan={plan} sel={sel} />;
}

interface CardProps {
  planner: DetailCardsPlanner;
  layout: Layout;
  plan: Plan;
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

/** How the project's offer runs it, or that it does not say (modelled at unity power factor), with a form to state it. */
/** The form for changing a stated control mode starts from it (an empty one when none is stated). */
const formOf = (c: Control | null): ControlForm =>
  c
    ? { mode: c.mode, pf: c.pf != null ? String(c.pf) : "", absorbing: c.absorbing ?? true, vm: c.vm_pu != null ? String(c.vm_pu) : "", range: c.q_range_pf != null ? String(c.q_range_pf) : "" }
    : { ...EMPTY_CONTROL };

function ControlBox({ control, editable, onSave }: { control: Control | null; editable: boolean; onSave: (c: Control) => Promise<boolean> }) {
  const [form, setForm] = useState<ControlForm | null>(null);
  const [error, setError] = useState<string | null>(null);
  const text = controlText(control);
  const save = async () => {
    if (!form) return;
    const { control: c, error: err } = controlFromForm(form);
    setError(err);
    if (c && (await onSave(c))) setForm(null);
  };
  return (
    <div className={`box ${text ? "dark" : "amber"}`}>
      <span style={{ fontSize: 11, fontWeight: 600, color: text ? C.mute : C.amber }}>Control mode</span>
      <span style={{ fontSize: 12, color: text ? C.ink : C.amberInk, lineHeight: 1.45 }}>
        {text ?? "Not stated: modelled at unity power factor. State it from the connection offer (a power factor, or voltage control for a large connection)."}
      </span>
      {editable && !form && (
        <button className="btn ghost" style={{ height: 24, padding: 0, alignSelf: "flex-start", fontSize: 11 }} onClick={() => setForm(formOf(control))}>
          {text ? "Change" : "State it"}
        </button>
      )}
      {form && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div className="seg" role="radiogroup" aria-label="Control mode">
            {(["pf", "voltage"] as const).map((m) => (
              <button key={m} role="radio" aria-checked={form.mode === m} className={form.mode === m ? "on" : ""} onClick={() => setForm({ ...form, mode: m })} style={{ padding: "0 10px" }}>
                {m === "pf" ? "Power factor" : "Voltage control"}
              </button>
            ))}
          </div>
          {form.mode === "pf" ? (
            <div style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 11.5 }}>
              <input className="fc-cell" style={{ width: 64 }} inputMode="decimal" value={form.pf} onChange={(e) => setForm({ ...form, pf: e.target.value })} aria-label="Power factor" placeholder="0.95" />
              <label style={{ display: "flex", gap: 4, alignItems: "center" }}>
                <input type="checkbox" checked={form.absorbing} onChange={(e) => setForm({ ...form, absorbing: e.target.checked })} />
                absorbing reactive power
              </label>
            </div>
          ) : (
            <div style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 11.5 }}>
              <input className="fc-cell" style={{ width: 64 }} inputMode="decimal" value={form.vm} onChange={(e) => setForm({ ...form, vm: e.target.value })} aria-label="Voltage setpoint (pu)" placeholder="1.00" />
              <span>pu, range ±</span>
              <input className="fc-cell" style={{ width: 64 }} inputMode="decimal" value={form.range} onChange={(e) => setForm({ ...form, range: e.target.value })} aria-label="Reactive range (power factor)" placeholder="0.95" />
              <span>pf</span>
            </div>
          )}
          {error && <span style={{ fontSize: 11, color: C.redInk }}>{error}</span>}
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn primary sm" onClick={() => void save()}>Save</button>
            <button className="btn ghost sm" onClick={() => { setForm(null); setError(null); }}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

function ProjectCard({ planner, layout, plan, id }: CardProps & { id: string }) {
  const { actions, derived } = planner;
  const x: QueueItem | undefined = derived.qById[id];
  const pre: RegistryItem | undefined = derived.prelim.find((p) => p.request_id === id);
  if (!x && !pre) return null;
  const item = (x ?? pre)!;
  const status = x ? x.status : "Prelim";
  const st = ST[status];
  const onlyHere = derived.branchOnly.has(id) && !derived.onMain;
  const importOnly = isTech(item.technology) && TECH[item.technology].importOnly;
  const rec = x?.recommended_year ?? null;
  const eff = x ? effYearOf(x) : null;
  const recText = !rec || eff == null ? "" : eff < rec ? `Earlier than recommended (${rec})` : eff > rec ? `Later than recommended (${rec})` : "Recommended by the optimiser";
  const recColor = !rec || eff == null ? C.mute : eff < rec ? C.amber : eff > rec ? C.mute : C.greenInk;
  const ready = Math.round((item.readiness_score ?? 0) * 100);
  const stored = planner.s.candidates.find((c) => c.request_id === id);
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
        <span className="chip" style={{ background: tint(st.c, "22"), color: st.c }}>{statusTitle(plan, status)}</span>
        {onlyHere && <span className="chip" style={{ border: `1px solid ${derived.hue}`, color: derived.hue }}>only on {derived.branch?.name}</span>}
        {x?.against_recommendation && <span className="chip" style={{ background: "rgba(255,195,107,0.16)", color: C.amberInk }}>against the recommendation</span>}
      </div>
      <div className="kv">
        <span>Technology</span><span>{techLabel(item.technology)}</span>
        <span>{importOnly ? "Import" : "Export"}</span>
        <span className="mono">{fmtMw(headlineMw(item))} MW{!importOnly && (item.import_mw ?? 0) > 0 && isTech(item.technology) && TECH[item.technology].imports ? ` · imports ${fmtMw(item.import_mw)}` : ""}</span>
        <span>Connection</span><span className="mono">{derived.ix ? busLabel(derived.ix, item.bus_id) : `Bus ${item.bus_id}`}</span>
        <span>Rank</span><span className="mono">{x?.rank != null ? `#${x.rank}` : "unranked"}</span>
        <span>Readiness</span><span className="mono">{ready}%</span>
        <span>Study treatment</span><span style={{ color: C.ink2 }}>{isTech(item.technology) ? TECH[item.technology].treatment : "Firm in both cases"}</span>
      </div>
      {stored && <ControlBox control={stored.control ?? null} editable={!derived.onMain} onSave={(c) => actions.setControl(id, c)} />}
      {x && eff != null && (
        <div className="box dark">
          <span style={{ fontSize: 11.5, color: C.mute }}>Energisation year</span>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {derived.onMain ? (
              <b className="mono" style={{ fontSize: 15 }}>{eff}</b>
            ) : (
              <Stepper value={eff} label="energisation year" onDec={() => void actions.setSchedule(id, clampYear(plan, eff - 1))} onInc={() => void actions.setSchedule(id, clampYear(plan, eff + 1))} />
            )}
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
          <span style={{ fontSize: 11, fontWeight: 600, color: C.amber }}>{x.status === "Rejected" ? "Not assessed: the application to complete" : "Binding constraint"}</span>
          <span style={{ fontSize: 12, color: C.amberInk, lineHeight: 1.45 }}>{nameElements(x.reason.why, derived.ix)}</span>
          <span style={{ fontSize: 11.5, color: C.ink2, lineHeight: 1.45 }}>{nameElements(x.reason.action, derived.ix)}</span>
          {x.status === "Deferred" && (
            <button className="btn warn sq" style={{ alignSelf: "flex-start" }} onClick={() => void actions.askAbout(`How could ${id} connect? What would it take?`)}>
              <Sparkle size={13} weight="fill" />
              Ask the agents how it could connect
            </button>
          )}
          {x.status === "Rejected" && (
            <button className="btn warn sq" style={{ alignSelf: "flex-start" }} onClick={() => void actions.askAbout(`${id} can't be assessed (${x.reason?.why ?? "its application is incomplete"}). What is missing, and what would you propose to complete it?`)}>
              <Sparkle size={13} weight="fill" />
              Ask the agents to complete it
            </button>
          )}
        </div>
      )}
    </div>
  );
}

const SEASONS: Season[] = ["Spring", "Summer", "Autumn", "Winter"];
const WEEKS = [2, 4, 6, 8];

function ElementCard({ planner, layout, plan, sel }: CardProps & { sel: ElementSel }) {
  const { s, actions, derived } = planner;
  const { ix } = derived;
  if (!ix) return null;
  const info = elementInfo(sel, ix, derived.yr, s.year);
  if (!info) return null;
  const d = s.maintDraft;
  const windows = s.outages.filter((o) => o.element_kind === sel.kind && o.element_id === String(sel.id));
  const repowered = repoweredNotes(sel, s.outages, s.year);
  const ctx = { result: s.result, ix, outages: s.outages, queue: derived.q };
  const Icon = sel.kind === "line" ? LineSegment : Intersect;
  return (
    <div className="detail glass" style={{ ...cardPos(planner, layout), width: 308, borderColor: "rgba(255,255,255,0.16)" }}>
      <CardHead
        icon={sel.kind === "gen" ? <TechIcon tech={ix.gen.get(sel.id)?.technology} size={18} color={C.lineHigh} /> : <Icon size={18} color={C.lineHigh} />}
        iconBg="rgba(255,255,255,0.08)"
        title={info.name}
        sub={info.kindLabel}
        onClose={() => actions.select(null)}
      />
      <div className="kv">
        <span>Rating</span><span className="mono">{info.rating}</span>
        <span>{info.loadLabel}</span><span className="mono" style={{ color: info.loadPct != null ? loadColor(info.loadPct) : C.ink }}>{info.load}</span>
      </div>
      {repowered.map((t) => (
        <span key={t} className="repowered">{t}</span>
      ))}
      {windows.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 600 }}>Scheduled on {derived.onMain ? "main" : derived.branch?.name}</span>
          {windows.map((o) => {
            const view = windowView(o, ctx);
            return (
              <div key={o.outage_id} className="mrow">
                <Wrench size={13} color={verdictColor(view.verdict) ?? C.lineHigh} />
                <span className="ellipsis" style={{ fontSize: 12 }}>{outageLine(o)}</span>
                <RemoveWindow onMain={derived.onMain} onRemove={() => void actions.removeOutage(o.outage_id)} />
                <span className="wdetail">
                  <VerdictChip view={view} />
                  <WindowDetail view={view} />
                </span>
              </div>
            );
          })}
        </div>
      )}
      <div className="box dark" style={{ gap: 10, padding: 12 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>Schedule works</span>
        <div className="form-row">
          <span className="lbl">Work</span>
          <div className="opts">
            {WORKS.map((w) => (
              <button key={w} className={`pill-opt${d.work === w ? " on" : ""}`} onClick={() => actions.setDraft({ work: w })}>{WORK_UI[w].label}</button>
            ))}
          </div>
        </div>
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
          <Stepper small value={d.year} label="year" onDec={() => actions.setDraft({ year: clampYear(plan, d.year - 1) })} onInc={() => actions.setDraft({ year: clampYear(plan, d.year + 1) })} />
        </div>
        <div className="form-row">
          <span className="lbl">Duration</span>
          <div className="opts">
            {WEEKS.map((w) => (
              <button key={w} className={`pill-opt${d.weeks === w ? " on" : ""}`} onClick={() => actions.setDraft({ weeks: w })}>{w} weeks</button>
            ))}
          </div>
        </div>
        {d.work === "maintenance" && (
          <div className="form-row">
            <span className="lbl">Type</span>
            <div className="opts">
              <button className={`pill-opt${d.kind === "outage" ? " on" : ""}`} onClick={() => actions.setDraft({ kind: "outage" })}>Full outage</button>
              <button className={`pill-opt${d.kind === "derate" ? " on" : ""}`} onClick={() => actions.setDraft({ kind: "derate" })}>Derate to {DERATE_PCT}%</button>
            </div>
          </div>
        )}
        {d.work === "repowering" && (
          <div className="sub-opts">
            <div className="form-row">
              <span className="lbl">Comes back with</span>
              <div className="opts">
                <button className={`pill-opt${d.repower === "uprate" ? " on" : ""}`} onClick={() => actions.setDraft({ repower: "uprate" })}>Uprate</button>
                <button className={`pill-opt${d.repower === "add_parallel" ? " on" : ""}`} onClick={() => actions.setDraft({ repower: "add_parallel" })}>{PARALLEL_LABEL[sel.kind]}</button>
              </div>
            </div>
            {d.repower === "uprate" && (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 11, color: C.mute, flex: 1 }}>{sel.kind === "gen" ? "Export rating" : "Rating"} factor</span>
                <Stepper
                  small
                  value={`${d.factor}x`}
                  label="factor"
                  words={["Lower", "Higher"]}
                  onDec={() => actions.setDraft({ factor: stepFactor(d.factor, -1) })}
                  onInc={() => actions.setDraft({ factor: stepFactor(d.factor, 1) })}
                />
              </div>
            )}
          </div>
        )}
        {d.work === "replacement" && <span className="work-note">Back like-for-like after the window.</span>}
        <span style={{ fontSize: 11, color: C.mute2, lineHeight: 1.4 }}>{draftHint(d, sel.kind, plan)}</span>
        <button className="btn primary sm" style={{ justifyContent: "center", height: 34 }} onClick={() => void actions.scheduleOutage(sel)}>
          <Wrench size={13} weight="bold" />
          {derived.onMain ? "Open a branch and schedule" : `Schedule on ${derived.branch?.name}`}
        </button>
      </div>
    </div>
  );
}
