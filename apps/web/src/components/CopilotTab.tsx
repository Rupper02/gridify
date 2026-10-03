// The Copilot's three deterministic chats: New project (a guided intake into the preliminary queue),
// Recommendations (the engine's "what would it take" levers, explained) and Maintenance (a works
// window: the engine studies every season and year and ranks them). The chat asks and phrases
// results; ranking, power flow and every window's verdict are the engine's. The picker that starts
// them, and the free-text "Ask the model" chat, live in AskTab.

import {
  ArrowRight,
  ArrowUp,
  CalendarCheck,
  CheckSquare,
  Database,
  GitBranch,
  Lightbulb,
  Lightning,
  NotePencil,
  Play,
  Plus,
  PlusCircle,
  Sparkle,
  Square,
  Wrench,
} from "@phosphor-icons/react";
import { useEffect, useRef } from "react";

import type { ChatMode, RecMsg } from "../hooks/planner/core";
import type { PlannerSlice } from "../hooks/planner/slice";
import { byStatus, deferredMw, nameElements } from "../lib/derive";
import { draftSlots, question, readinessScore } from "../lib/intake";
import type { ChatMsg } from "../lib/intake";
import { VERDICT, maintQuestion, maintSlots, windowLine } from "../lib/maintCopilot";
import type { MaintMsg } from "../lib/maintCopilot";
import { leverConnects, leverFrees, leverTryable, recsQuickReplies } from "../lib/recs";
import type { Layout } from "../lib/layout";
import { C, fmtMw } from "../theme";
import type { Suggestion, WindowOption } from "../types";
import { intakeCtx, maintCtx } from "../hooks/planner/useCopilot";

export type CopilotTabPlanner = PlannerSlice<
  "activeBranch" | "boundary" | "branches" | "chat" | "maxMw" | "model" | "result" | "running" | "sel" | "year",
  | "addPrelim" | "anotherProject" | "applyLever" | "evidenceDone" | "newChat" | "resume" | "runFromChat" | "scheduleWindow" | "send"
  | "setInput" | "startMaintChat" | "startProject" | "startRecs" | "toggleEvidence",
  "branch" | "hue" | "ix" | "onMain" | "profile" | "q" | "resultProfile"
>;

/** Maintenance: neutral silver ink (the design palette's ink2). */
export const MAINT = { c: C.ink2, bg: "rgba(201,214,232,0.12)", bd: "rgba(201,214,232,0.4)" };
/** The chat modes as the picker and the chat header name them (typed registries: a new mode must appear in each). */
export const MODE_TITLE: Record<ChatMode, string> = { ask: "Ask the model", project: "New project", recs: "Recommendations", maint: "Maintenance" };
export const MODE_ICON: Record<ChatMode, typeof PlusCircle> = { ask: Sparkle, project: PlusCircle, recs: Lightbulb, maint: Wrench };
const MODE_COLOR: Record<ChatMode, string> = { ask: C.accent, project: C.accent, recs: C.amberInk, maint: MAINT.c };
const TONE = {
  ok: { background: "rgba(94,230,168,0.16)", color: C.greenInk },
  warn: { background: "rgba(255,195,107,0.16)", color: C.amberInk },
  bad: { background: "rgba(255,107,107,0.16)", color: C.redInk },
} as const;

