// Values derived from the planner state that several components share.

import { useMemo } from "react";

import {
  branchHue,
  changedProjects,
  indexModel,
  knownProjects,
  preliminaryOf,
  staleness,
  yearResultFor,
  parentName,
} from "../../lib/derive";
import { type SiteRoom, bindingIndex, siteRooms } from "../../lib/capacity";
import { type DiffMap, diffMapFor, yearDeltaFor } from "../../lib/diff";
import { sectionsByStatus } from "../../lib/findings";
import { gateState } from "../../lib/gate";
import { lineTiers } from "../../lib/mapFeatures";
import { ALL_CAPABILITIES, mainIdOf, projectOf } from "../../lib/projects";
import { runView } from "../../lib/runStages";
import { profileOf } from "../../theme";
import type { QueueItem } from "../../types";
import type { PlannerState } from "./core";

export function useDerived(s: PlannerState) {
  const ix = useMemo(() => (s.model ? indexModel(s.model) : null), [s.model]);
  // the grid's own line voltages in three tiers: how lines are drawn, labelled and toggled on any grid
  const tiers = useMemo(() => lineTiers((s.model?.lines ?? []).map((l) => l.voltage_kv)), [s.model]);

  const view = useMemo(() => {
    const project = projectOf(s.projects, s.projectId);
    const mainId = mainIdOf(s.projects, s.projectId);
    const caps = project?.capabilities ?? ALL_CAPABILITIES;
    const synthetic = s.model?.crs === "synthetic";
    const onMain = !s.activeBranch || s.activeBranch === mainId;
    const branch = s.branches.find((b) => b.branch_id === s.activeBranch) ?? null;
    const hue = branchHue(s.branches, s.activeBranch, mainId);
    // null until the branch (or the engine's default) is known: nothing claims a profile before then
    const profile = profileOf(branch?.scenario ?? s.defaultScenario);
    const resultProfile = s.result ? profileOf(s.result.params.scenario) : profile;
    const q: QueueItem[] = s.result ? s.result.queue : [];
    const qById: Record<string, QueueItem> = Object.fromEntries(q.map((x) => [x.request_id, x]));
    // the branch's projects: as stored (the API), plus the ones added this session before the store was re-read
    const prelim = preliminaryOf(knownProjects(s.candidates, s.added[s.activeBranch] ?? []), s.result);
    const stale = staleness(s.result, branch, s.outages, s.reinforcements, prelim.length, changedProjects(s.candidates, q));
    const yearsSolved = s.result ? Object.keys(s.result.years ?? {}).length : 0;
    // years the engine ran but whose power flow did not converge: they have no figures to show
    const yearsFailed = s.result ? Object.values(s.result.years ?? {}).filter((y) => y.converged === false).length : 0;
    const yearsTotal = s.result?.years_total ?? s.plan?.years.length ?? 0;
    // where the run stands: the stamp, the roadmap, the readings, every Run button, the stale box and the gate read it
    const run = runView(s.run, { hasResult: !!s.result, yearsSolved, yearsFailed, yearsTotal, editedAt: s.editedAt });
    // projects that exist only on this branch: not in main's plan (the diff's base), or preliminary
    const branchOnly = new Set<string>(prelim.map((p) => p.request_id));
    if (!onMain && s.diff) s.diff.projects.forEach((p) => p.base_status == null && branchOnly.add(p.request_id));
    const bindLines = new Set<number>();
    q.forEach((x) => x.status === "Deferred" && x.reason?.element?.line_id != null && bindLines.add(x.reason.element.line_id));
    // the merge gate as the buttons show it, and the ledger's open counts for the tab's badge
    const gate = gateState(s.mergeCheck, stale, (branch?.status ?? "open") === "open", run, s.gateError);
    // what the branch is judged against and merges into: its parent (main, or the branch it was opened from)
    const parent = parentName(s.branches, branch, mainId);
    // the proposals waiting in the open conversation
    const pendingApprovals = s.thread?.approvals.filter((a) => a.status === "pending").length ?? 0;
    return { project, mainId, caps, synthetic, onMain, branch, hue, profile, resultProfile, q, qById, prelim, stale, yearsSolved, yearsFailed, yearsTotal, branchOnly, bindLines, gate, pendingApprovals, parent, run };
  }, [s.activeBranch, s.added, s.branches, s.candidates, s.diff, s.mergeCheck, s.model?.crs, s.outages, s.projectId, s.projects, s.reinforcements, s.result, s.run, s.thread]);

  // the ledger folded across plan years, per status: the Limits tab's findings fold reads it
  const findingSections = useMemo(() => sectionsByStatus(s.findings), [s.findings]);
  // the binding set by element, and the room at each substation: the Headroom layer and the Capacity tab read them
  const bindIx = useMemo(() => bindingIndex(s.limits), [s.limits]);
  const rooms = useMemo(() => (s.model ? siteRooms(s.model, s.hosting.export, s.hosting.import) : new Map<string, SiteRoom>()), [s.model, s.hosting.export, s.hosting.import]);

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

  return { ix, tiers, ...view, ...year, findingSections, bindIx, rooms };
}
