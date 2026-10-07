// Edits report what kind of edit they were: every edit stamps `editedAt` (a run requested before it is outdated, so Run
// restarts it), and the ones the refresh policy marks automatic ask for a quiet restart (the run itself debounces a
// burst of them into one job). The others leave the result stale until Run.

import { useCallback } from "react";

import { EDIT_POLICY, type EditKind } from "../../lib/refresh";
import type { Core } from "./core";
import type { RunFn } from "./useRun";

export type EditedFn = (kind: EditKind) => void;

export function useAutoRefresh({ patch }: Core, run: RunFn): EditedFn {
  return useCallback(
    (kind: EditKind) => {
      patch({ editedAt: Date.now() });
      if (EDIT_POLICY[kind].auto) void run({ quiet: true, restart: true });
    },
    [patch, run],
  );
}
