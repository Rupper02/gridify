# Work 8.1: what NGED's DFES 2025 holds for the shape of demand

*13 November 2026. Decided by the guide session overnight, for the owner to confirm. Read-only after the download.
Supported by NGED Open Data.*

**Files.**
- *Fetched* by the pipeline's manual asset `nged_dfes_detail` into `apps/pipeline/warehouse/nged-flows/dfes-2025/`
  (git-ignored, with `NOTICE.txt` and `fetched.json`):
  - DFES Profiles, 316,800 rows;
  - Profile Splits;
  - Annual Scaling Data;
  - Power Projections, 81,772 rows.
- *Not fetched:* the volumes per Electricity Supply Area (ESA, the area a primary substation supplies). Its download
  (`dfes_volume_projections_esa_v2.zip`, 55 MB) answers with a Cloudflare bot challenge (`403`, `cf-mitigated:
  challenge`). That was not bypassed. The portal's datastore copy of the same resource holds an **older edition**: its
  scenarios are Leading the Way, Consumer Transformation, System Transformation, Falling Short and Best View, not the
  2025 four. The local-authority volumes are the 2025 edition; they were read through the portal's API for the five
  councils Bicker Fen spans.
- *Licence:* the portal's `rights` field says "WPD Open Data Licence", the name before WPD became NGED. Used on the
  licence text the owner supplied (NGED Open Data Licence, December 2020); the same naming question as before.

## Profiles: present

**Heat pumps** (unit: MW per heat pump):
- domestic hybrid, air source (air-to-air and air-to-water), ground source, each with and without thermal storage, and
  a "(th)" variant of each;
- non-domestic, per m² of floorspace, by building class;
- large heat pumps for district heat, per unit of capacity.

**EV charge points** (unit: import per unit of installed capacity):
- domestic off-street, domestic on-street, workplace, car parks, destination, en route (local and national), depot,
  eHGV;
- a second set labelled "EV Charge Point (NESO)", with no units given.

**Days:** five representative days: winter peak demand, intermediate cool, intermediate warm, summer peak demand,
summer peak generation.

**Profile types:** unabated and flexed. The flexed variant exists only where the splits give a flexed share.

**Region:** heat-pump and EV profiles come as "All" plus three other areas (Manweb, SSE South, UKPN East). East Midlands
has its own rows only for a few technologies, so it takes "All".

**One defect in the published file.** The `time` column has lost its hour: every value reads `15:00.0` or `45:00.0` (an
hh:mm field saved as mm:ss). The clock is taken from row order within each group of 48 (00:15, 00:45 … 23:45), checked
two ways:
- *the minutes alternate* as row order predicts on 99.6% of "All" rows. The exceptions are a few groups (workplace
  charging on the intermediate days, some storage and generation rows), none of them a profile used here;
- *the shapes land where physics puts them:*
  - domestic demand peaks at 17:45, with its minimum at 03:15;
  - night storage heating peaks at 02:45 and is 0 at 09:15;
  - workplace charging peaks at 09:15;
  - unmanaged home charging peaks at 19:15, and the flexed variant moves it to 01:45 (0 at 17:15);
  - air-source heat pumps peak at 06:45, while the thermal-storage variant runs overnight (peak 03:15, minimum 19:45).

**Winter peak day, per unit:**
- *air-source heat pump:* 2.79 kW at 06:45; 2.35 kW mean over 17:15–19:15; 1.67 kW overnight;
- *ground-source heat pump:* 2.36 kW at 06:45;
- *hybrid heat pump:* 0 on the winter and intermediate-cool days (the boiler carries the cold days);
- *domestic off-street charge point, unmanaged:* 0.209 of capacity at 19:15;
- *domestic off-street charge point, flexed:* 0.206 at 01:45.

**Splits (Holistic Transition).**
- Domestic charge points: 35% unabated, 65% flexed in 2030; 36% and 64% in 2035.
- Public, workplace and depot charge points: 100% unabated.