export function CopilotChat({ planner, layout }: { planner: CopilotTabPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const chat = s.chat;
  const mode = chat.mode ?? "project";
  const isRecs = mode === "recs";
  const isMaint = mode === "maint";
  const it = isMaint ? null : chat.intake;
  const mt = isMaint ? chat.maint : null;
  const listRef = useRef<HTMLDivElement>(null);
  const msgs: (ChatMsg | RecMsg | MaintMsg)[] = isRecs ? chat.recs : isMaint ? (mt?.messages ?? []) : (it?.messages ?? []);
  const lastText = msgs[msgs.length - 1]?.text;
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs.length, lastText]);

  const target = derived.onMain ? (isRecs ? "main" : "a new branch") : (derived.branch?.name ?? "");
  const df = byStatus(derived.q, "Deferred");
  const ctx = intakeCtx(s);
  const q = it && !isRecs && it.step !== "done" ? question(it, ctx) : null;
  const mq = mt ? maintQuestion(mt, maintCtx(s)) : null;
  const ModeIcon = MODE_ICON[mode];
  const modeColor = MODE_COLOR[mode];

  // quick replies for the mode and step
  let quick: { label: string; on?: boolean; go?: boolean; icon?: "check" | "box" | "plus" | "next"; pick: () => void }[] = [];
  if (isRecs) quick = recsQuickReplies(derived.q).map((l) => ({ label: l, pick: () => actions.send(l) }));
  else if (mt && mq?.opts.length) quick = mq.opts.map((o) => ({ label: o, pick: () => actions.send(o) }));
  else if (mt && (mt.step === "results" || mt.step === "done")) quick = [{ label: "Plan another work", icon: "plus", pick: actions.startMaintChat }];
  else if (q?.multi && it)
    quick = [
      ...q.multi.map((l) => ({ label: l, on: it.readySel.includes(l), icon: it.readySel.includes(l) ? ("check" as const) : ("box" as const), pick: () => actions.toggleEvidence(l) })),
      { label: `Done · ${Math.round(readinessScore(it.readySel) * 100)}%`, go: true, icon: "next" as const, pick: actions.evidenceDone },
    ];
  else if (q) quick = q.opts.map((o) => ({ label: o, pick: () => actions.send(o) }));
  else if (it?.step === "done") quick = [{ label: "Start another project", icon: "plus", pick: actions.anotherProject }];

  const slots: { key: string; label: string; value: string; current: boolean }[] = mt ? maintSlots(mt) : it && !isRecs ? draftSlots(it) : [];
  return (
    <div className="chat-wrap">
      <div className="chat-head">
        <div style={{ display: "flex", alignItems: "center", gap: 8, whiteSpace: "nowrap", minWidth: 0, overflow: "hidden" }}>
          <ModeIcon size={15} color={modeColor} />
          <span style={{ fontSize: 13, fontWeight: 600, flex: "none" }}>{MODE_TITLE[mode]}</span>
          {layout.wide && <ArrowRight size={12} color={C.mute2} />}
          {layout.wide && <span style={{ fontSize: 12, color: C.mute, flex: "none" }}>{isRecs ? "on" : isMaint ? "scheduled on" : "queue on"}</span>}
          <span className="mono ellipsis" style={{ fontSize: 12, fontWeight: 600, color: derived.onMain ? C.mute : derived.hue, minWidth: 40, flex: "1 1 auto" }}>{target}</span>
          <button className="btn" style={{ height: 28, fontSize: 11.5, marginLeft: "auto", flex: "none" }} onClick={actions.newChat} title="New chat">
            <NotePencil size={13} />
            {layout.wide && "New chat"}
          </button>
        </div>
        {isRecs && (
          <div className="well ellipsis" style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", fontSize: 11.5, color: C.ink2, borderRadius: 10 }}>
            <Database size={13} color={C.mute} style={{ flex: "none" }} />
            <span className="ellipsis">
              {s.result ? `Last run · ${derived.resultProfile.label} demand · ${df.length} deferred · ${fmtMw(deferredMw(derived.q))} MW` : "No run yet"}
            </span>
          </div>
        )}
        {!isRecs && !layout.compactH && (
          <div className="slots">
            {slots.map((x) => (
              <div key={x.key} className={`slot${x.current ? " cur" : ""}`}>
                <span>{x.label}</span>
                <b style={{ color: x.value === "–" ? C.mute2 : x.current && x.value === "asking…" ? C.accent : C.ink }}>{x.value}</b>
              </div>
            ))}
          </div>
        )}
        {!isRecs && layout.compactH && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {slots.filter((x) => x.value !== "–").map((x) => (
              <span key={x.key} className={`slot-pill${x.current ? " cur" : ""}`}>
                {x.label}
                <b style={{ color: x.current ? C.accent : C.ink }}>{x.value}</b>
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="msgs" ref={listRef} aria-live="polite">
        {msgs.map((m, i) =>
          m.user ? (
            <div key={i} className="bubble-user">{m.text}</div>
          ) : (
            <div key={i} className="bubble-bot">
              <span className="av"><Lightning size={12} weight="fill" /></span>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
                <div className={`txt${"loading" in m && m.loading ? " loading" : ""}`}>{m.text}</div>
                {"summary" in m && m.summary && (
                  <div className="summary">
                    {m.summary.map(([k, v]) => [<span key={k + "k"}>{k}</span>, <span key={k + "v"}>{v}</span>])}
                  </div>
                )}
                {"levers" in m && m.levers && m.levers.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {m.levers.map((lv, j) => <LeverCard key={j} lv={lv} planner={planner} />)}
                  </div>
                )}
                {"windows" in m && m.windows && m.windows.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {m.windows.map((w) => <WindowCard key={`${w.season}${w.year}`} w={w} planner={planner} done={mt?.scheduled.includes(`${w.season} ${w.year}`) ?? false} />)}
                  </div>
                )}
                {m.action === "add" && (
                  <button className="btn primary sm" style={{ alignSelf: "flex-start" }} onClick={() => void actions.addPrelim()}>
                    <Plus size={13} weight="bold" />
                    {derived.onMain ? "Open a branch and add" : "Add to preliminary queue"}
                  </button>
                )}
                {m.action === "schedule" && mt?.season && mt.year && (
                  <button className="btn primary sm" style={{ alignSelf: "flex-start" }} onClick={() => void actions.scheduleWindow(mt.season!, mt.year!)}>
                    <CalendarCheck size={13} weight="bold" />
                    {derived.onMain ? "Open a branch and schedule" : `Schedule on ${derived.branch?.name ?? "the branch"}`}
                  </button>
                )}
                {m.action === "run" && (
                  <button className="btn primary sm" style={{ alignSelf: "flex-start" }} onClick={actions.runFromChat} disabled={s.running}>
                    <Play size={13} weight="bold" />
                    {`Run on ${derived.profile.label}`}
                  </button>
                )}
              </div>
            </div>
          ),
        )}
      </div>

      <div className="composer-wrap">
        {quick.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {quick.map((o) => (
              <button key={o.label} className={`quick${o.on ? " on" : ""}${o.go ? " go" : ""}`} onClick={o.pick} disabled={chat.busy}>
                {o.icon === "check" && <CheckSquare size={12} weight="fill" />}
                {o.icon === "box" && <Square size={12} />}
                {o.icon === "plus" && <Plus size={12} />}
                {o.label}
                {o.icon === "next" && <ArrowRight size={12} weight="bold" />}
              </button>
            ))}
          </div>
        )}
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            actions.send(chat.input);
          }}
        >
          <input
            value={chat.input}
            onChange={(e) => actions.setInput(e.target.value)}
            placeholder={isRecs ? "Ask what would unblock a project" : q || mq?.text ? "Type an answer, or pick one above" : isMaint ? "Give a season and year, or ask for the best window" : "Start another project, or ask in Recommendations"}
            aria-label="Message Copilot"
            disabled={chat.busy}
          />
          <button type="submit" aria-label="Send" disabled={chat.busy}>
            <ArrowUp size={14} weight="bold" />
          </button>
        </form>
        <span style={{ fontSize: 10.5, color: C.mute2 }}>
          {isRecs
            ? "Every lever is re-solved by the engine. Copilot only explains the result."
            : isMaint
              ? "Every window is studied by the engine. Copilot only asks and explains."
              : "Copilot fills the application. Ranking and power flow are computed by the engine."}
        </span>
      </div>
    </div>
  );
}

