# Gridify planner (`apps/web`)

The planner is the single-page app an engineer works in: the network on a map, the plan years along the bottom, the
branch's connections, limits and comparison in a side panel. It is **Vite + React 19 + TypeScript** around a full-bleed
MapLibre map with floating panels ("Gridify Glass", designed in `docs/design/gridify-glass/`). It has no server of its
own: every figure it shows comes from the API in `apps/api`, and it computes no physics.

## Run

```bash
pnpm install                     # once, from the repo root
pnpm --filter @gridify/api dev   # the API it talks to (see apps/api)
pnpm --filter web dev            # the planner on port 3000
pnpm --filter web typecheck      # tsc --noEmit; fails on unused locals and parameters
pnpm --filter web build          # typecheck + vite build -> dist/
```

**Configuration.** One variable: `VITE_API_BASE`, the API's origin (default `http://127.0.0.1:8000`; uvicorn listens on
IPv4 only, so `localhost` can fail where it resolves to IPv6 first). The browser remembers one thing per user: which
kinds of element the *Show* menu displays (`localStorage`, `lib/mapFeatures.ts`).

**Tests.** The planner has no unit tests; it is checked in a real browser against a running API (see `AGENTS.md`).

## What the screen shows

| Area | What it is |
|---|---|
| Header | The grid's name, the branch picker, the demand profile (Low / Standard / High), the map layer (*Flow*, *Loading*, *Voltage*, *Over rating*), *Show* (which kinds of element are drawn), *Run* |
| Left column | The result stamp (solved, solving, failed with a Retry) and the readings for the year in view: worst line and transformer, voltage range, breaches, the GSP's export against its limit; *What the model assumes*. A selected element replaces it with its card |
| Map | Lines and transformers coloured by the chosen layer; busbars, substations, today's generation, the branch's connections and loading tags as HTML markers; a branch's hue frames the map |
| Timeline | The plan years 2026–2035 with each year's breach count; the slider switches the year in view and never starts a run |
| Side panel | *Connections* (the branch's, by year, and *Add from the registry*), *Limits* (every breach in the year and every element that breaches across the plan, with its first year), *Compare* (a branch only: against its parent, with Merge and Discard), *Year runs* (the measured and grown years, half-hour by half-hour) |
| Detail card | The selected line, transformer, busbar, generator or connection: its figures, a sparkline across the years; a busbar's card places a new connection |

## How it behaves

- **Boot.** It reads the model, the plan years and the branches, then `main`'s result from the API's cache (the API runs
  `main` at startup), or starts a run when there is none. While the API is still starting it retries with a growing
  pause, then shows the failure on the stamp with a Retry.
- **Edits run by themselves.** Placing, moving in time or removing a connection, or changing the demand profile,
  re-runs the branch after a short debounce. The API's per-year cache re-solves only the years the edit touches, and the
  years on screen stay until their re-solved versions land.
- **One run at a time.** A newer request supersedes the run in flight (its job is cancelled). A run streams its years
  as they are solved (`GET /jobs/{id}?partial=true`), the year in view first.
- **`main` is read-only.** The first change made on `main` opens a branch (`draft-N`) for it, and the change lands there.
- **Compare** reads `GET /branches/{id}/diff` after every run: new and cleared breaches per year, the biggest loading
  movers, and the map coloured by the change in loading. A merge the API refuses (the parent changed since the branch
  was opened) is shown as a warning, and nothing changes.
- **Year runs** reads the run files the API serves (`GET /runs`, `/runs/{id}`): the *Over rating* layer colours lines
  and transformers by hours above rating, heavier for longer (steps in `geo.HOURS_STEPS`), or by peak loading. On a
  branch, *This branch through a whole year* runs the branch's connections through a grown year as a job (about 16
  minutes) and shows what they change.

## Code map

