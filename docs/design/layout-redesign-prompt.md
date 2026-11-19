# GridForge planner: layout redesign

Attached: the GridForge repo and the GridForge Glass design system (`GridForge Glass redesign.zip`).

---

Redesign the layout of the GridForge planner. Keep the visual language of the attached GridForge Glass design system (dark flat glass panels, one accent `#7ce3ff`, its palette, type and components). What you are changing is **where things live and how much is on screen at once**. The planner grew feature by feature and now crams everything into one view. Design an interface where everything fits, cleanly, across as few screens as possible.

Deliver interactive HTML prototypes, one file per screen, in the style of the design system's `.dc.html` references, plus a short spec (`README.md`) of the layout, the components and the behaviour.

## What GridForge is

A grid planning tool for a distribution network planning engineer. The loop:

1. **Understand a grid.** Where it is strong, what binds, where, in which season and year, and what will need reinforcement and when.
2. **Change it on a branch.** Add or move connection projects, schedule their year, plan maintenance works, simulate a reinforcement. `main` is the network as it exists today.
3. **Review the analysis and merge or discard.** A deterministic power-flow engine judges every change; a merge gate refuses a branch that makes things worse; AI agents explain the results and propose changes the operator approves.

The value is understanding, not a verdict. Every screen should help answer: is it **feasible**, **what limits it**, and **what would it take**.

For context on the product and the current planner, see `AGENTS.md` (*What this is*, *Domain rules*) and `apps/web/README.md` (every surface and behaviour today) in the repo.

## What is on screen today, all at once

Over a full-bleed map, on a 1440 x 900 laptop:

- **Header:** project capsule (opens the projects screen), branch picker, Diff, Merge, five map layers (Flow, Loading, Voltage, Demand, Headroom), a *Show* menu with eleven element-kind switches, the demand profile (Low, Standard, High), Run.
- **Left card:** the result stamp ("Solved 22:55 · High"), seven readings for the viewed year, *What the model assumes*. A selected element's detail card opens in the same corner, on top of the readings.
- **Map:** substations with name and ratio labels, demand-group labels ("19.6 / 14.0 MW · C"), project markers with ids, year tags, loading tags, works tags, a legend popover, zoom and fit, a run overlay in the middle while solving.
- **Right panel:** six tabs: Ask, Queue, Outages, Limits, Capacity, Review. They don't fit the tab bar (only the selected one shows its label; the last is clipped). Limits and Capacity overlap: both read the same list of binding elements, one sorted by severity, one by year.
- **Bottom dock, the connection roadmap:** a headline ("212.4 MW connected by 2030 · 16 deferred"), one column per plan year (2026 to 2035) with project and works chips, a phase band and cumulative MW, and a year slider.

## The problems

1. **Too much in one view.** Map, a left card, a right panel, a header and a bottom dock, each dense. The map, which is what the engineer reasons on, is squeezed between them and buried under labels, tags and overlays; panels sit on top of it and on top of each other. Make it clean: fewer things competing, one clear primary element per screen.
2. **The roadmap years say almost nothing.** Each year shows project chips labelled with registry ids (`ECR-AD82A`, `TEC-0AC5C`). With three or more projects in a year they truncate and wrap until nothing is readable, and an id says nothing about a project (technology, MW, where, status). The MW per year only shows on wide screens. You can't see at a glance what connects when, how much, and whether a year is in trouble. Per year, the roadmap should make readable: what connects (how many, how much, what kind), what works are planned and how they are judged, whether anything on the network breaches that year, and which year is being viewed.
3. **Everything should fit, not necessarily on one screen, but the fewer screens the better.** Split by what the engineer is doing at the time (understanding the grid, working on a branch, reviewing and merging), not by the order features were built. Every capability stays reachable.

Fix what else you see on the way: the tabs that don't fit, the duplicate labels on the map (a substation's name next to its demand group's), the Limits / Capacity overlap, panels that hide the map.

## Everything that must have a place

- **Projects screen:** the built-in grid and imported ones, the import form, its validation report.
- **Branches:** switch, open, rebase, "behind main", demand profile, Run and its progress (stages, years solved so far), stale and failed results.
- **Map:** the layers, the *Show* menu, the legend. Selecting a line, transformer, busbar, generator, project, demand group or works window opens its detail: rating and loading for the viewed year, a per-year sparkline, N-1 notes, *Ask the agents*, *Schedule works*.
- **The viewed year** and its readings. Changing year never re-runs anything.
- **Ask:** the conversation with the agents, stage chips (Plan, Assemble, Run, Check, Propose, Cite), an evidence drawer, approval cards (Approve / Deny), spend today and in total, Pause.
- **Queue:** connected (Phase 1 by 2030, Phase 2 by 2035), deferred and preliminary projects, the Deferred switch; the project card with its energisation year (the engine recommends, the operator may override).
- **Planned works:** schedule a window (line, transformer or generator; season, year; outage or derate), its verdict, the curtailment it needs.
- **Limits:** the binding elements, why each deferred project is deferred, N-1 causes, works verdicts, fault levels, the findings ledger.
- **Capacity:** when each element first goes over its limit and the lever (a higher-rated circuit, a larger transformer, voltage support); the room to connect per substation, generation and demand (measured on request, a few minutes the first time).
- **Review:** merge readiness (checks per plan year, warnings to acknowledge), the difference against the parent per year, diff colouring on the map, the engineer's note on the run.

