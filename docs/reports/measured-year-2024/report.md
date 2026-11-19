# The year 2024 at Bicker Fen: NGED's half-hourly flows through the engine

*Step 1 of the time-series work, 12–13 November 2026. Supported by NGED Open Data.*

**A second year:** 2025 through the same code and rules is in `second-year-2025.md` (Work 12): the offsets recur with the
same sign; Spilsby's reactive power and Manor Farm's zero were faults of 2024's data.

**Status: complete as a draft for the owner, 13 November 2026.** Result files: run A `93f28f08…db6ca1f`, run B
`e2e2032f…c65d817ba`, run C `2a8c96f5…ca7bbdf` (full hashes in section 2). The guide session decided several points
overnight under the owner's delegation; each is marked *(guide, overnight)* here and is listed in the specification for
the owner to confirm. The method and the pass rule are in
`docs/reports/timeseries-step1-spec-2026-11-12.md`; every figure below comes from `analyse.py` in this folder, run on the
saved result files.

**Terms.**
- **GSP**, Grid Supply Point: where this network meets the national transmission system, Bicker Fen 132 kV.
- **BSP**, Bulk Supply Point: a 132/33 kV substation (Sleaford, Skegness, Grantham).
- **Primary**: a 33/11 kV substation feeding a town.
- **Loading**: current as a percentage of the element's rating, its safe continuous limit.
- **Firm capacity**: what a substation can carry after losing its largest transformer.
- **MVAr**: reactive power, which loads wires without doing work. **MVA**: the total of active and reactive power, which
  is what a transformer's rating limits.

## 1. Summary

1. **The check of our model against NGED's did not pass as written.** Three of its four rules failed:
   - **Closure (rule 1).** The engine's infeed agrees with NGED's four 132 kV circuits within the tolerance on 59.5% of
     half-hours, against 95% required. The typical gap is 1.9 MW and 3.6 MW at the 95th percentile, about 4 points of
     loading on the smallest backbone circuit.
   - **Backbone (rule 2).** All 12 of the 132 kV circuits agree, but all 6 of the 132/33 kV transformers carry a
     steady 1.3 to 1.9 MW offset.
   - **Meshed branches (rule 3).** 70% of the meshed 33/11 kV branch groups agree, against 80% required.
   - **Radial branches (rule 4).** Passes: every radial branch matches within 0.09 MW.

   The failures concentrate on the BSP transformers and on the two 33 kV paths that tie Sleaford to Skegness and to
   Grantham (section 3). Experiment D found nothing in NGED's files to show those ties run open. Work 1 (3.4) then
   ruled out the impedance conversion, the injections, split boards and taps, fixed one definition error (transformer
   vk, at most 0.53%), and found Sleaford's published transformer impedance to be the one lever: it closes most of the
   Grantham side, while about 3 MW on the Skegness side stays unexplained. Because rules 1 and 2 failed, the utilisation below is shown with a validation label per element and
   the stated uncertainty, not as validated findings.
2. **NGED's published reactive power is wrong at Spilsby**, up to 54 MVAr through two 6 MVA transformers, and once at
   Billingborough. Taken as published, it produces every overload and voltage breach of the year and all 22 half-hours
   that would not solve. With it screened, **no line or transformer exceeds its rating at any half-hour of 2024, and no
   busbar leaves its statutory voltage band.**
3. **Two primaries ran above their firm capacity.** They stayed within their intact rating but would not have been
   after losing one transformer:
   - **New Beacon Road:** 14.3 MVA against a 14 MVA firm capacity, on 15 January 18:00, for 5 hours in the year;
   - **Alford:** 6.5 MVA against 6 MVA, on 20 November 17:00, for 9 hours.
4. **The planning cases understate local peaks.** The engine's 2024 planning cases load most elements *less* than the
   2024 run did (median ratio 1.23, 2024 peak to planning case). The winter-peak case gives each substation its share at the
   moment the whole GSP peaks, but each substation reaches its own peak at its own time. The large solar farms also sit
   on their own feeders in reality, not at the Sleaford busbar where the model put them (since fixed, Work 2: 4.2).
5. **Two more model findings:**
   - **Warth Lane's demand was missing from the model.** Its LTDS row is marked Removed. It is now restored; the coincidence
     of NGED's metered primary series for the Skegness group, 0.78, corroborates it.
   - **NGED's Grid Supply Point series is unexplained:** it shows a median 52 MW more export than its own four circuits.

## 2. What was run

**Inputs.** NGED's 2024 historic year (file ID 319): 17,568 half-hours, labelled by their end, on a fixed clock.
- Every half-hour sets 48 injections: 21 primaries from NGED's metered series, and 27 worked out from NGED's branch
  flows by Kirchhoff's law (the solar and wind farms on their own feeders, Middlemarsh's offshore wind, each BSP busbar's
  local generation).
