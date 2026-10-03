// Values derived from the planner state that several components share.

import { useMemo } from "react";

import {
  branchHue,
  indexModel,
  preliminaryOf,
  staleness,
  yearResultFor,
} from "../../lib/derive";
import { type DiffMap, diffMapFor, yearDeltaFor } from "../../lib/diff";
import { gateState, openCounts } from "../../lib/gate";
import { profileOf } from "../../theme";
import type { QueueItem } from "../../types";
import type { PlannerState } from "./core";

export function useDerived(s: PlannerState) {
  const ix = useMemo(() => (s.model ? indexModel(s.model) : null), [s.model]);

  const view = useMemo(() => {
    const onMain = !s.activeBranch || s.activeBranch === "main";
    const branch = s.branches.find((b) => b.branch_id === (s.activeBranch || "main")) ?? null;
    const hue = branchHue(s.branches, s.activeBranch);
    const profile = profileOf(branch?.scenario ?? "ht");
    const resultProfile = s.result ? profileOf(s.result.params.scenario) : profile;
    const q: QueueItem[] = s.result ? s.result.queue : [];
    const qById: Record<string, QueueItem> = Object.fromEntries(q.map((x) => [x.request_id, x]));
    const prelim = preliminaryOf(s.added[s.activeBranch] ?? [], s.result);
    const stale = staleness(s.result, branch, s.outages, s.reinforcements, prelim.length);
    const yearsSolved = s.result ? Object.keys(s.result.years ?? {}).length : 0;
    const yearsTotal = s.result?.years_total ?? 10;
    // projects that exist only on this branch: not in main's plan (the diff's base), or preliminary
    const branchOnly = new Set<string>(prelim.map((p) => p.request_id));
    if (!onMain && s.diff) s.diff.projects.forEach((p) => p.base_status == null && branchOnly.add(p.request_id));
    const bindLines = new Set<number>();
    q.forEach((x) => x.status === "Deferred" && x.reason?.element?.line_id != null && bindLines.add(x.reason.element.line_id));
    // the merge gate as the buttons show it, and the ledger's open counts for the tab's badge
    const gate = gateState(s.mergeCheck, stale, (branch?.status ?? "open") === "open", s.running);
    const openFindings = openCounts(s.findings);
    return { onMain, branch, hue, profile, resultProfile, q, qById, prelim, stale, yearsSolved, yearsTotal, branchOnly, bindLines, gate, openFindings };
  }, [s.activeBranch, s.added, s.branches, s.diff, s.findings, s.mergeCheck, s.outages, s.reinforcements, s.result, s.running]);

  const year = useMemo(() => {
    const { yr, exact } = yearResultFor(s.result, s.year);
    const studied = new Set(s.result?.studied?.outage_ids ?? []);
    const outLines = new Set<number>();
    s.outages.forEach((o) => o.year === s.year && o.element_kind === "line" && studied.has(o.outage_id) && outLines.add(Number(o.element_id)));
    // the branch vs main in the viewed year; in diff mode, the loading change per line and transformer
    const yearDelta = yearDeltaFor(s.diff, s.year);
    const diffDeltas: DiffMap | null = s.diffMode && s.diff ? diffMapFor(yearDelta) : null;
    return { yr, exact, outLines, yearDelta, diffDeltas };
  }, [s.diff, s.diffMode, s.outages, s.result, s.year]);

  return { ix, ...view, ...year };
}
