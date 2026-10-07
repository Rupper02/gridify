// Review: the branch against main as a consequence diff (the four tiles: MW by each phase's horizon, connected,
// deferred; the network effect
// in the viewed year with a year picker tied to the planner's year, the planned works on main vs the
// branch, what changed), the reinforcements proposed on it, the merge gate, the engineer's note on the run (one
// model call restating the engine's digest, written a few seconds after every run), then Merge into its parent (main,
// or the branch it was opened from) or Discard. A branch main moved past is
// offered a rebase first (RebaseCard). main has nothing to review, but its run has a note too.

import { ArrowRight, ArrowsClockwise, Check, GitMerge, type Icon, LockSimple, Minus, NotePencil, Plus, Prohibit, ShieldCheck, ShieldWarning, Trash, Warning, Wrench } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { useNow } from "../hooks/useNow";
import { type ModelIndex, lineName, nameElements, trafoName } from "../lib/derive";
import { type GateState, type GateView, gateText, gateTitle } from "../lib/gate";
import {
  type Namers,
  type Tone,
  flaggedYears,
  mergeChangeCount,
  outageTitle,
  reinforcementLabel,
  verdictOnBranch,
  verdictOnMain,
  workTitle,
  workTone,
  worksInOrder,
  yearEffect,
} from "../lib/diff";
import { VERDICTS } from "../lib/maintenance";
import type { Plan } from "../lib/plan";
import { type NoteState, flagFigure, noteState, runElapsed } from "../lib/trace";
import { C, ST, fmtMw, profileLabel, signed, tint } from "../theme";
import type { AgentRun, AgentsStatus, Diff, MergeCheck, OnMerge, RunNote, Status, WorkDelta, YearDelta } from "../types";
import { RebaseCard } from "./RebaseCard";
import { AgentText, DiffTile } from "./ui";

export type ReviewTabPlanner = PlannerSlice<
  "activeBranch" | "agentRuns" | "agents" | "branches" | "diff" | "diffError" | "mergeCheck" | "note" | "outages" | "plan" | "reinforcements" | "result" | "year",
  "createBranch" | "discardBranch" | "loadAgentRuns" | "loadNote" | "mergeBranch" | "previewRebase" | "rebaseBranch" | "refreshDiff" | "refreshMergeCheck" | "removeReinforcement" | "run" | "setYear",
  "branch" | "gate" | "hue" | "ix" | "onMain" | "parent" | "run" | "yearDelta"
>;

const statusLabel = (st: Status | null, parent: string): string => (st == null ? `not on ${parent}` : ST[st].label);