- The railway feeder is held at 0.

**Solving.** The engine solves each half-hour with the same AC power flow and tap-changer settling as the plan years,
in time order (tap positions carry over), with Warth Lane restored. Lines are rated by NGED's season for the month;
transformers have one rating all year. The register in the root README lists every input and assumption.

**Three runs** (git-ignored, under `apps/pipeline/warehouse/nged-flows/`):

| Run | Reactive power | Solved | sha256 |
|---|---|---|---|
| A, as published | NGED's MVAr as published | 17,546 of 17,568 | `93f28f08af3c4e7160838f1dbc21f2fe9289f3d14fa88307fd7078defdb6ca1f` |
| **B, screened** (the basis for utilisation) | Substituted where implausible: 841 node-half-hours, see 4.1 | 17,568 | `e2e2032ff380dd1e745ed41bfbdf64e76bf14f1c8b71f4362714481c65d817ba` |
| C, unity power factor (diagnostic only) | 0 everywhere | 17,568 | `2a8c96f5a6999b9110bb13e7e33371c05f19f4b600158089b55ab34c6ca7bbdf` |

Each run takes about 16 minutes on one core.

**Code state of each run.**
- **Run B** is on the current engine: Warth Lane restored, four seasons, and transformer vk = |Z| (3.4).
- **Runs A and C** were made before the vk fix and were not rerun. The fix moves no verdict and at most 2.6 points of
  any loading (3.4).
- **Run B before the fix** is kept as `measured-year-2024-screened-pre-vkfix.npz` (sha256
  `33f3cc1e1973409cc4b0a62cb83a1cb24743c507953a371ab2ae3a759455ff50`), with its figures in `screened-pre-vkfix/`.

**What the comparison compares.** Nearly every injection is taken from NGED's own solution, so the closure tests
mapping completeness and losses, and the branch comparison tests our impedances and topology against NGED's model.
**Neither tests the physical grid.**

## 3. The check: our network model against NGED's

**The pass rule as written** (fixed before any result), run A. Run B is shown beside it as "after the reactive-power
screen".

| Rule | What it asks | Run A | Run B |
|---|---|---|---|
| 1. Closure | Engine infeed within max(2 MW, 3%) of NGED's four circuits into Bicker Fen, on 95% of half-hours | **Fails**: 59.5% | Fails: 59.5% |
| 2. Backbone, 18 element groups | Each within 5% of rating on 95% of half-hours, same direction on 95% | **Fails**: 12 of 18 | Fails: 12 of 18 |
| 3. Meshed below 132 kV, 88 element groups | The same statistic on at least 80% of groups | **Fails**: 62 of 88 (70%) | Fails: 62 of 88 |
| 4. Radial below 132 kV, 20 element groups | Every solved half-hour within 0.5 MW + 2% | **Passes**: 20 of 20 (worst 95th percentile 0.09 MW) | Passes |

Reading the table:
- The 14 customer feeders used as inputs reproduce NGED's flow within 0.5 MW + 2% on every solved half-hour, as they
  should. Rule 4 is what caught two mapping bugs during the dry run: Gorse Lane dropped, and Middlemarsh cancelling.
- The specification's 100 meshed columns make 88 element groups once parallel pairs are merged.

### 3.1 Closure (rule 1)

**The gap** (run B): engine infeed minus NGED's four circuits has a median of +0.4 MW. Its absolute value has a median
of 1.86 MW, a 95th percentile of 3.57 MW and a maximum of 9.7 MW.

By season (absolute gap, median / 95th percentile / share within tolerance):

| Season | Median | 95th percentile | Within tolerance |
|---|---|---|---|
| Winter | 2.18 MW | 3.57 MW | 51% |
| Intermediate cool | 2.10 MW | 3.64 MW | 55% |
| Intermediate warm | 1.60 MW | 3.42 MW | 67% |
| Summer | 1.64 MW | 3.75 MW | 65% |

**In context.**
- The gap is 0.96% of the half-hour's gross injections at the median and 2.6% at the 95th percentile.
- Its 95th percentile is 4.0% of the smallest backbone circuit's summer rating (89 MVA). A backbone loading figure
  carries about ±4 points of this uncertainty.
- For information only (not part of the rule), from the guide's recount: the gap is within a 3 MW floor on 84% of
  half-hours and within 4 MW on 97%.

**What the gap is made of.**
- *The accounting.* Gap = engine losses − NGED's unplaced balance − the railway held at 0 − (metered vs balance
  differences). This is an exact identity: the residual is 6×10⁻¹⁵ MW, so it cannot score the cause.
  - Engine losses: median 1.34 MW.
  - Unplaced balance: NGED's own Kirchhoff imbalance at nodes where nothing is connected, median 0.68 MW, 95th
    percentile 6.6 MW.
  - Railway: mean 0.10 MW.
