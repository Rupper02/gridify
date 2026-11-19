# Design note: a year view in the planner (Work 5)

*13 November 2026. Decided by the guide session overnight, for the owner to confirm. Written before the build.*

**What it shows.** The planner gets a way to see where and when the grid breaks in a measured or grown year. A run
selector offers:
- 2024 as published;
- 2024 screened;
- 2030 Holistic Transition;
- 2035 Holistic Transition;
- 2035 Falling Behind.

For the chosen run, the map shows:
- **lines and transformers coloured by hours above rating,** with a second mode for peak loading;
- **busbars marked** where voltage leaves its band;
- **substations listed** where firm capacity is exceeded, with hours.

Selecting an element shows its figures and a month-by-hour grid of when it is over.

**Shape, in one pass** (the root AGENTS.md rule).
- **Engine:** a new module, `runs.py`.
  - `RUNS` is the catalogue: id, file name, kind, year, pathway, and how to make the file.
  - `summarise(folder, run_id)` returns a `RunSummary`: per element the peak, when, hours at or above 80, 90 and 100%
    and its step-1 label; voltage hours per busbar; firm-capacity hours per substation; the run's meta (year, pathway,
    kind, code fingerprint); and its limits in plain words.
  - `month_hour_grid(folder, run_id, kind, id)` returns 12 × 24 hours over rating for one element.
  - *Labels* (agrees, differs with its offset, input, held at 0, reactive input unreliable, not in NGED's file) come
    from `compare_with_source(folder)`. It runs on the screened 2024 file, by the rules step 1 used, and the class
    rules are derived from the run file itself, not lists:
    - "input" is a radial branch whose far side has only derived injections;
    - "held" sits beyond a held-at-zero cluster;
    - "unreliable" is a transformer of a node with more than 1% of its half-hours flagged by the reactive screen.
- **Contract:** pydantic types in `types.py`: `RunInfo`, `RunElement`, `RunBus`, `RunSubstation`, `RunSummary`,
  `RunGrid`.
- **API:** a new router, `routers/runs.py`, with a service in `runs_service.py` and the folder in `config.RUNS_DIR`
  (`GRIDIFY_RUNS_DIR`, default the pipeline's `warehouse/nged-flows`). Three endpoints:
  - `GET /runs` lists every catalogued run, whether its file exists, and how to make it if not.
  - `GET /runs/{id}` returns its summary, computed once and cached in-process (a few seconds per file).
  - `GET /runs/{id}/grid/{kind}/{element_id}` returns one element's month-by-hour grid.
  - No solving in the API: a year takes about 16 minutes. Running a year as a job from the planner is a later step.
- **Web:**
  - `types.ts` and `api.ts` get the new types and calls.
  - `usePlanner` gets the chosen run, its summary and the metric.
  - The header's `LAYERS` gains "Over rating" (`MapLayer` "hours").
  - `geo.ts` colours lines and transformers from the summary with the existing `loadColor` scale: hours mode maps
    >100% for any hour to red, ≥90% to amber, ≥80% to cream; peak mode takes `loadColor(peak)`.
  - `SidePanel.TABS` gains "Year runs" (one new component, `RunsTab`): the run selector, the limits one click away, the
    worst elements, the busbars out of band, and firm capacity.
  - `DetailCard` gets one section for the selected line, transformer or busbar: its label and offset, peak and when,
    hours at or above 80, 90 and 100%, and the month-by-hour grid, the only per-half-hour data sent to the browser.
  - Spilsby is visibly marked "reactive input unreliable: not a finding".

**Honesty in the view.**
- *Every element's label is shown.*
- *The run's limits sit at the top of the tab, in plain words:*
  - for a grown year: "2024's shape at this year's demand: the size of each substation's peak follows the growth
    source, when and for how long it is exceeded follows 2024's shape, so the hour counts are indicative, not a bound
    in either direction; one weather year; no new generation; no outages; no reinforcement" (corrected overnight from
    "a lower bound");
  - for 2024: that the check against NGED's model did not pass, and what that means for the numbers.
- *A missing file* is said so, with the command that makes it.

**Size.** One new component (`RunsTab`, with its month-by-hour grid), one selector, one detail section, one engine
module and one API router: a contained addition. Verification is in a real browser on the spare port.

## As built, and how it was checked (13 November 2026, overnight)

**One change from the plan, at the guide's request.** Hours mode encodes duration:
- red for any element above its rating, heavier for longer: up to 10 h, 10 to 100 h, 100 to 1,000 h, over 1,000 h
  (`geo.HOURS_STEPS`), by line weight and by transformer ring size;
- amber for an element that reaches 90% but is never over;
- grey for an unreliable input.

The legend is in the tab. On the map, elements over rating for 10 hours or more carry an hours badge, and substation
labels show their hours above firm capacity.

**Labels.** `runs.compare_with_source` reproduces step 1's labels except two radial customer spurs, Manor Farm and RAF
Cranwell's High G site. Their far side holds only injections taken from NGED's own flows, so the general rule now calls
them "input" rather than "agrees".
- *Railway branches:* they are meshed in the engine, so they are matched by a data rule instead: NGED's flow on them
  tracks the held-at-zero railway injection (correlation 0.9 or more).
- *Count on the screened 2024 run:* 102 agree, 32 differ, 18 input, 4 held, 2 unreliable.

**Checks run** (spare port 8010 with a temporary scenarios database; planner on 3010):
- **The API:**
  - `/runs` lists all five runs as available.
  - `/runs/2035-ht` takes 5.9 s the first time, then comes from the cache.
  - The grid for New Beacon Road T1 sums to 1,817.5 h.
- **The planner, driven in Chrome through the DOM:**
  - The "Year runs" tab lists the five runs, with "Over rating, longest first" at 28.
  - New Beacon Road T1 (1,818 h) and T2 (1,506 h) lead, with Skegness T2 next ("flow differs (+1.38 MW, 3.1% of rating)").
  - Selecting New Beacon Road T1 shows the report's figures: peak 152.8% on 15 January at 18:00; 4,182, 2,839 and
    1,818 h at the three thresholds; a 12 × 24 grid.
  - The limits text is one click away; for 2024 it says the check did not pass.
- **No file:** with the 2035 Falling Behind file moved aside (and restored, same sha256), the selector says "(no file)",
  `/runs/2035-fb` answers 404 with the command, and the tab shows how to make it. Choosing that run no longer raises a
  toast.
- **The map's encoding,** through the planner's own `buildGeo` in the page on the 2035 Holistic data:
  - largest rings (radius 26.2): New Beacon Road T1 and T2, Skegness GT2 and Alford T1, all over 1,000 h;
  - next (22.2): Skegness GT1, Great Hale, Sleaford 11 kV, Woodhall Spa;
  - Metheringham, at half an hour, takes the lowest step;
  - Spilsby is grey;
  - 12 busbars ringed out of band, 9 substations ringed above firm capacity.
- **Console:** zero errors.
- **Suites:** engine 34 passed; API 7 passed, 1 skipped; web typecheck clean and build succeeds.

**What the map looks like: checked later the same night,** when Chrome painted (screenshots in `screenshots/`:
`work5-2035-ht-over-rating.jpg`, `work5-new-beacon-road-t1.jpg`). Hours badges crowd each other around Skegness and
Horncastle, where several elements are over. The earlier note, kept for the record: **Not checked then: what the map looks like.** The screenshots the guide asked for could not be taken. Chrome on this machine
was not painting: `requestAnimationFrame` gave 0 frames a second although the tab reported itself visible and focused,
which is what a locked or sleeping screen does. Every screenshot timed out, and the map never reached its ready state
(so the overlay with the hours badges was not drawn). The view's data, logic and panels are verified as above. Its
visual appearance needs one look in a browser that is painting: take the screenshots then, and save them here.

**How to see it** (spare ports, so a running API on :8000 is untouched; a temporary scenarios database keeps the real
one out of it):

```bash
# terminal 1: the API on 8010
cd apps/api && GRIDIFY_SCENARIOS_DB=<a temp path>/scenarios.duckdb uv run uvicorn gridify_api.main:app --port 8010
# terminal 2: the planner on 3010, pointed at it
cd apps/web && VITE_API_BASE=http://127.0.0.1:8010 npx vite --port 3010 --strictPort
```

Open http://localhost:3010, turn on the *Over rating* layer in the header, open the *Year runs* tab and choose 2035
Holistic Transition. Three things to look at first:
1. **The heaviest rings:** New Beacon Road T1 and T2, Alford T1 and Skegness GT2, each over rating for more than
   1,000 hours. Click one for its month-by-hour grid. For New Beacon Road T1, three-quarters of its 1,818 h fall from
   November to February, and 44% between 16:00 and 21:00: mostly winter, leaning to the evening, not only at the peak.
2. **Spilsby is grey:** its reactive input is unreliable (NGED's MVAr exceeds the transformers' rating), so its hours are
   not a finding.
3. **A busbar ring at Horncastle:** Horncastle 33 kV is the worst of the 12 busbars out of band: 1,131 h below its
   statutory band, down to 0.884 pu.

**For the owner (guidance files are not edited without you):** `apps/api/AGENTS.md`'s layout list would name
`routers/runs.py`, and `packages/optimizer/AGENTS.md`'s "What it owns" would name `runs.py`, `timeseries.py` and
`nged_flows.py`. One line each.

**Since then** the catalogue (`runs.RUNS`) has gained the Warth Lane sensitivity (`2030-ht-warth-ltds`, grown-year
report section 6) and the three Work 6b branch examples (`2030-ht-grantham`, `2030-ht-grantham-tied`,
`2030-ht-thorns`, `branch-examples.md`). Each adds its own caveat to the limits text: a sensitivity, or an example of
one branch, not main.

## Work 7: a branch's year from the planner (as built, 13 November 2026, overnight)

Decided by the guide session overnight, for the owner to confirm. It fits the existing job machinery, so no design note
came first:
- **Engine.** `timeseries.growth_scale` (moved from the report's `run.py`; it reproduces the stored multipliers exactly),
  `run_year(..., about=)` and, in `runs`: `BASES`, branch run ids (`branch-<key>`), and `compare`.
- **API.** `year_runs.YearRuns` and `POST /branches/{id}/year-run`: one `JobRunner` job, keyed by `ResultCache.key` over
  the in-service connections, the pathway, the baseline and the engine fingerprint. The run file is the cached result.
  `GET /runs/{id}/compare` and the existing `/runs` endpoints serve it.
- **Planner.** On a branch, the Year runs tab has *This branch through a whole year* (a year and pathway, Run, the
  driver's progress, Stop). Then *What the branch changes* comes first: each element's peak and hours before and after,
  with the branch's own study-case figure beside it, and the MVAh above rating on the worst.

**Checked on the spare ports** (API 8010, temporary scenarios database; planner 3010):
- *A real run from the planner:* a branch holding Thorns Farm alone, 2030 Holistic Transition, took 20.6 minutes. The
  result is identical to the catalogued `grown-2030-ht-thorns.npz` (largest difference 0.0 on line and transformer
  loading, voltage, GSP flow, connection output and inputs; all 17,568 half-hours converged). Only `bus_q` differs: it is
  now saved scaled.
- *What the user sees:* line 115, 0 h → 402 h over rating, peak 26% → 141%, study cases 103%; 1,853 MVAh. Screenshots:
  `work7-thorns-branch-year.jpg`, `work7-thorns-line-115-badge.png`.
- *Cache:* running it again finished in 0.0 s.
- *Refusals:* main (no connection in service), an unknown pathway, a comparison asked of a catalogued run, and an unknown
  run id.
- *Responsiveness during the 20.6-minute run:* every 20 s for 59 rounds, eight reads the planner makes. All answered
  200. Medians were 29–106 ms (90th percentile up to 144 ms, highest 259 ms); idle they were 3–70 ms. The exception is
  one element's month-by-hour grid: 0.6 s median, 0.9 s at most (0.15 s idle).
- *What does wait:* any other job. A branch's plan-year run started during the year showed "queued behind 1" until the
  year finished; it then completed at once from the cache. On one worker, an edit made during a branch's year waits up
  to the year's remaining minutes for its re-solve. This is the limit to weigh.
- *A bug found and fixed:* turning on the Over rating layer replaced a branch's year with the first catalogued run. The
  run on screen now stays.
- *Console:* zero errors. *Suites:* engine 34 passed, API 7 passed and 1 skipped, web typecheck and build clean.
- *Cosmetic:* the line's hours badge partly overlaps the new connection's icon.

**Changed after the guide's review (same night).**
- *A plan run stops a year run.* When a branch's plan years need solving (not when they are cached), the API stops any
  year job first (`JobRunner.stop_kind`, with its reason). The year job notices at its next progress report: now every
  50 half-hours (`timeseries.PROGRESS_EVERY`), a few seconds. The tab says it was stopped and why.
  - *Nothing half-written:* `run_year` writes to `branch-<key>.part.npz`. Only a finished run is renamed to its name
    (`os.replace`, one step), and the `.part` file is removed in a `finally` however the job ends. The run id exists
    only when the whole file does.
  - *Measured once:* a year (Thorns Farm, 2035 Holistic Transition) was started from the planner, then a plan run for
    another branch (Grantham 240 MW, not cached) was requested 45 s in. The plan run started after **1.2 s** and finished
    4.7 s after the request. The year job ended as "cancelled" in the same second it was stopped, and no file of it was
    left. The planner showed the reason under Run.
- *Hours badges:* at the fitted view only elements over rating for 100 hours or more carry a badge (11 on the 2035
  Holistic Transition map, against 16 before). Zoomed in by 0.75 or more, or selected, every element over for 10 hours
  or more does. The rings are unchanged. Screenshot: `screenshots/work7-badges-100h.jpg`.

**Changed after the guide's second review (same night).**
- *The key now names the base.* The job was keyed over the connections in service, the pathway, the baseline and the
  fingerprint, but not the year it runs on: a branch whose connections are all in service by 2030 gave the same key for
  2030 and 2035, so the second would have been served the first's file. The key now starts with `year:<before>`. The
  2030 Thorns file made above is correct and kept, but no new key reaches it.
- *The catalogue behind the seam.* `runs.py` holds only general machinery: `RunCatalogue` (a grid's runs, bases,
  reference run and plain-words limits) and `RunFiles` (reads them, given the folder, the catalogue and a
  `net_factory`). NGED's catalogue is `nged_runs.py`, served by `GridSource.run_catalogue()`; `deps.py` builds the one
  `RunFiles`. The engine's output was compared before and after on all 15 entries: identical.
- *Six bases.* 2030 and 2035 on all three pathways are on file (grown-year report section 7).

## Work 15: agreement and input reliability judged apart (13 November 2026, overnight)

Decided by the guide session overnight, for the owner to confirm. Register: "The year view's labels".

- **Agreement with NGED's model** is a property of the network. It is now judged on **2025 screened**, the year that
  closes best (rule 1 on 94% of half-hours, against 60%), by the same rules, unchanged.
  - NGED's 2025 file compares every element its 2024 file did, plus six more (164 against 158). So no element needs a
    2024 label; a fallback was written, found to change nothing, and removed.
  - Each label carries the year it was judged on (`RunElement.label_year`, shown as the label's tooltip). The measured
    years' limits text says so.
- **Input reliability** is a property of the flows a run is built from. It is now read from each run's own file.
  - Every run file carries the screen's flags for its source flows, set when they are mapped, before any growth.
    Checked: they are identical to the source year's measured run, for grown, branch and 2025-based runs.
  - `2024-published` predates the screen and takes the flags of the run on the same flows
    (`RunCatalogue.screen_from`).
  - The imputation screen is not used by the view, so there was nothing to split.
- **No number changed.** Peaks, hours, voltages and firm-capacity hours are identical on all 14 catalogued runs (checked
  element by element, before and after).

**Label counts, before → after:**

| Runs | agrees | differs | input | not in file | held at 0 | unreliable (not a finding) |
|---|---|---|---|---|---|---|
| The 12 runs on 2024's flows | 102 → 98 | 32 → 39 | 18 → 21 | 14 → 8 | 4 → 4 | 2 → 2 |
| 2025 screened, and 2035 HT on 2025's flows | 102 → 100 | 32 → 39 | 18 → 21 | 14 → 8 | 4 → 4 | **2 → 0** |

Busbars marked "not a finding" are unchanged on every run. The firm-capacity list gains **Spilsby** on the two
2025-based runs (93 h on 2025 screened, 128 h on 2035 HT on 2025's flows) and is unchanged on the others.

**Every element whose label changed, and why** (the same on all 14 runs unless noted):
- *Spilsby 33/11 kV T1, T2 (trafos 33, 34), 2025-based runs only:* "reactive input unreliable" → "flow agrees". Spilsby's
  2025 reactive power is clean.
- *Agrees → differs: 11 elements.*
  - Grantham 132 kV sections and the Sleaford tees (lines 10, 15, 17), with offsets +1.69 to +1.76 MW.
  - Grantham 33 kV (lines 37, 38), +1.76 and +1.81.
  - Chapel St Leonards tee (lines 71, 58), +0.95 and +1.12.
  - Easton tee (line 35), +1.26.
  - Skegness – Warth Lane tee (line 75), −0.22.
  - Warth Lane T3 (trafo 41), +0.08.
  
  Each had the same sign in 2024 and has grown past the 5% test in 2025 (`second-year-2025.md`).
- *Differs → agrees: 4 elements.* Skegness 132/33 kV GT1, GT2 (trafos 26, 27) and the Tattershall tee (lines 114, 121):
  their 2024 offsets of 1.2–1.4 MW fall within the test in 2025.
- *Not in NGED's file → compared: 6 elements,* from NGED's newer model edition.
  - Grantham 132 kV 303 – #110 (line 9): differs, +1.81.
  - Lines 105 and 106: agree.
  - Lines 6, 11 and 80: input.
- *Differs in both years, offset re-measured on 2025: 24 elements.*
  - Sleaford 132/33 kV GT1, GT2: −1.91 → −2.46 MW.
  - Grantham GT1, GT2: +1.37, +1.33 → +1.81, +1.76.
  - Sleaford – Tattershall: −2.53 → −2.19.
  - The Whitecross – Burton Pedwardine – Great Hale – Billingborough ring: about ∓0.5 → ∓1.3.
  - The rest within 0.4 MW of 2024.

**Checked in the browser** (API 8011 and planner 3011, this session's code; zero console errors):
- *2024 screened:* Spilsby T1 and T2 greyed, "reactive input unreliable: not a finding"; not in the firm-capacity list.
- *2025 screened:* Spilsby first in the firm-capacity list, 6.98 MVA against 6, 93 h. Screenshot:
  `screenshots/work15-2025-spilsby-firm.jpg`.
- *2035 Holistic Transition (2024's flows):* Spilsby greyed (75.5 and 65 h, peaks 235% and 229%), not in the list. The
  Sleaford GTs show 2025's offset. Screenshot: `screenshots/work15-2035-ht-spilsby-greyed.jpg`.
- *2035 HT on 2025's flows:* Spilsby in the list (7.17 MVA, 128 h), with the caveat in its limits text (derived in 2025,
  so not grown).
