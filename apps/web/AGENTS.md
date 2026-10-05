# AGENTS.md — apps/web (the planner)

Vite + React 19 + TypeScript single-page planner, "GridForge Glass" (spec: `docs/design/gridforge-glass/`). Read the root
`AGENTS.md` first; this file adds what is specific to the planner. The file-by-file spec is `apps/web/README.md`.

## What it owns

- `src/hooks/usePlanner.ts` composes the hooks in `src/hooks/planner/`: `core`, `slice`, `useRun`, `useBranchFlows`,
  `useBranchList`, `useRegistry`, `useSelection`, `useProjectEdits`, `useMaintenance` (planned works, reinforcements and
  the branch's stored projects: `loadExtras`), `useFindings`, `useAgents` (the agents' status poll, the pause switch, a
  branch's reviews, the evidence drawer), `useAsk` (the planner's one conversation: a streamed reply that can be stopped,
  suggested questions, approvals and what each approved proposal refreshes), `useProjects` (the boot, the project switch,
  import, delete, the assumptions), `useDerived`.
- `src/api.ts` is the typed client: it re-exports `normReason`; `ApiError` carries the status and the API's `detail`;
  every read is project-scoped (`getModel(pid)`, `listBranches(pid)`, the agents' calls take `pid`); `importProject` posts
  the multipart form; `streamReply` wraps `EventSource`.
- `src/lib/` holds the pure derivations: `derive`, `ask` (suggested questions from the state in view; `PROPOSAL_EFFECT`,
  what an approved proposal refreshes), `plan` (the plan's years and phases, from `GET /forecasts`: never write a plan
  year in the planner), `runStages`, `layout`, `geo`, `icons`, `gate` (the merge gate's state for the
  buttons, finding titles, grouping and map targets), `trace` (a reply's events folded into text and stage chips,
  `STAGE_BY_TOOL_PREFIX`, the evidence line, the agents pill), `projects` (`mainIdOf`: the project's plan-of-record
  branch, `DEFAULT_PROJECT_ID`, capability chips, the import report's lines, the known-limit fields), `reasons.ts` (the
  reason normaliser registry).
- `src/components/` is the UI: `Header` (the project capsule opens `ProjectsScreen`; the agents pill), `ProjectsScreen`
  (the projects, Open / Delete, the import form with the known limits, the validation report), `LeftCards` (the result
  stamp carries *What the model assumes* and the synthetic-layout note), `MapView`, `MapMarkers`, `MapControls`,
  `DetailCards`, `Roadmap`, `SidePanel` (a typed `TABS` registry) → `AskTab` (the picker: *Ask anything*, suggested
  questions, conversations; the chat with its trace chips, Stop and approval cards) / `QueueTab` / `OutagesTab` /
  `FindingsTab` (an *evidence* link on agent findings) / `ReviewTab` (merge readiness, then the reviewer's comment),
  `StudyDrawer` (the study behind a cited step), `RunOverlay`, `ui`.
- `MapView.tsx` owns MapLibre (CARTO dark basemap). Icons come from `@phosphor-icons/react`. The planner is live-only
  against the API (`VITE_API_BASE`, default `http://localhost:8000`).

## Conventions

- **State** lives in one object (`PlannerState`, `hooks/planner/core.ts`; `patch` merges partial updates; `ref.current`
  is the latest state for async flows). `usePlanner` only composes the hooks under `hooks/planner/`, each of which takes
  the shared `Core` plus only the other hooks' actions it needs. Put a new flow in the hook that owns its concern, or a
  new hook; don't grow `usePlanner`.
- **Slices:** components never take the whole `Planner`. Each declares the slice it reads with
  `PlannerSlice<state keys, action keys, derived keys>` (+ `WithPatch` / `WithMap` / `WithFormInvalid` when needed,
  `hooks/planner/slice.ts`) and exports it as e.g. `QueueTabPlanner`; a parent's slice is the intersection of its
  children's (`SidePanelPlanner`, `MapViewPlanner`). Reading a field outside the slice fails to compile, so add the key to
  the slice when you use a new field. Only `App.tsx` (the composition root) sees the full `Planner`. Known limit: `patch`
  is still a free-form setter, so what a component may write is not narrowed. Actions that need state React hasn't
  flushed yet take an explicit override (e.g. `run({ activeBranch })`) instead of reading it back.
- **Long calls:** a cold run decides the queue in ~10-20 s, then solves the ten plan years at a few seconds each (about a
  minute; several under load); a cached run is near-instant. Every engine change makes everything cold (the engine
  fingerprint is in every cache key). `run()` keeps its in-flight flag in a ref and coalesces overlapping requests into
  one re-run; a failed call clears the flag and toasts. Keep that pattern for any long call; never drop requests silently.
- **Projects in the planner.** `s.projectId` is the active project and `derived.mainId` its plan-of-record branch
  (`lib/projects.mainIdOf`): never write `"main"` for a branch id in a hook or component (the word *main* in copy is fine:
  every project's plan of record is called that). `useProjects` boots the planner (the projects, then the default
  project's model and branches, then its main's run; the boundary card loads on its own, since on a cold API it is a full
  power flow) and switches projects by resetting everything that belonged to the previous one (`FRESH`). Loading is
  told, not assumed: the result stamp says *Loading the grid…*, a step that fails is retried with a growing pause
  (`lib/boot.ts`: the API still starting, or restarting under `--reload`) and then shown on the stamp with a Retry, never
  only as a toast. What a project cannot do is hidden by `derived.caps` (`project.capabilities`): no boundary card without
  a boundary, no Demand layer without demand groups, no registry section without a registry; a `synthetic` model
  (`model.crs`) gets a blank basemap (`MapView` is keyed by `crs`, so it remounts) and a note under the result stamp.
- **The agents in the planner.** `useAgents` polls `GET /projects/{pid}/agents` every 15 s (and a branch's reviews with it,
  since the reviewer comments a few seconds after a run); `useAsk` keeps one open `EventSource` per reply
  (`api.streamReply`), folds its events into `s.trace` while it streams and re-reads the stored message when it ends.
  A reply's proposals are decided one by one and the answer resumes once all of them are (`waiting_for` until then); the
  planner then polls the thread until the continued answer settles and refreshes what every approved proposal touched
  (`lib/ask.ts` `PROPOSAL_EFFECT`: a run shows the agent's run, which is the branch's run and cached; a project or a change
  to one re-reads the branch's stored projects (`GET /branches/{id}/candidates`, `s.candidates`) and the result shows as
  out of date; a reinforcement or a works window re-reads them and applies the edit policy); `cancelReply` stops a reply
  (`POST .../threads/{tid}/cancel`). The side panel's first tab is `ask` (the `Tab` key; label *Ask*) and it is the
  planner's **only** conversation: no scripted or deterministic chats, ever; every suggested question (`lib/ask.ts`
  `suggestedQuestions`, from what is in view) and every card button (*Ask the agents how it could connect*) goes to the
  answerer. The only non-answering state is `starting` (the API's runtime not launched yet): the pill says so and the
  composer waits.
- **Runs are explicit.** Adding a project (from the registry, or an agent's approved proposal) makes it Preliminary until
  the next run; changing the demand profile or a reinforcement marks the shown result stale (**Re-run**); a works window
  or an energisation year refreshes quietly by itself (`lib/refresh.ts` `EDIT_POLICY`). The year slider **never** starts a
  run: every run solves all years, and the slider only switches between them (years still arriving as partial results
  show as solving).
- Pure logic goes in `src/lib/` or `src/api.ts`; components stay thin (no new tests: see the root *Testing instructions*).
  Styles are classes in `src/styles.css`; inline styles only for data-driven colours.
- `MapView.tsx` owns the MapLibre instance: layers/icons are added once on `load`, data is pushed with `setData` from the
  memoised GeoJSON in `App.tsx`, and the HTML overlay (`MapMarkers`: project markers, substation names,
  loading/diff/outage tags) is re-projected on each `move`.
- The root `.gitignore` is a Python template that ignores every `lib/`; `apps/web/src/lib/` is explicitly un-ignored. Check
  `git status` shows new frontend files before committing.

## Verify before claiming done

- `pnpm --filter web typecheck && pnpm --filter web build` (the typecheck fails on unused locals and parameters: delete
  them, don't suppress).
- Then drive the dev server against a running API in the owner's real Chrome (the `claude-in-chrome` tools: look at every
  screen as a QA engineer would, read the console) and require **zero page errors**. A scripted headless browser
  (Playwright in a scratch dir, `--use-gl=swiftshader`) is a fallback, not the check, and never with an emulated viewport.
- Exercise the flow you changed (branch → add project → run → scrub the years → review; for the agents: ask → the trace
  → a proposal → approve → the planner refreshes).
- `uvicorn --reload` only restarts after the current job and the agent runtime have shut down: after an API edit during a
  long solve, check the log for "Application startup complete" before trusting what you see, or restart the API.
- Take a screenshot of a fresh tab before the first click: the Chrome extension drops input to a background tab until it
  has captured it, which looks like a click the planner ignored.
- To see a cold start without touching the real data, run a second API on a spare port with scratch databases and a dummy
  key (it starts, and any agent call fails, so nothing is spent), and a Vite copy pointed at it:
  ```bash
  cd apps/api && GRIDFORGE_SCENARIOS_DB=<scratch>/s.duckdb GRIDFORGE_DBOS_URL=sqlite:///<scratch>/dbos.sqlite \
    GRIDFORGE_PROJECTS_DIR=<scratch>/projects OPENROUTER_API_KEY=sk-invalid uv run uvicorn gridforge_api.main:app --port 8179
  cd apps/web && VITE_API_BASE=http://localhost:8179 pnpm exec vite --port 3177 --strictPort
  ```
