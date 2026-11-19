# Scoping note: a second supply point

*13 November 2026, Work 11. Decided by the guide session overnight, for the owner to confirm. Read-only: nothing is
built and nothing was downloaded beyond portal metadata and small datastore queries. Figures marked **read** were read
on this date from NGED's Connected Data Portal API, or from NESO's data portal where named. Every request carried only
dataset ids and supply-point names. No recommendation to build: whether and where to widen is the owner's choice.
Supported by NGED Open Data.*

**The finding first.** Bicker Fen's model ends at three open couplers inside substations it shares with Walpole
(Boston 132 kV, Tattershall 33 kV) and Staythorpe (Grantham North 132 kV), and no branch in NGED's own flows crosses
them. So in normal running Bicker Fen is a well-posed island, and studying it alone is sound. A second supply point
would add the option of moving those open points, not a missing boundary flow.

**The question.** Everything so far is one Grid Supply Point (GSP, where the transmission network feeds a distribution
network). Does the method repeat at another, or was it fitted to Bicker Fen?

## 1. What NGED publishes for other supply points, in the same form

| Dataset | Coverage (**read**) | How it is split |
|---|---|---|
| LTDS tabular model (Tables 1–7, Attachment 8 nodes) | All four NGED licence areas | **One resource per table** for all of NGED. Filter on the `GSP Group` column: Table 1 circuits have 441 rows for Bicker Fen 132kV, 462 for Walpole 132kV and 432 for Staythorpe 132kV |
| LTDS Table 5 generation | Same | Same resource, but its `GSP Group` is spelt differently ("Bicker Fen 132 kV S Stn", "Staythorpe  C  132 kV S Stn", with two spaces) |
| ECR (embedded capacity register) | All NGED | One resource. Filter on `grid_supply_point`, again spelt per GSP ("Staythorpe  C  132Kv S Stn") |
| GSP limits (Td limits and pre-event limits) | 45 supply-point groups | One resource per group and kind (180 in all) |
| Substation loading, half-hourly | 45 groups | One CSV per group (**2024**, modified March 2026), plus a **2025** CSV per group ("2025 Connected Export", published 30 October 2026) |
| Branch loading, half-hourly | 45 groups | The same two years |
| Bus mapping | Every bus of every group: 25,726 rows in 57 GSP names across four licence areas (15 in East Midlands, including "NGET") | One resource; every group in it has loading datasets |
| SGT flows (supergrid transformers) | East Midlands: 15 GSPs, Bicker Fen, Staythorpe and Walpole among them | One CSV per GSP; the description says 31 March 2022 to 31 March 2023 |
| DFES 2025 | All Electricity Supply Areas (ESAs) | One resource; ESAs are matched to primaries by name, as now |
| Connection queue | 45 groups | One resource per group |

**Licence.** Every package is labelled "WPD Open Data Licence", the same naming question as before.

**A side find.** Bicker Fen also has a **2025** measured year, published two weeks ago. It would be a second year to
check the method on, without a new grid.

## 2. The natural neighbours: where our model actually ends

Our model's edge is three couplers, not circuits between supply points. The LTDS rows that leave the model are four
"@1" circuits (zero impedance, no rating). NGED's bus mapping puts the far end of each on another GSP:

| Shared substation | Bicker Fen side | Other side | Neighbour |
|---|---|---|---|
| Boston 132 kV | sections MAIN2A, MAIN4 | MAIN1, MAIN6 | Walpole |
| Tattershall 33 kV | MAIN1 | #5L5 | Walpole |
| Grantham North 132 kV | MAIN1 | MAIN2A | Staythorpe |

Each substation is **split between two supply points**, and NGED's own 2024 branch flows for Bicker Fen hold no branch
that crosses to another GSP (all 164 lie inside its bus map). So in normal running these are open points: the two
networks meet only through the transmission system above. That makes Walpole and Staythorpe the two candidates.