- *The physical reading.* At the main 132 kV tees (Boston 603 and 503, Skegness 132 kV 103), the unplaced balance moves
  with the square of the through-flow, with correlation 0.91 to 0.94. That is how line losses behave: NGED's single value
  per branch leaves each branch's loss at one end.
- *What stays unexplained.* The size: the fitted coefficient is 4 to 6 times the engine's resistive loss on active
  flow, and about 70 times at the Sleaford tees (correlation 0.69). Which end NGED's value refers to cannot be
  established from the files: at a pure tee the in- and out-flows are the same series.

**Verdict on rule 1:** the cause is partly characterised (two loss accountings differ), not explained.

**NGED's Grid Supply Point node series** (shown, not judged): on 95% of half-hours it shows more export than NGED's own
four circuits, by a median of 52 MW, with a demand-shaped profile. Nothing in the files accounts for it.

### 3.2 The BSP transformers (rule 2) and the 33 kV mesh (rule 3)

**The six transformers that fail rule 2.** Each pair carries a steady offset of the same sign on both units, on the
132 → 33 kV direction:

| BSP | Pair offset, median (95th percentile range) |
|---|---|
| Sleaford | −3.8 MW (−7.0 to +7.3) |
| Skegness | +2.6 MW (+0.3 to +5.8) |
| Grantham | +2.7 MW (−6.5 to +5.3) |

What the offsets are not, and where the misses lie:
- **Not reactive power.** The unity-power-factor run gives the same offsets (−4.0, +2.6, +2.9).
- **Not the railway.** Correlation with it is −0.15 to +0.13.
- **The same place as the rule-3 misses.** The meshed branches that fail rule 3 lie on the two 33 kV paths that tie
  Sleaford to its neighbours:

| Path | Engine lines | Typical offset |
|---|---|---|
| Sleaford – Tattershall – Woodhall Spa – Horncastle – Spilsby – Skegness | 110, 114, 119, 121, 126, 96, 95, 98, 63, 67, 76 | 1.4–2.5 MW, 8–9% of rating; direction agrees on only 67–76% of half-hours on the Woodhall–Horncastle section |
| Sleaford – North Rauceby – Cranwell – Leadenham – Mill Farm – Grantham | 111, 100, 89, 40, 36 | 1.6–2.1 MW, up to 11% of rating; direction agrees on 69–84% |

  The engine carries about 2 MW more on each tie than NGED's model does, about 4 MW in all. That takes 4 MW off
  Sleaford's transformers and puts it on Skegness's and Grantham's, which matches the transformer offsets above. Why
  the two models route those few MW differently is not established: experiment D (3.3) found no sign in NGED's files
  that the ties run open. The candidates left are differences in impedance, in transformer taps, or in the derived
  injections at the BSP busbars.

### 3.3 Experiment D: are the ties run open in NGED's model?

*Decided by the guide overnight as an experiment, not a change to the engine's network.*

**The test.** A normally-open point is a branch that carries nothing. If NGED's model ran a Sleaford tie open, its
branch file would show a branch on that tie with no flow all year, or would leave the branch out.

**Step 1, read-only.**
- *Rule:* an NGED branch whose absolute flow is below 0.05 MW on at least 99% of the year's half-hours.
- *Result:* exactly one branch qualifies, the Manor Farm Irby spur (engine line 68). It is radial and on neither tie.
  Loosened to 90% of half-hours, the rule adds only the railway's branches (held at 0 by decision) and one radial line
  at RAF Cranwell.
- *Branches missing from NGED's file:* the 14 engine branches NGED's file does not carry are all short links inside a
  substation, a cable joint or a busbar section. None lies on either tie.
- *Every branch of both ties is in NGED's file and carries flow all year:* lines 110, 114, 119, 121, 126, 96, 95, 98,
  63, 67, 76 towards Skegness, and 111, 100, 89, 40, 36 towards Grantham.

**Verdict.** NGED's files do not support the reading that its model runs the ties open. As the experiment set out,
step 2 (a run with those lines out of service) was not made. The tie and BSP-transformer differences stay unexplained.

**Remaining candidates for the tie and BSP-transformer mismatch**, in the order they can be tested cheaply, as they
stood after experiment D (Work 1 tested them: 3.4):
1. *The derived BSP-busbar injections:* the only inputs on the ties' end buses that come from a balance, not a series.
   Settled by comparing each BSP busbar's derived injection with NGED's 33 kV BSP columns minus the primaries below it,
   and by checking that the derived values carry no loss term from the incident branches.
2. *The 132/33 kV transformer impedances and their per-unit conversion* from the LTDS's 100 MVA base. Settled by
   recomputing each unit's impedance from the LTDS row by hand and by running one week with the impedances scaled: if
   the offsets move in proportion, the impedance is the lever.