export function ReviewTab({ planner }: { planner: ReviewTabPlanner }) {
  const { s, actions, derived } = planner;
  const { branch, hue, ix, gate, parent } = derived;
  const [confirm, setConfirm] = useState(false); // the warnings step before "Merge anyway"
  // the note, and whether one is being written (a digest run in the runs list): read when the tab shows a branch or
  // main (the status poll refreshes both while it does)
  useEffect(() => {
    void actions.loadAgentRuns();
    if (s.activeBranch) void actions.loadNote(s.activeBranch);
  }, [actions, s.activeBranch]);
  const note = <NoteCard note={s.note} runKey={s.result?.run_key} runs={s.agentRuns} branchId={s.activeBranch} agents={s.agents} ix={ix} />;
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
        {note}
      </div>
    );

  const base = s.branches.find((b) => b.branch_id === branch?.parent_id); // what it is judged against and merges into
  const mismatch = base && branch && base.scenario !== branch.scenario;
  const { diff: d, plan } = s;
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
        <span style={{ color: C.mute }}>{parent}</span>
        <ArrowRight size={12} color={C.mute2} />
        <span style={{ color: hue, fontWeight: 600 }}>{branch?.name}</span>
      </div>
      {branch && open && <RebaseCard key={branch.branch_id} branch={branch} parent={parent} name={(t) => nameElements(t, ix)} onPreview={actions.previewRebase} onRebase={actions.rebaseBranch} />}
      {mismatch && (
        <div className="notice amber">
          {parent} is tested on {profileLabel(base!.scenario)} and this branch on {profileLabel(branch!.scenario)}. Part of the difference below comes from demand, not from
          the projects you added.
        </div>
      )}
      {!d || !plan ? (
        derived.run.problem ? (
          // the comparison waits for a run that will not come: say so, with the run's own Retry
          <span className="notice amber" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="grow">{derived.run.problem}</span>
            <button className="btn" onClick={() => void actions.run()}>Retry</button>
          </span>
        ) : s.diffError && !derived.run.inProgress ? (
          <span className="notice amber" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="grow">Could not compare with {parent}: {s.diffError}</span>
            <button className="btn" onClick={() => branch && void actions.refreshDiff(branch.branch_id)}>Retry</button>
          </span>
        ) : (
          <span className="mute" style={{ fontSize: 12 }}>
            {derived.run.inProgress ? `The comparison with ${parent} appears once every year of this run is solved.` : `Comparing with ${parent}…`}
          </span>
        )
      ) : (
        <>
          <Tiles d={d} plan={plan} />
          <YearPick years={plan.years} year={s.year} flagged={flaggedYears(d)} solved={(y) => !!d.years?.[String(y)]} onPick={actions.setYear} />
          <NetworkEffect yd={derived.yearDelta} year={s.year} names={names} />
          <Works works={d.works ?? []} parent={parent} year={s.year} title={(w) => workTitle(w, s.outages.find((o) => o.outage_id === w.outage_id), ix)} name={(t) => nameElements(t, ix)} onPick={actions.setYear} />
          <Changed d={d} parent={parent} name={(t) => nameElements(t, ix)} />
          <MergeChanges m={d.on_merge} hue={hue} parent={parent} title={(o) => outageTitle(o, ix)} />
        </>
      )}
      {s.reinforcements.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>Proposed reinforcements</span>
          {s.reinforcements.map((r) => (
            <div key={r.reinforcement_id} className="mrow">
              <GitMerge size={13} color={hue} />
              <span className="ellipsis" style={{ fontSize: 12 }}>{reinforcementLabel(r)}</span>
              <button className="icon-btn sm" onClick={() => void actions.removeReinforcement(r.reinforcement_id)} title="Remove" aria-label="Remove reinforcement" disabled={!open}>
                <Trash size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
      <MergeReadiness
        mc={s.mergeCheck}
        gate={gate}
        ix={ix}
        parent={parent}
        onRetry={gate.state === "unfinished" ? () => void actions.run() : () => branch && void actions.refreshMergeCheck(branch.branch_id)}
      />
      {note}
      {confirm && s.mergeCheck && (
        <div className="gate-card" style={{ borderColor: "rgba(255,195,107,0.4)" }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>Merge with these warnings?</span>
          {s.mergeCheck.verdict.warnings.map((w, i) => (
            <GateRow key={i} cls="warning" text={gateText(w, ix)} />
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, paddingTop: 4 }}>
        <button className="btn solid-hue grow" onClick={onMerge} disabled={!canMerge} title={gate.headline} data-gate={gate.state}>
          <GitMerge size={14} weight="bold" />
          {confirm ? "Merge anyway" : `Merge into ${parent}`}
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

/** One line of the gate: a blocker, a warning, with its kind's title. */
function GateRow({ cls, title, text }: { cls: string; title?: string; text: string }) {
  return (
    <span className={`gate-row ${cls}`}>
      <Warning size={12} style={{ flex: "none", marginTop: 2 }} />
      <span>
        {title && <b>{title}</b>}
        {title && " · "}
        {text}
      </span>
    </span>
  );
}

const GATE_ICON: Record<GateState, Icon> = { closed: LockSimple, checking: ArrowsClockwise, unfinished: Warning, failed: Warning, stale: ArrowsClockwise, blocked: Prohibit, warnings: ShieldWarning, ready: ShieldCheck };
const GATE_TONE: Record<GateState, "bad" | "warn" | "good" | "neutral"> = { closed: "neutral", checking: "neutral", unfinished: "warn", failed: "warn", stale: "bad", blocked: "bad", warnings: "warn", ready: "good" };
/** States with no verdict to show: the check is not in, or the result it would judge is not there. */
const NO_VERDICT: GateState[] = ["closed", "checking", "unfinished", "failed", "stale"];

/** The merge gate: may this branch become the plan of record? Blockers, warnings, and what its parent already carries.
 * `onRetry` asks the check again, or runs the branch again when its last run did not finish. */
function MergeReadiness({ mc, gate, ix, parent, onRetry }: { mc: MergeCheck | null; gate: GateView; ix: ModelIndex | null; parent: string; onRetry: () => void }) {
  const I = GATE_ICON[gate.state];
  const v = NO_VERDICT.includes(gate.state) ? null : (mc?.verdict ?? null);
  const row = (f: Parameters<typeof gateText>[0], cls: string, i: number) => <GateRow key={`${cls}${i}`} cls={cls} title={gateTitle(f.kind)} text={gateText(f, ix)} />;
  return (
    <div className="gate-card">
      <span className="gate-state" data-tone={GATE_TONE[gate.state]}>
        <I size={14} weight="bold" />
        {gate.headline}
        {(gate.state === "failed" || gate.state === "unfinished") && (
          <button className="btn" style={{ marginLeft: "auto" }} onClick={onRetry}>
            Retry
          </button>
        )}
      </span>
      {v?.blockers.map((b, i) => row(b, "blocker", i))}
      {v?.warnings.map((w, i) => row(w, "warning", i))}
      {v && v.context.length > 0 && (
        <details className="gate-context">
          <summary>Already on {parent}: {v.context.length} {v.context.length === 1 ? "item" : "items"} this branch inherits, not held against it</summary>
          {v.context.map((c, i) => (
            <span key={i} className="gate-row info">{gateText(c, ix)}</span>
          ))}
        </details>
      )}
      {v && <span className="mute" style={{ fontSize: 10.5 }}>Judged on {v.years_compared.length} plan years against {parent}; every figure is the engine's.</span>}
    </div>
  );
}

/** The state line under the note's title: being written (live elapsed), of an earlier run, none yet; nothing when current. */
function noteLine(ns: NoteState, now: number, agents: AgentsStatus | null): string | null {
  if (ns.kind === "writing") return `Writing the note… (${runElapsed(ns.run, now) ?? "just started"})`;
  if (ns.kind === "earlier") return "The note is for an earlier run; the next run writes a new one.";
  if (ns.kind === "current") return null;
  if (!agents || agents.status === "starting") return "The agents are starting with the API; the note is written a few seconds after a run once they are up.";
  return agents.status === "paused" ? "The agents are paused: the note is written once they resume." : "No note yet: it is written a few seconds after a run.";
}

/** The engineer's note on the branch's run: one model call restating the engine's digest of it (markdown, elements
 * named, no step ids), its flags (figures the digest does not carry) as muted chips, and where it stands. */
function NoteCard({ note, runKey, runs, branchId, agents, ix }: { note: RunNote | null; runKey: string | undefined; runs: AgentRun[]; branchId: string; agents: AgentsStatus | null; ix: ModelIndex | null }) {
  const ns = noteState(note, runKey, runs, branchId);
  const now = useNow(ns.kind === "writing");
  const line = noteLine(ns, now, agents);
  return (
    <div className="note-card">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <NotePencil size={13} color={C.accent} />
        <span style={{ fontSize: 12.5, fontWeight: 600, flex: 1, minWidth: 0 }}>Engineer's note</span>
        {note && <span className="mono" style={{ fontSize: 10.5, color: C.mute2 }}>{note.created_at.slice(0, 16).replace("T", " ")}</span>}
      </div>
      {line && (
        <span className="mute" style={{ fontSize: 11.5, lineHeight: 1.45 }} data-live={ns.kind === "writing" || undefined}>
          {line}
        </span>
      )}
      {note && (
        <>
          <div className="body md">
            <AgentText text={note.body} ix={ix} />
          </div>
          {note.flags.length > 0 && (
            <span className="chips" title="Figures in the note that appear in no tool output">
              {note.flags.map((f, i) => (
                <span key={i} className="chip flag">not in the digest: {flagFigure(f)}</span>
              ))}
            </span>
          )}
          <span className="evidence-line">run {note.run_key.slice(0, 10)} · the figures are the engine's digest, the words the model's</span>
        </>
      )}
    </div>
  );
}

/** What merging replaces on the parent: the planned works and reinforcements it adds, and those it removes. */
function MergeChanges({ m, hue, parent, title }: { m: OnMerge | undefined; hue: string; parent: string; title: (o: OnMerge["works_added"][number]) => string }) {
  if (!m || !mergeChangeCount(m)) return null;
  const rows = [
    ...m.works_added.map((o) => ({ key: o.outage_id, add: true, text: `${title(o)} · ${o.season} ${o.year}` })),
    ...m.works_removed.map((o) => ({ key: o.outage_id, add: false, text: `${title(o)} · ${o.season} ${o.year}` })),
    ...m.reinforcements_added.map((r) => ({ key: r.reinforcement_id, add: true, text: reinforcementLabel(r) })),
    ...m.reinforcements_removed.map((r) => ({ key: r.reinforcement_id, add: false, text: reinforcementLabel(r) })),
  ];
  return (
    <div className="merge-changes">
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>Merging changes on {parent}</span>
      <span className="mute" style={{ fontSize: 11.5 }}>{parent} takes this branch's planned works and reinforcements, so it gains and loses these.</span>
      {rows.map((r) => (
        <div key={r.key} className="mrow">
          {r.add ? <Plus size={12} color={hue} weight="bold" /> : <Minus size={12} color={C.redInk} weight="bold" />}
          <span className="ellipsis" style={{ fontSize: 12, color: r.add ? C.ink : C.mute }}>{r.text}</span>
        </div>
      ))}
    </div>
  );
}

/** The engine's diff names its two phase figures by their horizons (`mw_2030`, `mw_2035`): Phase 1's and Phase 2's. */
function Tiles({ d, plan }: { d: Diff; plan: Plan }) {
  const h = d.headline;
  const tile = (label: string, base: number, head: number, moreIsGood: boolean) => {
    const delta = head - base;
    const c = delta === 0 ? C.mute : delta > 0 === moreIsGood ? C.greenInk : C.redInk;
    return <DiffTile key={label} label={label} base={fmtMw(base)} head={fmtMw(head)} delta={delta === 0 ? "0" : signed(delta)} c={c} />;
  };
  return (
    <div className="tiles">
      {tile(`MW by ${plan.phase1}`, h.mw_2030_base ?? 0, h.mw_2030_head ?? 0, true)}
      {tile(`MW by ${plan.phase2}`, h.mw_2035_base ?? 0, h.mw_2035_head ?? 0, true)}
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
function YearPick({ years, year, flagged, solved, onPick }: { years: number[]; year: number; flagged: Set<number>; solved: (y: number) => boolean; onPick: (y: number) => void }) {
  return (
    <div className="year-pick" role="group" aria-label="Year to compare">
      {years.map((y) => (
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
function Works({ works, parent, year, title, name, onPick }: { works: WorkDelta[]; parent: string; year: number; title: (w: WorkDelta) => string; name: (t: string) => string; onPick: (y: number) => void }) {
  if (!works.length) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>Planned works</span>
      {worksInOrder(works, year).map((w) => {
        const tone = workTone(w);
        const vm = w.verdict_on_main ? VERDICTS[w.verdict_on_main].tone : "neutral";
        const vb = VERDICTS[w.verdict_on_branch]?.tone ?? "neutral";
        return (
          <button key={w.outage_id} className={`work-row${w.year === year ? " now" : ""}`} onClick={() => onPick(w.year)} title={w.message}>
            <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, minWidth: 0 }}>
              <Wrench size={12} color={C.mute} style={{ flex: "none" }} />
              <span className="ellipsis" style={{ fontWeight: 600 }}>{title(w)}</span>
              <span className="mono" style={{ marginLeft: "auto", fontSize: 11, color: C.mute }}>{w.year}</span>
            </span>
            <span className="verdicts">
              <span style={{ color: C.mute }}>{w.on_base ? parent : `${parent} · not scheduled, would be`}</span>
              <span className="chip" style={{ background: tint(TONE_INK[vm], "1f"), color: TONE_INK[vm] }}>{verdictOnMain(w)}</span>
              <ArrowRight size={11} color={C.mute2} />
              <span style={{ color: C.mute }}>branch</span>
              <span className="chip" style={{ background: tint(TONE_INK[vb], "1f"), color: TONE_INK[vb] }}>{verdictOnBranch(w)}</span>
            </span>
            <span className="effect" style={{ fontSize: 11.5, lineHeight: 1.4, color: TONE_INK[tone] }}>
              <ToneIcon tone={tone} />
              {name(w.consequence)}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function Changed({ d, parent, name }: { d: Diff; parent: string; name: (t: string) => string }) {
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
              <span style={{ padding: "1px 7px", borderRadius: 999, background: "rgba(255,255,255,0.06)", color: C.mute }}>{statusLabel(p.base_status, parent)}</span>
              <ArrowRight size={11} color={C.mute2} />
              <span style={{ padding: "1px 7px", borderRadius: 999, background: tint(c, "22"), color: c }}>{to ? statusLabel(to, parent) : "dropped"}</span>
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
