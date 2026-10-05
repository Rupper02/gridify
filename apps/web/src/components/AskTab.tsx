// Ask: the side panel's first tab and the planner's one conversation. The agents answer in plain
// words with every figure traced to a recorded tool step, run the engine's studies, and propose
// actions (a project or a change to one, a reinforcement, a works window, a run) that wait for the
// operator's approval here. The picker suggests questions from what is in view; a reply streams in
// with its planning stages as chips (Plan · Assemble · Run · Check · Propose · Cite) and can be stopped.

import { ArrowRight, ArrowUp, Check, Lightning, NotePencil, Pause, Play, Prohibit, Receipt, Sparkle, Stop, Warning, X } from "@phosphor-icons/react";
import { useEffect, useRef } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import type { PlannerSlice } from "../hooks/planner/slice";
import { suggestedQuestions } from "../lib/ask";
import { nameElements } from "../lib/derive";
import type { Layout } from "../lib/layout";
import { citeSteps, citedStep } from "../lib/markdown";
import { type FoldedTrace, STAGE_LABEL, type TraceChip, agentsPill, argsLine, evidenceLine, flagLines, foldTrace, toolLabel, traceFromMessage } from "../lib/trace";
import { C } from "../theme";
import type { Approval, ThreadMessage } from "../types";

export type AskTabPlanner = PlannerSlice<
  "activeBranch" | "agents" | "chat" | "outages" | "projectId" | "result" | "sel" | "thread" | "threads" | "trace" | "year",
  "ask" | "askAbout" | "cancelReply" | "closeThread" | "decideApproval" | "loadThreads" | "openEvidence" | "openThread" | "setAgentsPaused" | "setInput" | "startAsk",
  "branch" | "caps" | "hue" | "ix" | "onMain" | "pendingApprovals" | "q" | "tiers"
>;

/** Citations become small numbered chips; any other link opens in a new tab. */
const MD_COMPONENTS: Components = {
  a: ({ href, children }) => {
    const step = citedStep(href);
    if (step) return <sup className="cite" title={`Traced to tool step ${step}`}>{children}</sup>;
    return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
  },
};

export function AskTab({ planner, layout }: { planner: AskTabPlanner; layout: Layout }) {
  return planner.s.chat.open ? <AskChat planner={planner} layout={layout} /> : <Picker planner={planner} />;
}

const isStarting = (planner: AskTabPlanner): boolean => !planner.s.agents || planner.s.agents.status === "starting";

