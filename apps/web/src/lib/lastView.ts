// The project and branch the planner was showing, remembered in this browser so a reload comes back to them
// instead of to main. A per-viewer convenience: a missing or stale entry just opens the default.

const KEY = "gridforge.lastView";

export type LastView = { projectId: string; branchId: string };

export function loadLastView(): LastView | null {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return raw && typeof raw.projectId === "string" && typeof raw.branchId === "string" ? raw : null;
  } catch {
    return null; // private mode, blocked storage, bad JSON
  }
}

export function saveLastView(view: LastView): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(view));
  } catch {
    /* not remembered: fine */
  }
}
