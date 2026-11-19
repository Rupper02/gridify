# Shaping a year's demand from NGED's DFES: specification, fixed before any result

*13 November 2026. Decided by the guide session under the owner's delegation, for the owner to confirm. Local only.
Supported by NGED Open Data.*

## The question

The grown years keep the 2024 or 2025 shape and scale its size. NGED's own Power Projections say that under Holistic
Transition, Bicker Fen's winter peak moves from the evening to 09:45 or 13:15 by 2035 (data note, 8.1b). Can NGED's
published pieces be added onto the measured year, so that a year's hours fall where NGED puts them? The pieces are:
- volumes per Electricity Supply Area (ESA);
- per-unit profiles on five representative days;
- splits between unabated and flexed;
- annual scaling.

A shaped year is built only if the pieces reproduce NGED's own projection first.

## Data, and the edition

- **Volumes:** `dfes_volume_projections_ESA.csv`, inside the owner's browser download
  `dfes_volume_projections_esa_v2.zip` (resource `95c1a397-11f9-42dd-a1a7-401802de4f62`, file dated 22 January 2025).
  Read in chunks and subset to Bicker Fen's 21 ESAs (`subset_volumes.py`), written beside the download as
  `dfes_volumes_bicker_fen.csv` and `volumes_edition.json`.
