// Edits report what kind of edit they were; the ones the refresh policy marks automatic ask for a quiet run (the
// run itself debounces a burst of them into one job). The others leave the result stale until Run.

import { useCallback } from "react";

import { EDIT_POLICY, type EditKind } from "../../lib/refresh";
import type { RunFn } from "./useRun";

export type EditedFn = (kind: EditKind) => void;

export function useAutoRefresh(run: RunFn): EditedFn {
  return useCallback(
    (kind: EditKind) => {
      if (EDIT_POLICY[kind].auto) void run({ quiet: true });
    },
    [run],
  );
}
