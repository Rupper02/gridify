# Specification: a grown year

*13 November 2026. Decided by the guide session overnight, for the owner to confirm. Written before any run. A report,
not a product feature: nothing in the API or planner changes.*

**The question.** The two planning cases answer "is a limit breached at the GSP's extremes". The measured year answered
"what happened in 2024". In between: if 2024's half-hourly shape were carried at a future year's demand, which lines and
transformers would run over their rating, for how many hours, and when? And does the snapshot basis see the same
elements?

## Method

**Years and pathway.**
- 2030 and 2035 under Holistic Transition, the engine's default pathway.
- Then, as the low case, 2035 under Falling Behind.
- Each run is a full year in time order, one at a time, about 16 minutes.

**Demand.**
- Each metered primary's 2024 MW and MVAr series, after the reactive screen as in run B, is multiplied by the engine's
  own growth ratio for that primary and year. The ratio is `network.per_load_growth`, the same one the plan years use,
  weighted by the LTDS own maximum where a node carries several loads. So the grown year and the plan year share one
  growth source.
- The ratio is relative to the DFES base year 2025, the LTDS edition's current year, and is applied to the 2024
  series: the one-year offset is taken as zero.
- Warth Lane is grown the same way, on its own DFES area.
- The seam: `timeseries.run_year(..., scale={anchor bus: multiplier})`. The default (`None`) reproduces the measured
  year exactly; the check is below.

**Everything else as run B.**
- The derived injections are unchanged from 2024: the generators' own feeders, Middlemarsh, the BSP busbar balances.
- The railway is held at 0.
- Line ratings follow NGED's season for the month; the tap changers settle each half-hour.
- The network is the current engine's: Warth Lane restored, transformer vk = |Z|. The measured year's inputs sit on
  their own anchor buses, so the generator placement of Work 2 does not enter the grown run.

**Ash Farm** (48.38 MW of solar, connected July 2025) did not exist in 2024.
- *Its output:* the per-unit 2024 shape of Gorse Lane's feeder (derived from NGED's branch flows) times 48.38 MW.
  Gorse Lane is the largest solar site with a clean series: 38.4 MW, and its only runs of identical values are night-time
  zeros. Its two feeders peak at 77% of their rating; its output peaks at 1.055 of its 38.39 MW (corrected overnight:
  an earlier version read the 77% as the output's).
- *Where it enters:* it sits at Bicker Fen 132 kV, the slack bus, where an injection changes only the exchange with the
  transmission system, not any flow inside the network. It is therefore added to the GSP export in the analysis,
  exactly equivalent to injecting it there.

**No new connections** beyond what exists today: this is main, grown.

## What is reported, per year

1. **Per line and transformer:**
   - hours at or above 80%, 90% and above 100%, and the peak and when;
   - the months and hours of day the exceedances fall in;
   - step 1's labels: flow agrees, differs with its offset, input, reactive input unreliable.
2. **Voltage:** hours outside the statutory band per busbar.
3. **Beside each element, the same plan year's planning cases** (winter peak, summer minimum): is every planning-case
   breach also an overload in the grown year, and for how many hours? Does the grown year show overloads the planning
   cases miss?
4. **Firm capacity:** hours above firm per substation, beside Work 3's first-year table.
5. **The GSP:** its export and import through the year against its limits, with Ash Farm added.

## Limits, stated up front

- **The 2024 shape is kept.** Electrification changes the shape as well as the size: heat pumps peak on cold evenings,
  vehicles charge at night.
  - *What follows what:* the size of each substation's peak follows the engine's growth source, the DFES winter-peak
    ratio. When and for how long it is exceeded follows 2024's shape.
  - *So:* the hour counts are indicative, not a bound in either direction. A sharper peak means fewer hours above a
    threshold than scaled; load at times quiet in 2024 means new ones.
  - This is a uniform-growth year, not a forecast. (Corrected overnight: an earlier version said the counts were a lower
    bound.)
- **The metered series are net of embedded generation,** so growth also scales the generation behind seven primaries:
  Warth Lane 5.8 MW, Leadenham 3.6, Ruskington 2.1, Spilsby 2.0, Ingoldmells 1.8, Trusthorpe 1.6 and Easton 1.4
  (Work 3). Their grown peaks are understated, and their grown export overstated.
- **One weather year.** Generation is 2024's, with no growth in solar or wind.
- **Step 1's model differences remain:** the 33 kV tie mismatch, and its labels.
- **No outages.**

## Check before the runs

`run_year` with `scale=None`, and with every multiplier at 1.0, must reproduce run B: 0.0 difference on the first
48 half-hours.