3. *The 132 kV circuit impedances between the BSPs,* which set how 132 kV flow divides and so the angles at each BSP.
   Settled by comparing the 132 kV flows' split between parallel paths with NGED's, half-hour by half-hour.
4. *Split 33 kV busbars at the BSPs in NGED's model* (bus sections we merge). Settled by NGED's bus mapping: separate
   33 kV section nodes at a BSP, each with its own branches, would mean NGED runs the bars split where we merge them.
5. *Tap positions.* Settled by a week with the BSP taps fixed at neutral instead of regulated: a tap-driven circulating
   flow between BSPs would change with it.


### 3.4 Work 1: the candidates tested

*Decided by the guide session overnight, for the owner to confirm. One test week, 15–21 January 2024 (winter, when the
offsets are largest), screened inputs, scratch runs only. Over that week the BSP transformer offsets are Sleaford
−5.6 MW, Skegness +5.0 MW and Grantham +3.0 MW. The Skegness tie carries about 3.5 MW more than in NGED's model, the
Grantham tie about 2 MW more.*

**What was established:**
- **The impedances are converted correctly.** All 44 transformers and all 128 lines were recomputed by hand and match
  the LTDS under the engine's method.
  - Transformers: %Z on 100 MVA × rating ÷ 100. Sleaford GT1: X1 24.92% × 45 ÷ 100 = 11.214%, and R1 0.42% × 45 ÷ 100
    = 0.189%. The engine holds vkr 0.189% on 45 MVA.
  - Lines: ohms = %R or %X ÷ 100 × kV² ÷ 100. Bicker Fen–Boston: R1 0.8105% and X1 3.4614% with a base impedance of
    174.24 Ω give R 1.4122 Ω and X 6.0311 Ω, as the engine holds. Every line matches to 2 × 10⁻¹⁶.
- **The injections along the ties equal NGED's.** Each BSP busbar's injection is NGED's own balance there, the metered
  primaries match NGED's balance to 0.02 MW, and the leaves match exactly. With identical injections, only the network
  can route flow differently. Injecting NGED's unplaced 33 kV balances as well barely moves the offsets (−5.9, +4.5,
  +2.8 MW).
- **NGED's 33 kV boards run joined, as ours do.** In NGED's own flows each BSP's two transformers share to within
  0.06 MW (Sleaford), 0.48 MW (Skegness) and 0.23 MW (Grantham) at every half-hour, out of 7–16 MW each. A split board
  would put different section loads on them.
- **Taps are not the cause.** The two units of every pair are always on the same tap, and BSP taps move only between −2
  and +1. With every tap fixed at neutral the offsets grow slightly (−6.4, +5.4, +3.8 MW).

**One definition error, now fixed.**
- *What was wrong:* the engine set each transformer's short-circuit voltage vk from X alone, where pandapower defines
  it as the magnitude √(R² + X²). That understated vk by at most 0.53%, at Billingborough's 2T0 unit (Alford 0.5%,
  Wrangle 0.3%).
- *The fix:* vk = √(R1² + X1²) × rating ÷ 100 (README register).
- *Effect on the planning cases:* today unchanged. 2026 and 2030 move by at most 0.1 point. 2035 moves by at most
  1.5 points on a transformer, 1.1 on a line and one tap step (0.05 pu at one busbar). Breaches stay at 0, 0 and 15.
- *Effect on the 2024 year* (run B rerun after the fix):
  - every rule verdict and every label is unchanged;
  - the largest peak change is 2.6 points: Skegness's two 132/33 kV units now share 73.8% / 78.5% instead of
    76.4% / 76.1%;
  - Wrangle's transformer rises from 89.9% to 90.5%;
  - Alford is above firm for 9.0 hours instead of 9.5;
  - the voltage range is 0.959 to 1.041 pu instead of 0.960 to 1.043.

**What remains unexplained.**
- *Sleaford's transformer impedance is a lever, but not a defect.* The LTDS gives Sleaford's two 132/33 kV units 24.92%
  on 100 MVA, which is 11.2% on their 45 MVA rating, against 6.6 to 7.0% on rating at Skegness and Grantham.
  - As a sensitivity test only, giving Sleaford's units the others' per-unit impedance removes most of the Grantham-side
    mismatch: the tie falls from about 2.0 to 0.7 MW, the Grantham transformers from +3.0 to +0.7 MW, Sleaford's from
    −5.6 to −2.5 MW.
  - The engine holds NGED's published figure exactly, so whether NGED's own model uses it is a question for NGED
    (decision (a)). Nothing in the engine changes on the strength of it.
