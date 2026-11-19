# Two registry projects on a branch, through a grown 2030

*13 November 2026. Decided by the guide session overnight, for the owner to confirm. Supported by NGED Open Data.*

**What the snapshot basis misses, in one example.** A 40 MW solar farm on a 33 kV circuit near Sleaford takes that
circuit to 141% of its rating, and over it for 402 hours of 2030. The summer-minimum planning case puts the same
circuit at only 102.5%, because running every generator at full export at once first sends 8 MW the other way along
that line, and the farm's flow cancels that before it loads the circuit. In the year, at the farm's sunny half-hours,
that line carries about 1.5 MW without the farm, so the farm's flow arrives almost whole.

**The question.** The grown year (`report.md`) shows where the network as it is today, `main`, breaks in 2030 and 2035.
A planner's next question is what one project adds. Put it on a branch, run the same year, and see which circuits go
over their rating, for how many hours, and when. The build is in the scoping note (`scoping-6b-connections-in-a-year.md`)
and the README register ("A branch's connections in a grown year").

**How each example is run.**
- The base is the 2030 Holistic Transition grown year: 2024's half-hourly flows, each primary scaled to 2030 demand.
- The project is taken from NGED's Embedded Capacity Register (ECR) exactly as the registry gives it: its bus, technology,
  export and import capacities, and target year. It is added as one connection, in service from that year.
- Its output each half-hour is its rating times a 2024 per-unit shape from one real site: for solar, Gorse Lane's two
  feeders, capped at 1.
- The same plan year's two planning cases (winter peak, summer minimum) are run with the branch, for comparison.
- Files: `branches.py` (the examples), `run.py 2030 ht <variant>`, `analyse.py 2030 ht <variant>`, then
  `compare_branch.py <variant>`, which writes `2030-ht-<variant>/branch.json`.

**Limits, before the numbers.**
- *One weather year, one site's shape.* Every sunny half-hour of 2024 at Gorse Lane is a sunny half-hour here. Another
  year's weather would move the hours, not the circuits.
- *2030 demand on 2024's shape*, as the grown-year report says: hour counts are indicative, not a bound either way.
- *Only this project is added.* Nothing else in the queue is connected, so it is the project's effect on 2030 as the
  network stands, not its effect after everything ahead of it.
- *Intact network:* no outages, no reinforcement. A connection offer usually carries works this model does not have.
- *"MVAh above rating"* on the worst circuit is the energy above its rating through the year. It is a crude first
  indication of the export that would have to be held back: the overload is MVA on one circuit, not MW at the project;
  holding one project back shifts the others' flows; one weather year.
- *Not every project can be judged this way.* Five of the eight largest projects in the registry sit at Bicker Fen
  132 kV, the slack bus here: they change only the GSP exchange and load no circuit in this model (`compare_branch.py`
  says so for any such project).

## Example 1: 240 MW of solar + storage at Grantham 132 kV

**The project:** ECR-5812F, the largest accepted-to-connect generation project in the registry. 240 MW export, 240 MW
import, at Grantham 132 kV section 303, energising 2027. The registry files it as solar, so its storage half is not
modelled: it runs on the solar shape, exports up to 240 MW and never imports. That leaves the import of 240 MW, its
largest winter question, unstudied here and in the planning cases (which run solar at nil in winter).

**First, a question about the model, not a finding.** Grantham 132 kV has two sections, 303 and 403, each fed by its
own circuit from a Sleaford tee. The LTDS gives no coupler between them, so the engine runs them split. The project
connects to section 303, so all its export leaves on one circuit pair: Grantham 303 – Sleaford Tee 1 (line 15), then
Sleaford Tee 1 – Bicker Fen (line 2), each rated 137 MVA in winter and 128 MVA in summer.

### As the model stands (sections split)

| Circuit | Peak without → with | Hours ≥ 90% | Hours over rating | When |
|---|---|---|---|---|
| Bicker Fen – Sleaford Tee 1 (line 2) | 38% → **163%** (11 August, 14:00) | 688.5 | **568.5** | March–October, 09:00–17:00 |
| Sleaford Tee 1 – Grantham 303 (line 15) | 14% → **150%** (29 June, 14:00) | 662.5 | **527** | March–October, 09:00–17:00 |

- *Pattern:* 171 days. 71% of the overload hours fall May–August and 74% between 10:00 and 15:00: a solar overload,
  every sunny day.
- *Why line 2 is worse than line 15:* Sleaford 132 kV Tee 1 also takes Sleaford's own 33 kV export (its GT1), so the
  circuit to Bicker Fen carries both.
- *MVAh above rating on line 2:* about 20,500 MVAh in the year, up to 81 MVA above its rating at once. Against the
  project's 310 GWh, that is about 7% of its energy: a crude indication of what would have to be held back.
- *Planning cases with the branch:* the summer-minimum case shows the same two circuits, harder (line 2 at 180%,
  line 15 at 158%), and the GSP export at 568 MW against its 527 MW limit. The year agrees with the planning case
  here: the extreme is a sunny summer midday, and the year adds that it happens on 171 days.
- *The GSP through the year:* the export peak rises from 244 to 471 MW (23 August, 13:00), still below 527 MW for every
  half-hour. The import peak (172 MW) is unchanged, because the storage half is not modelled.
- *Elsewhere:* the Grantham 132/33 kV GT1 peaks at 91% (from 42%), with no hours over. No busbar leaves its band; the
  highest voltage anywhere rises from 1.041 to 1.064 pu. Firm-capacity hours move by under 2% (New Beacon Road 1,544
  → 1,524 h): a small knock-on, not a finding.

