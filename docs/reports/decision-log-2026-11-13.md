# Decision log: the measured-year work, 12–13 November 2026

*The modelling decisions taken during the measured-year work, in the order they were taken, each with its reason, what
it changed and where it is recorded. All of them are applied in the code and the Sources and assumptions register;
they have not yet been reviewed as a set. Supported by NGED Open Data.*

**How to read it.** Each line says what was decided, why, what it changed, and where it is recorded.
- *Reports* means a document in `docs/reports/`, with no change to the engine's planning output.
- *Spec* is `timeseries-step1-spec-2026-11-12.md`.
- *Register* is the root README's *Sources and assumptions*.

## Step 1: the measured year 2024

1. **Re-pin the DFES file, Warth Lane only.**
   - *What:* a diff had to show nothing else in `dfes.json` changed.
   - *Why:* the pin skips LTDS rows marked Removed, so Warth Lane's supply area was never bundled. Without it the
     engine fell back to the LTDS forecast (×4.4 by 2030).
   - *Changed:* Warth Lane's growth curve (the DFES path: 24.7 MW in 2030, 37.7 MW in 2035).
   - *Where:* spec, "Decided overnight" a.
2. **Mill Farm battery: its feeder flow taken whole.**
   - *Why:* the feeder flow carries the battery's export and import together (−6.7 to +7.1 MW). Zeroing the import would
     contradict that same flow.
   - *Changed:* that feeder's input in the measured year.
   - *Where:* spec b.
3. **Seasons: NGED's four, wording unverified.**
   - *What:* transformers keep a single rating, and every loading is also recounted against the summer rating as the
     conservative bound.
   - *Changed:* the line ratings used per half-hour.
   - *Where:* spec c; register.
4. **The report's shape.**
   - *What:* model comparison first, then utilisation, what an intact network leaves out, and the 2024 planning cases
     beside the year.
   - *Changed:* report only.
   - *Where:* spec.
5. **After the one-week dry run: option A.**
   - *What:* run the year under the pass rule as written and report rule 1 (closure, 75% of half-hours against the 95%
     required) as it falls.
   - *Why:* not to move a rule after seeing data.
   - *Changed:* report only.
   - *Where:* spec, "Added after the one-week dry run".
6. **Added before the year's results.**
   - *What:* the closure gap broken down; closure in context; a label on every element ("flow agrees", "flow differs"
     with its offset, "not compared"), with only the first counted as findings.
   - *Changed:* report only.
   - *Where:* spec.
7. **After the results: three runs, and a reactive-power screen.**
   - *What:* A as published, B screened, C unity (diagnostic). The screen flags a half-hour as implausible above
     1.5 × installed transformer capacity, and as suspect where MVAr exceeds 2 × MW and 2 MVAr; flagged half-hours take
     MW × tan(the LTDS angle).
   - *Why:* NGED's MVAr is physically impossible at Spilsby (up to 54 MVAr through 2 × 6 MVA) and once at Billingborough.
   - *Changed:* run B is the basis for utilisation.
   - *Where:* spec; measured-year report 4.1; register.
8. **Spilsby declared unreliable for the year.**
   - *What:* the screen flags more than 1% of its half-hours.
   - *Changed:* its transformers and 11 kV busbar are labelled "reactive input unreliable", not findings, here and in
     the planner.
   - *Where:* measured-year report 4.1.
9. **Experiment D: are the Sleaford 33 kV ties run open in NGED's model?**
   - *What:* read-only.
   - *Found:* NGED's files do not support it.
   - *Changed:* nothing in the network.
   - *Where:* measured-year report 3.3.
10. **Warth Lane demand restored** from an LTDS row marked Removed (18.61 MW).
    - *Why:* NGED's flows and the DFES carry the site; without it, Skegness's coincidence read 1.06, which is impossible.
    - *Changed:* every plan year. The winter-peak import goes from 137 to 144 MW today, and Skegness's other primaries
      are no longer overstated by about 37%.
    - *Where:* register "Warth Lane demand"; measured-year report 4.2.
11. **Work 1: the tie-mismatch candidates tested** on one January week.
    - *Found:* impedances, injections, joined boards and taps all ruled out. Sleaford's published transformer impedance
      is the one remaining lever.
    - *Fixed one definition error:* transformer vk set from X alone instead of √(R² + X²), at most 0.53% low.
    - *Changed:* planning cases by at most 0.1 point in 2026 and 2030, and by at most 1.5 points and one tap step in
      2035. Breaches unchanged (0, 0, 15).
    - *Where:* measured-year report 3.4; register "Transformer impedance".
12. **Work 2: large generators on their own feeders.**
    - *What:* 11 sites the ECR names (145.65 MW) moved from the BSP busbars to their feeders. Ash Farm (48.38 MW of
      solar, connected 2025, missing from this LTDS) added at Bicker Fen 132 kV by its coordinates.
    - *Changed:* the solar feeders now load to 65–84% at summer minimum (they were about 1%). Today's summer-minimum
      export goes from 292 to 340 MW. No breach changes in any year.
    - *Where:* register, two rows; measured-year report 4.2.

