# A second measured year: 2025 beside 2024

*13 November 2026, Work 12. Decided by the guide session overnight, for the owner to confirm. Same code, same rules,
same network (today's) as the 2024 report; one run, reactive power screened. Supported by NGED Open Data.*

**In short.**
- *The same rules give the same verdicts*, but the engine now matches NGED's infeed far better. Rule 1 (the GSP
  infeed) is met in 94% of half-hours, against 60% in 2024.
- *The model differences are stable.* Every element whose flow differs from NGED's model in both years does so with
  the **same sign and a similar size**: 28 of 28. They are differences between the two models (the Sleaford 33 kV
  ties, the Manor Farm and Mill Farm tees, the Sleaford and Grantham 132/33 kV transformers), not accidents of 2024.
- *Utilisation moves modestly between years.* No line or transformer goes over its rating in either year. The median
  element's peak moves by 1.7 points, the most loaded primaries' by up to 13.5. New Beacon Road and Alford are above
  firm for 6 and 8 hours (5 and 9 in 2024).
- *The input faults do not simply repeat:*
  - Spilsby's reactive power is clean in 2025;
  - Manor Farm's spur, at zero all through 2024, carries its solar;
  - Wrangle's 11 kV series is now zero for 99% of the year.

## What the 2025 files are (12.1)

- **What NGED published.** *Bicker Fen - 2025 Connected Export (ID 1124)*, substation and branch loading, published 30
  October 2026. NGED's package text: "different years worth of historic data … Historic Year (e.g. 2025)".
- **A measured year, not a scenario.** Calendar 2025, complete: 17,520 half-hours, 1 January 00:30 to 1 January 2026
  00:00, with no gaps.
  - Demand differs from 2024 as another weather year does: on the same weekday, the primaries' series correlate 0.6–0.9
    with 2024's; a scaled copy would give 1.0.
  - Apart from Wrangle (below) and the GSP's own node, means move by −25% to +47% at a few sites and by under 5% at
    most.
  - Generation varies day to day: Gorse Lane's solar has a median daily peak of 27 MW and 53.8 GWh in the year (49.6 in
    2024), on the same clock (the midday centroid within 0.15 h of 2024's in January, June and December).
- **The same 34 metered nodes.** The bus map is identical to 2024's.
- **NGED's network model behind the branch flows is a newer edition:**
  - 73 branches are listed the other way round. The mapper takes each branch's sign from its ends, so nothing changes;
    the analysis's fixed sets now name a branch either way (2024's figures recomputed unchanged);
  - 7 are new: Ash Farm's spur (`VICD1_105`–`BICF1_1005`), two RAF Cranwell 33 kV links, a Grantham 132 kV section in
    series with GT1, a Boston 132 kV link, Low Farm's tee, and a Spilsby–Stickford tee;
  - 4 are gone: Middlemarsh's 132/33 kV transformers and their 33 kV ties.
- **Layout.** The fetch (`nged_flows_2025`) rewrites the files to 2024's header layout. Every value was checked equal to
  the published file.

## The four rules, unchanged (12.3)

| Rule (spec, fixed before any result) | 2024 | 2025 |
|---|---|---|
| 1. GSP infeed: engine within tolerance of NGED's four circuits, 95% of half-hours | 59.5% (median gap 1.86 MW, 95th percentile 3.58) **fail** | **93.9%** (median 0.28 MW, 95th percentile 2.67) **fail** |
| 2. Backbone groups | 12 of 18 **fail** | 11 of 18 **fail** |
| 3. Other compared groups, 80% | 62 of 88 (70%) **fail** | 59 of 91 (65%) **fail** |
| 4. Input feeders reproduce NGED's flow | 20 of 20 pass | 23 of 23 pass |

Rule 1 nearly passes in 2025. Most of the change is at the Skegness 132/33 kV transformers, whose offsets fell from
1.3–1.4 MW to 0.5–0.7 MW (both now "agrees"). NGED's 2025 model no longer carries Middlemarsh's 132/33 kV
transformers, which the 2024 model did and ours does not. That fits the change, but it is **not verified**.

## The offsets, side by side

Median engine − NGED, MW, in the engine element's own direction. The elements that differ in either year:

