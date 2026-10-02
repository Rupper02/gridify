# GridForge — web

The planner UI: a single-page **Vite + React 19 + TypeScript** app around a MapLibre map. It talks to the FastAPI service in `apps/api` and has no server of its own.

| Path | Role |
|---|---|
| `src/App.tsx` | Composes the header, map, roadmap and side panel; derives the map's GeoJSON from state |
| `src/hooks/usePlanner.ts` | The controller: one state object, the actions (run, branch, add, diff, suggestions, merge, schedule) and the map handle |
| `src/api.ts` | Typed client for the API; `normReason` turns engine deferral reasons into plain-English *why / what to do* |
| `src/lib/` | Pure helpers: timeline + queue derivations (`derive.ts`), GeoJSON building (`geo.ts`), canvas map icons (`icons.ts`), label placement (`labels.ts`) |
| `src/components/` | `MapView` (MapLibre + overlays), `DetailCard`, `Tooltip`, `Roadmap`, `SidePanel` → `QueueTab` / `AlertsTab` / `ReviewTab`, `AddProjectDrawer` |
| `src/theme.ts`, `src/styles.css` | Status colours and the stylesheet |

```bash
pnpm --filter web dev        # http://localhost:3000  (needs the API: pnpm --filter @gridforge/api dev)
pnpm --filter web test       # vitest: reason normalisation, timeline/queue/alert derivations
pnpm --filter web build      # tsc --noEmit + vite build -> dist/
```

The API origin defaults to `http://localhost:8000`; set `VITE_API_BASE` to point elsewhere.

Map tiles: OpenFreeMap (Positron style), © OpenStreetMap contributors. Substation positions come from the API's model.

See the [root README](../../README.md) for the full system and the quickstart.
