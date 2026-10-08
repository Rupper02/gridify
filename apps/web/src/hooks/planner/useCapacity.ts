// The room to connect at each substation today: the engine's hosting-capacity study on the branch's network (its
// reinforcements; not its projects or demand growth), generation at summer minimum and demand at winter peak. Read from
// the cache while the Capacity tab or the Headroom layer shows; measured only when the operator asks (minutes the
// first time, shared by every branch with the same reinforcements).

import { useCallback, useEffect, useMemo } from "react";

import { api, failureText, notSolved } from "../../api";
import { type Direction, HOSTING_IDLE, hostingBuses, hostingKey, hostingParams } from "../../lib/capacity";
import { latestWins } from "../../lib/latest";
import { lineTiers } from "../../lib/mapFeatures";
import type { Core, PlannerState } from "./core";

const STUDY = "hosting_capacity";
const DIRECTION_LABEL: Record<Direction, string> = { export: "generation", import: "demand" };

const keyOf = (st: PlannerState): string => (st.model && st.activeBranch ? hostingKey(st.activeBranch, st.reinforcements.map((r) => r.reinforcement_id)) : "");
const busesOf = (st: PlannerState): number[] => (st.model ? hostingBuses(st.model, lineTiers(st.model.lines.map((l) => l.voltage_kv))) : []);

export function useCapacity({ patch, ref }: Core, s: Pick<PlannerState, "tab" | "layer" | "model" | "activeBranch" | "reinforcements" | "hosting">) {
  const begin = useMemo(() => latestWins(), []);

  /** The room as the cache holds it, both directions; "absent" until it has been measured for these inputs. */
  const loadHosting = useCallback(async () => {
    const st = ref.current;
    const key = keyOf(st);
    if (!key) return;
    const isLatest = begin("hosting");
    patch({ hosting: { ...HOSTING_IDLE, key, status: "reading" } });
    const buses = busesOf(st);
    const read = (d: Direction) =>
      api.cachedStudy(st.activeBranch, STUDY, hostingParams(buses, d)).catch((e) => {
        if (notSolved(e)) return null;
        throw e;
      });
    try {
      const [exp, imp] = await Promise.all([read("export"), read("import")]);
      if (!isLatest() || keyOf(ref.current) !== key) return;
      patch({ hosting: { ...HOSTING_IDLE, key, export: exp, import: imp, status: exp && imp ? "ready" : "absent" } });
    } catch (e) {
      if (isLatest() && keyOf(ref.current) === key) patch({ hosting: { ...HOSTING_IDLE, key, status: "failed", error: failureText(e) } });
    }
  }, [begin, patch, ref]);

  /** Measure what the cache lacks, generation first, as background jobs; the planner may move on meanwhile (the jobs
   * finish and stay cached, and nothing lands on another branch's view). */
  const measureHosting = useCallback(async () => {
    const st = ref.current;
    const key = keyOf(st);
    if (!key || st.hosting.status === "measuring") return;
    const bid = st.activeBranch;
    const buses = busesOf(st);
    const current = () => keyOf(ref.current) === key;
    patch((x) => ({ hosting: { ...x.hosting, key, status: "measuring", error: null, stage: "", fraction: 0 } }));
    try {
      for (const d of ["export", "import"] as Direction[]) {
        if (ref.current.hosting[d]) continue;
        const res = await api.runStudy(bid, STUDY, hostingParams(buses, d), (stage, fraction) => {
          const done = stage ? `${Math.round(fraction * buses.length)} of ${buses.length} busbars` : "waiting for the solver";
          if (current()) patch((x) => ({ hosting: { ...x.hosting, stage: `${DIRECTION_LABEL[d]}: ${done}`, fraction } }));
        });
        if (!current()) return;
        patch((x) => ({ hosting: { ...x.hosting, [d]: res } }));
      }
      patch((x) => ({ hosting: { ...x.hosting, status: "ready", stage: "", fraction: 1 } }));
    } catch (e) {
      if (current()) patch((x) => ({ hosting: { ...x.hosting, status: "failed", error: failureText(e) } }));
    }
  }, [patch, ref]);

  const want = s.tab === "capacity" || s.layer === "headroom";
  const key = s.model && s.activeBranch ? hostingKey(s.activeBranch, s.reinforcements.map((r) => r.reinforcement_id)) : "";
  const loadedFor = s.hosting.key;
  useEffect(() => {
    if (want && key && loadedFor !== key) void loadHosting();
  }, [want, key, loadedFor, loadHosting]);

  return { loadHosting, measureHosting };
}
