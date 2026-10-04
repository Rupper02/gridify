// The project's agents as the planner sees them: their status (polled), the pause switch, the
// reviewer's comments on the active branch, and the evidence drawer behind a step an agent cited.

import { useCallback, useEffect } from "react";

import { api } from "../../api";
import { mainIdOf } from "../../lib/projects";
import type { Core } from "./core";

const POLL_MS = 15_000;

export function useAgents({ patch, ref, toastMsg }: Core) {
  const loadAgents = useCallback(async () => {
    try {
      const pid = ref.current.projectId;
      const agents = await api.agentsStatus(pid);
      if (ref.current.projectId === pid) patch({ agents });
    } catch {
      /* the pill keeps its last state */
    }
  }, [patch, ref]);

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
        toastMsg(`Could not ${paused ? "pause" : "resume"} the agents: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
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
        toastMsg(`No evidence for that step: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
      }
    },
    [patch, ref, toastMsg],
  );
  const closeEvidence = useCallback(() => patch({ study: null }), [patch]);

  // the status, once at start and then every few seconds; a branch's reviews refresh with it (the
  // reviewer comments a few seconds after a run)
  useEffect(() => {
    void loadAgents();
    const id = window.setInterval(() => {
      void loadAgents();
      const bid = ref.current.activeBranch;
      if (bid && bid !== mainIdOf(ref.current.projects, ref.current.projectId)) void loadReviews(bid);
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [loadAgents, loadReviews, ref]);

  return { loadAgents, loadReviews, setAgentsPaused, openEvidence, closeEvidence };
}