| Path | Role |
|---|---|
| `src/main.tsx`, `src/App.tsx` | Mount, and the composition root: the layout (header, left column or detail card, map, timeline, side panel) and the map's GeoJSON, memoised from state |
| `src/hooks/usePlanner.ts` | The controller: one state object (`PlannerState`, written only through `patch`), the actions (boot, run, branches, connections, the view) and what is derived (the model index, the year in view, the comparison, the limiters) |
| `src/hooks/useViewport.ts` | The viewport's size (debounced) and the reduced-motion preference |
| `src/api.ts` | The typed client, one function per endpoint. A failed call throws `ApiError` with the status and the API's `detail`; `notSolved` recognises a 409 `not_solved`; `runBranch` starts a run job and follows it (progress, partial years, the result) |
| `src/types.ts` | The API's response shapes, mirrored by hand from `gridify_optimizer.types` and the API (change both in one pass) |
| `src/theme.ts` | Colours, the technologies (`TECH`), the demand profiles, branch hues |
| `src/styles.css` | The stylesheet: classes only, inline styles just for data-driven colours |
| `src/lib/model.ts` | The model indexed by id, element names, a breach in words, `limiters` (every element that breaches across the plan, with its first year) |
| `src/lib/geo.ts` | GeoJSON for the map, the comparison's deltas, the *Over rating* styling, the flow animation |
| `src/lib/mapFeatures.ts` | The kinds of element *Show* toggles, remembered per browser |
| `src/lib/placement.ts` | Marker fan-out, label boxes, loading tags |
| `src/lib/layout.ts`, `src/lib/icons.ts` | Breakpoints; the map's canvas icons |
| `src/components/Header.tsx` | The header (see above) |
| `src/components/LeftCards.tsx` | The stamp, the readings, *What the model assumes* |
| `src/components/DetailCard.tsx` | The selected element's card, and placing a connection at a busbar |
| `src/components/MapView.tsx` | Owns the MapLibre instance: layers and icons added once, data pushed with `setData` |
| `src/components/MapMarkers.tsx` | The HTML overlay (connections, substation names, tags), re-projected on every map move |
| `src/components/MapControls.tsx` | Zoom, fit, legend, and the toasts |
| `src/components/Timeline.tsx` | The plan years and the slider |
| `src/components/SidePanel.tsx` | The tabs (`TABS`): Connections, Limits, Compare |
| `src/components/RunsTab.tsx` | The *Year runs* tab and `RunDetail` (an element's figures and month-by-hour grid in a run) |
| `src/components/ui.tsx` | Shared pieces: the technology icon (`TECH_ICON`), the profile glyph, switches, steppers, sparklines, gauges, hints |

## The API calls it makes

| When | Calls |
|---|---|
| Boot | `GET /model`, `/forecasts`, `/branches`, then the branch's `/connections` and `/result` (or a run) |
| On demand | `GET /assumptions`, `/registry` |
| Editing a branch | `POST /branches`, `POST/PATCH/DELETE /branches/{id}/connections…`, `POST /branches/{id}/profile` |
| Running | `POST /branches/{id}/run`, `GET /jobs/{id}` (polled), `POST /jobs/{id}/cancel` |
| Compare, merge, discard | `GET /branches/{id}/diff`, `POST /branches/{id}/merge`, `/discard` |
| Year runs | `GET /runs`, `/runs/{id}`, `/runs/{id}/grid/{kind}/{element}`, `/runs/{id}/compare`, `POST /branches/{id}/year-run` |

## Extending it

- **A new technology:** add it to `TECH` in `theme.ts` and `TECH_ICON` in `components/ui.tsx`. Both are typed
  `Record<Tech, …>`, so the build fails until it has an entry in each. Its physics (what it does in each study case) is
  the engine's `config.GENERATION_FACTORS`, not the planner's.
- **A new side-panel tab:** an entry in `SidePanel.TABS` and its component.
- **A new API field:** `types.py` in the engine, the API, then `types.ts` and `api.ts` here, then the component that
  shows it, in one change.

Basemap: CARTO Dark Matter (no labels), © CARTO, © OpenStreetMap contributors. NGED's data: "Supported by NGED Open
Data", shown in the map's attribution.
