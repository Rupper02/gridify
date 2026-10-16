# GridForge web

The planner ("GridForge Glass", designed in `docs/design/gridforge-glass/`): a single-page **Vite + React 19 + TypeScript** app around a full-bleed MapLibre map, with floating panels on top. It talks to the FastAPI service in `apps/api` and has no server of its own.

| Path | Role |
|---|---|
| `src/App.tsx` | The composition root: lays out the header, the left column (or the selected element's card), the map, the timeline and the side panel; builds the map's GeoJSON from state |
| `src/hooks/usePlanner.ts` | The controller: one state object (`PlannerState`, written only through `patch`), the actions (the boot, the run, branches, connections, the view) and what is derived (the model index, the year in view, the comparison map, the limiters) |
| `src/api.ts` | The typed client. A failed call throws `ApiError` with the status and the API's `detail`; `notSolved` reads a 409 `not_solved`; `api.runBranch` starts a run job and follows it (progress, partial years, the result) |
| `src/types.ts` | The API's shapes |
| `src/lib/` | Pure helpers: `model` (the model indexed by id, element names, a breach in words, `limiters`: every element that breaches across the plan with its first year), `geo` (GeoJSON, the comparison's map deltas), `mapFeatures` (the kinds of element the Show menu toggles, remembered per browser), `placement` (marker fan-out, label boxes, tags), `layout` (breakpoints), `icons` (canvas map icons) |
| `src/components/` | `Header` (the grid, the branch picker, the demand profile, the map layer, Show, Run), `LeftCards` (the result stamp and the year's readings; *What the model assumes*), `DetailCard` (the selected line, transformer, busbar, generator or connection; a busbar's card places a new connection), `MapView` (MapLibre), `MapMarkers` (connections, substation names, loading and comparison tags), `MapControls` (zoom, fit, legend; the toasts), `Timeline` (the plan years, the slider), `SidePanel` (Connections, Limits, Compare), `ui` (shared bits) |
| `src/theme.ts`, `src/styles.css` | Colours, technologies (`TECH`), demand profiles, branch hues, and the stylesheet |

## How it behaves

- **Boot.** The model, the pathways and the branches, then `main`'s result from the cache (the API runs `main` at startup), or a run when there is none. The API still starting is retried with a growing pause, then shown on the stamp with a Retry.
- **Edits run by themselves.** Placing, moving in time or removing a connection, or changing the demand profile, re-runs the branch after a short debounce; the API's per-year cache re-solves only the years the edit touches. The years on screen stay until their re-solved versions land.
- **One run at a time.** A newer request supersedes the run in flight (its job is cancelled). A failed run stays on the stamp with a Retry.
- **The year never runs.** Every run solves every plan year; the timeline and the slider switch between them, and a year still solving says so.
- **`main` is read-only.** The first change made on `main` opens a branch (`draft-N`) for it. Every other branch has its own hue, which frames the map.
- **Compare** (a branch only) reads `GET /branches/{id}/diff` after every run: new and cleared breaches per year, the biggest loading movers, and the map coloured by the change in loading. Merge and Discard live there.

```bash
pnpm --filter web dev        # http://localhost:3000  (needs the API: pnpm --filter @gridforge/api dev)
pnpm --filter web build      # tsc --noEmit + vite build -> dist/
```

The API origin defaults to `http://127.0.0.1:8000` (uvicorn listens on IPv4 only); set `VITE_API_BASE` to point elsewhere.

Basemap: CARTO dark matter (no labels), © CARTO, © OpenStreetMap contributors.
