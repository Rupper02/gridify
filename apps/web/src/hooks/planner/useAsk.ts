// Ask the agents: the planner's one conversation. A question goes to a thread on the active branch;
// the reply streams back as events (tool calls with their step ids, tokens, the final message) and is
// then re-read as stored, with its trace, flags and evidence. A proposal the agent makes waits here for
// the operator's approval; approving runs it on the branch, the answer continues, and the planner
// refreshes what the proposal touched (lib/ask.ts). A reply on its way can be stopped.

import { useCallback, useEffect, useMemo, useRef } from "react";

import { api, failureText } from "../../api";
import { type ProposalEffect, proposalEffect } from "../../lib/ask";
import { mainIdOf } from "../../lib/projects";
import type { Approval } from "../../types";
import type { Core } from "./core";
import type { EditedFn } from "./useAutoRefresh";
import type { RunFn } from "./useRun";

const SETTLE_POLL_MS = 1000;
const SETTLE_MAX_POLLS = 90;

export function useAsk(
  { patch, ref, toastMsg }: Core,
  run: RunFn,
  refreshBranches: () => Promise<unknown>,
  loadExtras: (branchId: string) => Promise<void>,
  edited: EditedFn,
  afterRebase: (branchId: string) => Promise<void>,
) {
  const stop = useRef<(() => void) | null>(null); // closes the open event stream
  useEffect(() => () => stop.current?.(), []);

  /** What an approved proposal refreshes on the branch in view (lib/ask.ts PROPOSAL_EFFECT names the effect). */
  const APPLY: Record<ProposalEffect, (bid: string) => Promise<void>> = useMemo(() => {
    const extras = (kind: "project" | "reinforcement" | "works") => async (bid: string) => {
      await loadExtras(bid);
      edited(kind);
    };
    return {
      branch: async () => void (await refreshBranches()),
      // the agent's run is the branch's run: cached, so this only shows it
      run: async (bid) => {
        void refreshBranches();
        void run({ activeBranch: bid });
      },
      project: extras("project"),
      reinforcement: extras("reinforcement"),
      works: extras("works"),
      // the branch now holds its parent's state plus its own changes: the operator's own post-rebase steps
      rebase: afterRebase,
    };
  }, [afterRebase, edited, loadExtras, refreshBranches, run]);

  const setBusy = useCallback((busy: boolean) => patch((st) => ({ chat: { ...st.chat, busy } })), [patch]);
  const setInput = useCallback((input: string) => patch((st) => ({ chat: { ...st.chat, input } })), [patch]);

  const loadThreads = useCallback(async () => {
    try {
      const pid = ref.current.projectId;
      const threads = await api.listThreads(pid);
      if (ref.current.projectId === pid) patch({ threads });
    } catch {
      /* the picker lists none */
    }
  }, [patch, ref]);

  /** Re-read a thread as stored (ignored if another thread is open by then). */
  const reload = useCallback(
    async (tid: string) => {
      const t = await api.getThread(ref.current.projectId, tid);
      if (ref.current.thread?.thread_id === tid) patch({ thread: t });
      return t;
    },
    [patch, ref],
  );

  /** Follow a reply as it streams; when it ends, the stored message replaces the live trace. */
  const follow = useCallback(
    (tid: string, messageId: string) => {
      stop.current?.();
      setBusy(true);
      const end = api.streamReply(ref.current.projectId, tid, messageId, {
        onEvent: (ev) => patch((st) => ({ trace: [...st.trace, ev] })),
        onEnd: () => {
          stop.current = null;
          void reload(tid)
            .then(() => patch({ trace: [] }))
            .catch((e) => toastMsg(`Could not read the finished reply: ${failureText(e)}`, "warn"))
            .finally(() => setBusy(false));
          void loadThreads();
        },
        // the connection dropped: if the reply has settled meanwhile, stop following it (the API may be down: then
        // the stream keeps retrying and so does this probe, quietly)
        onDrop: () =>
          void api
            .getThread(ref.current.projectId, tid)
            .then((t) => {
              const m = t.messages.find((x) => x.message_id === messageId);
              if (m && m.status !== "queued" && m.status !== "streaming") end();
            })
            .catch(() => {}),
      });
      stop.current = end;
    },
    [loadThreads, patch, ref, reload, setBusy, toastMsg],
  );

  /** Open a stored conversation (and follow a reply still on its way). */
  const openThread = useCallback(
    async (tid: string) => {
      stop.current?.();
      try {
        const t = await api.getThread(ref.current.projectId, tid);
        patch((st) => ({ thread: t, trace: [], chat: { ...st.chat, open: true, input: "", busy: false }, tab: "ask", sideOpen: true }));
        const live = t.messages.find((m) => m.role === "assistant" && (m.status === "queued" || m.status === "streaming"));
        if (live) follow(tid, live.message_id);
      } catch (e) {
        toastMsg(`Could not open the conversation: ${failureText(e)}`, "warn");
      }
    },
    [follow, patch, ref, toastMsg],
  );

  /** A new conversation on the active branch (the thread is created with the first question). */
  const startAsk = useCallback(() => {
    stop.current?.();
    patch((st) => ({ thread: null, trace: [], chat: { ...st.chat, open: true, input: "", busy: false }, tab: "ask", sideOpen: true }));
    void loadThreads();
  }, [loadThreads, patch]);

  /** Back to the picker (a reply still on its way keeps going on the API; opening the thread again follows it). */
  const closeThread = useCallback(() => {
    stop.current?.();
    stop.current = null;
    patch((st) => ({ thread: null, trace: [], chat: { ...st.chat, open: false, input: "", busy: false } }));
  }, [patch]);

  /** Send a question: stored, then its reply followed as it streams. */
  const ask = useCallback(
    async (text: string) => {
      const v = text.trim();
      const st = ref.current;
      if (!v) return;
      if (st.agents?.status === "starting") {
        toastMsg("The agents are still starting with the API. Try again in a moment.", "warn");
        return;
      }
      patch((x) => ({ chat: { ...x.chat, open: true, input: "", busy: true } }));
      try {
        let tid = st.thread?.thread_id;
        if (!tid) {
          const t = await api.createThread(st.projectId, st.activeBranch === mainIdOf(st.projects, st.projectId) ? null : st.activeBranch, v.slice(0, 60));
          tid = t.thread_id;
          patch({ thread: { ...t, messages: [], approvals: [] } });
        }
        const r = await api.postMessage(st.projectId, tid, v);
        await reload(tid);
        patch({ trace: [] });
        if (r.paused) {
          toastMsg("The agents are paused: the question is stored, the reply waits until they resume.", "warn");
          setBusy(false);
        } else follow(tid, r.reply_id);
        void loadThreads();
      } catch (e) {
        setBusy(false);
        toastMsg(`Could not send that: ${failureText(e)}`, "warn");
      }
    },
    [follow, loadThreads, patch, ref, reload, setBusy, toastMsg],
  );

  /** A suggested question, or one from a card: a new conversation on the active branch, sent at once. */
  const askAbout = useCallback(
    async (text: string) => {
      stop.current?.();
      patch((st) => ({ thread: null, trace: [], chat: { ...st.chat, open: true, input: "", busy: false }, tab: "ask", sideOpen: true }));
      await ask(text);
    },
    [ask, patch],
  );

  /** Stop the reply on its way: the message is marked cancelled at once; what it computed stays cached. */
  const cancelReply = useCallback(async () => {
    const st = ref.current;
    const tid = st.thread?.thread_id;
    if (!tid) return;
    try {
      await api.cancelReply(st.projectId, tid);
      stop.current?.();
      stop.current = null;
      await reload(tid);
      patch({ trace: [] });
      toastMsg("Stopped. What it had already computed stays in the cache.");
    } catch (e) {
      toastMsg(`Could not stop it: ${failureText(e)}`, "warn");
    } finally {
      setBusy(false);
    }
  }, [patch, ref, reload, setBusy, toastMsg]);

  /**
   * Approve or deny a proposal. The answer continues once every proposal of its reply is decided: the
   * approved tools run on the branch, a new reply follows, and the planner refreshes what each approved
   * proposal touched (lib/ask.ts). A decision while others of the same reply are still open is recorded and waits.
   */
  const decideApproval = useCallback(
    async (approvalId: string, decision: "approve" | "deny", note = "") => {
      const st = ref.current;
      const tid = st.thread?.thread_id;
      if (!tid) return;
      const mine = st.thread?.approvals.find((a) => a.approval_id === approvalId);
      const siblings = st.thread?.approvals.filter((a) => a.message_id === mine?.message_id) ?? [];
      const bid = st.thread?.branch_id || mainIdOf(st.projects, st.projectId); // threads are project-wide: a thread without a branch is main's
      const before = st.thread?.messages.length ?? 0;
      setBusy(true);
      let r: Awaited<ReturnType<typeof api.decideApproval>>;
      try {
        r = await api.decideApproval(st.projectId, approvalId, decision, note);
      } catch (e) {
        setBusy(false);
        toastMsg(`Could not record the decision: ${failureText(e)}`, "warn");
        return;
      }
      try {
        if (r.waiting_for.length) {
          await reload(tid);
          toastMsg(`Recorded. ${r.waiting_for.length} more proposal${r.waiting_for.length > 1 ? "s" : ""} of this reply wait${r.waiting_for.length > 1 ? "" : "s"} for your decision; the answer continues once all are decided.`);
          return;
        }
        for (let i = 0; i < SETTLE_MAX_POLLS; i++) {
          await new Promise((r) => setTimeout(r, SETTLE_POLL_MS));
          const t = await reload(tid);
          const last = [...t.messages].reverse().find((m) => m.role === "assistant");
          if (t.messages.length > before && last && last.status !== "queued" && last.status !== "streaming") break;
        }
        // what every approved proposal of this reply touched, the run last (it shows what the others changed)
        const approved = siblings.filter((a) => (a.approval_id === approvalId ? decision === "approve" : a.status === "approved"));
        const active = ref.current.activeBranch;
        const branchOf = (a: Approval) => (typeof a.args.branch_id === "string" && a.args.branch_id ? a.args.branch_id : bid);
        // a proposal on a branch not in view changes that branch, not the view: the branch list is all that refreshes for it
        const elsewhere = approved.filter((a) => proposalEffect(a.tool) !== "branch" && branchOf(a) !== active);
        const here = approved.filter((a) => !elsewhere.includes(a));
        const effects = [...new Set(here.map((a) => proposalEffect(a.tool)).filter((e): e is ProposalEffect => e != null))];
        for (const effect of effects.sort((a, b) => Number(a === "run") - Number(b === "run"))) await APPLY[effect](active);
        if (elsewhere.length) {
          if (!effects.length) await refreshBranches();
          const names = [...new Set(elsewhere.map((a) => ref.current.branches.find((b) => b.branch_id === branchOf(a))?.name ?? branchOf(a)))];
          toastMsg(`Applied on ${names.join(" and ")}. Switch to it to see the change.`);
        }
      } catch (e) {
        toastMsg(`Recorded; the view could not refresh: ${failureText(e)}`, "warn");
      } finally {
        setBusy(false);
      }
    },
    [APPLY, ref, refreshBranches, reload, setBusy, toastMsg],
  );

  return { loadThreads, openThread, startAsk, closeThread, setInput, ask, askAbout, cancelReply, decideApproval };
}
