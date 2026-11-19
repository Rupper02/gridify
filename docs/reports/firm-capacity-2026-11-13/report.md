# Each substation against its own peak and firm capacity, 2026 to 2035

*13 November 2026. Work 3, decided by the guide session overnight, for the owner to confirm. A report, not a product
feature: nothing in the engine, API or planner changes. Every figure comes from `analyse.py` in this folder; the full
table is `substations.csv`. Supported by NGED Open Data.*

**Terms.**
- **Firm capacity:** what a substation can carry after losing one transformer, as NGED publishes it in LTDS Table 3.
- **Own maximum:** the substation's own peak demand in the LTDS. Not its share at the moment the whole Grid Supply Point
  peaks, which is what the engine's winter-peak case uses.
- **Primary:** a 33/11 kV substation. **BSP**, Bulk Supply Point: a 132/33 kV substation.
- **Pathway:** a DFES scenario, NGED's Distribution Future Energy Scenarios. **MVA:** apparent power, which is what a
  transformer's rating limits.
- **Run B:** the measured-year report's screened 2024 run: NGED's 2024 half-hourly flows through the engine, with the
  reactive-power screen, on the current engine (Warth Lane restored, transformer vk fixed).

## Where the margin is thinnest, and when

**First, the answer depends on the growth source at exactly one substation: Warth Lane.**
- *Under the DFES ratios the engine uses,* Warth Lane never exceeds its 38 MVA firm capacity by 2035.
- *Under NGED's own LTDS forecast,* it crosses in 2027 and reaches 85 MVA in 2030, about 3.5 times the DFES path. That
  is most likely one large new connection that the DFES ratios do not carry.
- *Run through a year:* the grown-year report's section 6 scales Warth Lane's 2024 series to that forecast. Its three
  transformers, two 33 kV circuits from Skegness and both Skegness 132/33 kV transformers then go over their rating,
  Warth Lane's for most of the year.
- *So:* the engine's choice of DFES ratios over the LTDS forecast is what keeps Warth Lane off the top of this table.
  Which source the plan years should use is the owner's decision; nothing in the engine changes here.

Every substation where the two sources differ by more than 20% in 2030 (24 assessed):

| Substation | Own maximum today (MVA) | 2030, DFES Holistic Transition (MVA) | 2030, NGED's LTDS forecast (MVA) | DFES ÷ LTDS | Firm (MVA) |
|---|---|---|---|---|---|
| Warth Lane | 19.4 | 24.1 | 85.0 | 0.28 | 38 |
| Great Hale | 3.9 | 6.0 | 4.7 | 1.28 | 14 |

Everywhere else the two agree within 20% by 2030.

Rows are sorted by the first year each substation's own maximum exceeds its firm capacity under the Standard pathway
(Holistic Transition). "Now" means the LTDS's current maximum already does.

