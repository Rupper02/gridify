// Copilot. A start screen picks the chat mode: New project (a guided intake into the preliminary
// queue) or Recommendations (the engine's "what would it take" levers, explained). Copilot fills the
// application and phrases results; ranking and power flow are the engine's.

import {
  ArrowRight,
  ArrowUp,
  CheckSquare,
  Database,
  GitBranch,
  Lightbulb,
  Lightning,
  NotePencil,
  Play,
  Plus,
  PlusCircle,
  Square,
} from "@phosphor-icons/react";
import { useEffect, useRef } from "react";

import type { RecMsg } from "../hooks/planner/core";
import type { PlannerSlice } from "../hooks/planner/slice";
import { byStatus, deferredMw, nameElements } from "../lib/derive";
import { draftSlots, question, readinessScore } from "../lib/intake";
import type { ChatMsg } from "../lib/intake";
import { leverConnects, leverFrees, leverTryable, recsQuickReplies } from "../lib/recs";
import type { Layout } from "../lib/layout";
import { C, fmtMw } from "../theme";
import type { Suggestion } from "../types";
import { intakeCtx } from "../hooks/planner/useCopilot";

export type CopilotTabPlanner = PlannerSlice<
  "activeBranch" | "boundary" | "branches" | "chat" | "maxMw" | "model" | "result" | "running" | "year",
  | "addPrelim" | "anotherProject" | "applyLever" | "evidenceDone" | "newChat" | "resume" | "runFromChat" | "send" | "setInput"
  | "startProject" | "startRecs" | "toggleEvidence",
  "branch" | "hue" | "ix" | "onMain" | "profile" | "q" | "resultProfile"
>;

export function CopilotTab({ planner, layout }: { planner: CopilotTabPlanner; layout: Layout }) {
  return planner.s.chat.mode ? <Chat planner={planner} layout={layout} /> : <Picker planner={planner} />;
}

function Picker({ planner }: { planner: CopilotTabPlanner }) {
  const { s, actions, derived } = planner;
  const target = derived.onMain ? "main" : derived.branch?.name;
  const modes = [
    {
      title: "New project", Icon: PlusCircle, c: C.accent, bg: "rgba(124,227,255,0.14)", bd: "rgba(124,227,255,0.4)",
      desc: "Add a connection application to the preliminary queue. I ask for technology, MW, import, bus, year and readiness.",
      ex: "\"Add a 49.9 MW battery at Boston\"", pick: actions.startProject,
    },
    {
      title: "Recommendations", Icon: Lightbulb, c: C.amberInk, bg: "rgba(255,195,107,0.14)", bd: "rgba(255,195,107,0.4)",
      desc: "Find what would unblock deferred projects. Each lever is re-solved and the MW it frees is measured.",
      ex: `"What would it take to connect ${byStatus(derived.q, "Deferred")[0]?.request_id ?? "a deferred project"}?"`, pick: () => actions.startRecs(),
    },
  ];
  return (
    <div className="scroll" style={{ padding: "6px 14px 16px", gap: 14 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <span style={{ fontSize: 15, fontWeight: 600 }}>Start a new chat</span>
        <span style={{ fontSize: 12, color: C.mute, lineHeight: 1.45 }}>
          Pick what you need. The chat works on <b className="mono" style={{ fontWeight: 600, color: derived.onMain ? C.mute : derived.hue }}>{target}</b> and its last run.
        </span>
      </div>
      {modes.map((m) => (
        <button key={m.title} className="mode-card" onClick={m.pick}>
          <span className="ic" style={{ background: m.bg, border: `1px solid ${m.bd}` }}>
            <m.Icon size={20} color={m.c} />
          </span>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{m.title}</span>
          <ArrowRight size={14} color={C.mute} style={{ marginTop: 2 }} />
          <span style={{ gridColumn: "2 / -1", fontSize: 12, color: C.ink2, lineHeight: 1.45, textWrap: "pretty" }}>{m.desc}</span>
          <span style={{ gridColumn: "2 / -1", fontSize: 11.5, color: C.mute, fontStyle: "italic" }}>{m.ex}</span>
        </button>
      ))}
      {s.chat.recent.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>Recent on this branch</span>
          {s.chat.recent.map((r) => (
            <button
              key={r.title + r.at}
              onClick={() => (r.mode === "project" ? (s.chat.intake ? actions.resume("project") : actions.startProject()) : s.chat.recs.length ? actions.resume("recs") : actions.startRecs())}
              style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 11px", borderRadius: 12, background: "var(--well)", border: "var(--well-bd)", textAlign: "left" }}
            >
              {r.mode === "project" ? <PlusCircle size={15} color={C.mute} /> : <Lightbulb size={15} color={C.mute} />}
              <span style={{ display: "flex", flexDirection: "column", minWidth: 0, lineHeight: 1.35 }}>
                <span className="ellipsis" style={{ fontSize: 12.5 }}>{r.title}</span>
                <span style={{ fontSize: 11, color: C.mute }}>{r.mode === "project" ? "New project" : "Recommendations"} · {r.at}</span>
              </span>
            </button>
          ))}
        </div>
      )}
      {s.result?.justification && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>Briefing from the last run</span>
          <span className="well" style={{ padding: "10px 12px", fontSize: 12, lineHeight: 1.5, color: C.ink2, whiteSpace: "pre-wrap" }}>{s.result.justification}</span>
          <span style={{ fontSize: 10.5, color: C.mute2 }}>Phrased by an LLM from the engine's figures. The queue and the physics are the engine's.</span>
        </div>
      )}
    </div>
  );
}

