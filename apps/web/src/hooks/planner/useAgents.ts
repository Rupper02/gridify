// The project's agents as the planner sees them: their status (polled), the pause switch, the runs
// list (read only while the Review tab shows it: the note's "writing" line), the engineer's note on the
// active branch's run, and the evidence drawer behind a step an agent cited.

import { useCallback, useEffect } from "react";

import { api, failureText } from "../../api";
import type { Core } from "./core";

const POLL_MS = 15_000;

export function useAgents({ patch, ref, toastMsg }: Core, projectId: string) {
  const loadAgents = useCallback(async () => {
    try {
      const pid = ref.current.projectId;
      const agents = await api.agentsStatus(pid);
      if (ref.current.projectId === pid) patch({ agents });
    } catch {
      /* the pill keeps its last state */
    }
  }, [patch, ref]);

  /** The project's agent runs, newest first. Ignored if the planner moved to another project. */
  const loadAgentRuns = useCallback(async () => {
    try {
      const pid = ref.current.projectId;
      const agentRuns = await api.listAgentRuns(pid);
      if (ref.current.projectId === pid) patch({ agentRuns });
    } catch {
      /* the list keeps its last state */
    }
  }, [patch, ref]);

  /** The engineer's note on a branch's run (main's too). Ignored if the planner moved on. */
  const loadNote = useCallback(
    async (bid: string) => {
      if (!bid) return;
      try {
        const note = await api.branchNote(bid);
        if (ref.current.activeBranch === bid) patch({ note });
      } catch {
        /* the Review tab shows no note */
      }
    },
    [patch, ref],
  );

  const setAgentsPaused = useCallback(
    async (paused: boolean) => {
      try {
        const pid = ref.current.projectId;
        patch({ agents: paused ? await api.pauseAgents(pid) : await api.resumeAgents(pid) });
        toastMsg(paused ? "Agents paused for this project. Nothing new starts until you resume." : "Agents resumed.");
      } catch (e) {
        toastMsg(`Could not ${paused ? "pause" : "resume"} the agents: ${failureText(e)}`, "warn");
      }
    },
    [patch, ref, toastMsg],
  );

  /** Open the evidence behind a step: the study it ran, re-read from the durable cache. */
  const openEvidence = useCallback(
    async (stepId: string) => {
      try {
        patch({ study: await api.stepEvidence(ref.current.projectId, stepId) });
      } catch (e) {
        toastMsg(`No evidence for that step: ${failureText(e)}`, "warn");
      }
    },
    [patch, ref, toastMsg],
  );
  const closeEvidence = useCallback(() => patch({ study: null }), [patch]);

  // the status, at once for each project opened and then every few seconds; while the Review tab shows, the branch's
  // note refreshes with it (the note is written a few seconds after a run), and the runs list while something shows it
  useEffect(() => {
    void loadAgents();
    const id = window.setInterval(() => {
      void loadAgents();
      const st = ref.current;
      const review = st.tab === "review" && !!st.activeBranch;
      if (review) void loadNote(st.activeBranch);
      if (review) void loadAgentRuns(); // the Review tab's note line reads them ("writing the note…")
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [loadAgentRuns, loadAgents, loadNote, ref, projectId]);

  return { loadAgents, loadAgentRuns, loadNote, setAgentsPaused, openEvidence, closeEvidence };
}
