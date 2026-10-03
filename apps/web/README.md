# GridForge web

The planner UI ("GridForge Glass", designed in `docs/design/gridforge-glass/`): a single-page **Vite + React 19 + TypeScript** app around a full-bleed MapLibre map, with floating panels on top. It talks to the FastAPI service in `apps/api` and has no server of its own.

| Path | Role |
|---|---|
| `src/App.tsx` | The composition root: the only file that sees the full `Planner`. Lays out the header, left cards, map, roadmap dock and side panel; derives the map's GeoJSON from state |
| `src/hooks/usePlanner.ts` | Composes the hooks under `src/hooks/planner/` into one `Planner` |
| `src/hooks/planner/` | `core` (the `PlannerState` object and `patch`), `slice` (the `PlannerSlice` types components declare), `useRun` (jobs, partial results, the stale check), `useBranchFlows`, `useBranchList`, `useRegistry`, `useSelection`, `useProjectEdits`, `useMaintenance` (outages), `useCopilot` (intake chat, recommendations, try-a-lever), `useDerived` |
| `src/api.ts` | Typed client for the API; re-exports `normReason` |
| `src/lib/` | Pure helpers, with vitest next to them: `derive` (queue and year derivations), `intake` (the Copilot's New project conversation), `recs` (Recommendations wording and lever actions), `runStages` (job stage to overlay step), `layout` (laptop breakpoints), `reasons` (the reason normaliser registry), `diff` (the per-year diff: Review sentences, map deltas, planned works wording), `geo` (GeoJSON), `icons` (canvas map icons) |
| `src/components/` | `Header` (branch picker, demand profile, Run / Re-run), `LeftCards` (result stamp and readings), `MapView` (MapLibre), `MapMarkers`, `MapControls`, `DetailCards` (project and element cards), `Roadmap` (year slider dock), `SidePanel` → `CopilotTab` / `QueueTab` / `OutagesTab` / `ReviewTab`, `RunOverlay`, `ui` (shared bits: `TechIcon`, toggles, steppers, diff tiles) |
| `src/theme.ts`, `src/styles.css` | Status, technology (`TECH`) and branch-hue colours, and the stylesheet |

## How it behaves

- **Runs are explicit.** Adding a project (from the registry or through the Copilot) puts it in *Preliminary* on the branch until the next run. Changing the demand profile does not run either. The result is shown as out of date (the button reads **Re-run**) when the profile, outages, reinforcements, schedule or preliminary projects have changed since it was computed.
- **The year slider never runs.** Every run solves all years 2026 to 2035; the slider switches between them. While a job runs, the queue and each year appear as the API publishes them, the year in view first. The run overlay follows the job's real stages.
- **Branches.** Each branch has its own hue, which frames the map. `main` is read-only for proposals (outages and reinforcements need a branch), but its demand profile stays editable: a deliberate departure from the design.
- **Copilot.** *New project* is a guided intake that drafts a project and adds it to the branch; *Recommendations* lists the levers for deferred projects, and *Try on &lt;branch&gt;* stores a lever as a simulated reinforcement for the next run to measure (on `main` it opens a new branch first).
- **Outages** schedules maintenance windows on a line, transformer or existing generator; **Review** shows the consequence diff against `main`: the 2030/2035 tiles, the network effect of the year on the timeline (its year picker moves the planner's year; a dot marks years where something gets worse), and the planned works with their verdict on `main` vs the branch. Diff mode tags the viewed year's line and transformer loading changes on the map.
- Icons come from `@phosphor-icons/react`.

```bash
pnpm --filter web dev        # http://localhost:3000  (needs the API: pnpm --filter @gridforge/api dev)
pnpm --filter web test       # vitest: reason normalisation, derivations, Copilot intake and recommendations, run stages
pnpm --filter web build      # tsc --noEmit + vite build -> dist/
```

The API origin defaults to `http://localhost:8000`; set `VITE_API_BASE` to point elsewhere.

Basemap: CARTO dark matter (no labels), © CARTO, © OpenStreetMap contributors. Substation positions come from the API's model.

See the [root README](../../README.md) for the full system and the quickstart.