function Picker({ planner }: { planner: AskTabPlanner }) {
  const { s, actions, derived } = planner;
  // the conversations on this branch, as stored: re-read whenever the picker shows for a project or branch
  useEffect(() => {
    void actions.loadThreads();
  }, [actions, s.projectId, s.activeBranch]);
  const target = derived.onMain ? "main" : derived.branch?.name;
  const starting = isStarting(planner);
  const pill = agentsPill(s.agents);
  const questions = suggestedQuestions({
    q: derived.q, sel: s.sel, outages: s.outages, year: s.year, ix: derived.ix,
    connectKv: derived.tiers.mid ?? derived.tiers.high, boundary: derived.caps.boundary,
  });
  const bid = derived.onMain ? null : s.activeBranch;
  const threads = s.threads.filter((t) => t.kind === "ask" && (t.branch_id ?? null) === bid).slice(0, 4);
  const health = s.threads.find((t) => t.kind === "health");
  return (
    <div className="scroll" style={{ padding: "6px 14px 16px", gap: 14 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <span style={{ fontSize: 15, fontWeight: 600 }}>Ask the agents</span>
        <span style={{ fontSize: 12, color: C.mute, lineHeight: 1.45 }}>
          Working on <b className="mono" style={{ fontWeight: 600, color: derived.onMain ? C.mute : derived.hue }}>{target}</b> and its last run. The agents plan the study, run the engine and propose what to do; you approve.
        </span>
      </div>
      <button className="mode-card" onClick={actions.startAsk} disabled={starting} title={starting ? pill.title : "Ask the agents"}>
        <span className="ic" style={{ background: "rgba(124,227,255,0.14)", border: "1px solid rgba(124,227,255,0.4)" }}>
          <Sparkle size={20} color={C.accent} weight="fill" />
        </span>
        <span style={{ fontSize: 14, fontWeight: 600 }}>Ask anything</span>
        <ArrowRight size={14} color={C.mute} style={{ marginTop: 2 }} />
        <span style={{ gridColumn: "2 / -1", fontSize: 12, color: C.ink2, lineHeight: 1.45, textWrap: "pretty" }}>
          {starting
            ? "The agents are starting with the API; the conversation opens as soon as they are up."
            : "A question in plain words. The agents run the engine's studies and answer with every figure traced to the step that produced it; what they propose waits for your approval."}
        </span>
        <span style={{ gridColumn: "2 / -1", fontSize: 11.5, color: C.mute, fontStyle: "italic" }}>"How could CR-2061 connect, and what would it take?"</span>
      </button>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>About what is in view</span>
        {questions.map((q) => (
          <button key={q} className="ask-q" onClick={() => void actions.askAbout(q)} disabled={starting} title="Send this question">
            {q}
          </button>
        ))}
      </div>
      <AgentsLine planner={planner} />
      {(threads.length > 0 || health) && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 4 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>Conversations</span>
          {threads.map((t) => (
            <button key={t.thread_id} className="thread-row" onClick={() => void actions.openThread(t.thread_id)}>
              <Sparkle size={15} color={C.mute} />
              <span style={{ display: "flex", flexDirection: "column", minWidth: 0, lineHeight: 1.35 }}>
                <span className="ellipsis" style={{ fontSize: 12.5 }}>{t.title}</span>
                <span style={{ fontSize: 11, color: C.mute }}>on {t.branch_id ? (derived.branch?.name ?? t.branch_id) : "main"} · {t.created_at.slice(0, 16).replace("T", " ")}</span>
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

/** The agents' status and the pause switch (nothing to show while they start). */
function AgentsLine({ planner }: { planner: AskTabPlanner }) {
  const { s, actions } = planner;
  const a = s.agents;
  if (!a || a.status === "starting") return null;
  const pill = agentsPill(a);
  const paused = a.status === "paused";
  return (
    <div className="well" style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", fontSize: 11.5 }}>
      <span className="agents-pill" data-tone={pill.tone} data-live={a.status === "running" || undefined} title={pill.title}>
        <Sparkle size={11} weight="fill" />
        {pill.label}
      </span>
      <span className="mono ellipsis" style={{ color: C.mute, flex: 1, minWidth: 0 }} title="What the agents spent on this project: OpenRouter's billed cost, today and in all">
        {a.spend ? `$${a.spend.credits.toFixed(2)} today · $${a.spend.total_credits.toFixed(2)} total` : ""}
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
  const starting = isStarting(planner);
  const paused = s.agents?.status === "paused";
  // the thread's branch by name when it is the one in view (its id otherwise: another branch's conversation)
  const target = t?.branch_id ? (t.branch_id === s.activeBranch ? (derived.branch?.name ?? t.branch_id) : t.branch_id) : derived.onMain ? "main" : (derived.branch?.name ?? "");
  const pending = t?.approvals.filter((a) => a.status === "pending") ?? [];
  const locked = starting || paused || s.chat.busy || streaming;
  return (
    <div className="chat-wrap">
      <div className="chat-head">
        <div style={{ display: "flex", alignItems: "center", gap: 8, whiteSpace: "nowrap", minWidth: 0, overflow: "hidden" }}>
          <Sparkle size={15} color={C.accent} weight="fill" />
          <span style={{ fontSize: 13, fontWeight: 600, flex: "none" }}>{t?.kind === "health" ? "Project health" : "Ask the agents"}</span>
          {layout.wide && <ArrowRight size={12} color={C.mute2} />}
          {layout.wide && <span style={{ fontSize: 12, color: C.mute, flex: "none" }}>on</span>}
          <span className="mono ellipsis" style={{ fontSize: 12, fontWeight: 600, color: target === "main" ? C.mute : derived.hue, minWidth: 40, flex: "1 1 auto" }}>{target}</span>
          <button className="btn" style={{ height: 28, fontSize: 11.5, marginLeft: "auto", flex: "none" }} onClick={actions.startAsk} title="New conversation">
            <NotePencil size={13} />
            {layout.wide && "New"}
          </button>
          <button className="btn" style={{ height: 28, fontSize: 11.5, flex: "none", padding: "0 8px" }} onClick={actions.closeThread} title="Back to the start" aria-label="Back to the start">
            <X size={13} />
          </button>
        </div>
      </div>

      <div className="msgs" ref={listRef} aria-live="polite">
        {!t && (
          <span className="mute" style={{ fontSize: 12, lineHeight: 1.5 }}>
            Ask about the plan on {target}: the queue, a project's options, a year, a limit, where capacity is left, the best window for a work. I say what I ran and what I did not study; what I propose waits for your approval.
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
            placeholder={starting ? "The agents are starting…" : paused ? "The agents are paused" : streaming ? "Waiting for the reply… Stop to cancel it" : "Ask about the plan"}
            aria-label="Ask the agents"
            disabled={locked}
          />
          {streaming ? (
            <button type="button" aria-label="Stop" title="Stop this reply" data-stop onClick={() => void actions.cancelReply()} disabled={s.chat.busy && !streaming}>
              <Stop size={14} weight="fill" />
            </button>
          ) : (
            <button type="submit" aria-label="Send" disabled={locked}>
              <ArrowUp size={14} weight="bold" />
            </button>
          )}
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
  const cancelled = m.status === "cancelled";
  const planning = !!live && chips.length === 0 && !text;
  const cited = live ? !!live.final : m.status === "done"; // the evidence is attached when the reply has ended, not when its first text starts
  const flags = flagLines(m.flags);
  const evidence = evidenceLine(m);
  return (
    <div className="bubble-bot">
      <span className="av"><Lightning size={12} weight="fill" /></span>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
        {(live || chips.length > 0) && (
          <div className="trace" aria-label="How the answer was made">
            <span className="tchip" data-status={planning ? "running" : "done"}><span className="tstage">{STAGE_LABEL.PLAN}</span>plan the study</span>
            {chips.map((c) => (
              <button
                key={c.step_id}
                className={`tchip${c.tool.startsWith("study_") ? " link" : ""}`}
                data-status={c.status}
                title={c.summary || (c.tool.startsWith("study_") ? "Open the evidence" : c.step_id)}
                onClick={c.tool.startsWith("study_") ? () => void actions.openEvidence(c.step_id) : undefined}
                disabled={!c.tool.startsWith("study_")}
              >
                <span className="tstage">{STAGE_LABEL[c.stage]}</span>
                {toolLabel(c.tool)}
                {c.status === "running" && c.progress && <span className="mono" style={{ fontWeight: 500, color: C.mute }}>· {c.progress}</span>}
                {c.solves > 0 && <span className="mono" style={{ fontWeight: 500, color: C.mute }}>{c.solves}</span>}
              </button>
            ))}
            {cited && chips.length > 0 && <span className="tchip" data-status="done"><span className="tstage">{STAGE_LABEL.CITE}</span>evidence attached</span>}
          </div>
        )}
        <div className={`txt md${planning ? " loading" : ""}${cancelled ? " mute" : ""}`}>
          {planning ? "Planning the study…" : (
            <Markdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>{citeSteps(nameElements(text, derived.ix))}</Markdown>
          )}
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
      <span style={{ fontSize: 11, color: C.mute, lineHeight: 1.4 }}>Nothing happens until you decide. Once every proposal of this reply is decided, the approved ones are applied on the branch and the answer continues; main is never edited.</span>
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
