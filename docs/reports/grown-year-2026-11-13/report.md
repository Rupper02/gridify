# A grown year: 2024's shape at 2030 and 2035 demand

*13 November 2026. Work 4, decided by the guide session overnight, for the owner to confirm. A report, not a product
feature. The method was fixed before any run (`spec.md`); every figure comes from `analyse.py` on the run files listed
at the end. Supported by NGED Open Data.*

**Terms.**
- **Grown year:** NGED's 2024 half-hourly flows, with each metered primary's demand multiplied by the engine's own
  growth ratio for the year. The same AC power flow then runs through all 17,568 half-hours.
- **Planning cases:** the engine's two snapshots for the same plan year, winter peak and summer minimum.
- **Firm capacity:** what a substation can carry after losing one transformer.
- **Pathways:** Holistic Transition is the engine's default; Falling Behind is NGED's low pathway.
- **Run B:** the measured-year report's screened 2024 run, the grown years' starting point.
- **Step 1 label:** how far an element's 2024 flow agreed with NGED's own model (measured-year report, section 3).

## Summary

**What the snapshot basis misses, in one example** (Work 6b, `branch-examples.md`). A 40 MW solar farm on a 33 kV circuit near Sleaford takes that
circuit to 141% of its rating, and over it for 402 hours of 2030. The summer-minimum planning case puts the same
circuit at only 102.5%, because running every generator at full export at once first sends 8 MW the other way along
that line, and the farm's flow cancels that before it loads the circuit. In the year, at the farm's sunny half-hours,
that line carries about 1.5 MW without the farm, so the farm's flow arrives almost whole.

**2030, Holistic Transition.**
- *Planning cases:* no breach.
- *Grown year:* no line or transformer with a reliable input exceeds its rating at any half-hour. (Only Spilsby's
  transformers do, for 3.5 hours, and their reactive input is unreliable.) One busbar, Horncastle 33 kV, leaves its
  statutory band for half an hour.
- *But two primaries run above their firm capacity for over a thousand hours:* New Beacon Road for 1,544 hours (peak
  20.4 MVA against 14) and Alford for 1,184 hours (8.9 against 6). On an intact network that is invisible; after losing
  one transformer it is a shortfall.

**2035, Holistic Transition.**
- *Planning cases:* 15 breaches (10 transformers, 5 busbar voltages).
- *Every one is also an overload, or a voltage excursion, in the grown year,* for between 72 and 1,818 hours. The
  planning cases flag nothing the grown year does not.
- *The grown year finds 16 more lines and transformers over their rating that the planning cases miss,* plus Spilsby's
  two (unreliable input). The largest:
  - Alford's transformer: 1,164 hours (planning case 99.8%, just under its limit);
  - Warth Lane: 176 hours;
  - Horncastle–Spilsby 33 kV: 157 hours;
  - Horncastle's two transformers: 75 hours each;
  - Leadenham: 37 and 16 hours.
- *Seven busbars leave their band that the planning cases do not flag* (up to 42 hours).
- *Nine substations run above firm capacity* (Leadenham's two halves counted once), led by Alford for 8,149 hours (most
  of the year) and New Beacon Road for 7,408.

**2035, Falling Behind (the low pathway).**
- *Planning cases:* no breach.
- *Grown year:* four elements with reliable inputs go over their rating, each for an hour or less: Alford's transformer,
  Wrangle's, and Horncastle's pair.
- *Firm capacity:* New Beacon Road and Alford are above it for about 2,050 hours each.