| Substation | Firm MVA | Installed MVA | Own maximum today (MVA) | First year above firm, by pathway: Holistic / Electric Engagement / Hydrogen / Falling Behind | NGED's own LTDS forecast: first year above firm | 2030 Holistic / NGED (MVA) | 2024 NGED metered peak (MVA), hours above firm | 2024 run B peak through the transformers (MVA) | Generation behind (MW) |
|---|---|---|---|---|---|---|---|---|---|
| New Beacon Road | 14 | 24 | 14.4 | now / now / now / now | 2026 | 20.5 / 18.9 | 14.4 (15 Jan 18:00), 9 h | 14.3 | 0.1 |
| Alford | 6 | 12 | 6.2 | now / now / now / now | 2026 | 8.3 / 7.3 | 6.3 (20 Nov 17:00), 3.5 h | 6.6 | 1.0 |
| Spilsby ¹ | 6 | 12 | 6.9 | now / now / now / now | 2026 | 9.4 / 8.5 | 6.6 from MW alone, 9 h (a lower bound) | 11.2 ¹ | 2.0 |
| Sleaford 11 kV | 23 | 24 | 13.7 | 2033 / 2033 / 2034 / not by 2035 | not by 2030 | 18.3 / 16.3 | 14.0, 0 h | 13.8 | 0.2 |
| **Sleaford BSP** | 90 | 90 | 62.8 | 2033 / 2033 / 2034 / not by 2035 | not by 2030 | 76.1 / 70.4 | (group totals, see note ²) | 54.8, 0 h | 16.1 at the busbar, 96.7 on its feeders |
| Chapel St Leonards | 9.5 | 12 | 6.2 | 2034 / 2034 / 2035 / not by 2035 | not by 2030 | 7.4 / 6.6 | 6.0, 0 h | 6.1 | 0.2 |
| Tattershall | 17 | 24 | 11.9 | 2034 / 2033 / 2034 / not by 2035 | not by 2030 | 14.1 / 13.2 | 11.8, 0 h | 12.1 | 0.6 |
| **Skegness BSP** | 90 | 90 | 54.6 | 2034 / 2034 / 2035 / not by 2035 | not by 2030 | 67.4 / 62.2 | (group totals ²) | 68.6, 0 h | 12.0 at its busbars, 38.0 on its feeders |
| Warth Lane ³ | 38 | 36 | 19.4 | not by 2035 under any pathway (Holistic reaches 36.8 in 2035) | **2027** | 24.1 / **85.0** | 19.7, 0 h | 19.9 | 5.8 |

Not above firm capacity by 2035 under any pathway (table in `substations.csv`):
- primaries: Billingborough (T1, T2), Cranwell (T1, T2), Easton, Great Hale, Ingoldmells, Leadenham (T1, T2), Market
  Overton, Ruskington, Skillington, Trusthorpe;
- Grantham BSP;
- the Grantham North railway feeder.

**No firm capacity published** (LTDS Table 3 gives 0), so these cannot be assessed: Horncastle (T1, T2), Metheringham
(T2), Woodhall Spa, Wrangle (T2), and the Mill Farm battery's own import.

¹ **Spilsby:** NGED's reactive power is unreliable (measured-year report, 4.1). The 2024 figure uses MW alone, a lower
  bound; even that exceeds firm capacity for 9 hours. Run B's 11.2 MVA through the transformers still carries some of the
  bad reactive power and is not a finding.

² **The BSP 2024 figures:** NGED's metered BSP columns are group totals, not the transformers' load, so the 2024 figure
  for a BSP is run B's flow through its two 132/33 kV units.

³ **Warth Lane:**
- *Restored overnight:* its LTDS row is marked Removed (measured-year report, 4.2).
- *The two forecasts disagree by a factor of 3.5 by 2030.* NGED's own LTDS forecast takes it from 18.6 MW today to
  81.6 MW in 2030, against a 38 MVA firm capacity. The DFES ratios the engine uses reach 23 MW in 2030 and 35 MW in 2035.
  The LTDS figure reads like a large new connection at Warth Lane that the DFES projection does not carry.
- *Its sites:* its installed capacity (3 × 12 MVA) sits below its firm capacity.

Also outside the table:
- **Wrangle (T2)** carries the caveats already found: NGED's 2024 series peaks at twice its LTDS maximum, and reads 0
  from 1 August. It has no published firm capacity.
- **The Middlemarsh row** (2.2 MW, firm 106 MVA) is the offshore wind farm's own station supply, not a substation's
  customers, and is left out.

**First year above installed capacity** (all units in service), Holistic / Electric Engagement / Hydrogen; never under
Falling Behind by 2035:

| Substation | Holistic | Electric Engagement | Hydrogen |
|---|---|---|---|
| New Beacon Road | 2032 | 2032 | 2033 |
| Great Hale (7.5 MVA installed, below its 14 MVA firm) | 2032 | 2032 | 2032 |
| Spilsby | 2033 | 2033 | 2033 |
| Sleaford 11 kV | 2033 | 2033 | 2034 |
| Sleaford BSP | 2033 | 2033 | 2034 |
| Alford | 2034 | 2034 | 2034 |
| Warth Lane | 2035 | 2035 | — |

