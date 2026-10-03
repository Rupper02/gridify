# GridForge web

The planner UI ("GridForge Glass", designed in `docs/design/gridforge-glass/`): a single-page **Vite + React 19 + TypeScript** app around a full-bleed MapLibre map, with floating panels on top. It talks to the FastAPI service in `apps/api` and has no server of its own.

| Path | Role |
|---|---|
| `src/App.tsx` | The composition root: the only file that sees the full `Planner`. Lays out the header, left cards, map, roadmap dock and side panel; derives the map's GeoJSON from state |
| `src/hooks/usePlanner.ts` | Composes the hooks under `src/hooks/planner/` into one `Planner` |
| `src/hooks/planner/` | `core` (the `PlannerState` object and `patch`), `slice` (the `PlannerSlice` types components declare), `useRun` (jobs, partial results, cancelling a superseded job, quiet runs), `useAutoRefresh` (edits the policy in `lib/refresh.ts` marks automatic re-run quietly), `useBranchFlows`, `useBranchList`, `useRegistry`, `useSelection`, `useProjectEdits`, `useMaintenance` (planned works), `useCopilot` (intake chat, recommendations, try-a-lever), `useDerived` |
| `src/api.ts` | Typed client for the API; re-exports `normReason` |
| `src/lib/` | Pure helpers, with vitest next to them: `derive` (queue and year derivations), `maintenance` (planned works in words: the schedule form body, tags, the verdict registry and its plain-English detail), `intake` (the Copilot's New project conversation), `recs` (Recommendations wording and lever actions), `runStages` (job stage to overlay step), `layout` (laptop breakpoints), `reasons` (the reason normaliser registry), `geo` (GeoJSON), `icons` (canvas map icons) |
| `src/components/` | `Header` (branch picker, demand profile, Run / Re-run), `LeftCards` (result stamp and readings), `MapView` (MapLibre), `MapMarkers`, `MapControls`, `DetailCards` (project and element cards), `WindowVerdict` (a works window's verdict chip and detail), `Roadmap` (year slider dock), `SidePanel` → `CopilotTab` / `QueueTab` / `OutagesTab` / `ReviewTab`, `RunOverlay`, `ui` (shared bits: `TechIcon`, toggles, steppers, diff tiles) |
| `src/theme.ts`, `src/styles.css` | Status, technology (`TECH`) and branch-hue colours, and the stylesheet |

## How it behaves

- **Cheap edits refresh by themselves; queue edits wait for Run** (`lib/refresh.ts` `EDIT_POLICY`). Scheduling a works window or changing an energisation year re-solves only the years it touches (the API's per-year cache) in a quiet run: no overlay, the stamp says it is updating. Adding a project (Preliminary until the next run), changing the demand profile or adding a reinforcement re-decides the queue, so the result shows as out of date (the button reads **Re-run**) until you run. A newer run cancels the one in flight.
- **The year slider never runs.** Every run solves all years 2026 to 2035; the slider switches between them. While a job runs, the queue and each year appear as the API publishes them, the year in view first. The run overlay follows the job's real stages.
- **Branches.** Each branch has its own hue, which frames the map. `main` is read-only for proposals (outages and reinforcements need a branch), but its demand profile stays editable: a deliberate departure from the design.
- **Copilot.** *New project* is a guided intake that drafts a project and adds it to the branch; *Recommendations* lists the levers for deferred projects, and *Try on &lt;branch&gt;* stores a lever as a simulated reinforcement for the next run to measure (on `main` it opens a new branch first).
- **Outages** lists the planned works on a line, transformer or existing generator, grouped by year with a summary line. The element card schedules them: *Maintenance* (full outage or derate to 50%), *Repowering* (uprate by 1.25x to 4x, or a parallel circuit / second unit, applied to the years after the window; the queue is not re-run for it) or *Replacement* (back like-for-like). Once a run studies a window it shows the engine's verdict (Feasible, Curtailment, Demand at risk, Not feasible) with the curtailed generators by name, MW and case, demand at risk, the windows studied with it, the N-1 screen during it and what the work leaves behind; map tags and roadmap chips carry the work type and are bordered in the verdict colour. **Review** shows the consequence diff against `main`, and diff mode highlights it on the map.
- Icons come from `@phosphor-icons/react`.

```bash
pnpm --filter web dev        # http://localhost:3000  (needs the API: pnpm --filter @gridforge/api dev)
pnpm --filter web test       # vitest: reason normalisation, derivations, Copilot intake and recommendations, run stages
pnpm --filter web build      # tsc --noEmit + vite build -> dist/
```

The API origin defaults to `http://localhost:8000`; set `VITE_API_BASE` to point elsewhere.

Basemap: CARTO dark matter (no labels), © CARTO, © OpenStreetMap contributors. Substation positions come from the API's model.

See the [root README](../../README.md) for the full system and the quickstart.