| Element | 2024 | 2025 | Label 2024 → 2025 |
|---|---|---|---|
| Sleaford 33 kV – Tattershall 33 kV (line 110) | −2.53 | −2.19 | differs, both |
| Skegness – Manor Farm tee, and the tee – Spilsby (lines 76, 67) | +2.17, +2.15 | +2.26, +2.23 | differs, both |
| Grantham 33 kV – Mill Farm tee – Leadenham (lines 36, 40) | +2.07, +2.00 | +2.29, +2.26 | differs, both |
| Cranwell – Leadenham (line 89) | −1.98 | −2.26 | differs, both |
| Sleaford 132/33 kV GT1, GT2 (trafos 29, 30) | −1.91, −1.89 | −2.46, −2.46 | differs, both |
| Sleaford – North Rauceby – Cranwell (lines 111, 100) | −1.64, −1.68 | −1.89, −1.88 | differs, both |
| Woodhall Spa tee – Horncastle (lines 126, 96, 95, 98) | −1.49 to −1.53 | −1.14 to −1.15 | differs, both |
| Horncastle – Spilsby (line 63) | −1.46 | −1.04 | differs, both |
| Grantham 132/33 kV GT1, GT2 (trafos 12, 13) | +1.37, +1.33 | +1.81, +1.76 | differs, both |
| Skegness 132/33 kV GT2, GT1 (trafos 27, 26) | +1.38, +1.27 | +0.50, +0.71 | differs → agrees |
| Tattershall tee (lines 114, 121) | +1.17, +1.18 | +0.96, +0.97 | differs → agrees |
| Grantham 132 kV sections and the Sleaford tees (lines 10, 15, 17), Grantham 33 kV (37, 38) | +1.33 to +1.37 | +1.69 to +1.81 | agrees → differs (the same offset, grown past the 5% test) |
| Whitecross – Burton Pedwardine – Great Hale – Billingborough (lines 115, 123, 102, 94, 28) | −0.47 to +0.50 | −1.32 to +1.29 | differs, both, larger |
| Chapel St Leonards tee (71, 58), Easton tee (35) | +0.58 to +0.71 | +0.95 to +1.26 | agrees → differs |
| Alford 33/11 kV T1, T2 | +0.24, −0.23 | +0.22, −0.21 | differs, both |

- 28 elements differ in both years, all with the same sign.
- 4 differ in 2024 only and 11 in 2025 only, each with the same sign in both years.
- The largest offsets cluster on the same circuits as in 2024: the Sleaford 33 kV ties and the 132/33 kV transformers at
  Sleaford and Grantham.
- **So the 2024 report's candidate stands:** a model difference around Sleaford and Grantham, most likely the
  Sleaford 132/33 kV impedance (measured-year 3.4), still a question for NGED.

## The input screens

| Screen | 2024 | 2025 |
|---|---|---|
| Spilsby 11 kV reactive power | 590 implausible + 242 suspect half-hours; raw MVAr up to 54.3 | **clean**: raw MVAr up to 2.4, nothing flagged |
| Trusthorpe 11 kV reactive power | 7 suspect | 24 suspect (under 1% of the year: not unreliable) |
| Billingborough 11 kV | 1 implausible | none |
| Runs of identical values: Wrangle 11 kV (`MW_46280`) | 7,317 half-hours; zero 42% of the year | **17,278 half-hours; zero 99% of the year** |
| Great Hale 11 kV (`MW_43500`) | 5,517 | none |
| Billingborough 11 kV T1 (`MW_47530`) | 22 | 136 |
| Grantham 33 kV group totals | none | 14 |

- **Spilsby's 2024 reactive power was a fault of that year's data.** It is gone in 2025.
- **Wrangle is worse.** In 2025 NGED's flows show Wrangle's 11 kV board drawing nothing through its transformer, and the
  engine agrees (peak 1%, against 90.5% in 2024). That is either a reconfiguration (load moved elsewhere) or a fault.
  It goes on the list of questions for NGED.
- **Great Hale's 2024 runs** do not recur.

## Utilisation (screened)

| Element (reliable in both years) | Peak 2024 | Peak 2025 | Hours ≥ 80%, 2024 → 2025 |
|---|---|---|---|
| Skegness 132/33 kV GT2 | 78.5% | 84.0% | 0 → 5 |
| Woodhall Spa 33/11 kV T2 | 72.6% | 83.6% | 0 → 8.5 |
| Leadenham 33/11 kV (×2) | 69.8%, 67.8% | 83.3%, 81.0% | 0 → 2, 0.5 |
| Horncastle – Spilsby 33 kV | 75.1% | 75.4% | 0 |
| Skegness 132/33 kV GT1 | 73.8% | 74.4% | 0 |
| Horncastle 33/11 kV (×2) | 71.3% | 63.9% | 0 |
| Wrangle 33/11 kV T3 | 90.5% | 1.0% | 1 → 0 (see the screens) |

- **Nothing reaches 90% in 2025** among the reliable elements, and nothing exceeds 100% in either year (on winter or
  summer ratings).
- The Middlemarsh 132 kV circuits, which carry NGED's own wind flow by construction, peak at 98.2% and 96.1% (93.7% in
  2024), at 80% or more for 1,389 and 1,030 hours (892 and 857).
