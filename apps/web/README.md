# GridForge — web

A Next.js shell around the GridForge planner. `/` redirects to `/planner/index.html`: a self-contained MapLibre app in `public/planner/`.

| File | Role |
|---|---|
| `public/planner/index.html` | The planner UI: map, queue, timeline, Review (branches, diff, copilot), registry |
| `public/planner/gridforge-api.js` | API client for the FastAPI service on `http://localhost:8000` (`config.base`); normalises engine deferral reasons into plain-English "why / what to do" |
| `public/planner/support.js` | The template runtime the page is written against. Treat it as a vendored dependency; don't edit it |

```bash
pnpm --filter web dev        # http://localhost:3000  (needs the API running: pnpm --filter @gridforge/api dev)
```

See the [root README](../../README.md) for the full system and the quickstart.
