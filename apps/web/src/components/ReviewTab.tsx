// Review: the branch against main as a consequence diff (the four 2030/2035 tiles, the network effect
// in the viewed year with a year picker tied to the planner's year, the planned works on main vs the
// branch, what changed), the reinforcements proposed on it, the merge gate, the reviewer agent's comment
// (the gate restated, prepared for engineer review), then Merge into main or Discard. main has nothing to review.

import { ArrowRight, ArrowsClockwise, Check, GitMerge, type Icon, LockSimple, Minus, Plus, Prohibit, ShieldCheck, ShieldWarning, Sparkle, Trash, Warning, Wrench } from "@phosphor-icons/react";
import { useState } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { type ModelIndex, lineName, nameElements, trafoName } from "../lib/derive";
import { type GateState, type GateView, gateText, gateTitle } from "../lib/gate";
import {
  type Namers,
  type Tone,
  VERDICT,
  WORK_CHANGE,
  flaggedYears,
  mergeChangeCount,
  outageTitle,
  verdictOnBranch,
  verdictOnMain,
  workTitle,
  worksInOrder,
  yearEffect,
} from "../lib/diff";
import { C, PLAN_YEARS, ST, fmtMw, profileOf, signed, tint } from "../theme";
import type { AgentsStatus, Diff, MergeCheck, OnMerge, Review, ReviewVerdict, Status, WorkDelta, YearDelta } from "../types";
import { DiffTile } from "./ui";

export type ReviewTabPlanner = PlannerSlice<
  "agents" | "branches" | "diff" | "mergeCheck" | "outages" | "reinforcements" | "reviews" | "year",
  "createBranch" | "discardBranch" | "mergeBranch" | "removeReinforcement" | "setYear",
  "branch" | "gate" | "hue" | "ix" | "mainId" | "onMain" | "reviewStale" | "yearDelta"
>;

const statusLabel = (st: Status | null, year?: number | null): string =>
  st == null ? "not on main" : st === "Phase1" || st === "Phase2" ? `${ST[st].label}${year ? ` · ${year}` : ""}` : ST[st].label;