**Annual scaling ("All").** Domestic heat-pump profiles fall to 0.936 (2030) and 0.882 (2035), which appears to be
efficiency. Non-domestic heat pumps fall to 0.65. Charge points stay at 1.0. Domestic demand falls to 0.896 and 0.843.

## Volumes (2025 edition, Holistic Transition, local authority; baseline → 2030 → 2035)

| Council | Domestic heat pumps (all types) | Domestic off-street charge points (MW) | EVs |
|---|---|---|---|
| East Lindsey | 1,837 → 8,451 → 21,143 | 6.4 → 63.8 → 174.3 | 1,813 → 15,412 → 42,986 |
| North Kesteven | 1,695 → 8,729 → 22,518 | 11.6 → 77.8 → 200.0 | 3,159 → 18,490 → 49,377 |
| Boston | 787 → 5,271 → 13,868 | 3.6 → 45.3 → 121.4 | 1,041 → 8,864 → 24,625 |

South Kesteven and Rutland were read too and are not shown. The 40 values
published as "[c]" (suppressed, chiefly district heating and some baseline thermal-storage counts) are not counted.

For scale: 21,000 air-source heat pumps at the profile's 2.35 kW is about 49 MW on a winter evening. 174 MW of home
chargers at the unmanaged profile's 0.18 is about 31 MW, less for the flexed share. Both are council-wide totals, and
East Lindsey reaches beyond Bicker Fen.

## NGED's own Power Projections already move the peak

Per ESA, scenario and year, the Power Projections give the year's peak half-hour, its MW and its season. For Bicker
Fen's 21 ESAs under Holistic Transition, the peaks below are all labelled winter, except where noted:
- *Baseline and 2025:* the winter peak falls at 17:45 or 18:15 everywhere.
- *2030:* it falls at **09:45** (7 ESAs), 12:15–13:15 (12) or 18:15 (2: Ingoldmells, Wrangle).
- *2035:* it falls at 09:45 or 13:15 everywhere.

| ESA | Baseline | 2030 | 2035 |
|---|---|---|---|
| Alford | 5.75 MW at 17:45 | 8.22 at 09:45 | 13.85 at 09:45 |
| Horncastle | 11.68 at 18:15 | 15.62 at 09:45 | 23.15 at 09:45 |
| New Beacon Road | 15.27 at 17:45 | 23.28 at 13:15 | 40.44 at 13:15 |
| Warth Lane | 18.86 at 17:45 | 24.73 at 09:45 | 37.73 at 09:45 |
| Sleaford 11 kV | 13.97 at 18:15 | 19.99 at 13:15 | 31.59 at 09:45 |

The grown years take each ESA's peak MW from this table but keep 2024's shape, so their peaks stay in the evening.
NGED's own projection says the peak moves to the morning or midday. It is NGED's figure, not a finding of this study,
and it is the plainest evidence that uniform scaling puts the hours in the wrong place.

## The check 8.2 would rest on cannot be run yet

For each ESA, the check needs that ESA's 2025-edition volumes of heat pumps and charge points. Those sit only in the
challenged ZIP. Local-authority volumes cannot stand in: ESAs do not nest in councils, and apportioning them would be a
guess the check is meant to test.

**What unblocks it:** one download of `dfes_volume_projections_esa_v2.zip` in a browser, by the owner (a person passes
the challenge), saved into `warehouse/nged-flows/dfes-2025/`. Everything else is in place.

**Proposed tolerance, for when it can run** (from the evidence above, fixed before any run):
- The summed pieces at the projection's own half-hour within **±10% or ±1 MW, whichever is larger**, at 15 of the 21
  ESAs.
- The peak at the same time of day (morning, midday or evening) at the same 15.
- Why 10%: this decomposition leaves out NGED's other building blocks (resistive heating, air conditioning,
  non-domestic growth, the domestic scaling), each a few percent.
