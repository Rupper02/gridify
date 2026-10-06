// The project's agents as the planner sees them: their status (polled), the pause switch, the runs
// list (read only while the pill's popover or the Review tab shows it), the reviewer's comments on the
// active branch, and the evidence drawer behind a step an agent cited.

import { useCallback, useEffect } from "react";

import { api, failureText } from "../../api";
import { mainIdOf } from "../../lib/projects";
import type { Core } from "./core";

const POLL_MS = 15_000;

export function useAgents({ patch, ref, toastMsg }: Core, projectId: string, loadFindings: (bid: string) => Promise<unknown>) {
  const loadAgents = useCallback(async () => {
    try {
      const pid = ref.current.projectId;
      const before = ref.current.agents?.running ?? 0;
      const agents = await api.agentsStatus(pid);
      if (ref.current.projectId !== pid) return;
      patch({ agents });
      // a run just ended: a specialist may have filed findings on the branch in view, so the ledger is read again
      if (before > agents.running && ref.current.activeBranch) void loadFindings(ref.current.activeBranch);
    } catch {
      /* the pill keeps its last state */
    }
  }, [loadFindings, patch, ref]);

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

  /** Open or close the pill's runs popover; opening reads the runs at once (the poll refreshes them while it is open). */
  const setRunsOpen = useCallback(
    (runsOpen: boolean) => {
      patch({ runsOpen });
      if (runsOpen) void loadAgentRuns();
    },
    [loadAgentRuns, patch],
  );

  /** The reviewer's comments on a branch (main is never reviewed). Ignored if the planner moved on. */
  const loadReviews = useCallback(
    async (bid: string) => {
      if (!bid || bid === mainIdOf(ref.current.projects, ref.current.projectId)) return;
      try {
        const reviews = await api.listReviews(bid);
        if (ref.current.activeBranch === bid) patch({ reviews });
      } catch {
        /* the Review tab shows no review */
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

  // the status, at once for each project opened and then every few seconds; a branch's reviews refresh
  // with it (the reviewer comments a few seconds after a run), and the runs list while something shows it
  useEffect(() => {
    void loadAgents();
    const id = window.setInterval(() => {
      void loadAgents();
      const st = ref.current;
      const bid = st.activeBranch;
      const onBranch = !!bid && bid !== mainIdOf(st.projects, st.projectId);
      if (onBranch) void loadReviews(bid);
      if (st.runsOpen || (onBranch && st.tab === "review")) void loadAgentRuns();
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [loadAgentRuns, loadAgents, loadReviews, ref, projectId]);

  return { loadAgents, loadAgentRuns, setRunsOpen, loadReviews, setAgentsPaused, openEvidence, closeEvidence };
}