/** One ranked window: the engine's verdict and figures, said plainly, and the schedule button. */
function WindowCard({ w, planner, done }: { w: WindowOption; planner: CopilotTabPlanner; done: boolean }) {
  const { actions, derived, s } = planner;
  const v = VERDICT[w.verdict];
  return (
    <div className="lever">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="mono" style={{ fontSize: 11, color: C.mute, flex: "none" }}>#{w.rank}</span>
        <span style={{ fontSize: 12.5, fontWeight: 600, flex: 1, minWidth: 0 }}>{w.season} {w.year}</span>
        <span className="chip" style={{ flex: "none", fontSize: 10.5, ...TONE[v.tone] }}>{v.label}</span>
      </div>
      <span style={{ fontSize: 11.5, color: C.ink2, lineHeight: 1.45 }}>{windowLine(w)}</span>
      <span className="mono" style={{ fontSize: 11, color: C.mute }}>
        line {Math.round(w.worst_line_loading_pct)}% · transformer {Math.round(w.worst_trafo_loading_pct)}% · {w.n1_findings == null ? "N-1 not screened" : `N-1 ${w.n1_findings}`}
      </span>
      <span style={{ fontSize: 11, color: C.ink3, lineHeight: 1.45, textWrap: "pretty" }}>{nameElements(w.message, derived.ix)}</span>
      <button className="btn hue" style={{ alignSelf: "flex-start", height: 28, fontSize: 11.5 }} onClick={() => void actions.scheduleWindow(w.season, w.year)} disabled={done || s.chat.busy}>
        <CalendarCheck size={12} />
        {done ? "Scheduled" : `Schedule on ${derived.onMain ? "a new branch" : derived.branch?.name}`}
      </button>
    </div>
  );
}

function LeverCard({ lv, planner }: { lv: Suggestion; planner: CopilotTabPlanner }) {
  const { actions, derived } = planner;
  const ok = lv.connects_target;
  const tryable = leverTryable(lv);
  return (
    <div className="lever">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, flex: 1, minWidth: 0 }}>{nameElements(lv.action, derived.ix)}</span>
        <span className="chip" style={{ flex: "none", fontSize: 10.5, background: ok ? "rgba(94,230,168,0.16)" : "rgba(255,195,107,0.16)", color: ok ? C.greenInk : C.amberInk }}>
          {ok ? "connects" : "partial"}
        </span>
      </div>
      <span className="mono" style={{ fontSize: 12, fontWeight: 600, color: C.greenInk }}>{leverFrees(lv)}</span>
      <span style={{ fontSize: 11.5, color: C.ink2 }}>{leverConnects(lv)}</span>
      {lv.narration && <span style={{ fontSize: 11.5, color: C.ink3, lineHeight: 1.45 }}>{nameElements(lv.narration, derived.ix)}</span>}
      {lv.caveat && <span style={{ fontSize: 11, color: C.mute, lineHeight: 1.4, textWrap: "pretty" }}>{lv.caveat}</span>}
      {tryable ? (
        <button className="btn hue" style={{ alignSelf: "flex-start", height: 28, fontSize: 11.5 }} onClick={() => void actions.applyLever(lv)}>
          <GitBranch size={12} />
          Try on {derived.onMain ? "a new branch" : derived.branch?.name}
        </button>
      ) : (
        <span style={{ fontSize: 11, color: C.mute2 }}>An operating change by the developer (power factor), not a network reinforcement, so it isn't added to the branch.</span>
      )}
    </div>
  );
}