## How the figures are formed

- **Demand.** Each LTDS Table 3 row's "Current Year Max Demand" (MW), converted to MVA with the row's own power factor
  (0.95 lagging where the LTDS leaves it blank, as the engine does).
  - *Firm capacity* is read as MVA; the LTDS does not state the unit (README register).
  - *Split substations:* where a substation appears as two rows fed from different BSPs (Leadenham, Billingborough,
    Cranwell), each row is assessed against its own published firm capacity.
- **A BSP's own maximum** is the sum of its two GT rows, as the engine reads it. Its firm capacity is as its rows
  publish it: 90 MVA at Sleaford and Skegness (one 45 MVA unit's 90 MVA emergency rating), 68 at Grantham.
- **Growth** uses the engine's own DFES ratios (`network.per_load_growth`), applied to the substation's own maximum, for
  every plan year 2026 to 2035 and every pathway.
  - *A BSP* has no DFES area, so its growth is its primaries' ratios weighted by their own maxima.
  - *NGED's own forecast* (LTDS Table 3, Forecast Years 1 to 5 = 2026 to 2030) is shown beside, where bundled.
- **Installed capacity** is the sum of the LTDS ratings of the substation's transformers. Where firm capacity exceeds it
  (Great Hale 14 against 7.5, Easton 18 against 12, Market Overton 14 against 7.5, Skillington 14 against 12, Warth Lane
  38 against 36), NGED's firm figure likely counts transfer capacity over the 11 kV network. It is shown as published.
- **2024.** NGED's metered node series for the row's node, as MVA (apparent power).
  - *The reactive screen of the measured-year report applies:* a half-hour whose MVAr is implausible or suspect takes
    MW × tan(the LTDS power-factor angle).
  - *Two figures are shown, and they differ slightly.* "Hours above firm" counts metered half-hours. "Run B peak" is the
    flow through the substation's transformers in the screened 2024 run, which adds the transformers' own reactive draw.
    New Beacon Road is above firm for 9 hours by the metered series and 5 by run B; Alford for 3.5 and 9.
  - *Half-substations:* run B's figure is for the whole site.
- **Net against gross.** The LTDS maximum is demand; the metered 2024 series is net of any generation behind the
  substation. The last column gives the generation the fleet places there now.
  - *Comparable:* where it is near 0 (New Beacon Road, Sleaford 11 kV, Chapel St Leonards, Market Overton, Cranwell).
  - *Not comparable:* where it is large (Warth Lane 5.8 MW, Leadenham 3.6, Ruskington 2.1, Spilsby 2.0, Ingoldmells
    1.8, Trusthorpe 1.6, Easton 1.4), the metered peak understates the demand.
  - *The BSPs:* Sleaford's group has 113 MW of solar behind it, mostly on its own feeders, so the BSP's 2024 flow is no
    guide to its demand.

## What this does not tell you

- **No transfers between substations and no switching.** A DNO meets a firm-capacity shortfall first by transferring
  load to a neighbour over the 11 kV or 33 kV network. None of that is modelled. A substation above firm capacity here
  may be covered by transfers today.
- **No flexibility or demand response,** no generation credit (the engine credits none), and no reinforcement NGED
  already plans. LTDS Table 7, the planned works, has no rows for this Grid Supply Point, so none is named.
- **Firm capacity as published:** its unit is read as MVA, and where it exceeds installed capacity it is shown as is.
- **One growth source.** The engine's DFES ratios per primary. NGED's own five-year forecast is shown beside it, and they
  disagree most at Warth Lane.
- **Demand only.** Firm capacity against reverse power flow from generation, the other direction, is not assessed.
- **Not a power flow.** These are substation totals against ratings. Line loading and voltage are the planning cases'
  job.