## The grown years and the year view

13. **Work 3: each substation against its own peak and firm capacity**, 2026 to 2035.
    - *Found:* the answer turns on one substation, Warth Lane. Under NGED's LTDS forecast it reaches 85 MVA by 2030,
      about 3.5 times the DFES path.
    - *Changed:* report only.
    - *Where:* `firm-capacity-2026-11-13/report.md`.
14. **Work 4: grown years.**
    - *What:* 2024's half-hourly shape at 2030 and 2035 demand, each primary scaled by the engine's own DFES ratio
      (2030 Holistic Transition, 2035 Holistic Transition, 2035 Falling Behind).
    - *Changed:* report only. Run files are in the git-ignored warehouse.
    - *Where:* `grown-year-2026-11-13/spec.md`, `report.md`; register "Grown year".
15. **Correction:** the grown years' hour counts were first called "a lower bound". They are indicative, not a bound in
    either direction.
    - *Where:* grown-year report, spec, design note, the planner's limits text.
16. **Work 5: a year view in the planner.**
    - *What:* run selector, Over rating layer, Year runs tab, a month-by-hour grid in the detail card. Duration is
      encoded as heavier red for longer, at the guide's request.
    - *Changed:* new engine module `runs.py`, API `/runs`, the planner's Year runs tab.
    - *Where:* `grown-year-2026-11-13/design-year-view.md`.
17. **Work 6a: Warth Lane at NGED's LTDS forecast**, 2030, as a sensitivity.
    - *Found:* 12 elements over rating instead of 2. Warth Lane's three transformers are over for 7,000–8,400 hours.
    - *Changed:* report and a catalogued run.
    - *Where:* grown-year report section 6.
18. **Work 6b scope: a branch's connections in a grown year.**
    - *What:* shapes from one 2024 site per technology; a battery on a placeholder daily rule; voltage control run at
      unity; report and engine only; two worked examples (Grantham 240 MW split and tied, and Thorns Farm 40 MW).
    - *Where:* `scoping-6b-connections-in-a-year.md`, "As decided"; register rows "A branch's connections" and "Year
      shape".
19. **Work 6b results.**
    - *Grantham:* its circuits to Bicker Fen are over rating for 527–569 hours with the sections split, about 70 tied.
    - *Thorns Farm:* line 115 is over for 402 hours, where the summer-minimum planning case shows only 102.5%.
    - *Changed:* report and catalogued runs.
    - *Where:* `branch-examples.md`.
20. **Consistency review of the three reports and the README.** Corrections and cross-references only; no figure moved
    except corrected errors (the Sleaford offset sign, the Gorse Lane 77%).
    - *Where:* listed in the guide's messages; each change is in its report.
21. **The guide's code read**, no result changed:
    - grown files now save the scaled reactive series;
    - the battery rule's clock stated (a fixed clock, most likely UTC);
    - the reactive-power sign convention stated as one definition for year and planning cases;
    - a comment moved.
    - *Where:* register "Year shape: battery"; grown-year report "Run files".

## A branch's year from the planner

22. **Work 7: run a branch's year from the planner.**
    - *What:* one job on the existing worker, keyed by the result cache's key. The run file is the cached result. The
      tab compares it with the catalogued year and shows the branch's study-case figure beside each changed element.
    - *Verified:* a run from the planner was identical to the catalogue's file.
    - *Where:* design-year-view.md "Work 7"; register; README API table.
23. **After review: a plan run stops a year run.**
    - *Why:* responsiveness.
    - *Measured:* the plan run waited 1.2 s.
    - *Also:* hours badges only for 100 hours or more at the fitted view.
    - *Where:* design-year-view.md "Changed after the guide's review".

## The shape of demand

24. **Work 8.1: NGED's DFES 2025 fetched whole** by a new manual pipeline asset (`nged_dfes_detail`) into the
    git-ignored warehouse, proceeding on the licence text the owner supplied although the portal labels it "WPD Open
    Data Licence".
    - *Found:* heat-pump and charging profiles present; the file's time column lost its hour (clock rebuilt from row
      order, checked).
    - *Stopped:* the per-ESA volumes ZIP is behind a bot challenge, not bypassed.
    - *Where:* `grown-year-2026-11-13/data-note-dfes-shape.md`; pipeline README.
25. **Work 8.1b: the Power Projections route.**
    - *Closed:* the file holds one peak per ESA, scenario and year (labelled with its season), not a day.
    - *Recorded:* NGED's own projections move Bicker Fen's winter peak from the evening to 09:45 or 13:15 by 2035 under
      Holistic Transition. Much of that rests on the scenario's assumption that home charging is managed out of the
      evening.
    - *Where:* the data note, 8.1b.