### With Grantham's two sections tied (this run only)

A zero-impedance tie between 303 and 403 shares the export between both circuit pairs:

| Circuit | Peak | Hours over rating | When |
|---|---|---|---|
| Bicker Fen – Sleaford Tee 1 and Tee 2 (lines 2, 3) | **107.5%** each | **70.5** each | May–August only, 10:00–16:00, 32 days |
| Sleaford Tee – Grantham 303 and 403 (lines 15, 17) | 89% each | 0 | |

- *MVAh above rating:* about 300 MVAh, at most 9.5 MVA above: about 0.1% of the project's energy.
- *Planning cases with the branch:* both Bicker Fen–Sleaford Tee circuits at 122% at summer minimum, and the GSP export
  at 571 MW against 527 MW.

**What it says.** Split, the project overloads its own circuit pair on most sunny days of the year, by up to 81 MVA.
Tied, it is a summer-midday problem of tens of hours on the two circuits into Bicker Fen, a few percent over rating. The
answer depends almost entirely on whether Grantham's sections run joined, which the public data does not say. With both
the split case and the planning cases also showing the GSP export limit crossed, an offer of this size is unlikely to
come without reinforcement or an export limit.

**The question for NGED:** is Grantham 132 kV run split, as the LTDS model has it, and does the 240 MW offer carry
reinforcement or an export limit that the LTDS does not yet show?

## Example 2: 40 MW of solar at the Whitecross Lane solar park 33 kV tee

**The project:** ECR-3D6F6, Thorns Farm. The largest accepted-to-connect generation project below 132 kV in service by
2030: 40 MW of solar, import 0.35 MW, at the Whitecross Lane solar park tee on a 33 kV circuit out of Sleaford,
energising 2027. (Pasture Farm, 45 MW at Grantham 33 kV, is larger but energises in 2032.)

**Where its power goes.** The tee sits on a ring: one way to Sleaford 33 kV (line 115, 3.7 km), the other through
Burton Pedwardine to Great Hale (lines 123 and 102). About 83% of the farm's output takes the short way to Sleaford.

| Circuit | Peak without → with | Hours ≥ 90% | Hours over rating | When |
|---|---|---|---|---|
| Sleaford 33 kV – Whitecross La tee (line 115), 27 MVA winter / 25 MVA summer | 26% → **141%** (6 June, 15:30) | 561.5 | **402** | March–October, 09:00–17:00 |

- *Pattern:* 150 days, 75% of the hours in May–August, 78% between 10:00 and 15:00.
- *MVAh above rating:* about 1,850 MVAh, up to 10 MVA above: about 4% of the farm's 52 GWh.
- *Further along:* Cranwell–Leadenham 33 kV peaks at 90% (from 69%) and the two Sleaford 132/33 kV transformers at 86%,
  with no hours over. Burton Pedwardine–Great Hale rises from 28% to 51%.

**The planning case understates this circuit, and why.** The summer-minimum case with the branch puts line 115 at only
103%, against the year's 141%. The farm's share of the flow on line 115 is the same in both (83–84%). What differs is
the flow already on the line:
- in the planning case, with every generator at full export at once, about 8 MW already runs out of Sleaford through
  the tee towards Great Hale, the opposite direction, and the farm's flow first cancels it;
- in the year, at sunny half-hours, the line carries about 1.5 MW without the farm, so the farm's flow arrives whole.

So "everything at full export" is not the worst case for every circuit: another generator's counter-flow can relieve
one. The planning case is still the harder test for the Sleaford 132/33 kV transformers, which it puts at 108–109%
(over their rating at summer minimum) where the year reaches 86%.

**What it says.** A 40 MW farm on a 25 MVA summer-rated circuit overloads it on most sunny days unless its output is
limited or the circuit is reinforced: an export limit of roughly 25–30 MW (the circuit's summer rating over the farm's 83% share), or a new circuit. This is the kind of
answer a planner can check against the offer, and the year adds when, how often and roughly how much.

**And in 2035.** The same branch, run from the planner on 2035 Holistic Transition (`branch-caac6e7e…`), puts line 115
at 146% at its peak (48.6% without the farm) but over rating for **369 hours** (1,649 MVAh), fewer than 2030's 402:
higher local demand absorbs some of the farm's export before it reaches the line. A later, busier year is not simply a
harder one for an export-driven overload: the hours fall while the peak does not, and only the year view shows the hours.

## For the owner

- The same three run files are in the planner's Year runs tab (`runs.RUNS`: `2030-ht-grantham`,
  `2030-ht-grantham-tied`, `2030-ht-thorns`), each with its caveat in the limits text.
- Running a branch's year from the planner, as a cached job, is the step after this (scoping note, "As decided").

## Run files

Under `apps/pipeline/warehouse/nged-flows/` (git-ignored), on the current working tree:
- `grown-2030-ht-grantham.npz`: sha256 `d9d5f6fd66983375a45896d325f29447f089daa97225022a86e8239ed79aa20b`
- `grown-2030-ht-grantham-tied.npz`: sha256 `1b24880a91867ac15c04e37eec2627717557e46ed9ff74de410d8f5680926b65`
- `grown-2030-ht-thorns.npz`: sha256 `6015fc3378e73a9555f86524766f7a6677f7f7ba8c2ed66228714dc85aaff4ce`

Each was compared with `grown-2030-ht.npz` (sha256 `248fc48e…4973`). The year driver with no connections reproduces it
exactly (difference 0.0).