- Why 15 of 21: two ESAs' early-year peaks fall in intermediate cool, not winter (Easton, Ruskington, until about
  2028), and a few will hold sites the
  decomposition does not cover.

## Work 8.1b: can the Power Projections stand in for the volumes? No

*Read-only. Asked by the guide: a route that needs no volumes, using NGED's own projected day shapes.*

**1. What the Power Projections hold:** one row per ESA, scenario and year: the year's peak half-hour, its time, its MW
and the season it falls in (81,772 rows, every group exactly one row). *Corrected in Work 9:* this first read "one row
per ESA, scenario, year and season". The season is a label on the annual peak (80,182 winter, 1,480 intermediate cool,
110 intermediate warm), not a peak per season.
- Seasons that occur: Winter, Intermediate Cool, Intermediate Warm. No summer.
- Years: baseline, 2025–2040, 2045, 2050. Four scenarios.
- There is no day of half-hours, so a time-varying ratio cannot be built from this file. **The route is closed.**
- NGED's definition of the seasons is in its methodology, not in the file. Those documents refused automated requests,
  so it is not read here.

**2. Whether its clock can be trusted.**
- *No hour-loss defect here.* This file carries full times (`09:45:00`, `18:15:00`, …). They are taken as published,
  not rebuilt from row order as the profiles file's were.
- *The times behave coherently across scenarios:*
  - every baseline winter peak, across the 1,005 NGED ESAs whose baseline peak is labelled winter, in every scenario, falls in the
    evening;
  - for Bicker Fen's 21 ESAs in 2035, the low-electrification Counterfactual keeps 17 in the evening;
  - Holistic Transition keeps none (10 morning, 11 midday);
  - Electric Engagement keeps 1;
  - Hydrogen Evolution keeps 3 (16 morning).
  - NGED-wide, 2035 evening peaks number 802 under Counterfactual against 26 under Holistic Transition.

  A scrambled or shifted clock would not order the scenarios by electrification like this. The headline stands, as
  NGED's own figure.

**3. Is a midday winter peak plausible on NGED's own account?** The file gives no breakdown by technology, so the 13:15
peak cannot be decomposed without the volumes. The published profiles show which pieces can move the peak:
- *Pieces that lower the evening:*
  - the flexed domestic-demand profile is exactly 0 at 18:15 (its peak is at 23:15), and Holistic Transition puts 5%
    (2030) and 10% (2035) of domestic customers on it;
  - flexed home charging is 0.011 of capacity at 18:15 against 0.203 unabated, and Holistic Transition puts 64–65% of
    home charge points on it;
  - the domestic annual scaling falls to 0.843 by 2035.
- *Pieces that raise the morning and midday* (all unabated; heat pumps are never flexed in any scenario):
  - non-domestic demand and heating peak between 09:15 and 12:45;
  - workplace, public and depot charging peak at 09:15;
  - air-source heat pumps peak at 06:45 and stay high through the day (2.15 kW at 13:15 against 2.35 at 18:15).

**So:** much of the move away from the evening is NGED's assumption that home charging, and a tenth of domestic
demand, is managed out of the evening. That is a scenario assumption, and any year shaped by these projections inherits
it. Under Holistic Transition the evening peak is assumed to be managed away. How much of the move comes from
flexibility and how much from daytime growth cannot be split without the volumes.

**What waits on the owner:** 8.2 and 8.3, on the one browser download of `dfes_volume_projections_esa_v2.zip`. An
unabated run, the value the scenario places on flexibility, needs the same volumes.

*Update, 13 November: the owner downloaded the ZIP (the 2025 edition), and 8.2's gate was run as fixed above. It
**failed**: 8 of 21 ESAs, with the rebuild short at 18 of the 19 tested. NGED's base demand cannot be reproduced
without its unpublished assignment of each ESA to a base-demand cluster. No shaped year was built, and 8.3 does not
follow. See `docs/reports/dfes-shape-2026-11-13/result.md`.*
