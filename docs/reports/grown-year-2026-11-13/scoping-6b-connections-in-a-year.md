# Scoping note: a branch's connections in a grown year

*13 November 2026. Decided by the guide session overnight, for the owner to confirm. Written read-only, before the
build. The guide accepted it with the decisions in "As decided" at the end; the build and its two examples are in
`branch-examples.md`.*

**The question.** A grown year shows where main breaks. The planner's question is what a branch adds: put a project on
a branch, and see how many more hours each line and transformer spends over its rating in 2030 or 2035.

## How the plan years apply a connection today

- **The contract** (`types.Connection`): `bus_id`, `technology`, `rating_mw` (export), `import_mw` (charging or demand;
  `None` means the same as the rating), `control` (a fixed power factor, voltage control, or `None` for unity), and
  `year`.
- **In service:** `years.in_service` keeps every connection with `c.year <= year`. A connection is in from its year on.
- **Injection** (`network.inject_connection`):
  - unity or fixed power factor: an `sgen` at its bus;
  - voltage control: a `gen` holding a setpoint.
- **Dispatch:** each of the two study cases scales it by `config.GENERATION_FACTORS`:
  - *winter peak:* solar and wind at 0; batteries, hybrids, demand and electrolysers importing at `import_mw`;
  - *summer minimum:* everything at full export; demand at 50% of `import_mw`.

## What a year needs instead: a value every half-hour

The seam exists. `network.solve_snapshot` already takes each `sgen`'s P and Q per half-hour, and `run_year` passes it an
empty series today. The build:
1. inject the branch's connections, in service by that year, as `sgen`s;
2. give each one a 2024 per-unit shape × its rating;
3. pass those as `sgen_p` (and Q from its power factor).

**One limit, stated.** `solve_snapshot` refuses voltage-controlled units (`net.gen`). A voltage-controlled connection
would run at unity in the year view, and the view says so on that connection. Teaching the snapshot to hold a `gen`'s
setpoint is a separate step.

**Shapes, one per technology, all from NGED's 2024 flows** (same weather year as the base, so they line up in time):

| Technology | 2024 shape | Why, and its weakness |
|---|---|---|
| Solar | Gorse Lane's feeder (38.4 MW), per unit of rating | Already used for Ash Farm. Its only runs of identical values are night-time zeros. Its output peaks at 1.055 of 38.39 MW (124 half-hours above 1), so it is capped at 1 for a new connection. |
| Offshore wind | The two Skegness–Middlemarsh 132 kV circuits, summed, per unit of their year maximum | About 179 MW at peak (89.5 MW on each circuit). The flow is net of anything else at Middlemarsh. Check its flags before use, as Gorse Lane's were checked. |
| Onshore wind | Bambers Farm (9.1 MW), if its series is clean | The only named onshore site of any size. Its connection is behind an 11 kV site transformer that is not modelled. If its series is flagged, fall back to the offshore shape and say so. |
| Battery | A fixed rule, not a shape | Charge at `import_mw` 11:00–14:00 and export at `rating_mw` 16:30–19:30, every day. This assumes about three hours' storage and no market. It is a placeholder that adds evening export and midday import. |
| Demand, electrolyser | Flat at `import_mw` | The worst case for hours: a data centre's shape. A known profile replaces it when one is published. |
| Solar + storage (hybrid) | Solar shape on export, battery rule on import | The ECR files many hybrids as "solar" with an import capacity; the storage half is then the battery rule. |
| Gas, biomass, other | Flat at `rating_mw` | Firm, as in the study cases. |

## What it reports

- Per line and transformer: hours over rating on main grown, and with the branch. Only the elements that change are
  shown, longest increase first.
- On the worst element: the **MWh above its rating** through the year. It is a crude estimate of what would have to be
  curtailed or reinforced away. It is crude because:
  - the overload is in MVA on one branch, not MW at the project;
  - it ignores how curtailing one project shifts the flow on the others;
  - it uses one weather year.
- The GSP export and import against their limits, as section 4 of the grown-year report.
- The limits text: "2024's shape and weather; per-technology shapes from one site each; batteries on a fixed rule;
  voltage control run at unity; no outages".

**Cost.** One grown year is about 16 minutes on the single worker. A branch run is one more year solve per year asked
for. That is a job, not a request, using the existing jobs mechanism. Cache it by the branch's connection signatures
(the same key `years.simulate` uses).

## Worked example to run first

**The project:** the largest accepted-to-connect generation project in the registry is **240 MW of solar + storage at
Grantham 132 kV (section 303)**, energising 2027, import 240 MW. (A 248 MW battery at Sleaford 132 kV is larger, but is
storage only.) Run it on 2030 Holistic Transition.

**Why not the Bicker Fen projects.** Five of the eight largest projects sit at Bicker Fen 132 kV, which is the slack
bus in this model. They change only the GSP exchange, not any flow inside the network. Ash Farm showed this (spec).
The view should say so for any project placed at the slack.

**What to expect, as a check on the build, not a finding:**
- Grantham's two 132 kV sections are not joined in the model. So the project's midday export leaves through the single
  Grantham 303 – Sleaford tee circuit, rated 137 MVA (128 MVA in summer).
- On Gorse Lane's shape, 240 MW peaks near 185 MW. Grantham's local demand is about 19 MW at most.
- So that circuit should run well over its summer rating at sunny middays, for hundreds of hours. The tee to Bicker Fen
  (137 MVA) should be close behind.
- If the build does not show this, the build is wrong.

**The question it raises for NGED:** does NGED run the Grantham 132 kV sections split, as the LTDS model does? A 240 MW
offer there suggests the connection works include reinforcement that the LTDS does not yet show.

## As decided (the guide session, overnight, for the owner to confirm)

- **Shapes:**
  - solar as proposed;
  - offshore wind as proposed, per unit of 180 MW. Lynn and Inner Dowsing are the only generation behind Middlemarsh;
    the circuits carry no runs of identical values;
  - onshore wind is Bambers Farm, whose only runs of identical values are calm zeros, so it passes the screen;
  - wind at 132 kV and above takes the offshore shape, below it the onshore one.
- **Battery:** the time rule stands, called a placeholder wherever it is shown. Any branch with storage also shows the
  study cases' worst case beside the year figure.
- **Seam:** the year driver takes the branch's connections in the contract `simulate` uses, with its energisation
  rule (`timeseries.run_year(..., connections=, plan_year=)`).
- **Scope:** a report and an engine capability only, with no API job and no planner control. Running a branch's year
  from the planner, as a cached job, is the step after this.
- **Output:**
  - "MVAh above rating" on the worst element, described as a crude first indication of export that would have to be
    held back;
  - any project on the slack bus is said to move only the GSP exchange.
- **Worked examples:**
  - Grantham as the registry places it, plus a variant with the two 132 kV sections tied for that run only;
  - the largest accepted-to-connect generation project below 132 kV that is in service by 2030.