- *About 3 MW on the Skegness side stays unexplained.* Its tie stays at about 2.7 MW in the sensitivity run, and its
  transformers fall only from +5.0 to +4.4 MW. One possible lead: the unplaced balance at the Boston 132 kV tees (3.1),
  up to 3.6 MW. Boston is where the Skegness supply comes from.

**Other misses**, small, and listed in `screened/comparison.csv`:
- Alford's two transformers share the load differently from NGED's model: ±0.24 MW, 4% of rating.
- A few 33 kV lines around Sleaford and Billingborough are off by 0.5 MW.

## 4. Findings

### 4.1 Input quality

**Spilsby's reactive power.**
- NGED's MVAr for Spilsby primary reaches 54 MVAr; active power peaks at 6.6 MW, through two 6 MVA transformers. Bad
  stretches fall in January (up to 34 MVAr), February, July and November to December (up to 54).
- **The screen** (README register; *guide, overnight*):
  - a half-hour is *implausible* when apparent power exceeds 1.5 × the substation's installed transformer capacity;
  - it is *suspect* when MVAr exceeds 2 × MW and 2 MVAr;
  - flagged half-hours have their reactive power substituted with MW × tan(the LTDS power-factor angle).
- **What it flags:**
  - Spilsby: 590 implausible and 242 suspect half-hours;
  - Billingborough: 1 implausible (27 February 18:00, 34 MVAr);
  - Trusthorpe: 7 suspect.
- **The threshold separates cleanly:** Spilsby sits at 3.5× capacity at its 99th percentile, while every other node
  stays at or below 0.88× all year.
- **Spilsby is declared unreliable for the year** *(guide, overnight)*. The rule: the screen flags more than 1% of the
  year's half-hours (Spilsby 832, 4.7%; Billingborough and Trusthorpe stay in). Values below both tiers are still
  wrong: even screened, Spilsby carries 11.2 MVA on 6.6 MW. So Spilsby's transformers and its 11 kV busbar are labelled
  "reactive input unreliable" and are not findings.

  | Spilsby transformers | Run A, as published | Run B, screened | Run C, active power only (lower bound) |
  |---|---|---|---|
  | Unit 34 | 581% | 94.2% (11 December 17:00) | 55.6% (20 November 17:30) |
  | Unit 33 | 565% | 91.6% | 54.0% |
- **The unsolved half-hours of run A.** 21 of the 22 are 11–13 December, Spilsby's worst stretch. The 22nd is
  27 February 18:00, the half-hour of Billingborough's 34 MVAr. Runs B and C solve all 17,568.

**Imputed stretches** (runs of 12 or more identical values, flagged separately from the reactive screen):
- **Wrangle (T2)** reads 0.00 from 1 August to the year end (6,489 half-hours).
- **Great Hale** has 5,517 flagged half-hours. 31% of its values are exactly 0, which looks like export clipped to zero.
- Horncastle (T2), Leadenham and Billingborough have 95, 30 and 22.

### 4.2 Model differences

- **The Sleaford ties and the BSP transformers** (3.2, 3.3): about 2 MW more on each tie than in NGED's model, and the
  matching transformer offsets. NGED's files do not show the ties run open, so the cause is not established.
- **The tee term** (3.1): NGED's losses appear at its nodes, at 4 to 70 times the size the engine's resistances predict.
- **Coincidence at the BSPs.** The coincidence of NGED's metered 2024 primary series for each BSP group (each group's
  coincident peak ÷ the sum of its primaries' own peaks) against the engine's (from the LTDS):

  | BSP group | NGED metered, 2024 | Engine |
  |---|---|---|
  | Skegness | 0.78 | 0.78 |
  | Grantham | 0.90 | 0.82 |
  | Sleaford | 0.81 | 0.93 |

  The same evidence exposed Warth Lane. Net flows from one year cannot settle it, but it is worth a look.