- **The edition is 2025's.** Its four scenarios are Counterfactual, Electric Engagement, Holistic Transition and
  Hydrogen Evolution (the 2025 four, not the older edition the portal's datastore holds). It runs baseline, 2025–2040,
  2045 and 2050, the years of the Power Projections. It has 8,469,896 rows over 1,082 ESAs, and every one of Bicker
  Fen's 21 is present by its exact name.
- **The other pieces:** the profiles, splits, annual scaling and Power Projections already fetched (Work 8.1). The clock
  of the profiles is rebuilt from row order, as checked there.

## The reconstruction, per ESA, for Holistic Transition, year Y

    P_Y(t) = B(t) + Σ_i ΔV_i(Y) · s_i(Y) · [ u_i(Y) · p_i,unabated(t) + f_i(Y) · p_i,flexed(t) ]

- **t:** the 48 half-hours of the representative day matching the season the projection labels that ESA's peak with
  (Winter → "Winter peak demand"; Intermediate Cool → "Intermediate cool peak demand").
- **ΔV_i(Y) = V_i(Y) − V_i(2025):** the growth in the volume of demand piece i since 2025. Cumulative counts, MW and
  floorspace as published; the new-dwellings and new-floorspace rows as published. "[c]" (suppressed) counts as
  unknown and is left out, and the count of such values is reported.
- **The demand pieces:**
  - domestic new dwellings;
  - non-domestic new floorspace by class;
  - heat pumps (every domestic type, non-domestic floorspace by class, large-scale MW);
  - EV charge points (NGED's own set, not the "(NESO)" set, whose units are not given);
  - resistive electric heating;
  - air conditioning;
  - hydrogen electrolysis;
  - agriculture;
  - rail.
  Generation and storage are left out: the Power Projections are a demand peak.
- **Profiles:** region East Midlands where the technology has its own rows, else "All". Each profile's units, as
  published, fix what it multiplies: per unit of installed capacity, per count, or per m².
- **s_i(Y):** the annual scaling for that technology and profile type ("All" locations).
- **u_i(Y), f_i(Y):** the splits; a piece with no split row is all unabated.
- **B(t), the base:** the ESA's primary's measured node series in NGED's 2025 flows (Bicker Fen), on the day of its
  2025 maximum within the same season, normalised to its maximum and multiplied by the projection's own 2025 peak MW.
  The level is NGED's, so the gate tests the increments, not the meters; the shape is measured.

**Left out, stated:** the domestic annual scaling applied to existing demand, existing non-domestic growth, and NGED's
base-demand cluster profiles (the profiles file has 200-odd "Demand" clusters, W1,S0,… and no published assignment of
an ESA to one). These are why the tolerance is 10%.

## The gate, fixed in the data note before the volumes were available

For **2035, Holistic Transition**, at each of the 21 ESAs:
1. **Size:** P_2035 at the projection's own half-hour within ±10% or ±1 MW of the projection's MW, whichever is larger.
2. **Time:** the half-hour where P_2035 is greatest falls in the same part of day as the projection's. The parts are
   night 23:00–05:00, morning 05:00–11:00, midday 11:00–16:00, evening 16:00–23:00.

The gate passes if **both** hold at **15 or more of the 21**. An ESA that cannot be tested (no metered series for its
primary in 2025, or a series that is zero on most of the year, as Wrangle's is) counts as a failure. 2030 is reported
beside it and is not part of the gate.

**If it fails:** stop, report what is missing, and build no shaped year.

**If it passes:** one shaped run, 2035 Holistic Transition, on Bicker Fen's 2025 flows.
- Each metered primary's series is the measured 2025 series plus that ESA's increments
  Σ ΔV_i(2035) · s_i · (u·p_unabated + f·p_flexed) at every half-hour. Each calendar day takes its season's
  representative day: Winter December–February, Intermediate Cool March, April and November, Intermediate Warm May,
  September and October, Summer June–August ("Summer peak demand").
- The base is the measured series, **not** rescaled: unlike the grown years, the base does not grow uniformly.
- **The increments are peak-day profiles applied to every day of their season,** so its hour counts lean high: an
  ordinary winter day gets the peak day's heat-pump kW. It is a shaped bound, not a forecast.
- Reactive power: each increment at the LTDS power factor of its primary, as the screen's substitution uses.
- The run is solved with the engine's own `run_year`, with the increments passed as an additive series per anchor
  bus. That is the one engine change, and the shaped run cannot exist without it.
- The run gets its own catalogue entry and its own limits text, and its labels are judged on 2025 screened, as every
  run's are.

## Addendum, after the gate failed: a sensitivity at the eight areas that passed (fixed before the run)

*Decided by the guide, for the owner to confirm.* The gate failed network-wide (`result.md`), so no shaped year is
offered. At eight areas the reconstruction passed the gate's test in both size and part of day: Alford, Cranwell,
Easton, Ingoldmells, New Beacon Road (Grantham), Skillington, Tattershall and Trusthorpe. For those eight only, the
question is what the shape does to **their own 33/11 kV transformers' hours**.

- **This is a sensitivity, not a shaped year.** The run is 2035 Holistic Transition on **2024's flows**, so it compares
  directly with the catalogued `grown-2035-ht`. Every other metered primary takes that run's uniform multiplier.
- **At the eight:** the measured 2024 series, not rescaled (multiplier 1), plus the area's increments
  Σ ΔV_i(2035 − 2025) · s_i · (u·p_unabated + f·p_flexed). Everything else is as fixed above:
  - the pieces and the profile regions;
  - the representative day by season month, applied to every day of its season;
  - the half-hour clock (NGED stamps the end of each half-hour);
  - reactive power for each increment at the power factor of that area's LTDS demand.
- **Inherited:** the scenario's assumption that home charging is managed out of the evening.
- **Reported, shaped against uniform, for each of the eight:**
  - its own 33/11 kV transformers' peak;
  - their hours above rating, with the months and hours of day those hours fall in;
  - the area's hours above firm capacity.

  Also: for how many of the eight the gate found the peak in the same part of day as NGED's (all eight, by
  construction of "passed").
- **Not reported:** network-wide counts, 132 kV or 33 kV circuits, BSP transformers, the supply point's exchange, and
  any element fed by a substation outside the eight. Those mix shaped and unshaped demand.
- **The engine is unchanged.** The increments are added to the measured year in the report script, before
  `run_year`. The run is not added to the planner's catalogue.
- **One question for the summary:** does keeping 2024's shape overstate or understate these transformers' hours above
  rating, and by roughly what factor?