function Chat({ planner, layout }: { planner: CopilotTabPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const chat = s.chat;
  const isRecs = chat.mode === "recs";
  const it = chat.intake;
  const listRef = useRef<HTMLDivElement>(null);
  const msgs: (ChatMsg | RecMsg)[] = isRecs ? chat.recs : (it?.messages ?? []);
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs.length]);

  const target = derived.onMain ? (isRecs ? "main" : "a new branch") : (derived.branch?.name ?? "");
  const df = byStatus(derived.q, "Deferred");
  const ctx = intakeCtx(s);
  const q = it && !isRecs && it.step !== "done" ? question(it, ctx) : null;

  // quick replies for the mode and step
  let quick: { label: string; on?: boolean; go?: boolean; icon?: "check" | "box" | "plus" | "next"; pick: () => void }[] = [];
  if (isRecs) quick = recsQuickReplies(derived.q).map((l) => ({ label: l, pick: () => actions.send(l) }));
  else if (q?.multi && it)
    quick = [
      ...q.multi.map((l) => ({ label: l, on: it.readySel.includes(l), icon: it.readySel.includes(l) ? ("check" as const) : ("box" as const), pick: () => actions.toggleEvidence(l) })),
      { label: `Done · ${Math.round(readinessScore(it.readySel) * 100)}%`, go: true, icon: "next" as const, pick: actions.evidenceDone },
    ];
  else if (q) quick = q.opts.map((o) => ({ label: o, pick: () => actions.send(o) }));
  else if (it?.step === "done") quick = [{ label: "Start another project", icon: "plus", pick: actions.anotherProject }];

  const slots = it && !isRecs ? draftSlots(it) : [];
  return (
    <div className="chat-wrap">
      <div className="chat-head">
        <div style={{ display: "flex", alignItems: "center", gap: 8, whiteSpace: "nowrap", minWidth: 0, overflow: "hidden" }}>
          {isRecs ? <Lightbulb size={15} color={C.amberInk} /> : <PlusCircle size={15} color={C.accent} />}
          <span style={{ fontSize: 13, fontWeight: 600, flex: "none" }}>{isRecs ? "Recommendations" : "New project"}</span>
          {layout.wide && <ArrowRight size={12} color={C.mute2} />}
          {layout.wide && <span style={{ fontSize: 12, color: C.mute, flex: "none" }}>{isRecs ? "on" : "queue on"}</span>}
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
                {m.action && (
                  <button
                    className="btn primary sm"
                    style={{ alignSelf: "flex-start" }}
                    onClick={() => (m.action === "add" ? void actions.addPrelim() : actions.runFromChat())}
                    disabled={m.action === "run" && s.running}
                  >
                    {m.action === "add" ? <Plus size={13} weight="bold" /> : <Play size={13} weight="bold" />}
                    {m.action === "add" ? (derived.onMain ? "Open a branch and add" : "Add to preliminary queue") : `Run on ${derived.profile.label}`}
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
            placeholder={isRecs ? "Ask what would unblock a project" : q ? "Type an answer, or pick one above" : "Start another project, or ask in Recommendations"}
            aria-label="Message Copilot"
            disabled={chat.busy}
          />
          <button type="submit" aria-label="Send" disabled={chat.busy}>
            <ArrowUp size={14} weight="bold" />
          </button>
        </form>
        <span style={{ fontSize: 10.5, color: C.mute2 }}>
          {isRecs ? "Every lever is re-solved by the engine. Copilot only explains the result." : "Copilot fills the application. Ranking and power flow are computed by the engine."}
        </span>
      </div>
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
