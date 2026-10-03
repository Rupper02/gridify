# Initial prompt for the coding agent

Paste this into Claude Code from the root of the gridforge repo, after copying this folder to `docs/design/gridforge-glass/`.

---

You are implementing a redesign of the GridForge planner UI in `apps/web` (Vite + React + TypeScript + MapLibre). The design package is in `docs/design/gridforge-glass/`.

**Read first, in this order:**
1. `AGENTS.md` and the root `README.md`. Their rules still apply: `main` is only what exists today, the LLM never computes physics, and honesty over fake precision.
2. `docs/design/gridforge-glass/README.md`: the full spec (layout, tokens, every screen, state, behaviour).
3. `docs/design/gridforge-glass/screenshots/`: what it should look like.
4. Open `GridForge Glass v2.dc.html` and `GridForge Components.dc.html` in a browser to click through the behaviour. They are **HTML design references, not code to copy**. All numbers in them are sample data.

**What to build:** recreate the design inside the existing app, reusing `usePlanner` and its slices, `api.ts`, `lib/derive.ts`, `lib/geo.ts` and `lib/icons.ts`. Wire every figure to the real API: optimize jobs, branches, registry, schedule, diff and suggestions. Where the API doesn't support something yet, add a clearly marked stub and list it for me rather than inventing data. That covers the three demand profiles, all-years results, maintenance windows and new technologies.

**Work in slices.** After each one, run `pnpm --filter web test` and `tsc`, and show me a screenshot before moving on:
1. Tokens and shared components (GlassPanel, Button, BranchCapsule, DemandProfileControl, SegmentedTabs, Switch, TechIcon via `@phosphor-icons/react`). Remove `backdrop-filter` everywhere.
2. App shell: full-bleed map, floating header, collapsible side panel (`]`), branch frame, laptop breakpoints (1180 / 1100 wide; 820 / 760 / 720 / 560 tall).
3. Map: CARTO dark basemap, voltage-weighted lines, flow / loading / voltage layers, HTML project markers with all states, Deferred toggle (off by default), clickable lines, transformers and generators.
4. Roadmap dock with year slider (switches stored per-year results; no re-run on drag), result stamp, readings, stale logic.
5. Side panel: Queue, Review (diff tiles + What changed), diff mode on the map.
6. Copilot: new-chat picker, New project intake (preliminary queue), Recommendations backed by `/branches/{id}/suggestions`.
7. Project card (energisation year with recommend-then-override), element card plus the Outages tab for maintenance.
8. Run overlay bound to `GET /jobs/{id}` stages.

**Constraints:**
- Desktop and laptop only. No mobile.
- Only one accent: `#7ce3ff`.
- No em-dashes in UI copy.
- Honour `prefers-reduced-motion`.
- Keep MapLibre attribution visible.
- Don't change API routes or the scenarios schema without asking. Propose the changes first.

Start by reading the files above. Then give me a short implementation plan with the API gaps you found before writing code.