26. **Work 9: a per-season peak table, closed without building it.**
    - *Why closed:* the Power Projections give the year's one peak, labelled with the season it falls in, so there is no
      peak for each season to tabulate.
    - *Corrected:* the data note had said "per season" (8.1b, point 1); it now says one row per ESA, scenario and year.
      Easton's and Ruskington's early-year peaks are labelled intermediate cool, not winter; the 8.2 tolerance says so.
    - *Where:* the data note.

## The six bases and the review

27. **Work 10: the planner's six bases all on file.** 2030 EE, 2035 EE and 2030 FB were run, with the same code and
    method, so every pathway and year the planner offers has a grown year a branch's year can run on.
    - *Found:* 2035 EE ends close to 2035 HT (24 reliable elements over rating against 26, the same nine substations
      above firm, import 259 MW against 262). Both 2030 bases on the high pathways have nothing reliable over rating
      beyond half an hour.
    - *Where:* grown-year report section 7, with the files' sha256.
28. **The guide's review: a key bug fixed, the run catalogue moved behind the GridSource seam.**
    - *Key bug:* a branch's year was keyed on the branch's inputs only, so its 2030 and 2035 runs shared one key, and the
      second would have been served the first's file. The key now includes the base run ("before"). The old Thorns 2030
      file is correct but no longer reachable; it is kept.
    - *Seam:* `runs.py` is now general (a `RunCatalogue` and the `RunFiles` that read it, given a `net_factory`); NGED's
      catalogue moved to `nged_runs.py`, served by `GridSource.run_catalogue()`. The API wires it in `deps.py`. A
      before/after snapshot of the engine's output was identical on all 15 entries.
    - *Also:* the network cache is gone (`net_factory` passed in); the year view says the firm-capacity list covers
      primaries only.
    - *Verified:* the API's `/runs` and a run's summary on a spare port match the analysis figures. Thorns asked for
      2030 and 2035 got two separate jobs and files (the old key would have joined them); the new 2030 file equals the
      old one exactly. In 2035 Holistic Transition, Thorns puts line 115 over rating for 369 hours (402 in 2030).
    - *Where:* design-year-view.md; packages/optimizer README; root README register.
29. **Work 11: a second supply point, scoped read-only.** Nothing built or downloaded beyond portal metadata.
    - *Found:* the model's edge is three couplers inside substations split between supply points: Boston 132 kV and
      Tattershall 33 kV with Walpole, Grantham North 132 kV with Staythorpe. NGED's own flows show no branch crossing
      them, so they are open in normal running.
    - *Found:* both neighbours have every dataset in the same form. Every exception found tonight came from the
      half-hourly check, which makes that check the commissioning test.
    - *Found:* Bicker Fen's **2025** half-hourly flows are now published.
    - *Where:* `scoping-second-supply-point-2026-11-13.md`.
30. **Work 12: a second measured year, 2025.**
    - *Settled first:* NGED's "2025 Connected Export (ID 1124)" is a measured historic year, not a scenario. It
      covers calendar 2025 complete, with the same 34 nodes. Its series differ from 2024's as another weather year does.
      NGED's model behind the branch flows is a newer edition (73 branches reversed, 7 new, 4 gone).
    - *Done:* a new manual asset `nged_flows_2025` (layout rewritten to 2024's, values checked unchanged). One screened
      run on today's network with the same code and rules: sha256 `43652c54…ed35c`. Two small fixes, 2024's figures
      unchanged: an empty shapes table, and branch sets that name a branch either way round. The run is catalogued
      as `2025-screened`.
    - *Found:* rule 1 at 94% of half-hours (60% in 2024). The 28 elements that differ from NGED's model in both years
      do so with the same sign. Nothing over its rating in either year. New Beacon Road and Alford are above firm for
      6 and 8 h (5 and 9). Spilsby, usable now, is above firm for 93 h. Spilsby's reactive fault and Manor Farm's zero
      were 2024 faults. Wrangle's 11 kV series is zero for 99% of 2025. Ash Farm's spur is in NGED's model at Bicker Fen
      132 kV (confirming the engine's placement) but carries nothing.
    - *Changed:* the grown years' limits text now gives the size of one weather year (peaks of the most loaded
      primaries moved by up to 13 points, the median element by 2). The measured limits text is year-neutral, with
      a note per year.
    - *Where:* `measured-year-2024/second-year-2025.md`; register "A second measured year: 2025".
31. **Work 13: the size of "one weather year".** 2035 Holistic Transition grown on 2025's flows instead of 2024's (same
    multipliers, network and method; `run.py ... flows-2025`, sha256 `0905650a…b6aaf`, catalogued as
    `2035-ht-flows-2025`).
    - *Found:* the totals hold (23 elements over rating against 24, 9,212 hours against 9,268; import 268 MW against
      262).
    - *Found:* single elements move a lot: peaks by a median of 3 points (up to 34), hours by up to a factor of five.
      New Beacon Road T1 goes from 1,818 to 1,499 h, Skegness GT1 from 745 to 135, Great Hale from 599 to 1,196.
    - *Not comparable:* Wrangle; Spilsby (usable in 2025, but derived and therefore not grown); the Manor Farm tee.
    - *Changed:* the grown years' limits text now gives this spread and says to read an element's hours as an order of
      magnitude. `analyse.py` (grown) reads Gorse Lane's feeders whichever way round they are listed.
    - *Where:* grown-year report section 8; register "A grown year on 2025's shape".
32. **Work 14: the builder on Staythorpe, a probe.** A throwaway script outside the repository; nothing entered the
    product.
    - *Found:* the general steps ran (buses, lines, transformers, loads, Table 5 fleet, small embedded). The build then
      **failed** at `ECR_ADDITIONS`: Ash Farm's Bicker Fen node, `KeyError: 'BICF1_MAIN1'`.
    - *Found, before the failure:* demand was scaled to Bicker Fen's GSP peak (149 MW against NESO's 258–264 MW for
      Staythorpe) with no warning. 4 of Staythorpe's demand primaries match no DFES supply area.
    - *Stopped there,* as briefed.
    - *Where:* `probe-staythorpe-builder-2026-11-13.md`.