- **How much one year moves.** Over the 136 elements reliable in both years, the median peak moves by 1.7 points (90th
  percentile 7.7). The most loaded primaries move most: Leadenham +13.5 and Woodhall Spa +11.0. This is the size that
  "one weather year" carries in every limits text. The grown years' text now says so.
- **Voltage:** no busbar outside its band in either year. The lowest is Metheringham 33 kV at 0.959 pu (2024) and
  0.960 pu (2025).

## Firm capacity

| Substation | Firm | 2024: peak, hours above | 2025: peak, hours above |
|---|---|---|---|
| New Beacon Road | 14 MVA | 14.26 MVA, 5 h | 14.43 MVA, 6 h |
| Alford | 6 MVA | 6.55 MVA, 9 h | 6.50 MVA, 8 h |
| Leadenham (each half) | 9.5 MVA | 8.26 MVA, 0 h | 9.86 MVA, 1.5 h |
| Spilsby | 6 MVA | not counted (reactive input unreliable) | **6.98 MVA, 93 h** |

- Spilsby's 2025 figure is new evidence. Its 2024 input could not be used, and with clean data it is above firm for
  93 hours.
- The planner now shows it too (Work 15): input reliability is read from each run's own flows, so the 2025 run lists
  Spilsby, while every run on 2024's flows still greys it.

## The GSP, Ash Farm and Manor Farm

- **The GSP.** NGED's four circuits' peak export rises from 209.0 MW (2024) to 242.6 MW. The engine's goes from 215.8
  to 240.3 MW. Peak import is 131.6 → 142.4 MW (NGED) and 137.1 → 143.1 MW (engine). The export limit, 527 MW, is
  never approached.
- **Ash Farm** (ECR: connected 11 July 2025).
  - *Where it connects:* NGED's 2025 model has its spur, from `VICD1_105` (Vicarage Drove: the ECR's site address) to
    bay `BICF1_1005` on Bicker Fen 132 kV. That is where the engine already places it (`ECR_ADDITIONS`, at Bicker Fen
    132 kV by coordinates), so the placement is now confirmed by NGED's own model.
  - *Its output:* the spur carries nothing all year (within ±0.05 MW; 3 MWh in total). The flows do not show it
    generating in 2025. Whether it was energised late or NGED's series omits it is a question for NGED.
  - *In the engine:* the measured year takes its injections from NGED's flows, so Ash Farm contributes nothing here
    either.
- **Manor Farm**. Its spur read 0 MW all through 2024. In 2025 it carries up to 18.7 MW (17.4 GWh), consistent with its
  17.86 MW of solar. **The 2024 zero was a fault in that year's data**, not a disconnected site.

## Run files

- `apps/pipeline/warehouse/nged-flows/measured-year-2025-screened.npz`: sha256
  `43652c5445be605e68fe316c504af3d55c17a01ea59b03c1e1f929fbf0bed35c`.
- Inputs: `bicker-fen-2025/` (git-ignored, with `NOTICE.txt` and `fetched.json`), from
  `uv run dagster asset materialize -m grid_simulator.definitions --select nged_flows_2025` in `apps/pipeline`.
- To rerun, from `packages/optimizer`:
  1. `uv run python -m gridify_optimizer.timeseries ../../apps/pipeline/warehouse/nged-flows/bicker-fen-2025 ../../apps/pipeline/warehouse/nged-flows/measured-year-2025-screened.npz screened`;
  2. `uv run python ../../docs/reports/measured-year-2024/analyse.py ../../apps/pipeline/warehouse/nged-flows/measured-year-2025-screened.npz ../../docs/reports/measured-year-2024 screened-2025 2025`;
  3. `uv run python ../../docs/reports/measured-year-2024/compare_2025.py`.
- Figures: `screened-2025/figures.json`, `elements.csv`, `comparison.csv`, `compare.json`.
- Code touched:
  - `nged_flows.map_year` builds its shapes table with an explicit index, so a year whose branch list lacks the
    reference columns gets an empty table instead of an error. 2024's output is unchanged.
  - `analyse.py` takes an optional year, and its fixed branch sets name a branch either way round. 2024's measured
    figures recompute identically; the planning-case columns of the stored 2024 files predate Works 1–2.
- In the planner: run `2025-screened`, measured.

## Experiment (Work 16a): Sleaford's 132/33 kV units at their neighbours' impedance

*An experiment, not a change to the engine. Decided by the guide session overnight, for the owner to confirm. The
engine keeps the published figure: an engine built on published data does not swap a published value for one inferred
from a fit. That is the owner's call once NGED answers.*

