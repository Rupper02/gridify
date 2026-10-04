// Ask the model: conversations with the answerer agent. A question goes to a thread on the active
// branch; the reply streams back as events (tool calls with their step ids, tokens, the final message)
// and is then re-read as stored, with its trace, flags and evidence. A proposal the agent makes waits
// here for the operator's approval; approving continues the answer.

import { useCallback, useEffect, useRef } from "react";

import { api } from "../../api";
import { mainIdOf } from "../../lib/projects";
import type { Core } from "./core";

const SETTLE_POLL_MS = 1000;
const SETTLE_MAX_POLLS = 90;

export function useAsk({ patch, ref, toastMsg }: Core, refreshBranches: () => Promise<unknown>) {
  const stop = useRef<(() => void) | null>(null); // closes the open event stream
  useEffect(() => () => stop.current?.(), []);

  const setBusy = useCallback((busy: boolean) => patch((st) => ({ chat: { ...st.chat, busy } })), [patch]);

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
            .finally(() => setBusy(false));
          void loadThreads();
        },
        // the connection dropped: if the reply has settled meanwhile, stop following it
        onDrop: () =>
          void api.getThread(ref.current.projectId, tid).then((t) => {
            const m = t.messages.find((x) => x.message_id === messageId);
            if (m && m.status !== "queued" && m.status !== "streaming") end();
          }),
      });
      stop.current = end;
    },
    [loadThreads, patch, ref, reload, setBusy],
  );

  /** Open a stored conversation (and follow a reply still on its way). */
  const openThread = useCallback(
    async (tid: string) => {
      stop.current?.();
      try {
        const t = await api.getThread(ref.current.projectId, tid);
        patch((st) => ({ thread: t, trace: [], chat: { ...st.chat, mode: "ask", input: "", busy: false }, tab: "ask", sideOpen: true }));
        const live = t.messages.find((m) => m.role === "assistant" && (m.status === "queued" || m.status === "streaming"));
        if (live) follow(tid, live.message_id);
      } catch (e) {
        toastMsg(`Could not open the conversation: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
      }
    },
    [follow, patch, ref, toastMsg],
  );

  /** A new conversation on the active branch (the thread is created with the first question). */
  const startAsk = useCallback(() => {
    stop.current?.();
    patch((st) => ({ thread: null, trace: [], chat: { ...st.chat, mode: "ask", input: "", busy: false }, tab: "ask", sideOpen: true }));
    void loadThreads();
  }, [loadThreads, patch]);

  /** Send a question: stored, then its reply followed as it streams. */
  const ask = useCallback(
    async (text: string) => {
      const v = text.trim();
      const st = ref.current;
      if (!v) return;
      if (!st.agents || st.agents.status === "off") {
        toastMsg("The agents are off: the API needs OPENROUTER_API_KEY.", "warn");
        return;
      }
      patch((x) => ({ chat: { ...x.chat, input: "", busy: true } }));
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
        toastMsg(`Could not send that: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
      }
    },
    [follow, loadThreads, patch, ref, reload, setBusy, toastMsg],
  );

  /** Approve or deny a proposal; approving runs it on the branch and the answer continues as a new reply. */
  const decideApproval = useCallback(
    async (approvalId: string, decision: "approve" | "deny", note = "") => {
      const tid = ref.current.thread?.thread_id;
      if (!tid) return;
      const before = ref.current.thread?.messages.length ?? 0;
      setBusy(true);
      try {
        await api.decideApproval(ref.current.projectId, approvalId, decision, note);
        for (let i = 0; i < SETTLE_MAX_POLLS; i++) {
          await new Promise((r) => setTimeout(r, SETTLE_POLL_MS));
          const t = await reload(tid);
          const last = [...t.messages].reverse().find((m) => m.role === "assistant");
          if (t.messages.length > before && last && last.status !== "queued" && last.status !== "streaming") break;
        }
        if (decision === "approve") void refreshBranches(); // a proposal may have opened a branch
      } catch (e) {
        toastMsg(`Could not record the decision: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
      } finally {
        setBusy(false);
      }
    },
    [ref, refreshBranches, reload, setBusy, toastMsg],
  );

  return { loadThreads, openThread, startAsk, ask, decideApproval };
}
