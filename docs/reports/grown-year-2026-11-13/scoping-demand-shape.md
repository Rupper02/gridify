# Scoping note: changing the shape of demand, not only its size

*13 November 2026. Decided by the guide session overnight, for the owner to confirm. Read-only: nothing is built and no
dataset was downloaded. Facts marked **read** were read from NGED's Connected Data portal API (metadata and its data
preview) on this date; **not verified** means search results only. Supported by NGED Open Data.*

**The question.** A grown year multiplies each primary's 2024 half-hours by one number, the DFES winter-peak ratio. That
grows the size of demand, not its shape. Heat pumps add load on cold mornings and evenings, and home EV charging adds
it in the evening and overnight, so the hours above a rating could move to times 2024 never stressed. What would it
take to add them with their own shapes?

## What exists

**NGED's DFES dataset** (portal id `dfes`; rights: "WPD Open Data Licence", classification Open, **read**; modified
10 September 2026; the 2025 edition by its workbook's name). It has more than the winter-peak power the engine uses:

| Resource | What it holds (**read** unless marked) | Use |
|---|---|---|
| DFES Volume Projections by Electricity Supply Area (ZIP, 55 MB) | Volumes per ESA, the area a primary supplies. Its column list could not be previewed (**not verified**); the local-authority version has the breakdown below | How many units each primary gains |
| DFES Volume Projections by Local Authority (124 MB) | Domestic heat pumps by type (hybrid, air source, ground source, each with or without thermal storage); non-domestic heat pumps as heated floorspace; EVs by vehicle type; EV charge points as MW by type (domestic off-street and on-street, workplace, car parks, destination, en route, depot); four scenarios; a baseline, each year 2025–2040, 2045, 2050 | The same, by council area |
| DFES Profiles (40.5 MB) | Half-hourly per-unit profiles: unabated and flexed, by technology and sub-technology, on five representative days (winter peak demand, summer peak demand, intermediate cool, intermediate warm, summer peak generation). Units per installed capacity, per dwelling or per m² | The shapes |
| DFES Profile Splits | The share of each technology on the unabated or the flexed profile, by scenario and year | How much is managed |
| DFES Annual Scaling Data | A factor per profile, technology, year and scenario, per licence area (East Midlands among them) | Scales the per-unit profiles |
| DFES Power Projections | Per ESA, year, scenario and season: the peak half-hour and its MW | What the engine uses today; the check for any new build |

**Settled in Work 8.1 (`data-note-dfes-shape.md`):** the full file has both. As first written: **the gap:** the portal's preview of DFES Profiles holds 6,250 rows and 26 technology and sub-technology pairs (**read**:
domestic, non-domestic building classes, air conditioning, car-park charge points, generation types and others). It has
**no heat-pump or home EV-charging profile**, although the splits and scaling data list both. The full 40.5 MB file
very likely holds them; one download would settle it.

**Published profiles that could be cited as a cross-check, not as the source:**
- *Electric Nation* (NGED's home EV smart-charging trial, about 700 cars): on the same portal under NGED's open licence;
  per charger and per session, 15- and 3-minute data. Building an after-diversity shape from it is work of its own.
- *Electrification of Heat Demonstration* (Energy Systems Catapult, UK Data Service): per-home heat-pump data; the
  30-minute series is listed as open under the Open Government Licence (**not verified**: catalogue entries disagree on
  which study number holds what).
- Not suitable: Elexon's settlement profile classes, which have no heat-pump or EV class, and whose detailed data is
  licensed.
- NGED's own after-diversity maximum demands for heat-pump homes sit in its design standard SD5A (**not verified**: the
  table was not seen). The DFES 2025 methodology PDF could not be read (the site refused automated requests).

## What a first version would assume

1. *Split the growth.* For each primary, take the DFES 2024 baseline and target-year volumes of heat pumps and home EV
   charging. Grow the 2024 series by the DFES ratio **without** those technologies, and add them back with their own
   shape. Without the split, they would be counted twice, because the winter-peak ratio already contains them.
2. *Add the shape.* Added MW in each half-hour = (units gained) × per-unit profile × annual scaling, combined over the
   flexed and unabated split.
3. *Map the representative days onto 2024.* Each 2024 day takes the representative day of its season (the engine's four
   seasons are the DFES Power Projections' seasons), with the winter-peak day for the coldest days. This is the engine's
   own planning assumption; the register would say so.
4. *Check it.* At each primary, the new year's winter-peak half-hour should land near DFES Power Projections' MW for that
   ESA, year and scenario. A large miss means the split or the mapping is wrong, and the version is not used.

## What it could not claim

- *Weather.* Five representative days are not a temperature response. A cold spell's depth and length, which set a
  heat-pump peak, would come from the mapping, not from data.
- *Diversity at small primaries.* The profiles are per unit, averaged over many customers. At a primary with a few
  hundred heat pumps, the real peak is sharper.
- *Behaviour.* The flexed share is a scenario assumption, so a "flexed" evening is a policy outcome, not a measurement.
- *The hours.* They would still be indicative: a better estimate of *when*, not a measurement of it.
- *Location below the primary.* ESA totals only; nothing about which feeder.

## To go further (owner's decision, since it means downloads)

- The DFES Profiles CSV (40.5 MB), to confirm it holds heat-pump and home EV profiles.
- The ESA volumes ZIP (55 MB), to confirm Bicker Fen's primaries appear, under the names the engine already maps.
- The DFES 2025 methodology PDF, read in a browser: how NGED combines these to reach its power projections, so the split
  in step 1 follows NGED's own method.
- The licence. The portal labels the DFES "WPD Open Data Licence", the name before the rebrand. Confirm it is the NGED
  Open Data Licence the owner already holds.