33. **Work 15: the year view judges agreement and input reliability apart.**
    - *Agreement* with NGED's model is a property of the network: it is now judged on 2025 screened, the best-closing
      year, by the same rules. NGED's 2025 file compares every element its 2024 file did, plus six more. Each label
      carries its year (`label_year`).
    - *Input reliability* is a property of a run's flows: it is now read from each run's own file (its screen flags,
      identical to its source year's measured run). `2024-published`, which predates the screen, takes those of the
      same flows.
    - *No number changed* on any of the 14 catalogued runs (checked element by element).
    - *Labels:* 11 elements go from "agrees" to "differs", 4 from "differs" to "agrees", 6 are newly compared, and 24
      keep "differs" with re-measured offsets. Spilsby becomes a finding, and joins the firm-capacity list, only on the
      two runs built on 2025's flows.
    - *Checked in the browser:* 2024 screened and 2035 HT still grey Spilsby; 2025 screened lists it at 93 h above
      firm; the grown year on 2025's flows lists it at 128 h with its caveat. Two screenshots; zero console errors.
    - *Where:* design-year-view.md "Work 15"; register "The year view's labels"; packages/optimizer README.
34. **Work 16a: the Sleaford impedance lead, tested on a full year (an experiment; the engine keeps the published figure).**
    - *Run:* 2025 screened with Sleaford's two 132/33 kV units at 6.6% (vk and vkr × 6.6/11.2, X/R kept), in the run's
      `net_factory` only. sha256 `52d090ed…f50b3`.
    - *Found:* it halves every offset in the Sleaford-Grantham cluster (Sleaford BSP pair −4.92 → −2.59 MW, Grantham
      +3.57 → +1.75; the Grantham tie 1.9–2.3 → 1.1–1.3 MW). 12 of 39 "differs" become "agrees", and 2 small RAF Cranwell
      sections go the other way.
    - *Not enough:* rules 1–3 still fail (rule 2 at 14 of 18, rule 3 at 73%). About half is left, so the lead stays a
      lead.
    - *Changed:* the question for NGED is now specific: what impedance and taps NGED's model holds for Sleaford GT1/GT2.
      The 2024 variant was not run, since it was conditional on this closing.
    - *Where:* `measured-year-2024/second-year-2025.md`, the experiment section.
35. **Work 16b: the supergrid transformers' import limit held for all four published seasons.**
    - *The limits:* 160.1 MW winter, 179.1 MW intermediate cool and warm, 110.8 MW summer, per SGT. That an
      intermediate limit sits above the winter one is unusual; it is held as published.
    - *Counting:* each half-hour of a year now counts against its own season's limit.
    - *Unchanged:* the planning cases never enforced the import limit (export only); they were recomputed for 2035 EE
      and are identical. The year view counts no import hours.
    - *Restated:* with both SGTs in service, no grown year exceeds its season's limit. Before, 2035 HT showed 56 h and
      2035 EE 47.5 h, nearly all winter half-hours measured against the summer limit. With one SGT out, the seasonal
      count is higher: 2035 HT 865 → 1,128 h (548 of them summer).
    - *Where:* register "Supergrid transformer limits"; grown-year report sections 4, 6 and 7; `import_hours.py`.
36. **Work 17: import is now a limit check in the planning cases.** It closes a gap 16b found: no breach of the
    supply point's import limit was ever listed.
    - *The check:* in each study case, the GSP's import against its season's limit with both SGTs in service: winter
      peak against 320.2 MW, summer minimum against 221.6 MW. It is listed as a `gsp_import` Reason with value, limit
      and case. `CaseSpec.season` maps a case to its season, and the builder puts the limits on the net
      (`net["gsp_import_limit_mw"]`). A grid that gives none gets no check. The loss of one SGT is not studied.
    - *Where it sits:* beside the export check in `feasibility`, not in `LIMIT_CHECKS`: those receive no supply-point
      flow, and the export check (its model) sits there too.
    - *No change on main:* all 40 plan years (2026–2035 × ht, ee, he, fb) are identical before and after, every field.
      Main's largest import is 263.4 MW.
    - *Fires:* a branch with the registry's largest import project (ECR-83EF2, the 248 MW Lincoln battery, charging at
      winter peak) imports 409 MW in 2026 against 320 MW, rising to 527 MW in 2035. The planner lists it under "GSP
      import limit" (screenshot `work17-gsp-import-limit.jpg`).
    - *Cache:* the engine fingerprint hashes the engine's source, so this change retires every cached year by itself.
      `year_signature` needs nothing, because the limit is a property of the grid, not of a plan's inputs.
    - *Contract:* one new `Reason.type` value, `gsp_import`. The web gives it a title and label (`model.ts`) and a type
      (`types.ts`).
    - *Where:* register "Supergrid transformer limits"; README limitations; packages/optimizer README checks list.

