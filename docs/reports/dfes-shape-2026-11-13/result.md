# Work 8.2: the gate fails, so no shaped year is built

*13 November 2026. Run once, as `spec.md` fixed it; nothing was tuned after the result. Supported by NGED Open Data.*

**Result:** for 2035 under Holistic Transition, the DFES pieces on the measured 2025 base reproduce NGED's Power
Projection at **8 of 21 ESAs**. The gate needs 15. **The shaped year is not built, and the engine is unchanged.**

| | 2030 (reported) | 2035 (the gate) |
|---|---|---|
| ESAs tested | 19 | 19 |
| Size within ±10% or ±1 MW | 11 | 8 |
| Peak in the same part of day | 6 | 12 |
| Both (pass) | 6 | **8** |
| Median error at the projection's half-hour | −9.0% | −11.7% |
| ESAs where the rebuild is below NGED's figure | 17 of 19 | 18 of 19 |

- **Untested, counted as failures (as the spec set):**
  - Spilsby: no metered 2025 series of its own;
  - Wrangle: its 2025 series is zero on 99% of the year.
- **Pass:** Alford, Cranwell, Easton, Ingoldmells, New Beacon Road, Skillington, Tattershall and Trusthorpe.
- **Size only:** Chapel St Leonards, Great Hale, Ruskington and Sleaford.
- **Size and time:** Billingborough, Horncastle, Leadenham, Market Overton, Metheringham, Warth Lane and Woodhall
  Spa.
- **Per ESA:** `gate.json` holds each ESA's figures (the base day, the rebuilt peak and its time, the increment, and
  each piece's peak).

## The finding

**NGED's published pieces (volumes, profiles, splits, scaling) do not reproduce NGED's own projected peaks at most of
Bicker Fen's supply areas.** The base demand behind those projections is a set of cluster profiles, and NGED publishes
no assignment of them to supply areas. The stand-in used here is the measured 2025 day, a net flow that peaks in the
evening. It is short, and where NGED's peak moves to the morning or midday it peaks at the wrong time. **A
network-wide shaped year cannot be validated from published data, and none is offered.**

No further attempt is made to make the gate pass. Fitting a cluster to each area from its measured shape would tune
the reconstruction to the answer.

## What the failure says

**The rebuild is short, not scattered.** It sits below NGED's figure at 18 of the 19 tested ESAs. Where it fails worst
(Leadenham −32%, Market Overton −34%, Woodhall Spa −31%), two things hold:
- NGED's peak is at 09:45 or 13:15;
- the measured base peaks in the evening, so at NGED's half-hour the base is well below its own maximum.

The increments are of the right kind (at Leadenham: home charging, agriculture, heat pumps, depot and workplace
charging). They are not big enough to fill the gap the base leaves.