## Rules

- No ranking-weight sliders or physics knobs anywhere: the engine sets them.
- Every figure is the engine's, shown with its study case (winter peak or summer minimum) and its year. Limitations are stated, not hidden.
- Agents only propose; the operator approves. Nothing merges without the gate.
- Desktop and laptop only: design at 1440 x 900, and make it hold at 1280 x 720.
- One accent, `#7ce3ff`. Status colours keep their meaning: red over a limit, amber over later or warning, a pale amber near a limit, green holds; Phase 1 green, Phase 2 blue.
- No em dashes in UI copy. Plain words; an engineer's terms (N-1, firm capacity, P2/8) are fine.
- Honour `prefers-reduced-motion`. Keep the map attribution visible.
- Design only with data the planner has today (listed above); where an idea needs something new, mark it.

## Real data to design with

The built-in grid: **NGED Bicker Fen 132 kV GSP**, Lincolnshire. Substations include Grantham, Grantham North, Sleaford, Skegness, Spilsby, Alford, Horncastle, Woodhall Spa, Tattershall, Metheringham, Ingoldmells, Chapel St Leonards, Trusthorpe, Leadenham, Cranwell, Ruskington, Great Hale, Billingborough, Easton, Skillington, Market Overton, New Beacon Road, Warth Lane, Wrangle. Plan years 2026 to 2035.

Branch **q4-applications** (off main, 20 projects added), High demand profile:

- Headline: 212.4 MW connected by 2030, 16 deferred (most of them by the GSP export limit). Four projects connect in 2027: ECR-AD82A, ECR-1427D, ECR-F702A, ECR-3F8BA.
- Readings in 2030: GSP export 513.2 of 527 MW at summer minimum; binding element Woodhall Spa 33/11 kV transformer at 98%, -3.4 MW room, breaches from 2031; voltage 0.943 to 1.044 pu, within band; N-1: 11 of 27 outages breach a limit; fault level 156% at Skegness 33 kV; demand headroom -5.6 MW at New Beacon Road; 3 customer alerts.
- In 2035: voltage 0.886 to 1.044 pu (12 busbars out of band); N-1: 15 of 27 outages breach; demand headroom -18.9 MW at New Beacon Road; 11 customer alerts.
- **When it needs reinforcement** (31 elements go over a limit, the first in 2031; 8 more come near one; 123 of 128 circuits and 27 of 44 transformers hold through 2035):
  - near from 2026: Skegness to Middlemarsh 132 kV, circuits 1 and 2 (92.7% at summer minimum, about 6.8 MW of room)
  - 2031: Horncastle 33 kV busbar (0.886 pu at winter peak in 2035, 9 outages breach it); Woodhall Spa 33/11 kV transformer (145.6%, about 3.4 MW over)
  - 2032: Alford 33/11 kV transformer 1 (142.7%)
  - 2033: Grange Farm Solar and Woodhall Spa 33 kV busbars (0.912 to 0.920 pu); Spilsby 33/11 kV transformers 1 and 2; Alford 33/11 kV transformer 2; Great Hale 33/11 kV transformer (142.2%)
  - 2034: Metheringham 33 kV busbar (0.924 pu; holds back ECR-83EF2); Skegness 132/33 kV transformers 1 and 2 (114%); Sleaford 132/33 kV transformers 1 and 2 (116%)
- **Room to connect today** (MW of new generation at summer minimum / new demand at winter peak, at the substation's best busbar): Grantham North 105 / 110 (132 kV), Grantham 105 / 110, Spilsby 65 / 30, Sleaford 60 / 85, Skegness 55 / 85, Ingoldmells 55 / 35, Chapel St Leonards 50 / 25, Alford 30 / 15, Warth Lane 25 / 35, Leadenham 25 / 25, Great Hale 25 / 20, Trusthorpe 25 / 10, Horncastle 25 / under 5, Cranwell 20 / 40, Tattershall 20 / 35, Woodhall Spa 20 / 5, Wrangle 15 / 10, Metheringham 10 / under 5, Market Overton 5 / under 5. Each has the limit the next MW breaks, e.g. "Bicker Fen to Sleaford 132 kV, circuit 2 overloaded at 100.2% of its summer rating".

## What to deliver

1. **The screens:** as few as work, each with one clear purpose and one primary element. For each, a short rationale.
2. **A mapping table:** every surface and capability above, and where it lives now.
3. **Prototypes** of each screen at 1440 x 900, and the same screens at 1280 x 720.
4. **The roadmap, redesigned,** shown with a year holding 0, 1, 3 and 8 projects, a works window, a year still solving, a year whose power flow does not converge, and the viewed year.
5. **Key flows, clickable:** select an element and read why it binds; run a branch and watch it solve; open the diff and merge; ask the agents and approve a proposal; measure the room to connect.
6. **Open questions,** and anything the design needs that the planner doesn't have yet.