## Step 4: a second supply point (Staythorpe), chosen by the guide after the owner asked it to decide

37. **Stage A: everything that belongs to one supply point is one record** (`nged_points.SupplyPoint`; `BICKER_FEN`
    is the default).
    - *Safeguards:* a supply point with no published peak fails to build (`require_peak`), and no other record can be
      built from Bicker Fen's bundled snapshot.
    - *No change:* every output is identical before and after (the built network, the model, the registry, the
      boundary, the forecasts, every plan year under four pathways, the 14 run summaries). One assumption message is
      reworded, because the constant it named no longer exists.
    - *Order:* the register row was written **after** the code this time, against the working rule. Nothing it records
      depended on the order; register first from here.
    - *Where:* `nged_points.py`; register "Supply points (Step 4, Stage A)"; packages/optimizer README.

38. **Stage B: Staythorpe's snapshot, fetched as Bicker Fen's is and kept apart** (`apps/pipeline/warehouse/supply-points/staythorpe/`,
    git-ignored; manual asset `staythorpe_snapshot`). Nothing is bundled into the package.
    - *Peak:* 261.169 MW, by Bicker Fen's exact method: NESO's STAY_1, FY2024/25, the plain mean of HE 263.580, EE
      262.331 and HT 257.595. Bicker Fen's 149.235 is the same plain mean, checked.
    - *Limits per SGT:* import 208.3 MW winter, 185.0 intermediate, 95.9 summer; export 578.2 MW.
    - *Record:* group spellings held exactly in `nged_points.STAYTHORPE`, which has no exceptions.
    - *Where:* register "Staythorpe's snapshot (Step 4, Stage B)".

39. **Stage C: the DFES name rule.** RD reads as ROAD, and the portal is searched on the first alphanumeric token.
    - *Bicker Fen:* matches and rows identical under the old and new rule (21 and 1,596), and its network unchanged.
    - *Staythorpe:* 17 → 20 primaries matched. Asfordby Colliery has no supply area.
40. **Stage C: the infeed sits on the published infeed site** (`SupplyPoint.infeed_node`, required).
    - *Why an inference:* Td Limits names the site and its SGT bays, which are not LTDS nodes.
    - *Bicker Fen:* `BICF1_MAIN1`, the same bus as before, with every output identical.
    - *Staythorpe:* `STAY1_MAIN1` (Staythorpe C), where "best connected" had picked Staythorpe B.
41. **Stage C: the builder records what its infeed cannot reach**, instead of dropping it unseen (`unreachable_demand`,
    `unreachable_generation`).
    - *Bicker Fen:* drops nothing.
    - *Staythorpe:* 20.87 MW unreachable (Asfordby Colliery 2 × 10.35 MW, Cotham Grange PV 0.16 MW). The coincidence
      scaling is applied before removal and not redone.

42. **Stage C: Hawton's BSP rows are an aggregate.** A named exception in Staythorpe's record, `bsp_aliases =
    {"Hawton SOP": "Hawton"}`, with its evidence: 76.8 MW on Hawton's own bars against its primaries' 81.6 MW (94%).
    - *Rejected:* a general prefix rule.
    - *Bicker Fen:* unchanged (full snapshot identical).
43. **Stage C: a screen for an aggregate counted as demand** (`possible_bsp_aggregate`, a builder assumption that
    changes nothing).
    - *Results:* it lists nothing at Bicker Fen and lists Hawton at Staythorpe before the alias.
