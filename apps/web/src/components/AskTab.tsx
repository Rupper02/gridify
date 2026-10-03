// Ask: the side panel's first tab. A picker starts a conversation with the agents ("Ask anything":
// free text, answered by the answerer agent with every figure traced to a recorded tool step) or one
// of the Copilot's deterministic chats (New project, Recommendations, Maintenance: CopilotTab). The
// Ask chat shows a reply as it streams: the planning stages as chips (Plan · Assemble · Run · Check ·
// Cite), the text, the flags on figures no tool produced, and the proposals waiting for approval.

import { ArrowRight, ArrowUp, Check, Lightning, NotePencil, Pause, Play, Prohibit, Receipt, Sparkle, Warning, X } from "@phosphor-icons/react";
import { useEffect, useRef } from "react";

import type { ChatMode } from "../hooks/planner/core";
import type { PlannerSlice } from "../hooks/planner/slice";
import { byStatus, nameElements } from "../lib/derive";
import type { Layout } from "../lib/layout";
import { type FoldedTrace, STAGE_LABEL, type TraceChip, agentsPill, argsLine, evidenceLine, flagLines, foldTrace, toolLabel, traceFromMessage } from "../lib/trace";
import { C } from "../theme";
import type { Approval, ThreadMessage } from "../types";
import { CopilotChat, type CopilotTabPlanner, MAINT, MODE_ICON, MODE_TITLE } from "./CopilotTab";

export type AskTabPlanner = CopilotTabPlanner &
  PlannerSlice<"agents" | "thread" | "threads" | "trace", "ask" | "decideApproval" | "openEvidence" | "openThread" | "setAgentsPaused" | "startAsk", "pendingApprovals">;

export function AskTab({ planner, layout }: { planner: AskTabPlanner; layout: Layout }) {
  const mode = planner.s.chat.mode;
  if (mode === "ask") return <AskChat planner={planner} layout={layout} />;
  if (mode) return <CopilotChat planner={planner} layout={layout} />;
  return <Picker planner={planner} />;
}

type GuidedMode = Exclude<ChatMode, "ask">;

