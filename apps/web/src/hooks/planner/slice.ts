// Narrow views of the planner. A component declares the slice it reads (`PlannerSlice<"result" | "sel",
// "selectProject">`) instead of taking the whole `Planner`: its real dependencies are in its type, a
// test can pass a small fake, and a parent's slice is the intersection of its children's slices.
// `patch` and `mapApi` are opt-in extras (`WithPatch`, `WithMap`) because most components need neither.

import type { Planner } from "../usePlanner";

export type PlannerSlice<
  S extends keyof Planner["s"] = never,
  A extends keyof Planner["actions"] = never,
  D extends keyof Planner["derived"] = never,
> = {
  s: Pick<Planner["s"], S>;
  actions: Pick<Planner["actions"], A>;
  derived: Pick<Planner["derived"], D>;
};

export type WithPatch = Pick<Planner, "patch">;
export type WithMap = Pick<Planner, "mapApi">;