44. **Found, not changed: Staythorpe's supply-point scaling factor is 1.50.**
    - *The figures:* Table 3's own maxima sum to 180.2 MW against NESO STAY_1's 261.2 MW (Bicker Fen: 0.96).
    - *Effect:* every Staythorpe planning-case load is inflated by half, and the plan years stop converging from 2031.
    - *NGED's own flows:* the 2025 SGT import peaks near 140 MW.
    - *Open, for the guide:* a scaling factor above 1 is not a coincidence, so either NESO's STAY_1 covers more than
      this LTDS group, or the group lacks demand.

45. **Stage C: a coincidence factor above 1 stops the build** (tolerance 1e-6, for rounding).
    - *Bicker Fen:* its factors are 0.82, 0.78 and 0.93 at the BSPs and 0.96 at the supply point; every output is
      identical.
    - *Staythorpe:* NESO's STAY_1 gives 1.505, so the build stops with the figures.
    - *History:* the same signal (Skegness at 1.064) was Warth Lane's trace before it was found.
46. **Stage C: Staythorpe's peak is 147.82 MW, NGED's metered coincident primary demand** (8 January 2025, 17:30),
    not NESO's STAY_1, which is not used and goes to the questions.
    - *Method tested where the answer is known:* at Bicker Fen it reads 142.16 and 143.28 MW, 95-96% of NESO's
      149.2. Bicker Fen keeps NESO's figure.
    - *Staythorpe:* factor 0.85; built 130.45 MW, plus 17.37 MW unreachable.
47. **Stage C: Ranskill–Daneshill Road, a normally-open point** (`STAYTHORPE.normally_open`; the circuit leaving the
    Daneshill Road ACR).
    - *Evidence:* inferred from four branches at 0.000 MW all year in NGED's 2025 file, the first use of Experiment D's
      criterion.
    - *Rerun:* rule 3 went from 69% to 79.7%; radial 32 of 32; closure unchanged at 100%.

48. **Stage C: a connector published as a circuit.** An LTDS row with R = 0, X ≤ 0.01% and no rating is a connector:
    a closed bus–bus switch, with the row kept out of service so no element id moves (`config.CONNECTOR_MAX_X_PCT`).
    - *Rows caught:* exactly the rows the builder had been giving an invented fallback rating. Bicker Fen: six (five
      "L0" at 0.01%, plus one "LK" between two Boston 132 kV sections). Staythorpe: eleven.
    - *Correction:* an earlier note said two at Bicker Fen. That came from a truncated print; the L0 experiment
      converted every L0 row, so its result covered all five.
    - *Bicker Fen, all forty plan years:* ids identical; breaches, convergence and headline figures identical. The
      largest moves are 0.1 point (a transformer) and 2.0 points (a line at 5.9% beside RAF Cranwell).
    - *Unchanged infidelity:* the CIM export still writes the row as a short line segment (owner's list).
    - *Also changed with it:* the flows mapper no longer matches NGED's column for a connector (it had mapped the
      Boston "LK" row), and the year view does not compare a group made only of out-of-service lines. Per-node
      injections move by at most 0.02 MW, so no Bicker Fen run was redone beyond the 2025 reference (the old file is
      kept as `-pre-connector`; rules and labels unchanged).

49. **Stage D: the Staythorpe report** (`docs/reports/staythorpe-2026-11-13/report.md`).
    - *First:* Staythorpe is an island in normal running by NGED's own model, as Bicker Fen is; outages and transfers
      are not covered.
    - *Leading finding:* Tuxford 33/11 kV (one 6 MVA unit) is above its nameplate today on measured data (7.23 MVA,
      8 January 2025), and both growth sources take it to about 2.5 times by 2030.
    - *Commissioning, 2025:* closure 100%, radial 32 of 32, rule 2 22 of 26, rule 3 59 of 74 (one group short of 80%).
    - *Study basis:* firm plant at full output halves Staythorpe's winter-peak import (70.8 against 143.6 MW at nil;
      the measured 2025 maximum is 142.1). Left open; nothing changed.
    - *Plan years:* Tuxford alone breaches 2028–2031; six transformers 2032–2033. Under Holistic Transition growth
      2034 has no valid operating point (the solver's solution is a voltage collapse, Tuxford 11 kV at 0.26 pu at winter peak; no loading
      from it is quoted) and 2035 does not converge.
    - *Item 44's open point* is closed by items 45 and 46; with the questions closed, what NESO's STAY_1 covers is
      recorded as undetermined from the published files.

50. **Work 8.2: the DFES pieces do not reproduce NGED's projection, so no shaped year was built**
    (`docs/reports/dfes-shape-2026-11-13/`).
    - *Edition:* the owner's download is the 2025 edition (the four 2025 scenarios, baseline to 2050, 1,082 ESAs, all
      21 of Bicker Fen's by exact name). It is subset beside the download.
    - *Order:* the specification and the register row were written before any gate code.
    - *Gate (2035 Holistic Transition):* 8 of 21 against the 15 required. The rebuild is short at 18 of the 19 tested
      ESAs (median −11.7%). Spilsby (no metered series) and Wrangle (zero series) count as failures, as the
      specification set.
    - *What is missing:* NGED's base demand. Its profiles file holds about 200 base-demand cluster profiles with no
      published assignment of an ESA to one, and the measured base is a net flow.
    - *Stopped as specified:* the engine is unchanged, no run was made and no catalogue entry added. The grown years keep
      their stated limit: their hours follow the measured evening shape, while NGED's projection puts the 2035 peak in
      the morning or at midday.