**What this says about the snapshot basis.**
- *Where it matches:* where the planning cases see a breach, the grown year confirms it.
- *What it misses:* elements just under 100% in the snapshot (Alford's 99.8%) and elements the GSP-level extremes do
  not stress, chiefly the 11 kV transformers and 33 kV lines of primaries whose own peak comes at a different time from
  the GSP's.
- *How long:* it says nothing of duration. A planning-case breach of 109% at Sleaford 11 kV is 360 hours a year in the
  grown year; one of 119% at New Beacon Road is 1,818.
- *Firm capacity:* none of this is seen. The firm-capacity shortfall at New Beacon Road and Alford is already the larger
  problem in 2030.

**Which limit would move the answer most.**
1. *2024's shape is kept.* The size of each substation's peak follows the engine's growth source, the DFES winter-peak
   ratio. When and for how long it is exceeded follows 2024's shape, which electrification will change. So the hour
   counts are indicative, not a bound in either direction (corrected overnight; an earlier draft called them a lower
   bound):
   - *Fewer hours:* the DFES ratio is a peak ratio applied to every half-hour, which assumes energy grows as fast as the
     peak. If electrification sharpens the peak, the hours away from it grow less than scaled here.
   - *More hours, or new ones:* new load at times that were quiet in 2024 (overnight vehicle charging, cold-morning
     heating) could put exceedances where the 2024 shape has none.
2. *One growth source.* At Warth Lane, NGED's own LTDS forecast is 3.5 times the DFES path by 2030 (firm-capacity
   report). On that forecast Warth Lane leads this report: section 6 runs it, and its three transformers, two 33 kV
   circuits from Skegness and both Skegness 132/33 kV transformers go over their rating for thousands of hours.

The other limits (net-of-generation scaling at seven primaries, one weather year, no generation growth, the 33 kV model
differences, no outages) shift particular elements; they do not change the overall picture.

**What one project adds (Work 6b, `branch-examples.md`).** The same 2030 year with one registry project on a branch:
- *240 MW of solar + storage at Grantham 132 kV:* with Grantham's two sections split, as the LTDS model has them, its
  circuits to Bicker Fen go over rating for 527–569 hours, on 171 days; tied, about 70 hours on 32 summer days. The
  answer turns on a running arrangement the public data does not give: a question for NGED.
- *40 MW of solar at the Whitecross Lane 33 kV tee:* its 25 MVA circuit to Sleaford is over rating for 402 hours. The
  summer-minimum planning case shows it at only 103%, because there another generator's counter-flow cancels part of
  the farm's.

## 1. Lines and transformers over their rating

**2035, Holistic Transition: every element above 100% at any half-hour.**

| Element | Step 1 label | Peak | Hours ≥80% | ≥90% | >100% | Months | Planning case (envelope) | Planning breach? |
|---|---|---|---|---|---|---|---|---|
| New Beacon Road 33/11 kV T1 | agrees | 152.8% | 4,182 | 2,839 | 1,818 | Sep–May | 118.7% | yes |
| New Beacon Road 33/11 kV T2 | agrees | 146.4% | 3,693 | 2,428 | 1,506 | Sep–Apr | 113.2% | yes |
| Skegness 132/33 kV GT2 | differs (+1.4 MW, 3%) | 140.5% | 3,774 | 2,237 | 1,176 | most months | 115.9% | yes |
| Alford 33/11 kV T1 | differs (−0.2 MW, 4%) | 156.2% | 3,064 | 1,933 | 1,164 | Aug–May | 99.8% | **no** |
| Woodhall Spa 33/11 kV T2 | agrees | 140.4% | 2,475 | 1,488 | 814 | Sep–Mar | 142.2% | yes |
| Skegness 132/33 kV GT1 | differs (+1.3 MW, 3%) | 133.3% | 2,814 | 1,538 | 745 | most months | 115.7% | yes |
| Great Hale 33/11 kV | agrees | 150.0% | 1,828 | 1,123 | 599 | Sep–Feb | 142.6% | yes |
| Sleaford 33/11 kV (×2) | agrees | 123.7% | 2,012 | 1,019 | 360 / 347 | Nov–Mar, Jun | 108.9% | yes |
| Warth Lane 33/11 kV T1 | agrees | 119.2% | 1,870 | 746 | 176 | Oct–Mar | 87.2% | **no** |
| Horncastle – Spilsby 33 kV | differs (+1.5 MW, 8%) | 133.4% | 1,645 | 590 | 157 | most months | 84.4% | **no** |
| Sleaford 132/33 kV GT2 / GT1 | differs (−1.9 MW, 4%) | 117.9% | 834 | 306 | 80 / 73 | Nov–Feb | 113.6% | yes |
| Horncastle 33/11 kV (×2) | agrees | 147.4% | 1,022 | 314 | 76 / 75 | winter and summer | 84.6% | **no** |
| Leadenham 33/11 kV (×2) | agrees | 118.9% | 960 | 244 | 37 / 16 | Nov–Mar | 74.6% | **no** |
| Tower 91ZB9F9–F10, 33 kV | agrees | 115.1% | 873 | 211 | 37 | Jan, Nov | 85.2% | **no** |
| Billingborough, Alford T2, Warth Lane T2 and T3, Wrangle, Tattershall–Woodhall Spa, the Trusthorpe link, Metheringham | various | 101–136% | — | — | 0.5–5 each | winter | 49–88% | **no** |
| Spilsby 33/11 kV (×2) | reactive input unreliable | 229–235% | — | — | 65–76 | Nov–Feb | 88–90% | no (not a finding) |