**What is missing is NGED's base.** The rebuild uses each primary's measured 2025 day, scaled to NGED's 2025 peak, as
the demand that exists today. NGED's projection evidently does not: its base is lower in the evening, or higher in the
morning and midday, or both. The profiles file has about 200 base-demand profiles labelled by cluster ("W1,S0,Sgen1,
IC0,IW0" and so on), and NGED publishes no assignment of an ESA to one. Without that assignment, the base NGED adds its
pieces to cannot be reproduced. There is a second reason the measured base is not NGED's: it is a net flow, with the
embedded generation behind each primary already inside it.

**What it does not say:** the gate tests whether the pieces add up to NGED's figure, not whether NGED's figure is right.
The 2035 midday and morning peaks remain NGED's own projection (data note 8.1b), resting largely on the assumption that
home charging is managed out of the evening.

## What this leaves standing

- The grown years stay as they are, with their limit stated: their size follows NGED's DFES; their hours follow 2024's
  or 2025's evening shape, while NGED's projection puts the 2035 peak in the morning or at midday.
- Adding the pieces anyway, onto a base the gate shows is not NGED's, would put the hours somewhere neither the
  measurements nor NGED's projection support. **It is not done.**

**Files:**
- In this folder: `subset_volumes.py`, `gate.py`, `gate.json`.
- Beside the download: `dfes_volumes_bicker_fen.csv` and `volumes_edition.json`.

## Addendum: what shape does at the eight areas that passed (a sensitivity, not a shaped year)

*As fixed in `spec.md`'s addendum before the run.*
- **The run:** 2035 Holistic Transition on 2024's flows. DFES-shaped demand at Alford, Cranwell, Easton, Ingoldmells,
  New Beacon Road, Skillington, Tattershall and Trusthorpe; every other primary grown uniformly. It is compared with
  the catalogued `grown-2035-ht`.
- **Solved:** all 17,568 half-hours in both runs.
- **What is read:** only those eight substations' own 33/11 kV transformers and firm capacity.
- **Part of day:** all eight passed the gate on part of day as well as size (that is what passing meant), so none has
  its hours placed at a time the gate contradicts.
- **Run file:** `apps/pipeline/warehouse/nged-flows/sensitivity-2035-ht-shaped8.npz`, sha256
  `9733f047ea4558ee4a176a80a0ca76f10b6e666481cd617f677bf59f7c0448eb`. Not catalogued.
- **Figures:** `sensitivity.json`, from `analyse_sensitivity.py`.

| Substation (firm) | Transformer | Uniform: peak, hours over rating | Shaped: peak, hours over rating | Hours above firm, uniform → shaped |
|---|---|---|---|---|
| New Beacon Road (14 MVA) | 1L3–1T0, 12 MVA | 152.8% (15 Jan 17:45), 1,818 h | 150.8% (8 Feb 13:15), **3,695 h** | 7,408 → 8,559 |
| | 2L3–1T0, 12 MVA | 146.4%, 1,506 h | 144.5%, **3,232 h** | |
| Alford (6 MVA) | 1L3–1T0, 6 MVA | 156.2% (20 Nov 16:45), 1,164 h | 135.6% (15 Jan 09:15), 1,151 h | 8,149 → 8,782 |
| | 2L3–1T0, 6 MVA | 106.3%, 5 h | 107.3%, 54.5 h | |
| Trusthorpe (19 MVA) | 2 × 12 MVA | 97.0%, 0 h | 85.6%, 0 h | 136 → 5 |
| Tattershall (17 MVA) | 2 × 12 MVA | 84.0%, 0 h | 81.3%, 0 h | 124 → 407 |
| Ingoldmells, Easton, Skillington, Cranwell | | 31–62%, 0 h | 32–66%, 0 h | 0 → 0 |

**When the hours fall:**
- **New Beacon Road, unit 1:**
  - *Uniform:* evening 856 h, midday 552, morning 410. By month: January to March and October to December.
  - *Shaped:* night 1,090 h, midday 910, evening 851, morning 844. By month: March and April rise to 564 and 505 h,
    while October falls from 153 to 8.
  - *Why the night appears:* the flexed home charging and the thermal-storage heat pumps, both overnight in NGED's
    profiles.
- **Alford, unit 1:**
  - *Uniform:* evening 483 h, midday 368, morning 314.
  - *Shaped:* midday 504 h, morning 413, evening 182, night 52.

**The answer for these substations.** Of the eight, only New Beacon Road's and Alford's transformers exceed rating in
either run.
- **At New Beacon Road,** keeping 2024's shape **understates** the hours above rating by about **a factor of two**, at
  almost the same peak. It also puts them in the evening of the winter months, where the shaped run spreads them over
  the night, midday and into spring.
- **At Alford,** the shape leaves the hours about the same (×1.0). It lowers the peak by 20 points and moves it from
  the evening to the morning.
- **Firm capacity:** the shape raises the hours above firm at New Beacon Road (×1.16), Alford (×1.08) and Tattershall
  (×3.3), and lowers them at Trusthorpe (136 → 5 h).

**Why the shaped counts lean high.** Each increment is the peak-day profile applied to every day of its season, so a
mild winter day gets the peak day's heat-pump kW. Uniform growth adds little on low days; the shaped run adds the full
increment every day. So "a factor of two" at New Beacon Road is an upper-side estimate: up to about two. How much of
it is the peak-day assumption is not separated here.

**Inherited:** the scenario's assumption that home charging is managed out of the evening. That assumption is what puts
New Beacon Road's new hours at night.
