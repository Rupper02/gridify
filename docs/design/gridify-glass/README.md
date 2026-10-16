# Handoff: Gridify Glass (planner redesign)

## Overview
A redesign of the Gridify connection-queue planner (`apps/web` in `Rupper02/gridify`). It keeps the existing model (`main` = today's network, branches of optional projects, a power-flow-checked queue) and adds:

- **Copilot chat** with two modes picked at the start of each chat: **New project** (a guided intake that adds an application to the *preliminary* queue) and **Recommendations** (the "what would it take" levers, explained in chat).
- **Branch identity**: every branch has a hue that frames the workspace, colours the branch capsule and rings every project that only exists on that branch. `main` is silver, locked and read-only.
- **Three demand profiles** (Low / Standard / High) instead of the FES list. Every result is stamped with the profile it was solved on, and a mismatch shows as out of date.
- **All years solved in one run** (2026 to 2035). The year slider only switches between stored results.
- **Diff mode** on the map against `main`.
- **Planned maintenance** (outages and derates) on lines, transformers and existing generators, studied in its season.
- More technologies (gas, biomass/EfW, hydrogen, demand connections), a project detail card, an element card, a deferred-projects toggle and a collapsible side panel.

## About the design files
The files in this bundle are **design references created in HTML**. They are prototypes that show the intended look and behaviour, not production code to copy. The task is to **recreate them in the existing `apps/web` app** (Vite + React + TypeScript + MapLibre), using its patterns (`usePlanner` controller and slices, `api.ts`, `lib/derive.ts`, `lib/geo.ts`).

All numbers, project names, coordinates, per-line loading deltas, lever MW figures and maintenance impacts in the prototype are **sample data**. In the real app they must come from the engine and API (`/branches/{id}/optimize`, `/diff`, `/suggestions`, the registry, and so on). The LLM only phrases results and never computes physics; keep that rule from `AGENTS.md`.

## Fidelity
**High-fidelity.** Colours, type, spacing, radii and interactions are final. Recreate them closely using the codebase's own components and libraries.

## Layout (desktop and laptop; mobile is out of scope)
The page is full-viewport (`100vh`, min-height 560px). The MapLibre map fills the **whole** viewport, and everything else floats over it as solid tinted "glass" panels.

**Panel recipe (use everywhere):**
- Background: `linear-gradient(140deg, rgba(30,42,60,.97), rgba(18,26,39,.97))`
- Border: `1px solid rgba(255,255,255,.14)`
- Shadow: `inset 0 1px 0 rgba(255,255,255,.22), 0 6px 18px rgba(2,6,14,.28)`
- **No `backdrop-filter`.** The user explicitly rejected blur.

| Region | Position |
|---|---|
| Header | top 10, left/right 10, height 48, radius 14 |
| Side panel | top 68, right 10, bottom 10, width `clamp(320px, 30vw, 420px)`, radius 20; collapsible |
| Left cards (result stamp, readings) | top 68, left 10, width 248. Below 1100px wide they collapse to a single pill |
| Layer toggles (Flow / Loading / Voltage + Deferred switch) | top 68, right = side panel width + 20 |
| Roadmap dock | left 10, right = side panel width + 20, bottom 10, height 164 (132 below 720px tall), hidden below 560px tall |
| Legend + zoom (+ / − / FIT) | bottom-right of the map area, above the dock |
| Detail cards (project / element) | top 68, right = side panel width + 128, width 296 to 308, max-height fits above the dock |

When the side panel is hidden, every "side panel width" offset becomes 0. The "Copilot, queue and review" reopen button sits at top 68 right 10. The layer toggles move to top 114, and detail cards to top 114 right 150. The map refits with padding on every layout change.

**Responsive breakpoints (laptops):**
- `vw < 1180`: header compacts. Profile buttons become L / S / H, Diff and Merge become icon-only, the Run label becomes "Run" or "Re-run", and the branch sub-line hides.
- `vw < 1100`: left cards collapse into one pill; map attribution moves under it.
- `vh < 820`: the Copilot draft-application grid collapses to a single row of pills.
- `vh < 760`: the readings card hides.
- `vh < 720`: the dock shrinks.
- `vh < 560`: the dock hides.

## Screens and components

### Header
- **Logo:** 30×30 tile with a cyan lightning icon.
- **Branch capsule** (36px tall): branch icon chip, branch name in Geist Mono 13.5/600, and a sub-line ("from main · 2 added · 1 preliminary"). It opens a branch menu listing each branch with its hue dot, meta and profile, plus "New branch from main".
- **Diff / Merge buttons:** shown on branches only. Diff toggles diff mode; Merge goes to the Review tab.
- **Demand profile segmented control:** Low / Standard / High, each with a 1/2/3-bar meter glyph. Disabled with a lock on `main` (main runs on Standard).
- **Run button:** cyan, `linear-gradient(180deg,#9aeaff,#5fd0ef)`, text `#062030`. The label reads "Run on High", or "Re-run on High" when stale.

### Branch frame
On a branch: a 2px inset border in the branch hue around the whole viewport, plus `inset 0 0 120px <hue at 11%>`. A tweak (`branchFrame`) can switch it off.

### Left: result stamp + readings
- **Stamp:** shows the solved profile with its bar glyph and "All years solved · N planned outages".
- **Stale state** (amber box with a Re-run button) when either:
  - the profile changed since the run, or
  - new maintenance hasn't been studied yet.
- **Readings card:**
  - GSP export gauge: 24 ticks, cyan, the last ticks amber above 90%.
  - Worst element.
  - Voltage band.
  - Peak demand multiplier.
  - N-1 findings.
  - All values follow the selected year.

### Map (MapLibre, CARTO dark-matter-nolabels basemap)
- **Lines:** 132 kV `#dce6f2` 2.8px; 33 kV `#6f8ba8` 1.8px.
- **Line states:**
  - Binding constraint: amber `#ffc36b` dashed `[3,2]` with a 9px amber glow.
  - Overloaded: `#ff6b6b` with a glow.
  - Open point: dashed `[2,2]` plus a square icon.
  - Planned outage: grey dotted line plus an "OUT · Summer" tag.
- **Flow layer:** animated `line-dasharray` sequence, `#bff2ff`, cycled every 70ms; disabled under reduced motion.
- **Loading layer:** colours lines by %, with % tags.
- **Voltage layer:** colours buses by pu, with a red ring on breaches.
- **Other symbols:** transformers (two-circle icon), loads (triangles sized by MW), existing generation (teal `#2fbfa5` circles sized by √MW).
- **Project markers:** HTML, a 26px rounded tile in the status colour with a Phosphor tech icon and a mono ID label.
  - Deferred and preliminary: dashed outline.
  - Branch-only: hue ring.
  - Not yet energised in the selected year: 40% opacity.
  - Selected: cyan halo.
- **Deferred toggle:** deferred projects are **hidden unless the Deferred switch is on** (a selected one stays visible).
- **Clicks:** a project opens the project card; a line, transformer or generator opens the element card.

### Diff mode
- **Banner:** "main → branch" with a key (added, loading change, newly over 100%, unchanged dimmed) and a close button.
- **Lines:** unchanged lines dim to `#3d4f66`; changed lines turn amber or red with "+N%" tags.
- **Projects:** unchanged ones fade to 28%; added ones get a hue "+" badge.
- **Flow animation:** pauses.
- **Panel:** opens the Review tab.

### Roadmap dock
- **Header:** "Connection roadmap", a summary line, and the year with its lens on the right ("Phase 1 · Clean Power lens" in green, "Phase 2 · Strategic lens" in blue, "as-is today" in grey).
- **Year columns:** ten columns (2026 to 2035). Each holds project chips plus maintenance chips, a phase band (2027–30 green `#5ee6a8`, 2031–35 blue `#8fb4ff`) and cumulative MW.
- **Year slider:** a custom range under the columns, aligned to them, with the filled part in cyan.
- **Unscheduled column:** deferred chips.

### Side panel tabs
Copilot / Queue / Outages / Review, as a pill segmented control. A collapse button sits on its left (keyboard `]`).

**Copilot, start screen:**
- Two mode cards: New project (cyan) and Recommendations (amber), each with a description and an example prompt.
- A "Recent on this branch" list.

**Copilot, New project:**
- **Draft application grid:** Technology, Export, Import (load), Connection, Energise, Readiness. The slot being asked shows a cyan border.
- **Steps:**
  1. Technology: Solar PV, Onshore wind, Battery, Solar + battery, Gas (CCGT/OCGT), Gas engines, Biomass/EfW, Hydrogen electrolyser, Demand. Each gets a study-treatment note; Demand skips the export step.
  2. Export MW: rejects anything over the 300 MW intake cap.
  3. Import MW.
  4. Bus: suggests buses with headroom.
  5. Year.
  6. Readiness evidence: multi-select, giving a score of 0.1 plus land 0.3, planning 0.35 and finance 0.25.
  7. Name.
- **Finish:** a summary card, then "Add to preliminary queue". The project lands in a dashed **Preliminary · not simulated yet** group, and Copilot offers "Run on <profile>".

**Copilot, Recommendations:**
- **Context line:** e.g. "Last run · Standard demand · 3 deferred · 135 MW".
- **Quick replies:** e.g. Unblock CR-2024, What limits the GSP?
- **Lever cards:** title, MW freed, projects it connects, a caveat, a connects/partial tag and "Try on <branch>". These map to `/branches/{id}/suggestions`.

**Queue:** groups Preliminary, Phase 1, Phase 2 and Deferred. Each row shows a tech icon tile, ID, a "this branch" tag, applicant, tech · bus, MW, and "energises YYYY". Deferred rows show the binding reason. Clicking a row opens the project card.

**Outages:** maintenance windows on the branch. Each row shows the element, season and year, duration, type and its studied impact (colour-coded). Rows can be removed. There is an empty state. It is read-only on main.

**Review:**
- `main → branch` header, plus a profile-mismatch warning.
- Four diff tiles (MW by 2030, MW by 2035, Connected, Deferred) as base → head with a delta.
- Network effect.
- "What changed" list.
- Merge into main (hue button) and Discard.

### Project detail card
- **Header:** tech tile, ID and applicant.
- **Tags:** status chip, plus an "only on <branch>" tag.
- **Details:** technology, export/import, connection, rank, readiness and study treatment.
- **Energisation year stepper:** shows "Recommended by the optimiser", "Earlier than recommended" (amber) or "Later than recommended". This maps to `POST /branches/{id}/schedule`.
- **Deferred projects only:** a binding-constraint box with a "What would it take?" button that opens a Recommendations chat for that project.

### Element card (line / transformer / generator)
- **Details:** name, kind, rating and loading in the selected year.
- **Existing windows:** listed with their impact.
- **Schedule maintenance form:**
  - Season (Spring / Summer / Autumn / Winter).
  - Year stepper.
  - Duration (2 / 4 / 6 / 8 weeks).
  - Type (Full outage / Derate to 50%).
  - A hint on which study case applies: summer means summer minimum, winter means winter peak, spring and autumn mean both with seasonal ratings.
- **Adding a window:** marks the result stale until the next run.

### Run overlay
A card over the map area:
- **Title and badges:** "Solving AC power flow", the profile and branch badge, and "every year 2026 to 2035".
- **Progress:** a progress rail with a travelling pulse.
- **Stages:**
  1. Ranking.
  2. Winter peak, 2026 to 2035.
  3. Summer minimum, 2026 to 2035.
  4. N-1 and planned outages.
  5. Drafting the briefing.
- **Readout:** a mono line, e.g. "year 2029 · Newton-Raphson iter 3 · mismatch …". Bind it to the real job stage from `GET /jobs/{id}`.

## State (beyond the existing planner state)
- **Branch:** `branchId`, plus per-branch `profile` (`low|std|high`), `result` profile and run time.
- **UI:** `tab` (`copilot|queue|outages|review`), `sideOpen`, `layer` (`flow|loading|voltage`), `showDeferred`, `diff`, `legendOpen`, `menuOpen`.
- **Selection and year:** `year`, `sel` (project id), `selEl` (`line:<id>|trafo:<id>|gen:<id>`), `yearOv` (per-project energisation overrides).
- **Chat:** `chatMode` (`null|project|recs`), project intake (`step`, `slots`, `readySel`, `messages`), recommendations (`recMsgs`).
- **Projects:** `prelim[]` (unsimulated, per branch).
- **Maintenance:** `maint[]` as `{ el, season, year, weeks, type, branch, fresh }`; `fresh` means not studied yet.
- **Stale rule:** `stale = profile !== resultProfile || any fresh maintenance on the branch`.

## Design tokens
**Base:**
- `#0b111a` night grid (background)
- `#152031` substation
- `#2b3d57` ambient
- `#eaf0f7` ink
- `#c9d6e8` ink-2
- `#9aa9bc` mute
- `#7d8da3` mute-2

**Accent:**
- `#7ce3ff` Arc cyan: the single interactive accent, also live flow and preliminary.

**Planning states:**
- Phase 1 `#5ee6a8`
- Phase 2 `#8fb4ff`
- Deferred / constrained / stale `#ffc36b`
- Overload / breach `#ff6b6b`
- Rejected `#7d8da3`
- Existing generation `#2fbfa5`

**Branch hues:**
- main `#c9d6e8`
- branch 1 `#7ce3ff`
- branch 2 `#ff9f7a`
- Tints are made by appending alpha to the hue: `1f` for backgrounds, `80` for borders, `1c` for glow.

**Type:**
- Families: Geist (UI) and Geist Mono (IDs, numbers, bus/branch names).
- Sizes: 10.5 / 11 / 11.5 / 12 / 12.5 / 13 / 15 / 17 / 19.

**Radius:**
- Panels 14 to 20.
- Cards and inner boxes 10 to 12.
- Buttons 9 to 12.
- Chips, toggles and the segmented control: full pill.

**Motion:**
- Default easing `cubic-bezier(.16,1,.3,1)`.
- Side panel slide: 320ms.
- All animation is disabled under `prefers-reduced-motion`.

## Assets
- **Icons:** Phosphor Icons (`@phosphor-icons/react` in the app). Examples: `lightning`, `git-branch`, `git-diff`, `git-merge`, `lock-simple`, `solar-panel`, `wind`, `battery-charging`, `solar-roof`, `fire`, `plant`, `drop`, `buildings`, `wrench`, `hourglass-medium`, `sidebar-simple`, `chat-circle-dots`, `list-numbers`, `lightbulb`, `wave-sine`, `gauge`.
- **Map style:** CARTO `dark-matter-nolabels`; keep the attribution visible.
- **Map icons:** transformer, load and open point are drawn on canvas, as in the existing `lib/icons.ts`.

## Screenshots
Captured at 1440×900 (scaled), in `screenshots/`:
- `01-default-copilot-intake.png`: branch view, Copilot new-project intake mid-flow, stale result
- `02-branch-menu.png`: branch switcher
- `03-new-chat-picker.png`: new chat mode picker
- `04-recommendations-levers.png`: Recommendations chat with lever cards
- `05-queue-deferred-on.png`: Queue tab, Deferred switch on
- `06-project-card.png`: project detail card (deferred, binding constraint)
- `07-element-card-maintenance.png`: line card with the maintenance form, Outages tab
- `08-diff-mode.png`: diff vs main on the map + Review tab
- `09-loading-layer.png` / `10-voltage-layer.png`: map layers
- `11-sidebar-hidden.png`: side panel collapsed
- `12-run-overlay.png`: run in progress (all years)
- `13-main-read-only.png`: main, locked profile, empty review

## Components
`Gridify Components.dc.html` documents each reusable piece with exact styles and states:
- GlassPanel
- Button (primary / secondary / branch-hue / warning / destructive)
- BranchCapsule
- DemandProfileControl + ProfileGlyph
- SegmentedTabs, LayerToggle, Switch
- ProjectMarker (all seven states)
- TechIcon set
- QueueRow
- ChatBubble, QuickReply, Composer
- DraftSlot, ModeCard
- LeverCard
- MaintenanceRow, OutageTag, YearStepper
- GspGauge, StaleNotice, DiffTile
- RoadmapYear, YearSlider

Build these as shared components first, then compose the screens.

## Files
- `Gridify Components.dc.html`: component sheet (open in a browser next to `support.js`).
- `Gridify Glass v2.dc.html`: the full interactive prototype. Open it in a browser next to `support.js`. Its logic class holds all the derivations and sample data.
- `Gridify Palette.dc.html`: colour, branch-hue, demand-profile and line-language sheet.
- `support.js`: runtime for the prototype files only (not for the app).

Repo mapping:
- Header: `components/Header.tsx`
- Side panel: `SidePanel.tsx` with `QueueTab`, `ReviewTab` and `AlertsTab`. Alerts is replaced by Outages; Copilot replaces `AddProjectDrawer`.
- Map: `MapView.tsx` / `lib/geo.ts`
- Overlays: `MapOverlays.tsx`
- Roadmap: `Roadmap.tsx`
- Run overlay: `RunOverlay.tsx`
- Tokens: `theme.ts` / `styles.css`