export function ReviewTab({ planner }: { planner: ReviewTabPlanner }) {
  const { s, actions, derived } = planner;
  const { branch, hue, ix, gate } = derived;
  const [confirm, setConfirm] = useState(false); // the warnings step before "Merge anyway"
  if (derived.onMain)
    return (
      <div className="scroll" style={{ padding: "4px 14px 16px", gap: 12 }}>
        <div className="empty" style={{ padding: 18, gap: 10 }}>
          <LockSimple size={20} color={C.mute} />
          <b style={{ fontSize: 13 }}>main has nothing to review</b>
          <span>It is the plan of record. Open a branch, add projects or change the demand profile, then compare it here.</span>
          <button className="btn" style={{ borderColor: "rgba(124,227,255,0.45)", background: "rgba(124,227,255,0.12)", color: C.accent }} onClick={() => void actions.createBranch()}>
            New branch
          </button>
        </div>
      </div>
    );

  const main = s.branches.find((b) => b.branch_id === derived.mainId);
  const mismatch = main && branch && main.scenario !== branch.scenario;
  const d = s.diff;
  const open = branch?.status === "open";
  const canMerge = gate.state === "ready" || gate.state === "warnings";
  const onMerge = () => {
    if (gate.state === "warnings" && !confirm) {
      setConfirm(true);
      return;
    }
    setConfirm(false);
    void actions.mergeBranch({ acknowledge: gate.state === "warnings" });
  };
  const names: Namers = {
    line: (id) => (ix ? lineName(ix, id) : `Line ${id}`),
    trafo: (id) => (ix ? trafoName(ix, id) : `Transformer ${id}`),
  };
  return (
    <div className="scroll" style={{ padding: "4px 14px 16px", gap: 12 }}>
      <div className="mono" style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
        <span style={{ color: C.mute }}>main</span>
        <ArrowRight size={12} color={C.mute2} />
        <span style={{ color: hue, fontWeight: 600 }}>{branch?.name}</span>
      </div>
      {mismatch && (
        <div className="notice amber">
          main is tested on {profileOf(main!.scenario).label} and this branch on {profileOf(branch!.scenario).label}. Part of the difference below comes from demand, not from
          the projects you added.
        </div>
      )}
      {!d ? (
        <span className="mute" style={{ fontSize: 12 }}>Comparing with main…</span>
      ) : (
        <>
          {d.narration && <span style={{ fontSize: 12.5, lineHeight: 1.5, color: C.ink3 }}>{d.narration}</span>}
          <Tiles d={d} />
          <YearPick year={s.year} flagged={flaggedYears(d)} solved={(y) => !!d.years?.[String(y)]} onPick={actions.setYear} />
          <NetworkEffect yd={derived.yearDelta} year={s.year} names={names} />
          <Works works={d.works ?? []} year={s.year} title={(w) => workTitle(w, s.outages.find((o) => o.outage_id === w.outage_id), ix)} onPick={actions.setYear} />
          <Changed d={d} name={(t) => nameElements(t, ix)} />
          <MergeChanges m={d.on_merge} hue={hue} title={(o) => outageTitle(o, ix)} />
        </>
      )}
      {s.reinforcements.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>Proposed reinforcements</span>
          {s.reinforcements.map((r) => (
            <div key={r.reinforcement_id} className="mrow">
              <GitMerge size={13} color={hue} />
              <span className="ellipsis" style={{ fontSize: 12 }}>{r.label || `${r.action} ${r.kind} ${r.element_id}`}</span>
              <button className="icon-btn sm" onClick={() => void actions.removeReinforcement(r.reinforcement_id)} title="Remove" aria-label="Remove reinforcement" disabled={!open}>
                <Trash size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
      <MergeReadiness mc={s.mergeCheck} gate={gate} ix={ix} />
      <Reviews reviews={s.reviews} stale={derived.reviewStale} agents={s.agents} ix={ix} />
      {confirm && s.mergeCheck && (
        <div className="gate-card" style={{ borderColor: "rgba(255,195,107,0.4)" }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>Merge with these warnings?</span>
          {s.mergeCheck.verdict.warnings.map((w, i) => (
            <span key={i} className="gate-row warning">
              <Warning size={12} style={{ flex: "none", marginTop: 2 }} />
              <span>{gateText(w, ix)}</span>
            </span>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, paddingTop: 4 }}>
        <button className="btn solid-hue grow" onClick={onMerge} disabled={!canMerge} title={gate.headline} data-gate={gate.state}>
          <GitMerge size={14} weight="bold" />
          {confirm ? "Merge anyway" : "Merge into main"}
        </button>
        {confirm ? (
          <button className="btn" onClick={() => setConfirm(false)}>
            Cancel
          </button>
        ) : (
          <button className="btn danger" onClick={() => void actions.discardBranch()} disabled={!open}>
            Discard
          </button>
        )}
      </div>
      {!open && <span className="mute" style={{ fontSize: 11.5 }}>This branch is {branch?.status}. Open a new one to propose more.</span>}
    </div>
  );
}

const GATE_ICON: Record<GateState, Icon> = { closed: LockSimple, checking: ArrowsClockwise, stale: ArrowsClockwise, blocked: Prohibit, warnings: ShieldWarning, ready: ShieldCheck };
const GATE_TONE: Record<GateState, "bad" | "warn" | "good" | "neutral"> = { closed: "neutral", checking: "neutral", stale: "bad", blocked: "bad", warnings: "warn", ready: "good" };

/** The merge gate: may this branch become the plan of record? Blockers, warnings, and what main already carries. */
function MergeReadiness({ mc, gate, ix }: { mc: MergeCheck | null; gate: GateView; ix: ModelIndex | null }) {
  const I = GATE_ICON[gate.state];
  const v = gate.state === "stale" || gate.state === "checking" || gate.state === "closed" ? null : (mc?.verdict ?? null);
  const row = (f: Parameters<typeof gateText>[0], cls: string, i: number) => (
    <span key={`${cls}${i}`} className={`gate-row ${cls}`}>
      <Warning size={12} style={{ flex: "none", marginTop: 2 }} />
      <span>
        <b>{gateTitle(f.kind)}</b> · {gateText(f, ix)}
      </span>
    </span>
  );
  return (
    <div className="gate-card">
      <span className="gate-state" data-tone={GATE_TONE[gate.state]}>
        <I size={14} weight="bold" />
        {gate.headline}
      </span>
      {v?.blockers.map((b, i) => row(b, "blocker", i))}
      {v?.warnings.map((w, i) => row(w, "warning", i))}
      {v && v.context.length > 0 && (
        <details className="gate-context">
          <summary>Already on {mc?.into ?? "main"}: {v.context.length} {v.context.length === 1 ? "item" : "items"} this branch inherits, not held against it</summary>
          {v.context.map((c, i) => (
            <span key={i} className="gate-row info">{gateText(c, ix)}</span>
          ))}
        </details>
      )}
      {v && <span className="mute" style={{ fontSize: 10.5 }}>Judged on {v.years_compared.length} plan years against {mc?.into ?? "main"}; every figure is the engine's.</span>}
    </div>
  );
}

const REVIEW_LABEL: Record<ReviewVerdict, string> = { blocked: "blocked", mergeable_with_warnings: "mergeable with warnings", mergeable: "mergeable" };
const REVIEW_TONE: Record<ReviewVerdict, { background: string; color: string }> = {
  blocked: { background: "rgba(255,107,107,0.16)", color: C.redInk },
  mergeable_with_warnings: { background: "rgba(255,195,107,0.16)", color: C.amberInk },
  mergeable: { background: "rgba(94,230,168,0.16)", color: C.greenInk },
};

/** The reviewer agent's comment on the branch's current run, like a PR bot: the gate restated, prepared for engineer review. */
function Reviews({ reviews, stale, agents, ix }: { reviews: Review[]; stale: boolean; agents: AgentsStatus | null; ix: ModelIndex | null }) {
  const rv = reviews.find((r) => r.status === "prepared_for_review") ?? null;
  const off = !agents || agents.status === "off";
  const restate = (b: Review["blockers"][number], cls: string, i: number) => (
    <span key={`${cls}${i}`} className={`gate-row ${cls}`}>
      <Warning size={12} style={{ flex: "none", marginTop: 2 }} />
      <span>
        <b>{gateTitle(b.kind)}</b> · {nameElements(b.restated, ix)}
      </span>
    </span>
  );
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>Review</span>
      {off ? (
        <span className="mute" style={{ fontSize: 11.5, lineHeight: 1.45 }}>No reviewer: the agents need OPENROUTER_API_KEY on the API. The gate above decides either way.</span>
      ) : !rv ? (
        <span className="mute" style={{ fontSize: 11.5, lineHeight: 1.45 }}>
          {agents.status === "paused" ? "The agents are paused; no review comes until they resume." : "Waiting for the reviewer: it comments a few seconds after every run."}
        </span>
      ) : (
        <div className="review-card">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Sparkle size={13} color={C.accent} weight="fill" />
            <span style={{ fontSize: 12.5, fontWeight: 600, flex: 1, minWidth: 0 }}>Prepared for engineer review</span>
            <span className="chip" style={REVIEW_TONE[rv.verdict]}>{REVIEW_LABEL[rv.verdict]}</span>
          </div>
          {stale && <div className="notice amber">Of an earlier run: the reviewer comments again once the current run has finished.</div>}
          <span className="body">{nameElements(rv.body, ix)}</span>
          {rv.blockers.map((b, i) => restate(b, "blocker", i))}
          {rv.warnings.map((w, i) => restate(w, "warning", i))}
          {rv.not_studied.length > 0 && <span className="mute" style={{ fontSize: 11, lineHeight: 1.4 }}>Not studied: {rv.not_studied.join("; ")}</span>}
          <span className="evidence-line">run {rv.run_key.slice(0, 10)} · {rv.created_at.slice(0, 16).replace("T", " ")} · the figures are the gate's, the words the reviewer's</span>
        </div>
      )}
    </div>
  );
}

/** What merging replaces on main: the planned works and reinforcements it adds, and those it removes. */
function MergeChanges({ m, hue, title }: { m: OnMerge | undefined; hue: string; title: (o: OnMerge["works_added"][number]) => string }) {
  if (!m || !mergeChangeCount(m)) return null;
  const rows = [
    ...m.works_added.map((o) => ({ key: o.outage_id, add: true, text: `${title(o)} · ${o.season} ${o.year}` })),
    ...m.works_removed.map((o) => ({ key: o.outage_id, add: false, text: `${title(o)} · ${o.season} ${o.year}` })),
    ...m.reinforcements_added.map((r) => ({ key: r.reinforcement_id, add: true, text: r.label || `${r.action} ${r.kind} ${r.element_id}` })),
    ...m.reinforcements_removed.map((r) => ({ key: r.reinforcement_id, add: false, text: r.label || `${r.action} ${r.kind} ${r.element_id}` })),
  ];
  return (
    <div className="merge-changes">
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>Merging changes on main</span>
      <span className="mute" style={{ fontSize: 11.5 }}>Main takes this branch's planned works and reinforcements, so it gains and loses these.</span>
      {rows.map((r) => (
        <div key={r.key} className="mrow">
          {r.add ? <Plus size={12} color={hue} weight="bold" /> : <Minus size={12} color={C.redInk} weight="bold" />}
          <span className="ellipsis" style={{ fontSize: 12, color: r.add ? C.ink : C.mute }}>{r.text}</span>
        </div>
      ))}
    </div>
  );
}

function Tiles({ d }: { d: Diff }) {
  const h = d.headline;
  const tile = (label: string, base: number, head: number, moreIsGood: boolean) => {
    const delta = head - base;
    const c = delta === 0 ? C.mute : delta > 0 === moreIsGood ? C.greenInk : C.redInk;
    return <DiffTile key={label} label={label} base={fmtMw(base)} head={fmtMw(head)} delta={delta === 0 ? "0" : signed(delta)} c={c} />;
  };
  return (
    <div className="tiles">
      {tile("MW by 2030", h.mw_2030_base ?? 0, h.mw_2030_head ?? 0, true)}
      {tile("MW by 2035", h.mw_2035_base ?? 0, h.mw_2035_head ?? 0, true)}
      {tile("Connected", h.n_connected_base ?? 0, h.n_connected_head ?? 0, true)}
      {tile("Deferred", h.n_deferred_base ?? 0, h.n_deferred_head ?? 0, false)}
    </div>
  );
}

const TONE_INK: Record<Tone | "warn", string> = { bad: C.redInk, good: C.greenInk, neutral: C.ink2, warn: C.amberInk };
const MAX_EFFECTS = 10;

function ToneIcon({ tone }: { tone: Tone }) {
  return tone === "bad" ? <Warning size={12} /> : tone === "good" ? <Check size={12} /> : <ArrowRight size={12} />;
}

/** One chip per plan year, tied to the planner's year (the map and the timeline follow it). */
function YearPick({ year, flagged, solved, onPick }: { year: number; flagged: Set<number>; solved: (y: number) => boolean; onPick: (y: number) => void }) {
  return (
    <div className="year-pick" role="group" aria-label="Year to compare">
      {PLAN_YEARS.map((y) => (
        <button key={y} className={y === year ? "on" : ""} onClick={() => onPick(y)} disabled={!solved(y)} aria-pressed={y === year}
          title={flagged.has(y) ? `${y}: something gets worse on this branch` : String(y)}>
          {y}
          {flagged.has(y) && <span className="flag" />}
        </button>
      ))}
    </div>
  );
}

function NetworkEffect({ yd, year, names }: { yd: YearDelta | null; year: number; names: Namers }) {
  const items = yd ? yearEffect(yd, names) : [];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>Network effect in {year}</span>
      <div className="well" style={{ display: "flex", flexDirection: "column", gap: 6, padding: "11px 12px", fontSize: 12, lineHeight: 1.45 }}>
        {!yd ? (
          <span className="mute">{year} is not solved on both plans yet. Re-run the branch to compare it.</span>
        ) : items.length ? (
          items.slice(0, MAX_EFFECTS).map((x, i) => (
            <span key={i} className="effect" style={{ color: TONE_INK[x.tone] }}>
              <ToneIcon tone={x.tone} />
              {x.text}
            </span>
          ))
        ) : (
          <span className="mute">No material change to loadings, voltages, GSP export or N-1 in {year}.</span>
        )}
      </div>
    </div>
  );
}

/** The branch's planned works: each window's verdict on main's plan and on the branch's, and what that means. */
function Works({ works, year, title, onPick }: { works: WorkDelta[]; year: number; title: (w: WorkDelta) => string; onPick: (y: number) => void }) {
  if (!works.length) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>Planned works</span>
      {worksInOrder(works, year).map((w) => {
        const ch = WORK_CHANGE[w.change];
        const vm = w.verdict_on_main ? VERDICT[w.verdict_on_main].tone : "neutral";
        const vb = VERDICT[w.verdict_on_branch]?.tone ?? "neutral";
        return (
          <button key={w.outage_id} className={`work-row${w.year === year ? " now" : ""}`} onClick={() => onPick(w.year)} title={w.message}>
            <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, minWidth: 0 }}>
              <Wrench size={12} color={C.mute} style={{ flex: "none" }} />
              <span className="ellipsis" style={{ fontWeight: 600 }}>{title(w)}</span>
              <span className="mono" style={{ marginLeft: "auto", fontSize: 11, color: C.mute }}>{w.year}</span>
            </span>
            <span className="verdicts">
              <span style={{ color: C.mute }}>main</span>
              <span className="chip" style={{ background: tint(TONE_INK[vm], "1f"), color: TONE_INK[vm] }}>{verdictOnMain(w)}</span>
              <ArrowRight size={11} color={C.mute2} />
              <span style={{ color: C.mute }}>branch</span>
              <span className="chip" style={{ background: tint(TONE_INK[vb], "1f"), color: TONE_INK[vb] }}>{verdictOnBranch(w)}</span>
            </span>
            <span className="effect" style={{ fontSize: 11.5, lineHeight: 1.4, color: TONE_INK[ch.tone] }}>
              <ToneIcon tone={ch.tone} />
              {w.consequence}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function Changed({ d, name }: { d: Diff; name: (t: string) => string }) {
  const movers = d.projects.filter((p) => p.change !== "unchanged");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>What changed</span>
      {!movers.length && <span className="mute" style={{ fontSize: 12 }}>No project moved.</span>}
      {movers.map((p) => {
        const to = p.head_status;
        const c = to ? ST[to].c : C.mute;
        return (
          <div key={p.request_id} className="mover">
            <span className="mono" style={{ fontSize: 12.5, fontWeight: 600 }}>{p.request_id}</span>
            <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, whiteSpace: "nowrap", minWidth: 0 }}>
              <span style={{ padding: "1px 7px", borderRadius: 999, background: "rgba(255,255,255,0.06)", color: C.mute }}>{statusLabel(p.base_status)}</span>
              <ArrowRight size={11} color={C.mute2} />
              <span style={{ padding: "1px 7px", borderRadius: 999, background: tint(c, "22"), color: c }}>{to ? statusLabel(to) : "dropped"}</span>
            </span>
            <span className="mono" style={{ fontSize: 11.5, color: C.mute }}>{fmtMw(p.rating_mw)} MW</span>
            <span className="ellipsis" style={{ gridColumn: "2 / -1", fontSize: 11, color: C.mute }}>
              {p.head_reason ? name(p.head_reason.short) : p.rank_delta ? `rank ${p.rank_delta > 0 ? "down" : "up"} ${Math.abs(p.rank_delta)}` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}