| | Bicker Fen (today) | Walpole | Staythorpe |
|---|---|---|---|
| LTDS circuits | 441 | 462 | 432 |
| Distinct primaries (Table 3) | 40 | 42 | 38 |
| BSP groups (Table 3) | Grantham, Skegness, Sleaford, plus generator sites | Boston, Bourne, Spalding & South Holland, Stamford, Sleaford REP | Checkerhouse, Hawton, Grantham North and South 132/11 kV, Asfordby |
| Buses in NGED's bus map | 461 | 708 | 455 |
| Connected generation, LTDS Table 5 | 376.5 MW (180 offshore wind at Middlemarsh, 169 solar) | 275.7 MW (99 solar, 73 onshore wind, 66 biomass) | 222.1 MW (153 solar, 56 other) |
| ECR connected / accepted not connected | 245.9 / 2,100.9 MW (144 rows) | 276.9 / 519.7 MW (195 rows) | 321.4 / 569.0 MW (143 rows) |
| Td limits per SGT, import winter / summer, export | 2 SGTs: 160.1 / 110.8, export 263.5 | 3 SGTs listed (S2, S4, S5): 205.7 / 157.7, export **73.4** | 2 SGTs: 208.3 / 95.9, export 578.2 |
| NESO FES 2024/25 peak demand (NESO portal, summed over demand types) | 147–150 MW (BICF_1) | 195–200 MW (WALP_B) or 508–518 MW (WALP_1): see below | 258–264 MW (STAY_1) |

- **Walpole:** shares two substations with Bicker Fen, so two of our three boundaries would close.
  - Its export limit is 73.4 MW per SGT, against Bicker Fen's 263.5 MW, so export is the constraint there: a different
    planning question from Bicker Fen's.
  - Open points:
    - Walpole also feeds UKPN's network in Norfolk.
    - NESO lists two Walpole entries; which one is NGED's side is not stated in the table (WALP_B is the likelier at
      this size; **not verified**).
    - The Td table lists 3 SGTs while the bus map has 5 tertiary buses.
- **Staythorpe:** shares Grantham North.
  - It has two SGTs and a high export limit.
  - Its demand peak is larger than Bicker Fen's.
  - Its Table 5 holds 101 MW not yet connected.
- **Both** have every dataset in section 1, in the same form.

## 3. What in our code is general, and what is written for Bicker Fen