51. **Work 8.2 addendum: shaped demand at the eight areas that passed the gate** (decided by the guide; a sensitivity,
    not a shaped year, and not catalogued).
    - *Order:* the specification and the register row were written before the run.
    - *The run:* 2035 Holistic Transition on 2024's flows, shaped at Alford, Cranwell, Easton, Ingoldmells, New Beacon
      Road, Skillington, Tattershall and Trusthorpe, uniform elsewhere. The engine is unchanged (the increments are
      added in the report script). sha256 9733f047…c0448eb.
    - *Result:* only New Beacon Road and Alford exceed rating.
      - *New Beacon Road:* 2024's shape understates the hours by up to about ×2 (1,818 → 3,695 h, at the same peak),
        moving them to the night, midday and spring.
      - *Alford:* hours unchanged (1,164 → 1,151 h), with the peak lower (156% → 136%) and in the morning.
      - The shaped counts lean high (peak-day profiles applied every day).
    - *Where:* dfes-shape `result.md` (addendum); grown-year report section 5, one bullet.

52. **Work 18: a voltage-collapse floor** (decided by the guide; `config.COLLAPSE_VM_FLOOR_PU = 0.5`; the register row
    was written before the code).
    - *Rule:* a case that converges with an in-service busbar below 0.5 pu, after the taps settle, has **no valid
      operating point**. It is reported like a non-converged case: one `voltage_collapse` reason naming the busbar and
      its voltage, `converged` false, no loadings and no breach list.
    - *Year driver:* such a half-hour is not solved, and is counted in the run file's `collapsed`. `RunSummary.collapsed`
      is shown in the Year runs tab as "(n a voltage collapse, m did not converge)" when anything is unsolved.
    - *After a collapse,* the next solve starts flat, not warm from the collapsed voltages.
    - *Why 0.5:* below the nose of the P–V curve, V = E / √(2(1 + sin φ)), for any demand at 0.8 lagging or better
      (0.56 pu). Not a statutory limit (the bands are unchanged), and not a stability study.
    - *No change on main:* all 40 plan years under the four pathways and all 14 catalogued summaries are identical
      before and after.
      - The lowest plan-year busbar is **0.9157 pu** (2035 Electric Engagement); the guide's remembered 0.916 holds.
      - The lowest solved half-hour in any Bicker Fen run file is **0.735 pu**, in the 2024 year run on NGED's published
        reactive power (Spilsby's faulty MVAr). In the grown years it is 0.884 pu.
    - *Firing at Staythorpe:*
      - 2034 HT is now "no valid operating point at winter peak demand", with Tuxford 11 kV at 0.26 pu.
      - 2035 still does not converge.
      - 2033 is unchanged (6 breaches, lowest 0.951 pu).
      - No saved Staythorpe half-hour sits below the floor (lowest solved 0.733 pu in 2035 grown), so its grown years
        are unaffected. The 148 unsolved half-hours there failed to converge.
    - *Corrected:* the "0.05 pu" quoted for 2034 was the summer-minimum case, solved after the collapse from the
      collapsed winter state.
    - *Not shown in the browser:* the collapse wording. At Bicker Fen even a large demand connection goes straight from
      valid to non-convergent (Alford 11 kV: 27 MW valid, 28 MW does not converge), and Staythorpe is not in the
      planner. The planner was checked on the spare ports: it loads, the run line reads as before, and there are no
      console errors.
    - *Checks:* engine 34 passed; API 7 passed, 1 skipped; web typecheck and build clean.

## Only the owner can do these

**On this machine:** *done (13 November): the owner ended the stray API process (PID 5024, port 8000) and the Vite dev server (PID 41616, port 3010).*

**Downloads:** *done (13 November): the owner downloaded `dfes_volume_projections_esa_v2.zip` into `apps/pipeline/warehouse/nged-flows/dfes-2025/`; Work 8 resumes from it.*

**Decisions to confirm or reverse:** items 1–36 above.

**An observation about the engine, not a change** *(acted on: Work 18, item 52, adds a 0.5 pu collapse floor)*:
nothing in the engine distinguished a collapsed power-flow solution (a converged low-voltage solution) from a valid
one, so a plan year could report breaches from one. Staythorpe's 2034
is such a case (Step 4, item 49). At Bicker Fen the lowest voltage in any plan year is 0.916 pu (the guide's figure),
so it has not arisen there.

**Open choices (no recommendation made):**
- Whether and where to widen to a second supply point: Walpole or Staythorpe (item 29; the scoping note's section 5
  gives the first step).
- *Decided:* the reference run for the planner's agreement labels
  **stays 2024 for now**. Two different things share that one reference today, and they should not:
  - *agreement with NGED's model* is a property of our network, and 2025 is the better year to judge it on (it closes
    on 94% of half-hours);
  - *whether an element's input is reliable* is a property of the year a run is built from. Every grown year and branch
    year is built from 2024's flows, where Spilsby's reactive power is corrupt, so taking that flag from 2025 would
    silently clear Spilsby in runs still fed the bad series.
  
  **Recommended next change to the year view:** take agreement from the best-closing year and input reliability from
  each run's own source year. It is contained but changes what the planner says on every run, so it is to be done
  deliberately and checked in the browser, not at the end of a night. *Done later the same night as item 33, with
  that browser check.*
- Of these, items 1–3 and 7–8 change the measured year's inputs, and items 10–12 change every plan year.
- Item 24 includes the licence-name question: the portal says "WPD Open Data Licence".

**NGED's season table:** the month-to-rating table from NGED's Network Development Plan methodology. Pasting it settles
the seasons' wording (item 3).

**AGENTS.md lines** (guidance files are edited only by the owner):
- `packages/optimizer/AGENTS.md` "What it owns": `runs.py` (general), `nged_runs.py` (NGED's catalogue), `timeseries.py`, `nged_flows.py`, `network.solve_snapshot`,
  `GridSource.measured_year`;
- `apps/api/AGENTS.md` layout: `routers/runs.py`, `year_runs.py`;
- `apps/pipeline/AGENTS.md`, if it lists assets: `nged_flows`, `nged_dfes_detail` (`defs/flows.py`).

*Closed: on 13 November the owner decided not to send these questions; the list below is kept as it stood and is no longer maintained.*

**Questions for NGED** (nged.data@nationalgrid.co.uk, the address in the licence), with the evidence for each:

| Question | Evidence | Where |
|---|---|---|
| Spilsby's 2024 reactive-power series | Up to 54 MVAr through 2 × 6 MVA transformers; 832 half-hours flagged. Clean in 2025 (up to 2.4 MVAr), so a 2024 data fault | measured-year 4.1; second-year-2025 |
| The GSP node series | Not used for closure; shown only beside it | measured-year 3 |
| Why Warth Lane's demand row is marked Removed | The site is in NGED's flows (5.8–18.9 MW) and the DFES; without it, Skegness's coincidence is 1.06 | register "Warth Lane demand" |
| Manor Farm PV's 2024 series | Its spur reads 0 MW all through 2024; in 2025 it carries up to 18.7 MW (17.4 GWh), so the 2024 zero looks like a data fault | measured-year 3.3, 7a; second-year-2025 |
| Where Ash Farm connects | Placed at Bicker Fen 132 kV by coordinates (0.33 km); the point is not published | register "Connected sites missing" |
| What impedance NGED's model holds for Sleaford 132/33 kV GT1 and GT2, and their normal taps | Published 24.92% on 100 MVA (11.2% on 45 MVA) against 6.6–7.0% at Skegness and Grantham. On the full 2025 year, 6.6% halves every offset in the Sleaford-Grantham cluster and turns 12 elements from "differs" to "agrees", but rules 1–3 still fail: about half is left | measured-year 3.4; second-year-2025 (Work 16a) |
| What connection lies behind the LTDS forecast at Warth Lane, and its profile | 85 MVA by 2030, about 3.5 × the DFES path | firm-capacity report; grown-year section 6 |
| Whether Grantham 132 kV runs split, and whether the 240 MW solar + storage offer there carries reinforcement or an export limit | Split: over 500 hours over rating in 2030; tied: about 70 | branch-examples.md |
| The DFES Profiles file's time column | Every value reads `15:00.0` or `45:00.0`; the hour is lost | data-note-dfes-shape.md |
| What area NESO's STAY_1 covers | NESO's 2024/25 peak for STAY_1 is 261.2 MW, 1.50 times the 173.6 MW of Staythorpe's own LTDS coincident maxima, while NGED's metered primaries peak at 147.8 MW and its SGTs import at most 142 MW (to NESO and NGED) | staythorpe report |
| Bourne West 25 kV in 2025 | NGED's series at BYTH8_MAIN2 (Table 3: 2.93 MW) is exactly 0 on all 17,520 half-hours, beside Wrangle's 99% | staythorpe report |
| Wrangle 11 kV in 2025 | NGED's series is zero for 99% of 2025 (42% in 2024): a reconfiguration or a fault? | second-year-2025 |
| Ash Farm's output in 2025 | Connected 11 July 2025 per the ECR; its spur to Bicker Fen 132 kV bay 1005 is in NGED's 2025 model but carries nothing all year | second-year-2025 |