- **Generator placement (since fixed, Work 2).**
  - *What was wrong:* LTDS Table 5 lists generation by BSP (for example 112.8 MW of solar "at Sleaford 33 kV"), so the
    planning cases put it on the BSP busbar. In reality the big farms sit on their own feeders: Gorse Lane 2 × 19 MW,
    White Cross Lane 22 MW, Ermine Farm 26 MW. Those feeders load to 57–85% in 2024 (NGED's derived feeder flows), and
    the planning cases loaded them to about 1%.
  - *The fix:* the engine now places the 11 sites the ECR names on their own feeders (README register: "Generators on
    their own feeders"). The summer-minimum case loads those feeders to 65–84%, close to the 2024 figures, and no
    breach changes in any year.
- **Wrangle: an inconsistency in NGED's own data, not in our model.**
  - *Both models have one unit.* NGED's files carry one Wrangle 11 kV node series (Wrangle Main 2) and one Wrangle
    33/11 kV transformer branch (#3T0), as the engine does. NGED's other Wrangle buses are 33 kV switchgear and a tee.
  - *The LTDS* lists that one 6 MVA transformer (replacing the old 2T0, marked Removed) and one demand row, Wrangle
    (T2), with a 2.53 MW maximum. It has no Wrangle T1 row, Removed or otherwise.
  - *The inconsistency:* the metered series peaks at 5.08 MW (25 January 23:00, clean data, before the imputed stretch),
    twice that LTDS maximum, and the transformer reaches 90.5% (89.9% before the vk fix).
  - *A possible cause:* a 33 kV busbar-section node (1S4/1S8) suggests the other half of Wrangle sits outside this
    data, with load moving between the halves: high in January, zero from August.
  - *So:* the 90.5% is what NGED's metered series puts through the unit both models have. The label "flow agrees" stands,
    with this caveat beside it.

### 4.3 Utilisation in 2024 (run B, screened)

**No line or transformer exceeds 100%**, on NGED's monthly ratings or on the summer rating all year (line peak 94.0%).

| Element | Label | Peak (when) | Hours ≥80% | Hours ≥90% | Peak on summer rating all year | 2024 planning cases: winter / summer |
|---|---|---|---|---|---|---|
| Skegness – Middlemarsh 132 kV (×2) | input: carries NGED's own flow by construction | 93.7% (1 March 12:00) | 857 / 892 | 166 / 162 | 94.0% | 3% / 93% |
| Wrangle 33/11 kV transformer | flow agrees with NGED's model (see the Wrangle note in 4.2) | 90.5% (25 January 23:00) | 1 | 0.5 | 90.5% | 32% / 21% |
| Sleaford – White Cross Lane 33 kV | input: carries NGED's own flow by construction | 84.6% (26 June 15:00) | 225 | 0 | 84.6% | 1% / 1% |
| Sleaford – Gorse Lane 33 kV (×2) | input: carries NGED's own flow by construction | 77.3% (11 August 13:30) | 0 | 0 | 77.3% | 2% / 2% |
| Skegness 132/33 kV GT1 / GT2 | flow differs (+1.3 / +1.4 MW, 3% of rating) | 73.8% / 78.5% (19 January 18:00) | 0 | 0 | same | 58% / 32% |
| Horncastle – Spilsby 33 kV | flow differs (+1.5 MW, 8% of rating) | 75.1% (17 December 16:30) | 0 | 0 | 83.7% | 46% / 27% |
| Woodhall Spa 33/11 kV | flow agrees | 72.6% (21 November 17:30) | 0 | 0 | 72.6% | 74% / 33% |
| Horncastle 33/11 kV (×2) | flow agrees | 71.3% (17 December 13:30) | 0 | 0 | 71.3% | 41% / 19% |

How to read the table:
- "Flow agrees" rows are findings of our model.
- "Input" rows carry NGED's own derived flow by construction: their loading is NGED's flow against our rating, exactly
  as good as NGED's derived figure and no better, not a result of our model.
- "Flow differs" rows show the engine's figure with its offset beside it.
- *The planning-case column* was computed before Work 2 moved the named generators onto their feeders. The solar
  feeders' 1–2% there are now 65–84% at summer minimum (4.2); the other rows are unaffected.
- Every line and transformer, with its label, both rating bases and the planning cases, is in `screened/elements.csv`.
- Duration curves for the ten most loaded elements are in `screened/figures.json`.
- Half-hours flagged as imputed in an element's BSP group are excluded in the `*_unflagged` columns:
  - in the Skegness and Sleaford groups this leaves 10,251 and 11,995 half-hours;
  - for 132 kV elements it leaves 4,678, because every group's flags count there;
  - the largest change is 11 points (the Bicker Fen to Boston circuits), because the Skegness and Sleaford flags cover
    much of the year.

**Voltages.** Run B: from 0.959 pu (Metheringham 33 kV, 15 January 08:30) to 1.041 pu (Middlemarsh 132 kV, 5 February
00:30). No busbar leaves its statutory band. Run A puts Spilsby 11 kV at 0.735 to 1.259 pu and six busbars around
it outside their band (Spilsby 33 kV for 113 hours, and the 33 kV tees and Stickney towards Skegness, plus Horncastle
33 kV for 5.5 hours): the Spilsby fault.

**The GSP.** The engine's peak export is 216 MW (NGED's four circuits: 209 MW) and its peak import 137 MW (132 MW),
against the 527 MW export limit.

### 4.4 Firm capacity (run B)

Firm capacity is the load a substation can carry after losing one transformer, the margin it is planned to keep.

**New Beacon Road** (firm 14 MVA, installed 2 × 12 MVA):
- *The peak:* 14.26 MVA through its transformers on 15 January 18:00, 101.9% of firm.
- *How it is formed:* the two units' MVA at that half-hour, 7.30 + 6.96, each unit's loading × its 12 MVA rating.
- *The input:* the substation's input was 14.40 MW and −0.95 MVAr, 14.43 MVA. Engine active power 7.40 + 7.06 MW
  against NGED's own 7.38 + 7.04 MW, so the model reproduces NGED's split.
- *Duration:* above firm for 5 hours in 2024.

**Alford** (firm 6 MVA, installed 2 × 6 MVA):
- *The peak:* 6.55 MVA on 20 November 17:00, 109.1% of firm. This is a different day from run A's figure, so it is not
  the Spilsby fault.
- *The input:* 6.08 MW and 1.77 MVAr, 6.33 MVA, already above firm before transformer losses.
- *Duration:* above firm for 9.0 hours.
- *Sharing:* the units share unevenly, 4.12 and 2.42 MVA (active power 3.94 and 2.18 MW). NGED's own model splits it
  3.41 and 2.67 MW, so part of the unevenness is ours (rule 3 lists both units at ±0.24 MW). The total above firm does
  not depend on the split.

**Next:** Leadenham at 87%. Spilsby is left out: its reactive input is unreliable.

**What this means and does not mean.**
- *It means:* at those half-hours both substations were within their intact rating, at 59% and 55% of installed
  capacity, but carried more than they could have after losing one transformer. That is the condition a DNO's
  firm-capacity check is there to catch.
- *It does not say:* whether NGED had switching or transfer capacity to cover it, whether the firm figures are MVA (the
  LTDS does not state the unit; the register records the reading), or anything about other years.
- No outage study is added here.

## 5. The planning cases beside the 2024 run

**The comparison.** The population is the 170 lines and transformers outside the "reactive input unreliable" class.
For each, the 2024 run's peak loading is set against the higher of the engine's two 2024 planning cases (winter peak,
summer minimum).
- *All 170:* the 2024 peak is higher by more than half a point on 130.
- *The 126 whose planning-case loading is above 10%*, where a ratio means something: the 2024 peak is higher on 97.
  The ratio of 2024 peak to planning case has a median of 1.23, a 10th percentile of 0.78 and a 90th percentile of
  1.71.

**Three reasons, in order of size:**
1. **Coincidence.** The winter-peak case scales every primary to its share at the GSP's peak (factors 0.75 Skegness, 0.78 Grantham, 0.89 Sleaford), as
   the SQSS group-demand condition asks. But each primary reaches its own peak at its own time, and NGED's 2024 primary
   peaks match the LTDS maxima closely (median ratio 1.02 over 21 primaries; outliers Wrangle 2.0×, Horncastle 1.33×,
   Ingoldmells 1.25×). So the winter-peak case loads local elements below their own peaks by roughly 1 ÷ coincidence.
   It is a GSP-level condition, not a check of each substation against its own peak. DNOs check firm capacity against
   each substation's own peak, which is what 4.4 does.
2. **Generator placement** (4.2): the solar farms' feeders.
3. **Ratings.** On 1 March the Middlemarsh circuits carry the intermediate-cool rating. On the summer rating they reach
   94.0%, against the planning case's 92.9% with 180 MW of wind (NGED's derived wind peak is 186 MW, from its own load flow, not metered).

**Where the planning cases are the extreme, as intended:** the summer-minimum export (292 MW against the 2024 run's peak of
216; 340 MW since Work 2 added Ash Farm and placed the named generators) and the winter-peak import (137 MW against 137,
coincidentally equal; 144 MW since Warth Lane was restored).

*This comparison was made before Work 2 placed the named generators on their own feeders. Reason 2 is now resolved in
the engine; reasons 1 and 3 stand. The 2024 runs themselves are unaffected by Work 2: their inputs sit on their own
anchor buses, not on the engine's generators.*

**What this shows about the study basis:** the two planning cases are extremes for the GSP, not for each element. A
check per element needs each substation's own peak. That is the owner's decision for a later step; nothing was changed.

## 6. What this does not tell you

- **The future.** One past year, 2024 weather and demand, no growth, no new connections. The grown-year report
  (`docs/reports/grown-year-2026-11-13/report.md`) carries this year to 2030 and 2035 demand.
- **Security of supply.** Networks are planned to stand the loss of one circuit or transformer, so headroom on an intact
  network overstates what is usable. The outage study was removed from the product on 2026-10-16 and is not re-added
  here. It is the natural next question, and the owner's decision.
- **The physical grid.** Most inputs are NGED's own derived values, and the check compares two models.
- **Curtailment.** Any curtailment NGED applied in 2024 is already inside its figures.
- **Peaks inside a half-hour.** Only half-hourly averages are modelled.
- **Real-time ratings.** Ratings are static seasonal ratings, with the month table's wording unverified against NGED's
  document; transformers have one rating all year.
- **Imputed values.** NGED's imputation is unflagged, so the stretches the screen does not catch are in the data.
- **The low-voltage network** below 11 kV.

## 7. Decisions for the owner

In the order an engineer would take them:

a. **Ask NGED** (nged.data@nationalgrid.co.uk, the address in the licence):
   - Spilsby's reactive-power series;
   - the GSP node series;
   - why Warth Lane's demand row is marked Removed;
   - Manor Farm PV: the ECR has it connected since 23 February 2024, but NGED's 2024 flows show its spur at 0 MW all
     year;
   - where Ash Farm (Vicarage Drove, 48 MW, connected July 2025) connects: placed at Bicker Fen 132 kV by its
     coordinates (0.33 km away);
   - whether the LTDS impedance for Sleaford's 132/33 kV units, 24.92% on 100 MVA, is what NGED's own model uses. It
     comes to 11.2% on their 45 MVA rating, against 6.6 to 7.0% at Skegness and Grantham, and the Sleaford–Grantham side
     of the mismatch largely closes if Sleaford's were similar (3.4);
   - whether Grantham 132 kV's two sections run split, as the LTDS model has them, and whether the 240 MW solar +
     storage offer there carries reinforcement or an export limit the LTDS does not show. Split, that project
     overloads its own circuits to Bicker Fen for over 500 hours of 2030; tied, about 70
     (`docs/reports/grown-year-2026-11-13/branch-examples.md`).

   The answers would confirm or replace the screen, the closure reference, the Warth Lane exception and the remaining
   model difference.
b. **A per-substation check in the study basis**: each substation against its own peak and its firm capacity, beside the
   two GSP-level planning cases. That would turn 4.4 from a one-year finding into a check every plan year reports.
c. **The 33 kV ties out of Sleaford.** NGED's files do not show them run open (3.3), and Work 1 (3.4) ruled out the
   injections, the impedance conversion, split boards and taps. What is left is Sleaford's published impedance (the
   question in a) and about 3 MW on the Skegness side. NGED's running arrangement and its model's impedances would
   settle both.
