# Specification: a measured year through the engine at Bicker Fen

*12 November 2026. Read-only scoping, nothing built. Scripts are throwaway, in the implementer's scratch directory;
figures below come from running them on NGED's 2024 files and on the engine as committed.*

**Terms used.** GSP = Grid Supply Point, where the distribution network meets the national transmission network (here
Bicker Fen 132 kV). BSP = Bulk Supply Point, a 132/33 kV substation. Primary = a 33/11 kV substation feeding a town's
11 kV network. Node / bus = a busbar in the network model. Branch = a line, cable or transformer between two nodes.
PSS/E = the commercial power-flow tool NGED uses. LTDS = NGED's Long Term Development Statement (the network data the
engine is built from). OLTC = on-load tap changer (a transformer's automatic voltage adjuster).

## a. The data

| | Substation (node) loading | Branch loading |
|---|---|---|
| Portal resource | `c95d6700-9728-42b3-ac99-f8762b17954c`, "Bicker Fen Substation Load", 6.79 MB CSV | `d82aeab2-25f2-4157-98ac-ae0412a8b97d`, "Bicker Fen Branch Load", 16.5 MB CSV |
| Package | `substation-loading` | `branch-loading` |
| Last modified | 2026-03-19 (file name `..._id_319_2026.csv`) | same |
| Period | 2024-01-01 00:30 to 2025-01-01 00:00, **17,568 half-hours** (2024 is a leap year), every 30 min, no gaps, no repeated or missing hour at the clock changes: a fixed clock, probably UTC, labelled at the half-hour's **end** (not confirmed: see below) | same timestamps |
| Content | 34 node columns, **MW and MVAr** each | 164 branch columns, one value each (MW by the README's reading; the header gives no unit). Column = `from bus_to bus_circuit_kind` (L line, T/G transformer, S supergrid transformer) |
| Nature | Net flow at each node: demand positive, generation negative ("conventional power flow, HV to LV"). Metered substation flows, **cleansed and imputed by NGED** ("identification and replacement of erroneous time-series values with imputed alternatives ... populate any outage periods"). No flag says which values were imputed | **Derived, not measured**: NGED's own load flow (PSS/E) run on the node series every half-hour. Sign by from → to |
| Completeness | No blank values (because NGED imputes). Suspect stretches: Wrangle (T2) holds one value for 6,489 half-hours in a row (135 days); Great Hale repeats its previous value 35% of the time, Market Overton 18.5% | No blanks |

Bus names come from NGED's "Bus Mapping" table (`6ba4ccd6-a9f8-405e-a3cf-45c79de9f16e`, 461 rows for Bicker Fen). They
use the same codes as the LTDS (`SLEA5_MAIN1`), so they map onto the engine without a hand-made table.

**A newer pair exists**: "Bicker Fen - 2025 Connected Export (ID 1124)", substation `4fdb16c8-...` and branch
`02482039-...`, last modified 2026-10-30. Its meaning is not confirmed (probably a different generation scenario on the
historic flows). Not downloaded.

**Licence.** `substation-loading` and `branch-loading` both carry **"WPD Open Data Licence"** (`wpd-open-data`). The
portal gives no URL for the terms, and I have not read them. This is not the "WPD Shared Data Licence" that covers the
Sleaford data in `forecast/`, which must not be committed. The `ltds-tabular-model` package, already bundled in this
repository, carries the same Open Data Licence, so committing it has a precedent, but that is no substitute for reading
the terms. **Until the owner decides, the files stay outside git.**

**Unread.** NGED's usage guidance PDF
(`https://dso.nationalgrid.co.uk/downloads/15104/nged-curtailment-analysis-data-usage-guidance.pdf`) refuses automated
fetches (HTTP 403). It should settle the timezone, the duplicated nodes and the 2025 file. The owner can download it in a
browser.

**Disclosure.** I asked the portal for only the first and last bytes of each 2024 file. It ignored the range request and
sent both whole files (about 23 MB). They sit in Claude's local tool-output folder and the scratch directory, outside the
repository. Nothing else was fetched beyond metadata.

## b. The match to the engine

**Branches: 158 of 164 map onto an engine line or transformer** (by the bus codes at both ends; a parallel pair maps to
both of its engine elements). The 6 that don't:
- the two wind-farm feeders into Middlemarsh 33 kV (Inner Dowsing, Lynn) and Middlemarsh's two 132/33 kV transformers:
  the engine connects the 180 MW of wind straight at Middlemarsh 132 kV;
- the two Bicker Fen supergrid transformers (400/132 kV), which the engine does not model. Their series doesn't reconcile
  with the GSP node (correlation 0.26, mean +27 MW import while the GSP exported 45 MW on average). Unexplained: excluded.

**Nodes: the 34 columns land on 25 engine buses.**
- The GSP (`BICF1_MAIN1`, `MAIN2`, `RES2`): the net flow at Bicker Fen 132 kV, at most 278.4 MW export
  (2024-08-23 12:30) and at most 48.8 MW import (2024-11-18 17:00). This matches the README's figures. It is the
  reference for the balance check, not an input.
- 22 primary 11 kV busbars, plus the 33 kV busbars at Skegness, Sleaford and Grantham.
- Five pairs of columns are identical: Cranwell, Skegness 33, Sleaford 33, Grantham 33 and the GSP. *Corrected in
  Stage 0:* at primaries the columns are **shares, to be summed**. Kirchhoff's law at the bus reproduces the sum
  exactly, for Cranwell's identical pair too. The 33 kV BSP columns are something else: see Stage 0 (i).

**Demand: 24 of the engine's 43 loads (132.7 of 149.2 MW at winter peak) sit on a bus with a series.** The 19 without
one (16.6 MW) are:
- the Grantham North 25 kV railway feeder (7.1 MW);
- Mill Farm battery's import (5.35 MW);
- the station loads of the Middlemarsh and Low Farm generator sites;
- 12 customer sites at 33 kV (solar and wind farms' own import, RAF Cranwell High G), each 0.01 to 1 MW.

**A finding: Warth Lane.** NGED's 2024 series shows live demand at `WALN5_MAIN1`, 5.8 to 18.9 MW, mean 10.7. The
engine has **no load there**: the only Warth Lane row in the LTDS demand table (18.61 MW) is marked *Removed*, and the
build drops Removed rows. Either the LTDS row is stale or the substation was re-recorded under another name. Fixing it
changes engine output, so it is the owner's call.

**Generators: none of the 14 connected generators (LTDS Table 5) has a series of its own.**
- 11 sit on a measured bus. Their output is **inside** that node's net figure and cannot be separated from demand:
  Sleaford 33 kV solar 112.8 MW, Skegness solar and wind, Grantham, Warth Lane, Ruskington, Ingoldmells, Easton, Spilsby,
  Trusthorpe, Leadenham.
- The Middlemarsh wind (180 MW) has no node series. Its output can be read off NGED's two radial feeder flows (up to
  186 MW together, mean 68 MW). Radial means one line in, nothing else on it, so the line flow is the farm's output, but
  as computed by NGED's load flow, not metered.
- Grantham North 132 kV solar (8.7 MW) has neither.

**What can be separated: only the net flow per node.** Demand and embedded generation at one node cannot be split from
these files. Splitting them needs a model (for example solar output from weather times the connected capacity), which is
out of step 1.

*(Superseded by Stage 0 (i), which uses the right reference and the right summing rule; the paragraph below is kept
for the record.)* **The balance doesn't close on the node series alone.** Take the GSP's net flow, then subtract the sum of the other
nodes (each pair counted once) and the Middlemarsh wind. The remainder averages **−83 MW** (5th to 95th percentile −129
to −23): generation that sits in no node series. It is the customer-site generators on their own 33 kV feeders, which
appear only as branch flows: Grange Lane (2 × up to 20 MW), Ermine Farm (22 MW), White Cross (22 MW), Bambers (9 MW) and
others. The engine counts these sites inside Table 5's totals at a BSP busbar (for example 112.8 MW at Sleaford 33 kV),
not on their own feeders. Feeding only the node series would therefore understate the export by about a third. How to
treat this is an owner decision (below).

Checked another way, the four 132 kV circuits into Bicker Fen track the GSP node (correlation 0.94) but differ by up to
106 MW. So something else connects at Bicker Fen 132 kV that this pair of files doesn't show.

## c. The cost

The test runs `network._solve` on the built network: the AC power flow, then the tap changers settling, as the engine
does it (pandapower 3.5.5 with numba). Demand and generation were varied over 200 half-hours spread through the year.

- **One half-hour: 55 ms mean** (median 59, 95th percentile 99), 1.75 power flows per half-hour on average (taps settling).
  One bare warm-started power flow takes 24 ms. Building the network once takes 2.2 s.
- **A year (17,568 half-hours): about 16 minutes on one core.** Solving the half-hours in time order (each warm-started
  from the last) gives 49 ms each, about 14 minutes.
- Measured on this machine. One process on one core fits "one heavy job at a time". Splitting by month across both cores
  would halve it, but isn't needed for step 1.
- Results: about 5.5 million figures for a year (loading per line and transformer, voltage per bus, per half-hour),
  about 22 MB at single precision. Kept as a file per run, not in the API's memory.

## d. The smallest seam (proposal, not implemented)

1. **Not a `CASE_SPECS` entry.** `CASE_SPECS` lists the planning conditions every plan year is studied in. A measured
   half-hour is an observation, not a planning condition, and adding an entry would change every plan year's result.
2. **One engine function** in `network.py`: `solve_snapshot(net, load_p, load_q, sgen_p, sgen_q, rating_ratio) -> dict`.
   - It sets per-load and per-generator values (pandas Series keyed by the engine's own element ids), solves with
     `_solve` (the same tap settling), restores the net and returns what `_run_case` returns: voltages, line and
     transformer loading, the GSP flow. It adds each branch's MW for the check.
   - To share the code rather than duplicate it, extract `_run_case`'s "set the inputs, solve, restore, collect" into one
     private helper. `_run_case` then applies its case scaling and `merit_order` through it, and `solve_snapshot` applies
     the measured values.
   - Proof that the refactor changes nothing: `simulate([], PlanParams())` before and after, compared field by field,
     plus the engine suite.
3. **Hours over rating** are counted from `line_pct` and `trafo_pct` against the existing `LINE_LOADING_MAX_PCT` and
   `TRAFO_LOADING_MAX_PCT`, and voltages against `VOLTAGE_BANDS`. The same thresholds, so there is no second definition of
   a breach. (`case_breaches` can't be reused as it stands: it looks up a planning-case label.)
4. **NGED-specific mapping stays behind `GridSource`.** The mapping covers bus codes to engine loads and generators,
   duplicated nodes, radial feeders and signs. One function, e.g. `NgedSource.measured_injections(path)`, yields per
   half-hour Series keyed by engine ids. The engine still makes no network calls. The CSVs come from a pipeline asset (or
   a local path) and stay out of git until the licence is settled.
5. **A driver** (`timeseries.run_year(net_factory, injections, progress)`) loops over the half-hours. It writes a results
   file and a summary per element: hours over rating, worst loading and when.
6. **Ratings per half-hour.** The engine knows a winter rating and a summer/winter ratio per line, and one rating per
   transformer. The LTDS also publishes *Intermediate Cool* and *Intermediate Warm* circuit ratings, which the engine
   doesn't read. Which rating applies in which month is a study-basis change: it needs a source and a register entry
   before code.
7. **Register entries needed first:**
   - the measured year as an input (NGED-derived, cleansed and imputed);
   - net-at-node: embedded generators on a measured bus are set to 0, because their output is inside the net figure;
   - duplicated node columns counted once;
   - how unmeasured loads and generators are treated;
   - the month-to-rating mapping;
   - reactive power from NGED's MVAr series.

## e. The check

**What it is.** NGED's branch flows are the output of NGED's own load flow (PSS/E) on the same node series. So comparing
our branch flows with theirs tests **our network model and our mapping against NGED's model**, not against the physical
grid. Measured independently, as far as the files say:
- the node series: metered net substation flows, though cleansed and imputed with no flag;
- the GSP node series, which is very likely metered at the supergrid transformers (not confirmed).

**Pass rule, proposed before any result is seen** (the tolerances are assumptions for the owner to accept or change):
1. **Closure at the GSP.** The engine's GSP flow against NGED's GSP node series: within max(2 MW, 3% of the flow) on 95%
   of half-hours. This tests the inputs and the mapping before anything else.
2. **132 kV circuits and the 132/33 kV transformers** (the backbone): each within 5% of the element's rating on 95% of
   half-hours, with the same flow direction on 95% of the half-hours where either side carries more than 1 MW.
3. **33 kV and 11 kV branches**: the same statistic for each. Pass if at least 80% of them meet it, and list every one
   that doesn't with its typical offset. Expect misses here: the engine runs the 33 kV mesh closed because the LTDS
   publishes no normally-open points, while NGED's model runs it as NGED does. A persistent offset is a topology or
   mapping finding, not noise.
4. Parallel pairs are compared on their sum. The supergrid transformers and the six unmapped branches are excluded and
   named. Signs are aligned to NGED's from → to.
5. **If rule 1 or 2 fails, no hours-over-rating figure is shown as a finding** until the cause is explained.

## f. What the owner would see

**The output:**
- A table, one row per line and transformer: hours above its rating in 2024, the worst loading and when (date and
  half-hour), and the months it happens in.
- The map coloured by hours over rating.
- A month × hour-of-day grid of overload hours for the worst elements.
- Hours outside the statutory voltage band per busbar.
- The GSP's export through the year against its 527 MW limit.
- The check report from (e).

The likely headline is few or no overloads in 2024: today's worst element reaches 93% only in the planning extreme. That
would itself be a result: it shows how much margin the planning cases build in.

**What it will not tell them:**
- **The future.** No demand growth, no new connections: 2024 only, one year's weather.
- **Whether NGED curtailed anyone.** Any curtailment is already inside the flows.
- **Outages.** No N-1, the loss of one circuit or transformer; the network runs intact.
- **Peaks inside a half-hour.** Only half-hourly averages.
- **Real-time ratings.** Static seasonal ratings are used, not ratings that follow the weather.
- **The low-voltage network** below 11 kV.
- **Demand versus generation at each node.** Only the net figure.
- **Which half-hours NGED imputed.** Unflagged, so a long flat stretch like Wrangle's looks like data.

## Decisions for the owner

1. **Licence.** Read the WPD Open Data Licence terms. Until then, keep the CSVs out of git (a gitignored local folder,
   fetched by a pipeline asset).
2. **Which file.** The 2024 historic file (ID 319) as the measured year, or the newer "2025 Connected Export (ID 1124)"
   once its meaning is known.
3. **Unmeasured injections** (about 83 MW on average at the GSP):
   - (A) take the radial customer-feeder and Middlemarsh flows from NGED's derived branch file, and say so;
   - (B) leave them out and accept that closure (check rule 1) will fail;
   - (C) model them, which is beyond step 1.

   Recommended: **A** for the generators. For the 16.6 MW of loads with no series (railway, battery, station loads):
   hold them at 0, and say so.
4. **Ratings by month.** Which months take winter, intermediate or summer ratings, with a source. Also whether the engine
   should read the LTDS intermediate ratings.
5. **Warth Lane.** Add its demand back (an engine output change, with a register note) or leave it and record it.
6. **README wording.** "Observed flows" would become: "NGED-derived: metered node flows, cleansed and imputed; branch
   flows from NGED's load flow".
7. **Pass-rule tolerances** in (e): accept or change before anything is run.
8. **Where step 1 lives.** An engine function plus a pipeline asset and a report in `docs/reports/`, or straight into the
   API and planner. Recommended: the report first.

---

## Stage 0: the open points, settled before any result exists

*Added later on 12 November 2026, after the owner's decisions (the 2024 file, option A, unmeasured loads at 0, Warth
Lane added back, NGED's four seasons). Read-only: scratch scripts, nothing in the engine changed.*

### (i) The 106 MW at Bicker Fen 132 kV, and the closure reference

**What the files show.**
- **Primary nodes are exactly NGED's load-flow inputs.** At every primary, the injection worked out from NGED's branch
  flows equals the node series to 0.02 MW at the 95th percentile. The method is Kirchhoff's current law: at a bus, what
  flows in equals what flows out plus what the bus consumes. Where a primary has two columns, it equals their **sum**:
  Leadenham, Horncastle, Cranwell and Billingborough. So the two columns are shares, not copies, and my first draft was
  wrong.
- **The 33 kV BSP columns are not local injections.** At Grantham they equal the flow through the BSP's 132/33 kV
  transformers, i.e. the whole group below, primaries included (to 3.4 MW at the 95th percentile). At Sleaford and
  Skegness they don't match even NGED's own transformer flows (95th percentile 78 MW and 25 MW), presumably because of
  the 33 kV mesh. **They are not used as inputs.** Summing them with the primaries double-counted, which is what made the
  first draft's balance fail.
- **The GSP node series** (`BICF1_MAIN1`, `MAIN2`, `RES2`) **does not reconcile with anything in the files:**
  - it shows more export than the four 132 kV circuits into Bicker Fen carry on 95% of half-hours: median 52 MW,
    range −106 to +72;
  - the gap is shaped like demand (37 to 41 MW at night, 66 MW at 18:00 to 19:00 UTC) and runs through every month;
  - the two supergrid transformer series don't explain it (correlation 0.34);
  - no regression on the circuit flows, the transformer series, the wind or the node sums fits better than 11 MW
    standard deviation.

  The LTDS lists nothing else at Bicker Fen 132 kV: four circuits, the busbars, and a bay `BICF1_1005` that is marked
  Removed. What NGED's GSP series represents can't be settled from these files: most likely a different metering point or
  definition. **It is not used as the closure reference.** It is reported beside the result, not judged.

**Closure reference (pass rule 1): the sum of the four 132 kV circuits into Bicker Fen in NGED's branch file**
(Boston ×2, Sleaford ×2: `432706_489916`, `432702_489912`, `44033_489910`, `44030_489906`). The engine's infeed at Bicker
Fen equals exactly this sum by construction, since these four lines are the only branches at its slack bus. Honest
scope: every injection except the primary series is itself worked out from the same branch file, so this closure tests
two things: that the mapping is complete, and that the two models' losses agree. It does not test the measurements.

### (ii) Inputs and the comparison set

**The engine's inputs per half-hour:**
- **The 22 primary 11 kV series**, as NGED meters them, cleansed and imputed: 26 columns, pairs summed.
  - Two mapping corrections for Stage 3: Trusthorpe's series goes to the buses NGED's transformers land on (engine
    buses 91 and 92, not 90), and Woodhall Spa's to bus 138.
  - Embedded generators on those buses are set to 0: their output is inside the net figure.
- **Every other injection, worked out from NGED's branch flows by Kirchhoff's law at the engine bus.** These are labelled
  derived, not metered:
  - the 14 customer-site feeders;
  - Middlemarsh (both 132/33 kV transformers, the wind entering at 132 kV: up to 180 MW);
  - the local injection at each BSP 33 kV busbar (the Sleaford, Skegness and Grantham solar and wind sit there).
- **Held at 0, as decided:** the Grantham North 25 kV railway feeder (NGED shows 0 to 7.4 MW, mean 0.1).
- **Not a decision, flagged:** under option A the Mill Farm battery's feeder flow carries its export and its import
  together (−6.7 to +7.1 MW). I propose taking it whole, like the other feeders, rather than zeroing the import, which
  would contradict the same feeder flow. The guide and owner to confirm.

**Excluded from the comparison (inputs, or different by construction): 26 of 164 columns.**
- The 14 customer-site feeders: their flow is the input.
- Middlemarsh's two transformers and two wind-farm feeders (unmapped, and the input).
- The two Middlemarsh 132 kV lines (`464902_439105`, `464904_439102`): radial, so they carry only the input wind.
- The two supergrid transformers: unexplained, see (i).
- The railway's two transformers and its two 132 kV lines (`475600_443409`, `475601_443411`, `429607_443408`,
  `443410_429609`): the input is held at 0, so they differ by construction.

**Compared: 138 columns, in three sets.**
- **Rule 2, the backbone (18):**
  - 12 circuits at 132 kV: Bicker Fen–Boston ×2, Bicker Fen–Sleaford ×2, Sleaford tee–Sleaford ×2, Grantham–Sleaford
    tee ×2, Boston–Low Farm tee, Low Farm tee–Skegness, Skegness–Boston, Grantham 132 kV internal;
  - the 6 BSP 132/33 kV transformers at Sleaford, Skegness and Grantham.
- **Rule 3, the meshed branches below 132 kV (100):** their flow depends on impedances and running arrangement, so this
  is the model test.
- **Radial branches below 132 kV (20):** a radial branch's flow is fixed by the injections beyond it whatever the
  impedances, so it tests the mapping only. **All must agree to within 0.5 MW + 2%** (losses). Any miss is a mapping error
  to fix before any result counts.

Caveat: injections at the BSP 33 kV busbars are worked out from their incident branches, so those branches share one
constraint (their sum). How the flow splits between them is still the model's.

### (iii) NGED's four seasons, and transformers

**What I could verify.** NGED's PDFs refuse automated download (HTTP 403). Chrome opens the Network Development Plan
report but its PDF viewer gives no text. What follows comes from search-result excerpts, not the documents themselves.
- **The source of the seasons.** NGED's DFES 2024 customer behaviour report: the definition of seasons is taken from
  Engineering Recommendation P27/2 (the Energy Networks Association's standard for overhead-line ratings, 2019 revision).
- **Two of the four seasons by month.** WPD/NGED Standard Technique SD8A (NGED's overhead-line ratings standard),
  reproducing P27's 2019 table:
  - Intermediate Cool: March, April, November;
  - Intermediate Warm: May, September, October.
- **The other two, by elimination only (not seen):** Winter December to February, Summer June to August. This agrees with
  the guide's summary.
- **Transformers.** NGED's East Midlands Network Development Report (excerpt): NGED policy records transformer ratings
  for two seasons only, summer and winter; its intermediate-season analysis uses the summer rating. The LTDS gives one
  "Nominal Rating" per transformer, not seasonal, so **the engine holds every transformer at its LTDS nominal rating all
  year**, as it does today. NGED's summer-for-intermediate rule can't be applied without a seasonal figure.

**Register status:** the circuit months go in as "NGED (SD8A / P27/2)", wording unverified, until the owner pastes the
table from the NDP report.

### (iv) Warth Lane

**The row.** LTDS Table 3: Warth Lane, Skegness BSP, node `WALN5_MAIN1`, maximum demand 18.61 MW, power factor 0.96,
minimum-demand factor 51.17%, firm capacity 38 MVA, status *Removed*. **Proposed figure: the row's own**, which is the
latest NGED published.

**Why it is marked Removed (circumstantial, not confirmed by NGED).** In the same LTDS edition, Warth Lane's 11 kV board
was rebuilt:
- transformer `WALN5_3T0` Removed, `WALN5_13T0` New;
- new busbar sections `WALN5_MAIN2` and `MAIN3` with their breakers;
- transformer 2T0 moved from MAIN1 to MAIN2.

The demand row was marked Removed and no New row was issued. Everything else says the site is live:
- the same edition keeps its 5 MW of solar as Connected;
- NGED's 2024 flows show 5.8 to 18.9 MW of demand there;
- DFES 2025 projects it.

The likeliest reading is an omission during the rebuild. **Proposal:** a named exception in `nged.py` (an LTDS demand
row Removed in error, keyed by node, with this reason), recorded in the register. Not a general rule.

**Growth (needs an owner yes).** The DFES pin (`pin_nged_published`) skips Removed rows, so Warth Lane's supply area was
never bundled. It exists on the portal as "WARTH LANE SKEGNESS 33 11kV S STN": Holistic Transition 19.9 MW in 2025,
24.7 MW in 2030, 37.7 MW in 2035. Without it, the engine falls back to the LTDS five-year forecast, 18.6 to 81.6 MW
(×4.4), which breaks the plan by 2030. Adding Warth Lane therefore also needs a **re-pin of `dfes.json`**: a fetch that
changes bundled data.

**Before and after** (scratch build from a modified copy of the tables plus the 76 DFES rows; Standard pathway):

| | As built | Warth Lane added, DFES growth | (LTDS-forecast fallback) |
|---|---|---|---|
| Winter-peak demand today | 149.2 MW over 43 loads | 149.2 MW over 44 (Warth Lane 13.86 MW; the 12 other Skegness-group loads (7 primaries, 5 customer sites) ×0.73, every other load unchanged; see the correction below) | same |
| Summer-minimum export to transmission | 301.3 MW | 292.2 MW (−9.1) | 292.2 |
| Worst line / transformer today | 92.7% / 79.5% | 92.9% / 79.2% | same |
| Warth Lane's three transformers today | 17 / 15 / 16% | 45 / 39 / 37% | same |
| Lowest voltage today | 0.967 pu | 0.977 pu | same |
| 2030 | 0 breaches; worst transformer 97.0% | 0 breaches; 96.4% | 15 breaches; line 69 at 135%, a transformer at 221% |
| 2035 | 31 breaches; worst line 103.7%, transformer 144.4%, Vmin 0.888 | 15 breaches; 92.8%, 142.2%, 0.917 | 56 breaches |

**Where the 16 breaches go (mechanism; corrects the first explanation, which blamed the GSP-wide anchor).**

*The rule.* The build scales each BSP's primaries so that their sum is the BSP's own published maximum (the coincidence
at each BSP, `nged._bsp_membership`). Then it scales the BSP totals to NESO's GSP peak.

*What adding Warth Lane does.*
- Warth Lane belongs to Skegness BSP. Adding its 18.61 MW to Skegness's member sum lowers Skegness's coincidence, so
  **every other Skegness-group load (7 primaries and 5 customer sites) is multiplied by 0.73**, today and in every year.
- The Sleaford and Grantham groups are unchanged (×1.00), and so is the GSP factor.
- Total winter-peak demand stays 149.2 MW today. In 2035 it is 260.3 MW against 259.1: Warth Lane's own DFES ratio
  (×1.90) is close to its neighbours', so the ratios are not the cause.
- The rescaled loads in 2035:

  | Load | 2035 before | 2035 after |
  |---|---|---|
  | Horncastle (T1) | 18.9 MW | 13.8 MW |
  | Trusthorpe | 17.8 MW | 13.0 MW |
  | Spilsby | 15.3 MW | 11.1 MW |
  | Alford | 13.7 MW | 10.0 MW |
  | Ingoldmells | 11.5 MW | 8.4 MW |
  | Chapel St Leonards | 10.5 MW | 7.6 MW |
  | Wrangle (T2) | 3.8 MW | 2.8 MW |

  Warth Lane itself goes to 26.3 MW (13.86 MW × DFES ×1.90).

*The 16 cleared breaches.* All are in that group, all at winter peak:
- **Transformers (7):** Alford's two 33/11 kV units (141% and 126%), Spilsby's two (127% and 130%), Horncastle's two
  (112%), Chapel St Leonards (106%);
- **Lines (2):** Horncastle–Spilsby 33 kV (101%) and Tattershall–Woodhall Spa 33 kV (104%);
- **Voltages (7):** busbars on the Trusthorpe, Bambers, Woodhall Spa and Horncastle 33 kV feeders (0.927 to 0.933 pu).

*The 15 that remain.* No new ones appear. The 15 that remain move little:
- the Skegness 132/33 kV transformers rise from 114% to 116%, because Warth Lane's load is now carried through them;
- the Sleaford ones fall from 116% to 112%;
- the Horncastle 33 kV voltage rises from 0.888 to 0.917 pu.

*Corroboration.* As built, Skegness's coincidence is **1.02** (README register). A coincidence above 1 means the BSP's
own maximum exceeds the sum of its primaries' maxima, which can only happen if a member is missing. With Warth Lane
included it falls to about 0.78, in line with Grantham (0.78) and Sleaford (0.89).

*So, as built,* the engine **overstates the seven other Skegness primaries by about 37%** (1/0.73), today and in every plan
year. That is the main effect of the Warth Lane decision: it corrects them.

### Decisions taken since Stage 0

**Decided by the owner** (relayed by the guide, about 20:40):
- the 2024 file (ID 319);
- option A for unmeasured generation;
- the railway feeder at 0;
- the README rewording;
- step 1 as an engine function, a fetched data path and a report;
- the pass-rule tolerances.

**Decided by the guide session overnight, 12–13 Nov 2026, for the owner to confirm** (the owner delegated decisions
while away):
- **a. DFES re-pin, Warth Lane only.** Same resource. A diff must prove nothing else in `dfes.json` changed; if anything
  differs from the pinned file, stop and keep the old pin.
- **b. Mill Farm battery:** its feeder flow taken whole.
- **c. Seasons:** NGED's four, as in (iii), marked "source wording unverified". Transformers keep their single LTDS
  rating. Every loading is also recounted against the summer rating all year, as the conservative bound.
- **The report's shape**, now that the step's limits are clear:
  - it leads with the model comparison: every branch outside tolerance, with its offset and the likely cause, fixed
    later, not in this step;
  - utilisation: peak loading and when, hours at or above 80, 90 and 100%, duration curves for the ten most loaded
    elements, voltage hours outside band;
  - what an intact-network view leaves out (security of supply after losing one circuit or transformer, an owner
    decision not to be re-added here);
  - the 2024 planning cases beside the measured year.

The pass rule is unchanged.

### (v) Imputation screen

**Rule:** a run of **12 or more consecutive identical half-hourly values (6 hours)** at a node flags those half-hours.
Zero runs are flagged too, because an outage can't be told from clipping.

**On the 2024 file:**
- **Wrangle (T2):** 0.00 from 2024-08-01 11:00 to the end of the year, 6,489 half-hours. It looks like the transformer
  out of service or a data stop.
- **Great Hale:** 5,517 half-hours in zero runs of up to 17 hours. 31% of its values are exactly 0, which looks like
  export clipped to zero.
- **Smaller runs:** Horncastle (T2) 95 half-hours, Leadenham 30, Billingborough 22.
- **A shared gap:** a 3-hour run starting 2024-09-21 23:00 hits four nodes at once, which looks like a gap filled with a
  held value.
- **In total,** 12,890 half-hours carry a flag at some node, but only 147 if Wrangle and Great Hale are set aside.

**Reporting:**
- **(a) Hours over rating on all half-hours.**
- **(b) Excluding the half-hours flagged at any node in the element's own BSP group.** 132 kV elements and the BSP
  transformers count every node. Because Wrangle (Skegness group) and Great Hale (Sleaford group) dominate the flags, (b)
  rests on far fewer half-hours in those groups, and the report says how many.

### The pass rule, final form (fixed before any result)

1. **Closure:** the engine's infeed at Bicker Fen against the sum of the four 132 kV circuits into Bicker Fen in NGED's
   file, within max(2 MW, 3% of the flow) on 95% of half-hours. NGED's GSP node series is shown beside it, not judged.
2. **Backbone (the 18 in (ii)):** each within 5% of the element's rating on 95% of half-hours, with the same flow
   direction on 95% of the half-hours where either side carries more than 1 MW. Parallel pairs are compared on their sum;
   signs follow NGED's from → to.
3. **Meshed branches below 132 kV (the 100 in (ii)):** the same statistic for each. Pass if at least 80% meet it; every
   one that doesn't is listed with its typical offset, as a topology or mapping finding.
4. **Radial branches below 132 kV (the 20 in (ii)):** all within 0.5 MW + 2%. Any miss is a mapping error to fix before
   rules 1 to 3 are read.
5. **Excluded and named:** the 26 columns in (ii).
6. **If rule 1, 2 or 4 fails,** no hours-over-rating figure is presented as a finding until the cause is explained.

---

## Added after the one-week dry run, before the year's results

*Decided by the guide session overnight, 12–13 Nov 2026, for the owner to confirm. None of this changes a pass rule.*

**The dry run** (1–7 July 2024):
- all 336 half-hours converge;
- rule 4 passes;
- rule 1 holds on only 75% of half-hours, against the 95% required (median gap 1.5 MW, 95th percentile 3.2 MW).

The guide chose option A: run the year under the rule as written and report rule 1's outcome as it falls.

**Added to the report:**
1. **The closure gap broken down, per half-hour, for the year and by season.** Engine infeed minus NGED's four circuits =
   (engine losses − NGED's implied losses) + unplaced balance + residual.
   - The test: is the unplaced balance at each 132 kV tee correlated with the square of the through-flow on its
     incoming branches? That would mean NGED's single value per branch puts each branch's losses at one end.
   - Which end NGED's value refers to, if that can be established.
   - The cause counts as explained if the residual is under 1 MW at the 95th percentile.
2. **Closure in context.** The gap as a share of the half-hour's gross flow (sum of absolute injections) and of the
   smallest backbone circuit rating; what it means for a loading figure, in percent of rating.
3. **Validation per element.** Every line and transformer is labelled:
   - **"flow agrees with NGED's model":** its branch group meets the rule 2 or rule 3 statistic;
   - **"flow differs":** with its typical offset in MW and percent of rating;
   - **"not compared":** an input, or unmapped.

   Only the first label's utilisation figures are findings; the others show the engine's figure with the offset beside
   it.

Also kept in the report: rule 4's output, and the unplaced totals per bus for the year.

## Added after the year's results were seen

*Decided by the guide session overnight, 12–13 Nov 2026, for the owner to confirm. No pass rule changed.*

**The fault.** NGED's published MVAr is physically impossible at two primaries:
- **Spilsby:** up to 54 MVAr through 2 × 6 MVA transformers, with stretches in January, February, July and from
  November to the year end;
- **Billingborough:** 34 MVAr in one half-hour (27 February 18:00).

Every overload and voltage breach in the run on the published data traces to it, and so do the 22 half-hours that
did not solve. Outside the 888 affected half-hours, no element exceeds its rating.

**Three runs, each a full year in time order:**
- **A, "as published":** the first run, unchanged. Its verdict is the verdict on the pass rule as written.
- **B, "screened":** the reactive-power screen (README register). Flagged half-hours have their reactive power
  substituted by P × tan(the LTDS power-factor angle); active power is untouched. B is the basis for utilisation, and
  the pass rule is shown on it too, as "after the reactive-power screen".
- **C, "unity power factor":** diagnostics only. Do the BSP transformers' offsets and the unsolved half-hours come from
  reactive power, and how much of each element's loading is reactive?

**The 1.5× threshold separates cleanly:**
- Spilsby is at 3.5× capacity at its 99th percentile;
- Billingborough's single half-hour reaches 2.55×;
- every other node stays at or below 0.88× all year.
