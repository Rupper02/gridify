// Which edits re-run the plan by themselves. An edit that leaves the queue's decisions alone (a
// window, a scheduled year) only re-solves the years it touches (the engine's per-year cache), so it
// refreshes quietly in the background; an edit that re-decides the queue (a project, a demand
// profile, a reinforcement the trials must see) waits for the operator's Run and shows as stale.

export type EditKind = "schedule" | "works" | "project" | "profile" | "reinforcement";

export interface EditPolicy {
  /** Refresh automatically (quiet, debounced) instead of waiting for Run. */
  auto: boolean;
}

export const EDIT_POLICY: Record<EditKind, EditPolicy> = {
  schedule: { auto: true }, // re-solves only the years whose energised set changes
  works: { auto: true }, // re-solves the window's year (and later years for a repowering)
  project: { auto: false }, // re-ranks and re-trials the queue
  profile: { auto: false }, // re-trials every phase at the new demand
  reinforcement: { auto: false }, // changes every trial's network
};

/** Wait this long after the last auto edit before refreshing, so a burst of edits is one run. */
export const AUTO_REFRESH_DEBOUNCE_MS = 600;

/**
 * Merge a new run request into the one already waiting (`pending` undefined: none is waiting). The
 * merged run is quiet only if every request that formed it was; a request without the flag is a Run.
 */
export const mergeQuiet = (pending: boolean | undefined, next: boolean | undefined): boolean =>
  (pending ?? true) && !!next;