d. **Large generators on their own feeders:** done overnight (Work 2), for the owner to confirm. 11 named sites
   (145.65 MW) moved. Ash Farm (48 MW of solar, connected 2025, missing from this LTDS edition) was added at Bicker Fen
   132 kV. The ambiguous sites stay at the busbars and are listed in the register.
e. **Whether to bring back an outage study** (removed on 2026-10-16). Every headroom figure here is on an intact network.
f. **Confirm the overnight decisions** and the season table:
   - the reactive screen and Spilsby's unreliable class;
   - the Mill Farm battery taken whole;
   - the DFES re-pin for Warth Lane;
   - the month-to-rating table (wording unverified; pasting the table from NGED's NDP methodology report settles it).
g. **Agent guidance (AGENTS.md):** `packages/optimizer/AGENTS.md`'s "What it owns" list does not yet name the measured
   year (`nged_flows.py`, `timeseries.py`, `network.solve_snapshot`, `GridSource.measured_year`). Adding one line there is
   the owner's call.

## 8. Reproduce

```bash
cd apps/pipeline && uv run dagster asset materialize -m grid_simulator.definitions --select nged_flows
cd ../../packages/optimizer
W=../../apps/pipeline/warehouse/nged-flows
uv run python -m gridify_optimizer.timeseries $W/bicker-fen-2024 $W/measured-year-2024.npz published
uv run python -m gridify_optimizer.timeseries $W/bicker-fen-2024 $W/measured-year-2024-screened.npz screened
uv run python -m gridify_optimizer.timeseries $W/bicker-fen-2024 $W/measured-year-2024-unity.npz unity
for r in published:measured-year-2024 screened:measured-year-2024-screened unity:measured-year-2024-unity; do
  uv run python ../../docs/reports/measured-year-2024/analyse.py $W/${r#*:}.npz ../../docs/reports/measured-year-2024 ${r%%:*}
done
```

**Housekeeping, for the owner.**
- *An old API worker is still running.* PID 5024 is a uvicorn worker of an API process started during this work (12 Nov,
  about 20:24) for the attribution check. Its parent was stopped, but the worker kept port 8000 and
  `apps/api/data/scenarios.duckdb` open, and it serves the engine code from before Warth Lane was restored.
- *What that blocks:* until it is ended, `pnpm --filter @gridify/api dev` cannot start on port 8000.
- *How to end it:* Task Manager, or `Stop-Process -Id 5024` in PowerShell. This session's permission check refused to
  stop it.
- *How the browser checks ran meanwhile:* a fresh API on port 8010 with a temporary scenarios database
  (`GRIDIFY_SCENARIOS_DB`), and the planner on port 3010 with `VITE_API_BASE=http://127.0.0.1:8010`.

Supported by NGED Open Data (NGED Open Data Licence, December 2020).