**The lead.** Work 1 found, on one winter week of 2024, that Sleaford's two 132/33 kV transformers at an impedance like
their neighbours' close most of the Sleaford-Grantham side of the mismatch. Their neighbours:
- Grantham GT1 and GT2: 6.77% and 6.98% on 45 MVA;
- Skegness GT1 and GT2: 6.55% and 6.57%.

Sleaford's published figures are 11.22% and 11.19%. On 2025, what remains of the mismatch is exactly the Sleaford and
Grantham cluster.

**What was run.** The full 2025 year, screened, through the same driver (`experiment_sleaford.py`):
- Sleaford's two 132/33 kV units have `vk_percent` and `vkr_percent` both multiplied by 6.6 / 11.2 (0.589), for this
  run only. That gives 6.61% and 6.59% (vkr 0.189% → 0.111%), so X/R is kept.
- The change lives in the run's `net_factory` alone. The built network, the bundled data and the planning cases are
  untouched.
- Every half-hour solved. Run file `measured-year-2025-screened-sleaford-vk.npz`, sha256
  `52d090ed43fe16637ed4314ba80be57f0f44849985c6e6705e1445feeb9f50b3`. Figures in `screened-2025-sleaford-vk/` (the
  same `analyse.py`; `compare_sleaford.py` for the comparison).

**The four rules, unchanged.**

| Rule | 2025 as built | 2025, Sleaford at 6.6% |
|---|---|---|
| 1. GSP infeed within tolerance, 95% of half-hours | 93.9% (median gap 0.28 MW) **fail** | 93.8% (median gap 0.22 MW) **fail** |
| 2. Backbone groups | 11 of 18 **fail** | **14 of 18** **fail** |
| 3. Other compared groups, 80% | 59 of 91 (65%) **fail** | **66 of 91 (73%)** **fail** |
| 4. Input feeders | 23 of 23 pass | 23 of 23 pass |

**Labels.**
- Of the 39 elements that differ as built, **12 now agree**:
  - the Grantham 132 kV lines from the Sleaford tees (lines 15, 17) and the Grantham 132 kV sections (9, 10);
  - Grantham 33 kV (37, 38) and the Easton tee (35);
  - the whole Sleaford – Whitecross – Burton Pedwardine – Great Hale – Billingborough ring (115, 123, 102, 94, 28).
- **27 still differ.**
- **2 that agreed now differ:** the two RAF Cranwell feeder sections (lines 107, 109), by ±0.18 MW. They sit just at the
  edge of the radial test.

**The BSP pair offsets** (engine minus NGED, from 132 kV to 33 kV, MW; median, with the 5th and 95th percentiles):

| BSP | As built | Sleaford at 6.6% |
|---|---|---|
| Sleaford | −4.92 (−7.55 to +8.27) | **−2.59** (−4.20 to +5.09) |
| Grantham | +3.57 (−7.27 to +5.68) | **+1.75** (−4.93 to +2.97) |
| Skegness | +1.21 (−0.50 to +2.77) | +0.72 (−0.16 to +2.09) |

**Sleaford's own units**, offset per unit: +2.46 → +1.29 MW. Grantham's GT1/GT2: +1.81/+1.76 → +0.89/+0.86 MW.

**The two ties** (offset in MW, as built → experiment):

| Tie | Elements | As built | Experiment |
|---|---|---|---|
| Sleaford to Grantham (North Rauceby, Cranwell, Leadenham, Mill Farm) | lines 111, 100, 89, 40, 36 | 1.9 to 2.3 | **1.1 to 1.3** |
| Sleaford to Skegness (Tattershall, Woodhall Spa, Horncastle) | lines 110, 119, 126, 96, 95, 98, 63 | 1.0 to 2.2 | 0.6 to 1.9 |

On both ties every element keeps its label ("differs" stays "differs"; lines 114 and 121 keep "agrees").

**What it says.**
- One change, applied to the two units the lead names, halves every offset in the Sleaford-Grantham cluster: the BSP
  pairs, both ties and the 132/33 kV units at both sites. It turns 12 elements from "differs" to "agrees".
- It does **not** pass rules 1–3. About half of the mismatch is left, on the same circuits, with the same sign.
- So the lead is stronger, but it stays a lead. The impedance NGED's model holds for Sleaford's units is very likely
  lower than the published 11.2%. But a neighbour-like 6.6% does not by itself reproduce NGED's flows: something else
  on the same path carries the rest (the derived BSP-busbar injections, tap positions, or an impedance between 6.6% and
  11.2% combined with one of those).
- **The question for NGED, now specific:** what impedance does your model hold for Sleaford 132/33 kV GT1 and GT2 (the
  LTDS publishes 11.2% on 45 MVA, against 6.6–7.0% at Grantham and Skegness), and at what tap positions are they
  normally run?
- The guide's 2024 variant was conditional on this closing; it did not, so it was not run.