How to read it:
- *Hours of day:* the exceedances fall across the working day and evening, 07:00 to 22:00.
- *"Differs" rows* carry their step-1 offset against NGED's model: about ±4 points of loading on the 132/33 kV units.
- *Full tables:* `2035-ht/elements.csv`, `2030-ht/elements.csv` and `2035-fb/elements.csv` cover every element, with
  the peak and when, hours at or above 80, 90 and 100%, the months and hours of day, and the planning case beside each.

**2030, Holistic Transition, and 2035, Falling Behind.** Only Spilsby (unreliable) and, in the low 2035 case, Alford,
Wrangle and Horncastle's pair go over, each for an hour or less. The most loaded reliable elements:
- *2030:* Wrangle 98.8%, Woodhall Spa 94.7% (160 hours at or above 80%), the Middlemarsh wind circuits 94%, the Skegness
  132/33 kV units 94%.
- *2035 Falling Behind:* Skegness GT2 97.9% (291 hours at or above 80%) and Woodhall Spa 97.3% (225 hours).

## 2. Voltage

| Year | Lowest | Busbars outside the statutory band (hours) | Planning-case voltage breaches |
|---|---|---|---|
| 2030 Holistic | 0.937 pu, Horncastle 33 kV | Horncastle 33 kV 0.5 | none |
| 2035 Holistic | 0.884 pu, Horncastle 33 kV (11 Dec 17:00) | Horncastle 33 kV 1,131; Metheringham 33 kV 650; Grange Farm (Kirkby on Bain) 33 kV 199 ×2; Woodhall Spa 33 kV 92 and its tee 36; three poles on the Woodhall Spa – Horncastle line 40–42; Trusthorpe 33 kV 2; Alford 33 kV 0.5; Spilsby 33 kV 0.5 | five busbars: Horncastle, Grange Farm ×2, Metheringham, Woodhall Spa. All five also leave their band in the grown year |
| 2035 Falling Behind | 0.936 pu, Horncastle 33 kV | Horncastle 33 kV 4.5 | none |

## 3. Firm capacity: hours above firm in the grown years