**General already** (works for any NGED GSP's tables):
- the builder's logic: node merging, lines and transformers from impedances, seasonal ratios, BSP groups and their
  coincidence (`_coincidence`), demand split over busbars, edition handling;
- DFES matching by ESA name;
- the half-hourly mapping (`nged_flows`: clusters, Kirchhoff closure, the reactive screen);
- the year driver (`timeseries`) and the run machinery (`runs.py` since tonight);
- the API and the planner, which see one `GridSource`.

**Written for Bicker Fen** (each must be found again for a new GSP):

| Item | Where | What it is | Found again by |
|---|---|---|---|
| `LTDS_GSP_GROUP`, `ECR_GSP`, flows' `GSP` | nged.py, registers.py, flows.py | The supply point's name in three spellings | Reading each dataset's spelling |
| Resource ids (fault, DFES, ECR, bus map) | nged.py, registers.py, flows.py | Shared across GSPs | Nothing (same ids) |
| Substation and branch loading resource ids | flows.py | Bicker Fen's own CSVs | The portal listing |
| `GSP_BOUNDARY`, `GSP_CENTER`, `OSM_BBOX` | nged.py, registers.py | Td limits, map centre, OSM search box | The Td resource; geography |
| `GSP_PEAK_DEMAND_MW` (the BSP scaling to NESO's peak) | nged.py | 149.235 MW from BICF_1 | NESO's GSP id (ambiguous at Walpole) |
| `TRANSMISSION_PROJECTS` | nged.py | NESO TEC entries at Bicker Fen | The TEC register by hand |
| `REMOVED_IN_ERROR` (Warth Lane) | nged.py | A demand row marked Removed but live | Checking against the half-hourly flows |
| `GENERATION_SITES` (11 sites) | nged.py | Table 5 totals split onto named feeders | Checking ECR names against flows |
| `ECR_ADDITIONS` (Ash Farm) | nged.py | A connected site newer than the LTDS | ECR against LTDS, then flows |
| `YEAR_SHAPES` column names | nged_flows.py | The branches carrying Gorse Lane's and Lynn and Inner Dowsing's output | Choosing a reference site per technology |
| `HELD_AT_ZERO` (Grantham North 25 kV railway) | nged_flows.py | An unmeasured load | Checking against the flows |
| Bundled snapshot, `data/nged/` | nged.py | One directory, one grid | A directory (or key) per GSP |
| `NgedSource` id and name, `nged_runs.CATALOGUE` | sources.py, nged_runs.py | One source, one catalogue | Per GSP |
| The slack | `_add_gsp_infeed` | One ext_grid at the best-connected 132 kV bus | Works per GSP; two GSPs in one net need one each |

**What building a second one would take.** A parameterised source works better than a second class: `NgedSource(gsp)`
with a small per-GSP record holding the names, resource ids, limits, NESO id, centre and the named exceptions. Every
exception tonight was found the same way: put NGED's own half-hourly flows through the engine and look where they
disagree (Warth Lane's missing demand, the feeders, Ash Farm, the railway load, Spilsby's reactive power, the 132/33 kV
impedance at Sleaford). **That check is the commissioning test for any new supply point.** The exceptions cannot be
guessed beforehand; the check finds them.

## 4. What two side by side would add, and what they would not

**Would add:**
- *The split substations whole.* Boston, Tattershall and Grantham North modelled with both halves, so a planner can
  study closing a coupler: a transfer of load or generation between supply points. That is a real planning option
  (moving an open point) that one GSP cannot show.
- *Boundaries no longer assumed.* Tonight they are open by the data's own evidence. With both sides they are switches
  the model holds.
- *The same method at a second grid,* which is the actual test of whether it generalises.
- *A different constraint:* at Walpole, export (73.4 MW per SGT).

**Would still be missing:**
- *The transmission level.* Each GSP stays a slack bus. With couplers open, the two networks are electrically
  independent in the model; their interaction through the 400 kV network (shared circuits, Viking Link, Triton Knoll)
  is not modelled.
- *UKPN's side of Walpole,* not in NGED's data.
- *Outages* (still none), which is when open points matter most.

## 5. Effort, in tonight's stages

| Stage | Tonight at Bicker Fen | For a second GSP |
|---|---|---|
| Fetch | The pipeline's fetch assets | Parameterise by GSP: small (names, ids) |
| Build the network | The builder, already general | Run it on the new tables. Unknown until tried: it may hit a table form Bicker Fen never had (three-winding transformers in Table 2b, more SGTs) |
| Commission: the measured year against NGED's flows | Step 1 plus Works 1–2: most of a night | The same again. The per-GSP exceptions come from here |
| Grown years and the year view | Works 3–7 | Mostly reuse, once the source is parameterised |
| Two GSPs in one network (couplers) | Not done | A further step: two slacks and the shared substations' sections joined |

**First thing to do if the owner says go.** Fetch the LTDS tables for one candidate (Staythorpe is the simpler: two
SGTs, one shared substation) into a second snapshot, and run the existing builder on them unchanged. Whether it converges, and what it
trips on, answers "does it repeat" at the lowest cost, before any half-hourly data.

## Side observations

- **Bicker Fen's 2025 measured year** is published (above).
- **The intermediate seasons' import limits.** Bicker Fen's Td limits give an import limit for the intermediate seasons
  too: 179.1 MW per SGT, above the winter 160.1. `GSP_BOUNDARY` held winter and summer only (all four seasons since Work 16b). No result changes:
  section 4 of the grown-year report judged import against both and noted the seasons.