function Picker({ planner }: { planner: AskTabPlanner }) {
  const { s, actions, derived } = planner;
  const target = derived.onMain ? "main" : derived.branch?.name;
  const off = !s.agents || s.agents.status === "off";
  const pill = agentsPill(s.agents);
  const modes: { mode: GuidedMode; c: string; bg: string; bd: string; desc: string; ex: string; pick: () => void }[] = [
    {
      mode: "project", c: C.accent, bg: "rgba(124,227,255,0.14)", bd: "rgba(124,227,255,0.4)",
      desc: "Add a connection application to the preliminary queue. I ask for technology, MW, import, bus, year and readiness.",
      ex: "\"Add a 49.9 MW battery at Boston\"", pick: actions.startProject,
    },
    {
      mode: "recs", c: C.amberInk, bg: "rgba(255,195,107,0.14)", bd: "rgba(255,195,107,0.4)",
      desc: "Find what would unblock deferred projects. Each lever is re-solved and the MW it frees is measured.",
      ex: `"What would it take to connect ${byStatus(derived.q, "Deferred")[0]?.request_id ?? "a deferred project"}?"`, pick: () => actions.startRecs(),
    },
    {
      mode: "maint", ...MAINT,
      desc: "Plan an outage, a repowering or a replacement. I find the window that keeps customers supplied.",
      ex: "\"When can I take the most loaded line out for 6 weeks?\"", pick: actions.startMaintChat,
    },
  ];
  const resumeOrStart: Record<GuidedMode, () => void> = {
    project: () => (s.chat.intake ? actions.resume("project") : actions.startProject()),
    recs: () => (s.chat.recs.length ? actions.resume("recs") : actions.startRecs()),
    maint: () => (s.chat.maint ? actions.resume("maint") : actions.startMaintChat()),
  };
  const bid = derived.onMain ? null : s.activeBranch;
  const threads = s.threads.filter((t) => t.kind === "ask" && (t.branch_id ?? null) === bid).slice(0, 4);
  const health = s.threads.find((t) => t.kind === "health");
  return (
    <div className="scroll" style={{ padding: "6px 14px 16px", gap: 14 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <span style={{ fontSize: 15, fontWeight: 600 }}>Ask the model</span>
        <span style={{ fontSize: 12, color: C.mute, lineHeight: 1.45 }}>
          Working on <b className="mono" style={{ fontWeight: 600, color: derived.onMain ? C.mute : derived.hue }}>{target}</b> and its last run. The agents plan the study; the engine does the physics.
        </span>
      </div>
      <button className="mode-card" onClick={actions.startAsk} disabled={off} title={off ? pill.title : "Ask the agents"}>
        <span className="ic" style={{ background: "rgba(124,227,255,0.14)", border: "1px solid rgba(124,227,255,0.4)" }}>
          <Sparkle size={20} color={C.accent} weight="fill" />
        </span>
        <span style={{ fontSize: 14, fontWeight: 600 }}>Ask anything</span>
        <ArrowRight size={14} color={C.mute} style={{ marginTop: 2 }} />
        <span style={{ gridColumn: "2 / -1", fontSize: 12, color: C.ink2, lineHeight: 1.45, textWrap: "pretty" }}>
          {off
            ? "The agents are off: the API needs OPENROUTER_API_KEY. Everything below works without it."
            : "A question in plain words. The agents run the engine's studies and answer with every figure traced to the step that produced it; what they propose waits for your approval."}
        </span>
        <span style={{ gridColumn: "2 / -1", fontSize: 11.5, color: C.mute, fontStyle: "italic" }}>"Where can 20 MW of export connect at 33 kV today?"</span>
      </button>
      <AgentsLine planner={planner} />
      <span style={{ fontSize: 12.5, fontWeight: 600, marginTop: 2 }}>Guided, no key needed</span>
      {modes.map((m) => {
        const Icon = MODE_ICON[m.mode];
        return (
          <button key={m.mode} className="mode-card" onClick={m.pick}>
            <span className="ic" style={{ background: m.bg, border: `1px solid ${m.bd}` }}>
              <Icon size={20} color={m.c} />
            </span>
            <span style={{ fontSize: 14, fontWeight: 600 }}>{MODE_TITLE[m.mode]}</span>
            <ArrowRight size={14} color={C.mute} style={{ marginTop: 2 }} />
            <span style={{ gridColumn: "2 / -1", fontSize: 12, color: C.ink2, lineHeight: 1.45, textWrap: "pretty" }}>{m.desc}</span>
            <span style={{ gridColumn: "2 / -1", fontSize: 11.5, color: C.mute, fontStyle: "italic" }}>{m.ex}</span>
          </button>
        );
      })}
      {(threads.length > 0 || health) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>Conversations</span>
          {threads.map((t) => (
            <button key={t.thread_id} className="thread-row" onClick={() => void actions.openThread(t.thread_id)}>
              <Sparkle size={15} color={C.mute} />
              <span style={{ display: "flex", flexDirection: "column", minWidth: 0, lineHeight: 1.35 }}>
                <span className="ellipsis" style={{ fontSize: 12.5 }}>{t.title}</span>
                <span style={{ fontSize: 11, color: C.mute }}>on {t.branch_id ?? "main"} · {t.created_at.slice(0, 16).replace("T", " ")}</span>
              </span>
            </button>
          ))}
          {health && (
            <button className="thread-row" onClick={() => void actions.openThread(health.thread_id)}>
              <Lightning size={15} color={C.mute} />
              <span style={{ display: "flex", flexDirection: "column", minWidth: 0, lineHeight: 1.35 }}>
                <span className="ellipsis" style={{ fontSize: 12.5 }}>Project health</span>
                <span style={{ fontSize: 11, color: C.mute }}>the steward's briefs after runs, merges and data changes</span>
              </span>
            </button>
          )}
        </div>
      )}
      {s.chat.recent.some((r) => r.mode !== "ask") && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>Recent on this branch</span>
          {s.chat.recent.filter((r): r is typeof r & { mode: GuidedMode } => r.mode !== "ask").map((r) => {
            const Icon = MODE_ICON[r.mode];
            return (
              <button key={r.title + r.at} className="thread-row" onClick={resumeOrStart[r.mode]}>
                <Icon size={15} color={C.mute} />
                <span style={{ display: "flex", flexDirection: "column", minWidth: 0, lineHeight: 1.35 }}>
                  <span className="ellipsis" style={{ fontSize: 12.5 }}>{r.title}</span>
                  <span style={{ fontSize: 11, color: C.mute }}>{MODE_TITLE[r.mode]} · {r.at}</span>
                </span>
              </button>
            );
          })}
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

/** The agents' status and the pause switch (hidden when they are off). */
function AgentsLine({ planner }: { planner: AskTabPlanner }) {
  const { s, actions } = planner;
  const a = s.agents;
  if (!a || a.status === "off") return null;
  const pill = agentsPill(a);
  const paused = a.status === "paused";
  return (
    <div className="well" style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", fontSize: 11.5 }}>
      <span className="agents-pill" data-tone={pill.tone} data-live={a.status === "running" || undefined} title={pill.title}>
        <Sparkle size={11} weight="fill" />
        {pill.label}
      </span>
      <span className="mono ellipsis" style={{ color: C.mute, flex: 1, minWidth: 0 }}>
        {a.budget ? `today ${a.budget.credits.toFixed(2)} cr · ${a.budget.solves} solves` : ""}
      </span>
      <button className="btn" style={{ height: 26, fontSize: 11, padding: "0 9px" }} onClick={() => void actions.setAgentsPaused(!paused)} title={paused ? pill.title : "Pause the agents for this project"}>
        {paused ? <Play size={11} weight="bold" /> : <Pause size={11} weight="bold" />}
        {paused ? "Resume" : "Pause"}
      </button>
    </div>
  );
}

function AskChat({ planner, layout }: { planner: AskTabPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const t = s.thread;
  const listRef = useRef<HTMLDivElement>(null);
  const live = foldTrace(s.trace);
  const msgs = t?.messages ?? [];
  const streaming = msgs.some((m) => m.role === "assistant" && (m.status === "queued" || m.status === "streaming"));
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs.length, live.text, live.chips.length]);
  const off = !s.agents || s.agents.status === "off";
  const paused = s.agents?.status === "paused";
  const target = t?.branch_id ?? (derived.onMain ? "main" : (derived.branch?.name ?? ""));
  const pending = t?.approvals.filter((a) => a.status === "pending") ?? [];
  const locked = off || paused || s.chat.busy || streaming;
  return (
    <div className="chat-wrap">
      <div className="chat-head">
        <div style={{ display: "flex", alignItems: "center", gap: 8, whiteSpace: "nowrap", minWidth: 0, overflow: "hidden" }}>
          <Sparkle size={15} color={C.accent} weight="fill" />
          <span style={{ fontSize: 13, fontWeight: 600, flex: "none" }}>{t?.kind === "health" ? "Project health" : "Ask the model"}</span>
          {layout.wide && <ArrowRight size={12} color={C.mute2} />}
          {layout.wide && <span style={{ fontSize: 12, color: C.mute, flex: "none" }}>on</span>}
          <span className="mono ellipsis" style={{ fontSize: 12, fontWeight: 600, color: target === "main" ? C.mute : derived.hue, minWidth: 40, flex: "1 1 auto" }}>{target}</span>
          <button className="btn" style={{ height: 28, fontSize: 11.5, marginLeft: "auto", flex: "none" }} onClick={actions.startAsk} title="New conversation">
            <NotePencil size={13} />
            {layout.wide && "New"}
          </button>
          <button className="btn" style={{ height: 28, fontSize: 11.5, flex: "none", padding: "0 8px" }} onClick={actions.newChat} title="Back to the start" aria-label="Back to the start">
            <X size={13} />
          </button>
        </div>
      </div>

      <div className="msgs" ref={listRef} aria-live="polite">
        {!t && (
          <span className="mute" style={{ fontSize: 12, lineHeight: 1.5 }}>
            Ask about the plan on {target}: the queue, a year, a limit, where capacity is left. I say what I ran and what I did not study.
          </span>
        )}
        {msgs.map((m) =>
          m.role === "user" ? (
            <div key={m.message_id} className="bubble-user">{m.content}</div>
          ) : (
            <BotMessage key={m.message_id} m={m} live={m.status === "queued" || m.status === "streaming" ? live : null} approvals={pending.filter((a) => a.message_id === m.message_id)} planner={planner} />
          ),
        )}
      </div>

      <div className="composer-wrap">
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            void actions.ask(s.chat.input);
          }}
        >
          <input
            value={s.chat.input}
            onChange={(e) => actions.setInput(e.target.value)}
            placeholder={off ? "The agents are off (no API key)" : paused ? "The agents are paused" : streaming ? "Waiting for the reply…" : "Ask about the plan"}
            aria-label="Ask the model"
            disabled={locked}
          />
          <button type="submit" aria-label="Send" disabled={locked}>
            <ArrowUp size={14} weight="bold" />
          </button>
        </form>
        <span style={{ fontSize: 10.5, color: C.mute2 }}>The agents plan the study and phrase the result; the engine computes. Every figure is traced to a tool step; one no tool produced is flagged.</span>
      </div>
    </div>
  );
}

/** One reply: its stage chips (live or stored), the text, the flags, the evidence line, the proposals waiting. */
function BotMessage({ m, live, approvals, planner }: { m: ThreadMessage; live: FoldedTrace | null; approvals: Approval[]; planner: AskTabPlanner }) {
  const { actions, derived } = planner;
  const chips: TraceChip[] = live ? live.chips : traceFromMessage(m);
  const text = live ? live.text : m.content;
  const failed = m.status === "failed" || !!live?.error;
  const planning = !!live && chips.length === 0 && !text;
  const cited = live ? live.cited : m.status === "done";
  const flags = flagLines(m.flags);
  const evidence = evidenceLine(m);
  return (
    <div className="bubble-bot">
      <span className="av"><Lightning size={12} weight="fill" /></span>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
        {(live || chips.length > 0) && (
          <div className="trace" aria-label="How the answer was made">
            <span className="tchip" data-status={planning ? "running" : "done"}><span className="stage">{STAGE_LABEL.PLAN}</span>plan the study</span>
            {chips.map((c) => (
              <button
                key={c.step_id}
                className={`tchip${c.tool.startsWith("study_") ? " link" : ""}`}
                data-status={c.status}
                title={c.summary || (c.tool.startsWith("study_") ? "Open the evidence" : c.step_id)}
                onClick={c.tool.startsWith("study_") ? () => void actions.openEvidence(c.step_id) : undefined}
                disabled={!c.tool.startsWith("study_")}
              >
                <span className="stage">{STAGE_LABEL[c.stage]}</span>
                {toolLabel(c.tool)}
                {c.solves > 0 && <span className="mono" style={{ fontWeight: 500, color: C.mute }}>{c.solves}</span>}
              </button>
            ))}
            {cited && chips.length > 0 && <span className="tchip" data-status="done"><span className="stage">{STAGE_LABEL.CITE}</span>evidence attached</span>}
          </div>
        )}
        <div className={`txt${planning ? " loading" : ""}`} style={{ whiteSpace: "pre-wrap" }}>
          {planning ? "Planning the study…" : nameElements(text, derived.ix)}
        </div>
        {failed && <span style={{ fontSize: 11.5, color: C.redInk }}>{live?.error ?? "The answer failed."}</span>}
        {flags.map((f, i) => (
          <span key={i} className="flag-note">
            <Warning size={11} weight="fill" style={{ marginRight: 4, verticalAlign: -1 }} />
            {f}
          </span>
        ))}
        {approvals.map((a) => <ApprovalCard key={a.approval_id} a={a} planner={planner} />)}
        {evidence && (
          <span className="evidence-line">
            <Receipt size={10} style={{ marginRight: 4, verticalAlign: -1 }} />
            {evidence}
          </span>
        )}
      </div>
    </div>
  );
}

function ApprovalCard({ a, planner }: { a: Approval; planner: AskTabPlanner }) {
  const { actions, s } = planner;
  return (
    <div className="approval">
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>Proposal · {toolLabel(a.tool)}</span>
      <span className="mono" style={{ fontSize: 11, color: C.ink2, lineHeight: 1.45, whiteSpace: "pre-wrap" }}>{argsLine(a.args) || "no arguments"}</span>
      <span style={{ fontSize: 11, color: C.mute, lineHeight: 1.4 }}>Nothing happens until you decide. Approving runs it on the branch and the answer continues; main is never edited.</span>
      <div style={{ display: "flex", gap: 6 }}>
        <button className="btn primary sm" onClick={() => void actions.decideApproval(a.approval_id, "approve")} disabled={s.chat.busy}>
          <Check size={12} weight="bold" />
          Approve
        </button>
        <button className="btn" style={{ height: 32 }} onClick={() => void actions.decideApproval(a.approval_id, "deny", "declined in the planner")} disabled={s.chat.busy}>
          <Prohibit size={12} />
          Deny
        </button>
      </div>
    </div>
  );
}
