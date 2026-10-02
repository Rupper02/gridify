// Values derived from the planner state that several components share.

import { useMemo } from "react";

import type { QueueItem } from "../../types";
import type { PlannerState } from "./core";

export function useDerived(s: PlannerState) {
  return useMemo(() => {
    const onMainView = !s.activeBranch || s.activeBranch === "main";
    const activeB = onMainView ? null : (s.branches.find((b) => b.branch_id === s.activeBranch) ?? null);
    const eg30 = activeB ? activeB.growth_2030 : s.g30;
    const eg35 = activeB ? activeB.growth_2035 : s.g35;
    
    // For year-specific studies, use the timeline year as the phase key
    const phaseKey = String(s.timelineYear);
    // Fallback to legacy 2030/2035 if year-specific phase doesn't exist
    const legacyPhase = s.timelineYear <= 2030 ? ("2030" as const) : ("2035" as const);
    
    // Try to get year-specific phase, fall back to legacy phase
    const ph = s.result 
      ? (s.result.phases[phaseKey] ?? s.result.phases[legacyPhase]) 
      : null;
    
    const phase = phaseKey;  // expose the actual phase key being used
    const q: QueueItem[] = s.result ? s.result.queue : [];
    const qById: Record<string, QueueItem> = Object.fromEntries(q.map((x) => [x.request_id, x]));
    const fc = s.forecasts.find((x) => x.id === s.forecastId);
    const fcEff = activeB ? (s.forecasts.find((x) => x.id === activeB.scenario) ?? fc) : fc;
    const reviewB = s.branches.find((b) => b.branch_id === s.activeBranch) ?? null;
    const hasReviewBranch = !!(reviewB && reviewB.branch_id !== "main");
    const manualIds = new Set(s.cands.filter((c) => c.manual).map((c) => c.request_id));
    return { onMainView, activeB, eg30, eg35, phase, ph, q, qById, fc, fcEff, reviewB, hasReviewBranch, manualIds };
  }, [s.activeBranch, s.branches, s.cands, s.forecastId, s.forecasts, s.g30, s.g35, s.result, s.timelineYear]);
}
