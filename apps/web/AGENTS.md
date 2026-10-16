# AGENTS.md — apps/web (the planner)

Vite + React 19 + TypeScript single-page planner, "Gridify Glass" (spec: `docs/design/gridify-glass/`). Read the root
`AGENTS.md` first; this file adds what is specific to the planner. The file-by-file spec is `apps/web/README.md`.

## Conventions

- **State** lives in one object (`PlannerState` in `src/hooks/usePlanner.ts`); `patch` writes it synchronously, so
  `ref.current` is the latest state for async flows. Components read `planner.s`, call `planner.actions` and use
  `planner.derived`; they never write state. If the hook grows past what one file holds comfortably, split it by concern
  (the run, branches, connections) rather than adding layers.
- **One run at a time.** `actions.run()` is the only way a run starts; a newer request supersedes the one in flight (its
  job is cancelled) and a failure stays on the stamp with a Retry, never only as a toast. Edits re-run the branch by
  themselves after a debounce. The year slider never starts a run.
- **`main` is read-only**: the first edit made on it opens a branch (`usePlanner.editable`). Never write `"main"` for a
  branch id outside `MAIN_ID`.
- The planner writes no plan year itself: the years come from `GET /forecasts`.
- Pure logic goes in `src/lib/`; components stay thin. Styles are classes in `src/styles.css`; inline styles only for
  data-driven colours. Icons come from `@phosphor-icons/react`.
- `MapView.tsx` owns the MapLibre instance: layers and icons are added once on `load`, data is pushed with `setData` from
  the memoised GeoJSON in `App.tsx`, and the HTML overlay (`MapMarkers`) is re-projected on each `move`.
- The API origin is `VITE_API_BASE`, default `http://127.0.0.1:8000` (uvicorn listens on IPv4 only).
- The root `.gitignore` ignores every `lib/`; `apps/web/src/lib/` is explicitly un-ignored. Check `git status` shows new
  frontend files before committing.

## Verify before claiming done

- `pnpm --filter web typecheck && pnpm --filter web build` (the typecheck fails on unused locals and parameters: delete
  them, don't suppress).
- Then drive the dev server against a running API in the owner's real Chrome (the `claude-in-chrome` tools) and require
  **zero page errors**. Exercise the flow you changed (branch → connect at a busbar → the run → scrub the years → Limits →
  Compare → merge or discard).
- Take a screenshot of a fresh tab before the first click: the Chrome extension drops input to a background tab until it
  has captured it.
