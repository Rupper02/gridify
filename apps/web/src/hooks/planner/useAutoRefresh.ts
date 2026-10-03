// Edits report what kind of edit they were; the ones the refresh policy marks automatic re-run the
// plan quietly (no overlay) after a short debounce. The others leave the result stale until Run.

import { useCallback, useEffect, useRef } from "react";

import { AUTO_REFRESH_DEBOUNCE_MS, EDIT_POLICY, type EditKind } from "../../lib/refresh";
import type { Core } from "./core";
import type { RunFn } from "./useRun";

export type EditedFn = (kind: EditKind) => void;

export function useAutoRefresh({ patch, ref }: Core, run: RunFn): EditedFn {
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  return useCallback(
    (kind: EditKind) => {
      if (!EDIT_POLICY[kind].auto) return;
      const bid = ref.current.activeBranch;
      patch({ refreshing: true });
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        if (ref.current.activeBranch === bid) void run({ activeBranch: bid, quiet: true });
        else patch({ refreshing: false });
      }, AUTO_REFRESH_DEBOUNCE_MS);
    },
    [patch, ref, run],
  );
}