| Substation | Firm (MVA) | 2030 Holistic: peak MVA, hours above | 2035 Holistic: peak, hours | 2035 Falling Behind: peak, hours | Work 3: first year above firm (Holistic) |
|---|---|---|---|---|---|
| Alford | 6 | 8.9, 1,184 | 15.8, **8,149** | 9.9, 2,047 | now |
| New Beacon Road | 14 | 20.4, 1,544 | 35.9, **7,408** | 21.8, 2,065 | now |
| Leadenham (whole site against each half's 9.5) | 9.5 | 9.9, 1 | 14.1, 926 | 10.5, 4.5 | not by 2035 |
| Sleaford 11 kV | 23 | — | 29.7, 596 | — | 2033 |
| Trusthorpe | 19 | — | 23.3, 136 | — | not by 2035 |
| Tattershall | 17 | — | 20.1, 124 | — | 2034 |
| Billingborough T1 (whole site against T1's 9.5) | 9.5 | — | 12.4, 117 | — | not by 2035 |
| Chapel St Leonards | 9.5 | — | 10.9, 19 | — | 2034 |
| Warth Lane | 38 | — | 39.2, 2 | — | not by 2035 (LTDS forecast: 2027) |

How to read it:
- *The MVA* is the flow through each substation's transformers in the grown run, the whole site.
- *Spilsby is left out:* its reactive input is unreliable.
- *Leadenham and Billingborough* are each published as two halves fed from different BSPs, each with its own firm
  capacity. The whole-site flow against one half's firm overstates their hours.
- *Where the grown year and Work 3 differ,* the difference is the shape: Work 3 grows the LTDS maximum; the grown year
  grows 2024's metered series, net of generation.
  - Trusthorpe and Billingborough exceed firm in the grown year but not in Work 3: their 2024 metered peaks are above
    their LTDS maxima.
  - Spilsby, Sleaford BSP and Skegness BSP are the reverse.

## 4. The GSP through the year

| Year | Peak export (MW) | Peak import (MW) | Export limit 527 MW | Import above the limit of its own season, both SGTs (before Work 16b: above 2 × 110.8 all year) |
|---|---|---|---|---|
| 2024, measured (run B) | 216 (no Ash Farm) | 137 | never reached | never (never) |
| 2030 Holistic | 244 (with Ash Farm) | 172 | never reached | never (never) |
| 2035 Holistic | 200 | 262 | never reached | **never** (was: above 221.6 for 56 hours, nearly all in winter) |
| 2035 Falling Behind | 238 | 184 | never reached | never (never) |

- *Ash Farm* adds up to 51 MW at midday, 62.6 GWh a year, on Gorse Lane's 2024 shape.
- *Against the planning cases,* the export never comes near their 340 MW. That case is every generator at full output at
  minimum demand, and 2024 never combined the two.
- *The import limits* are published per supergrid transformer for each of NGED's four seasons: 160.1 MW winter, 179.1
  MW intermediate cool and warm, 110.8 MW summer (README register; the intermediate limit above the winter one is
  unusual, held as published).
  - *Since Work 16b,* each half-hour is counted against the limit of its own season (the run file's season, NGED's
    months). Before, the summer limit stood for the whole year, with November to March called winter by assumption.
  - *Restated:* with both SGTs in service, no grown year's import exceeds its season's limit. The 56 hours in 2035
    Holistic were winter half-hours, measured against the summer limit.
- *With one supergrid transformer out,* the 2035 Holistic import would exceed a single unit's limit of the season for
  **1,128 hours**: 347 winter, 177 intermediate cool, 56 intermediate warm, 548 summer. Before this was 865 hours,
  counted against the winter limit all year; the summer limit is the lowest, so the seasonal count is higher. That is an
  outage condition; it is noted for context, not studied (`import_hours.py`, `import_hours.json`).

## 5. Limits, again

- *2024's shape and weather are kept;* only size grows. The size of each peak follows the growth source. When and for
  how long it is exceeded follows 2024's shape, which electrification will change, so the hour counts are indicative,
  not a bound in either direction.
  - *What shape does, where it could be tested (Work 8.2 addendum):* DFES-shaped demand reproduces NGED's 2035 peak at
    eight areas only: Alford, Cranwell, Easton, Ingoldmells, New Beacon Road, Skillington, Tattershall and Trusthorpe.
    Of their transformers, only New Beacon Road's and Alford's go over rating.
    - *New Beacon Road:* the shaped run roughly doubles the hours (1,818 → 3,695 and 1,506 → 3,232) at the same peak,
      moving them into the night, midday and spring.
    - *Alford:* about the same hours (1,164 → 1,151), with a lower peak (156% → 136%), moved from the evening to the
      morning and midday.
    - The shaped counts lean high (`docs/reports/dfes-shape-2026-11-13/result.md`).
- *The metered series are net of embedded generation,* so growth also scales the generation behind Warth Lane (5.8 MW),
  Leadenham (3.6), Ruskington (2.1), Spilsby (2.0), Ingoldmells (1.8), Trusthorpe (1.6) and Easton (1.4). Their grown
  demand peaks are understated.
- *Generation is 2024's,* with no new solar, wind or batteries. "Main, grown" means no new connections.
- *Step 1's model differences remain.* The Skegness and Sleaford 132/33 kV units and the Horncastle–Spilsby 33 kV line
  carry an offset of about 1.3 to 1.9 MW against NGED's model (Skegness's above it, Sleaford's below); their rows say
  "differs".
- *No outages, no transfers between substations, no flexibility.*

## 6. Sensitivity: Warth Lane at NGED's own forecast (2030)

*Decided by the guide session overnight, for the owner to confirm.* The firm-capacity report found NGED's two forecasts
for Warth Lane far apart: the DFES path never crosses firm capacity by 2035, while NGED's LTDS forecast crosses it in
2027 and reaches 81.6 MW by 2030. This run is 2030 Holistic Transition with one change: Warth Lane's 2024 series is
scaled by the LTDS figure, 81.588 / 18.61 = **4.38**, instead of the DFES ratio of 1.24. Every other substation is as in
the 2030 run above.

**Read this first.** A jump from 18.6 MW to 81.6 MW in five years is not organic growth. It most likely reflects one
specific new connection at Warth Lane (the LTDS does not say which), and its shape is unknown. Multiplying 2024's shape
by 4.38 lifts the night troughs as much as the evening peak, so this run is a placeholder for the *size* only. The hours
below are what that size does if it followed 2024's shape; a real connection could be flatter (more hours) or peakier
(fewer).

**What breaks.** Twelve elements are over their rating at some point, against two in the DFES 2030 run (both Spilsby,
whose reactive input is unreliable). All ten new ones are on the route from Skegness to Warth Lane, and every one is
labelled "flow agrees with NGED's model" except the two Skegness transformers ("differs", by 1.27 and 1.38 MW):

| Element | Peak, DFES 2030 | Peak, LTDS 2030 | Hours above 100%, LTDS 2030 |
|---|---|---|---|
| Warth Lane 33/11 kV T1 (trafo 39) | 76.1% | 299.3% | 8,414 |
| Warth Lane 33/11 kV, the 3L3 unit (trafo 41) | 65.6% | 269.6% | 7,524 |
| Warth Lane 33/11 kV, the second 2L3 unit (trafo 40) | 66.2% | 260.6% | 7,372 |
| Skegness – Warth Lane 33 kV (circuit 1) | 47.3% | 184.2% | 4,214 |
| Wrangle tee – Warth Lane 33 kV | 46.7% | 183.5% | 3,220 |
| Skegness 132/33 kV GT2 | 94.1% | 183.1% | 3,489 |
| Skegness 132/33 kV GT1 | 88.8% | 176.5% | 2,815 |
| Skegness – Wrangle tee 33 kV | 48.4% | 146.5% | 1,851 |
| Skegness – Warth Lane tee 33 kV | 52.0% | 123.0% | 231 |
| Warth Lane tee – Warth Lane 33 kV | 29.4% | 120.9% | 146 |

- *The year has 8,784 hours.* Warth Lane T1 is over its rating for 96% of them: the scaled troughs alone exceed it.
- *The Skegness supergrid side holds.* The Skegness–Middlemarsh 132 kV circuits rise from about 94% to 96.5% peak
  (they carry NGED's own flow by construction), and the Boston–Skegness 132 kV lines fall, because more of Warth Lane's
  load now flows in from Skegness.
- *The 33 kV ring beyond Warth Lane eases:* the Warth Lane tee – Ingoldmells link drops from 25.9% to 14.9%.

**Voltage barely moves.** The lowest busbar is Warth Lane 11 kV at 0.930 pu, outside its band for 5 hours (none in the
DFES run); Horncastle 33 kV goes from 0.5 to 1 hour. The tap changers hold voltage; the limit here is thermal.

**Firm capacity.** Warth Lane's firm capacity is 38 MVA. Its peak through the transformers goes from 24.9 MVA to
**99.5 MVA**, above firm for **7,382 hours**. The peak is above the LTDS's 81.6 MW because the multiplier scales the
2024 metered series, whose peak through the transformers (about 20 MVA) is above the LTDS maximum of 18.61 MW and
includes reactive power. Every other substation's hours above firm move by 7 hours or less (Alford 1,184 to 1,191; New Beacon Road 1,544 to 1,542).

**The GSP.** Peak import rises from 172 MW to 232 MW (Ash Farm included, as in section 4). It passes the summer level of
2 × 110.8 MW for 5 hours, all in November to March, so it stays inside the winter limit of 2 × 160.1 MW (counted
against each half-hour's own season since Work 16b: never above). With one supergrid transformer out, import would
exceed a single unit's 160.1 MW winter limit for 391 hours (Ash Farm included; on the infeed without it, as `import_hours.py` counts, 425 against the winter limit all year and 559 against each half-hour's own season), against 9.5 in the
DFES run; that is an outage condition, noted for context. Peak export falls from 244 to 219 MW.

**What it means.** If NGED's own 2030 figure for Warth Lane is right, it is the place this grid breaks first, and the
DFES-based plan years do not see it (the engine's planning cases for 2030 show no breach). The work it implies is at
Warth Lane itself (all three transformers), on two 33 kV circuits from Skegness, and at the two Skegness 132/33 kV
transformers. The question to put to NGED: what connection is behind the LTDS forecast at Warth Lane, and what is its
profile?

## 7. The six bases a branch's year can run on (Work 10)

*Added 13 November, decided by the guide session overnight, for the owner to confirm.* The planner runs a branch's year
on any of six grown years: 2030 and 2035 on Holistic Transition (HT), Electric Engagement (EE) and Falling Behind (FB).
2030 EE, 2035 EE and 2030 FB were run for this, with the same code and method as the other three. Every half-hour
converged in all six. "Reliable" leaves out the elements whose reactive input is unreliable (Spilsby) and the circuits
that carry NGED's own flow by construction; an element whose flow differs from NGED's model is counted, with its
offset in section 1.

| Base | Reliable elements over rating | Worst three (peak, hours over 100%) | Busbars outside band | Substations above firm | GSP import peak | Import above its season's limit, both SGTs (before: above 2 × 110.8 all year) |
|---|---|---|---|---|---|---|
| 2030 HT | 0 | none | 1 (Horncastle 33 kV, 0.5 h) | 3 | 172 MW | 0 h (never) |
| 2030 EE | 1 | Wrangle 33/11 kV T3 100.6%, 0.5 h | 1 (Horncastle 33 kV, 0.5 h) | 3 | 173 MW | 0 h (never) |
| 2030 FB | 0 | none | 0 | 2 (New Beacon Road 314 h, Alford 243 h) | 153 MW | 0 h (never) |
| 2035 HT | 26 | New Beacon Road T1 152.8%, 1,818 h; NBR T2 146.4%, 1,506 h; Skegness GT2 140.5%, 1,176 h | 12 (Horncastle 33 kV 1,131 h) | 9 | 262 MW | 0 h (56 h) |
| 2035 EE | 24 | New Beacon Road T1 141.4%, 1,204 h; Alford T1 157.3%, 1,195 h; Skegness GT2 140.1%, 1,095 h | 14 (Horncastle 33 kV 1,165 h) | 9 | 259 MW | 0 h (47.5 h) |
| 2035 FB | 4 | Alford T1 100.9%, 1 h; Wrangle T3 104.4%, 0.5 h; Horncastle T1 100.4%, 0.5 h | 1 (Horncastle 33 kV, 4.5 h) | 3 | 184 MW | 0 h (never) |

Leadenham's two halves count as one substation. Import hours are counted without Ash Farm, as in section 4, each
half-hour against the limit of its own season (Work 16b). In brackets: the earlier count against the summer limit all
year, whose 2035 hours fell nearly all in winter.

**2035 Electric Engagement.** It ends close to Holistic Transition: 24 reliable elements over rating against 26, the
same nine substations above firm, Horncastle 33 kV as deep (0.884 pu) and out of band slightly longer, and import within
3 MW, so the 2035 picture does not hang on which high-electrification pathway is chosen. The order of the worst changes
(New Beacon Road eases by about 600 hours, Alford holds), and Falling Behind remains the case where 2035 looks like 2030.

## 8. The size of "one weather year" (Work 13)

**The totals hold between the two base years while single elements move by up to a factor of five. So an element's
hours are an order of magnitude, and the set of elements is the finding.** On 2024's shape, 24 reliable elements are
over rating for 9,268 hours summed, with import at 262 MW. On 2025's shape the figures are 23, 9,212 hours and 268 MW.

*Added 13 November, decided by the guide session overnight, for the owner to confirm.* The same grown year, 2035
Holistic Transition, built from two different measured years:
- *on 2024's shape:* `2035-ht`, as above;
- *on 2025's shape:* `2035-ht-flows-2025`, NGED's 2025 flows (`measured-year-2024/second-year-2025.md`).

Everything else is the same: the network, the method, screened reactive power, and each metered primary's multiplier
(identical where both years meter it). All half-hours converged in both runs. The spread below is what "one weather
year" carries.

**The totals hold; individual elements do not.**

| | On 2024's shape | On 2025's shape |
|---|---|---|
| Reliable elements over rating | 24 | 23 |
| Their hours over rating, summed | 9,268 | 9,212 |
| Substations above firm | 10 (Leadenham counted per half) | 11 (Billingborough T2 for half an hour) |
| Lowest voltage | 0.884 pu, Horncastle 33 kV | 0.901 pu, Metheringham 33 kV |
| Busbars outside band | 12 | 9 |
| GSP import peak (export peak) | 262 MW (200) | 268 MW (232) |
| GSP import above its season's limit, both SGTs (before: above 2 × 110.8 all year; no Ash Farm) | 0 h (56 h) | 0 h (54 h) |

Element by element, the 131 elements reliable in both measured years:
- the peak moves by a median of 3.0 points (90th percentile 12.2, largest 33.9);
- the hours over rating move far more than the peaks:

| Element | Peak, 2024 → 2025 shape | Hours over rating, 2024 → 2025 shape |
|---|---|---|
| New Beacon Road 33/11 kV T1 | 152.8% → 152.5% | **1,818 → 1,499** |
| New Beacon Road T2 | 146.4% → 146.3% | 1,506 → 1,270 |
| Alford T1 | 156.2% → 151.2% | 1,164 → 1,142 |
| Woodhall Spa T2 | 140.4% → 160.2% | 814 → 1,161 |
| Great Hale | 150.0% → 183.9% | 599 → 1,196 |
| Skegness 132/33 kV GT2 | 140.5% → 130.6% | 1,176 → 425 |
| Skegness 132/33 kV GT1 | 133.3% → 121.1% | 745 → 135 |
| Sleaford 33/11 kV (×2) | 123.7% → 128.6% | 360 / 347 → 427 / 413 |
| Warth Lane T1 | 119.2% → 122.6% | 176 → 361 |
| Sleaford 132/33 kV GT2 / GT1 | 117.9% → 120.6% | 80 / 73 → 201 / 195 |
| Leadenham (×2) | 118.9% → 142.5% | 37 / 16 → 152 / 106 |
| Horncastle 33/11 kV (×2) | 147.4% → 129.2% | 76 / 75 → 35 / 35 |
| Tower 91ZB9F9–F10, 33 kV | 115.1% → 105.7% | 37 → 14 |

| Substation above firm | Firm | On 2024's shape: peak, hours | On 2025's shape: peak, hours |
|---|---|---|---|
| Alford | 6 MVA | 15.8, 8,149 | 15.5, 7,922 |
| New Beacon Road | 14 MVA | 35.9, 7,408 | 35.9, 7,142 |
| Leadenham (each half) | 9.5 MVA | 14.1, 926 | 16.9, 1,487 |
| Sleaford 11 kV | 23 MVA | 29.7, 596 | 30.8, 657 |
| Billingborough T1 | 9.5 MVA | 12.4, 117 | 14.5, 232 |
| Tattershall | 17 MVA | 20.1, 124 | 20.8, 192 |
| Trusthorpe | 19 MVA | 23.3, 136 | 21.4, 43 |
| Chapel St Leonards | 9.5 MVA | 10.9, 19 | 11.2, 38 |
| Warth Lane | 38 MVA | 39.2, 2 | 40.3, 11 |

**What this means.**
- The size of the 2035 problem holds: the same elements, almost the same total hours, the same import.
- The worst elements whose peak sits far above rating (New Beacon Road, Alford) keep their place, with hours within
  about 20%.
- Elements nearer their limit swing by a factor of two to five: Skegness GT1 745 → 135 hours, Great Hale 599 → 1,196,
  Leadenham 37 → 152.
- So an element's hours in a grown year are an order of magnitude, not a figure. Where hours decide between options,
  one weather year is not enough. A planner should read them as "hundreds" or "about a thousand".

**Where the two bases are not comparable** (kept out of the counts above):
- *Wrangle 33/11 kV T3* (135.6% → 1.5%): NGED's 2025 Wrangle series is zero for 99% of the year.
- *Spilsby 33/11 kV (×2)* (229–235% → 59–61%), and the Horncastle–Spilsby line (133.4% → 127.1%, 157 → 397 h, which
  the counts above do include): Spilsby's reactive power is corrupt in 2024 and usable in 2025. Also, in 2025
  Spilsby's node series no longer matches NGED's balance at its cluster (NGED's newer model has a Spilsby–Stickford
  tee). So the engine derives Spilsby's injection there, and **a derived injection is not grown**: on 2025's shape,
  Spilsby's demand stays at its 2025 level instead of × 2.21.
- *The Manor Farm tee lines*: Manor Farm's solar reads zero in 2024 and flows in 2025.
- *Everywhere:* NGED's model edition behind the two years differs (`second-year-2025.md`).

## Run files

- Grown runs (git-ignored), under `apps/pipeline/warehouse/nged-flows/`:
  - `grown-2030-ht.npz`: sha256 `248fc48e644300abc2f4f1dcdbea149cf6b8febaf99641ebb0916cdc03ec4973`
  - `grown-2035-ht.npz`: sha256 `bfe781346f348015251b32a3f7c8175d6a449b9012d759536f5b5f1503b98f0f`
  - `grown-2035-fb.npz`: sha256 `ad49cc795428b89baf3eec6ce92e82fdde22e262c99a9261934d7908be43ecfa`
  - `grown-2030-ee.npz` (section 7): sha256 `2f0ecedd023e4ea4e5109a71964173c60c451d22298f40134aa9e13c91e67e33`
  - `grown-2035-ee.npz` (section 7): sha256 `17cc49b32e2a1640346018a0ab4bc911fd7b7ae0ce44662d317eff42c0a7627c`
  - `grown-2030-fb.npz` (section 7): sha256 `921cf0352c9a55902217185b1811286430bbf5df0f3d32c1d42bb648651f8ba2`
  - `grown-2035-ht-flows-2025.npz` (section 8): sha256 `0905650affb8cac940d16390d0dd4486f456e6c7959d8cc5459eb9e2b9eb6aaf`
    (`run.py 2035 ht flows-2025`, `analyse.py 2035 ht flows-2025`, then `compare_base_year.py`)
  - `grown-2030-ht-warth-ltds.npz` (section 6): sha256 `cbc983fc033ec2665ef4d4ef75661b1de37241ab8b89c324b048dbb3b42f1d20`
  - the three Work 6b branch examples (Grantham split and tied, Thorns Farm): listed with their sha256 in
    `branch-examples.md`
- Code state: the current working tree (Warth Lane restored, vk = |Z|, generators on their feeders), screened inputs,
  each metered primary scaled by the multipliers in each file's `meta.scale`.
- The seam reproduces run B exactly with no scaling (`spec.md`).
- *A record note:* in the grown files made before 13 November's code read (all listed here except section 7's three, which save the scaled series), the saved `bus_q` is the
  unscaled 2024 series; the solve used the scaled one, so every result is right. `run_year` now saves the scaled
  series, so a new file describes what was solved.
- To rerun:
  - `cd packages/optimizer && uv run python ../../docs/reports/grown-year-2026-11-13/run.py <year> <pathway>`
  - then `analyse.py <year> <pathway>`.
  - Section 6: `run.py 2030 ht warth-ltds`, `analyse.py 2030 ht warth-ltds`, then `compare_warth.py`.
