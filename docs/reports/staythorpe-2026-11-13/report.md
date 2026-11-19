# Staythorpe: a second supply point, built and commissioned the way Bicker Fen was

*13 November 2026, Step 4. Decided by the guide session under the owner's delegation, for the owner to confirm.
Everything here is local: the snapshot is in the git-ignored warehouse, nothing is bundled into the package, and
Staythorpe's runs are not in the planner's catalogue (showing a second supply point is the owner's decision).
Supported by NGED Open Data.*

## First: Staythorpe is an island in normal running, by NGED's own model, as Bicker Fen is

Twelve circuit ends leave Staythorpe's LTDS group:
- ten are couplers with no impedance ("@1", "*1") at Bourne 132 kV (to Walpole), Checkerhouse 132 kV and Mansfield
  33 kV ×2 (West Burton), Grantham North 132 kV (Bicker Fen), Melton Mowbray 132 kV ×2 (Grendon) and two Staythorpe
  132 kV bays (Willington);
- two are lines open at their far bay: Checkerhouse–Mansfield 33 kV, and Ollerton–Thoresby 33 kV (Chesterfield).

**None of the twelve appears in NGED's own Staythorpe branch files, in 2024 or 2025, and no branch in either file has an
end inside another supply point's bus map.** In normal running no power crosses Staythorpe's boundary, so its
planning cases and measured years solved alone are well-posed, in the same sense as Bicker Fen's.

What this does not cover: the same circuits closed under an outage or a load transfer. No part of this work studies
either.

## 1. The findings, in order of weight

1. **Tuxford 33/11 kV is above its nameplate today, on measured data.**
   - *The unit:* one 6 MVA unit (9.5 MVA emergency rating), in both the LTDS (Table 2a, TUXF3_1H3–TUXF5_1T0) and
     NGED's own model (one Tuxford 33/11 kV branch in its file).
   - *The measured peak:* 6.94 MW and 2.03 MVAr (7.23 MVA) on 8 January 2025 at 09:00, at the LTDS's own power factor
     (0.96).
   - *Agreement:* NGED's own branch flow through the unit at that half-hour, 6.94 MW from 33 to 11 kV, agrees with
     the engine's 7.00 MW.
   - *Hours:* above its nameplate for about 126 hours of 2025 on the node series alone (above 6 MW: 70.5 h in 2025,
     17 h in 2024). The engine's year puts it over its rating for 166 h, peak 125.2%. It stays below its emergency
     rating.
   - *Against the LTDS:* the LTDS maximum (4.84 MW) understates the measured peak by 43%.
   - *Growth:* both growth sources take it to about 2.5 times by 2030 (DFES Holistic Transition ×2.54; the LTDS's own
     forecast ×2.56).
   - *What the files leave undetermined:* whether the unit is run to a cyclic or emergency rating by design.
2. **The method's mapping check passes on the first run.** In 2025, the closure against NGED's flows into the infeed
   busbar holds on 100% of half-hours (median gap 0.06 MW), and every radial group matches. Section 3.
3. **The main open model question is now shared by both supply points.** Each has a 33 kV path tying two BSPs that
   carries about 2 MW differently from NGED's model, with the two BSPs' transformers offset to match. Section 5.
4. **Six exceptions were found and named, each with its evidence and kind, and four things were found and left as they
   are** (Section 4). Three general rules came out of Staythorpe and apply to both supply points, with Bicker Fen shown
   unchanged or changed by a stated amount: a coincidence factor above 1 stops the build; demand or generation the
   infeed cannot reach is recorded, not dropped unseen; a connector published as a circuit is a connector.
5. **The study basis credits firm plant in full, and at Staythorpe that halves the winter-peak import.** Section 6.

## 2. What Staythorpe is, beside Bicker Fen

| | Bicker Fen | Staythorpe |
|---|---|---|
| LTDS circuits (live) | 427 | 430 |
| Buses / lines / transformers built | 139 / 128 / 44 | 154 / 135 / 40 |
| 132/11 kV transformers | none | 4 (Grantham North GT3/GT4, Grantham South GT1/GT2, 15 MVA) |
| Infeed | Bicker Fen 132 kV main bar | Staythorpe C 132 kV main bar (Staythorpe B fed through three 600 A circuits) |
| SGT limits per unit (import winter / intermediate / summer; export) | 160.1 / 179.1 / 110.8; 263.5 MW | 208.3 / 185.0 / 95.9; 578.2 MW |
| Supply-point peak the build scales to | 149.235 MW, NESO FES (BICF_1) | 147.82 MW, NGED's metered flows (see 4.4) |
| Coincidence factor at the supply point | 0.959 | 0.852 |
| Connected generation built | 64 sgens | 48 sgens, 236.2 MW |

## 3. The commissioning check, 2025, the same rules, beside Bicker Fen

Both are judged by `rules.py` (Bicker Fen's rules with the classes defined from the network, so both are classed the
same way). The closure reference, stated before the result, is the circuits NGED shows out of the infeed busbar:
- Bicker Fen: its four 132 kV circuits;
- Staythorpe: five, namely Hawton ×2 and Staythorpe B ×3. Their sum balances NGED's two SGTs: mean 56.4 MW in, 56.4
  MW out.

| Rule | Bicker Fen 2025 | Staythorpe 2025 (reference run) |
|---|---|---|
| Radial rule: every radial group within 0.5 MW + 2% on every half-hour | 18 of 18 | **32 of 32** |
| Input feeders reproduce NGED's flow | 21 of 21 | 26 of 26 |
| 1. Closure on 95% of half-hours (larger of 2 MW and 3%) | 93.9%, median gap 0.28 MW: **fail** | **100%**, median gap 0.06 MW, 95th percentile 0.19: **pass** |
| 2. Backbone groups | 12 of 23: fail | 22 of 26: fail |
| 3. Meshed groups, 80% | 59 of 90 (65.6%): fail | 59 of 74 (79.7%): fail, one group short |
| Not compared | connector 1 | connector 1, open point 1 |

The Bicker Fen column uses `rules.py`, which classes groups from the network; its own report's hand-listed classes
give 93.9% / 11 of 18 / 59 of 91 / 23 of 23, unchanged by the connector rule.

**Staythorpe's run history** (each rerun kept beside the reference):
1. Run 1, the build as first made: radial 29/29, closure 100%, rule 2 20/26, rule 3 54/78 (69%).
2. Run 2, with the Ranskill open point: radial 32/32, rule 3 59/74 (79.7%).
3. The reference run, with the connector rule: rule 2 22/26. The Staythorpe B–C pair now passes.

- Reference run: `apps/pipeline/warehouse/supply-points/staythorpe/measured-year-2025-screened.npz`, sha256
  `c2f43db76512b527c4175845eb58276afa145b10fb18bffe61017ec4cb579c2e`.
- Mapping: 23 metered nodes and 26 derived. No half-hour unsolved.

## 4. The exceptions record, as it stands

Staythorpe's record (`nged_points.STAYTHORPE`) holds four entries beyond the names its data is filed under. Each has
its evidence and its kind:

1. **The infeed node, `STAY1_MAIN1`. Kind: inference.**
   - NGED's Td Limits table names the site and its supergrid transformers' bays (`#180`, `#280`), which are not LTDS
     nodes at either supply point. The infeed sits on that site's main busbar.
   - "Best connected 132 kV bus", the rule it replaced, picks the wrong site (Staythorpe B).
   - Bicker Fen's record names `BICF1_MAIN1`, the same bus as before.
2. **Hawton's BSP rows are an aggregate: `bsp_aliases {"Hawton SOP": "Hawton"}`. Kind: a published row, named.**
   - The rows are filed under a group name that differs from the one Hawton's primaries use.
   - They put 76.8 MW on Hawton's own 33 kV bars, against the primaries' 81.6 MW (94%): the pattern of every other
     BSP aggregate at both supply points.
   - Counted as demand, they put Hawton's 45 MVA transformers at 170% in 2026.
   - The screen `possible_bsp_aggregate` lists this case and nothing at Bicker Fen.
3. **The Ranskill–Daneshill Road normally-open point. Kind: inferred from NGED's half-hourly flows, not an LTDS row.**
   - Four branches in series read 0.000 MW on every half-hour of 2025, where the LTDS's closed mesh carried up to
     1.5 MW. This is the first use of the zero-flow criterion Experiment D set at Bicker Fen, which found none there.
   - The circuit leaving the Daneshill Road auto-recloser is opened.
   - It took rule 3 from 69% to 79.7%: it also cleared a loop through Hallcroft Road, Low Farm and Retford Road that
     had been carrying its circulation.
4. **The supply-point peak, 147.82 MW. Kind: NGED's metered flows (a different kind of figure from Bicker Fen's).**
   - NESO's STAY_1 figure (261.169 MW) is 1.50 times the group's 173.6 MW of coincident maxima, so the build refuses
     it: a coincidence cannot exceed 1. What area NESO's figure covers is not established from the published files.
   - In its place is the coincident maximum of the group's metered 11 kV primary demand in NGED's own files (8 January
     2025, 17:30). The method reads Bicker Fen at 95–96% of NESO's figure, and the shortfall is demand on unmetered
     nodes, so it reads a few per cent low.

**Found and not added:**
- **Asfordby Colliery.** A New 20.24 MW Table 3 row sits at 33 kV bars no LTDS transformer feeds. The infeed cannot
  reach it, so it is recorded (2 × 8.62 MW at the current peak). NGED's 2025 flows carry no Asfordby node and 0.15 MW
  mean on its 132 kV feeders: consistent with leaving it out.
- **Cotham Grange PV.** A 0.14 MW stale 33 kV demand row, likewise unreachable. The PV itself connects at 132 kV in
  NGED's 2025 model.
- **Bourne West 25 kV** (BYTH8_MAIN2). NGED's series is exactly 0 on all 17,520 half-hours of 2025, beside Wrangle at
  Bicker Fen. Whether it is out of use or unmetered is not established from the published files.
- **The Checkerhouse–Hawton corridor** (Section 5).

**Built: 130.45 MW.** Against the 147.82 MW peak, the other 17.37 MW is the unreachable rows. The coincidence scaling
is applied before they are removed and is not redone.

## 5. The shared model question: a 33 kV tie between two BSPs, at both supply points

- **Bicker Fen:** the Sleaford–Grantham cluster. The two Sleaford 33 kV ties carry about 2 MW more or less than
  NGED's model, with the Sleaford and Grantham 132/33 kV transformers offset to match.
  - Neutral experiments: the L0 experiment moved the cluster by at most 0.001 MW.
  - A partial experiment: Sleaford's transformers at their neighbours' impedance halve every offset (Work 16a).
- **Staythorpe:** the same signature on the 33 kV path Checkerhouse – Ollerton tee – Bevercotes – Tuxford – Cobb Farm
  tee – Carlton-on-Trent – Hawton.
  - Offsets of 1–2 MW (95th percentile 4–7 MW) along it.
  - Hawton's and Checkerhouse's 132/33 kV transformers at +0.55 to +0.59 MW each, within 5% of rating on 85% of
    half-hours.
  - These four transformers are the four rule-2 failures left.

So it is no longer a Bicker Fen oddity: two supply points show a BSP-to-BSP 33 kV tie that NGED's model loads
differently by about 2 MW. The cause is not established from the published files. The candidates, as at Bicker Fen:
- the BSP transformers' impedances or tap positions;
- the derived injections on the BSP busbars (both supply points' BSP 33 kV node series are group totals, not
  injections).

## 6. The study basis: firm plant at winter peak

The winter-peak case runs firm plant (non-weather, non-battery generation) at full output, at both supply points.
2026, Holistic Transition, winter peak:

| | Firm plant | Import, firm at full output (the study basis) | Import, firm at nil |
|---|---|---|---|
| Staythorpe | 72.2 MW | 70.8 MW | **143.6 MW** |
| Bicker Fen | 9.2 MW | 147.9 MW | 157.4 MW |

At Staythorpe, with firm plant at nil, the case imports 143.6 MW, and the measured 2025 maximum is 142.1 MW. **On the
one day it mattered, the firm plant was not there.** Whether the winter-peak case should credit it is the owner's
decision about the study basis. Nothing changes here. At Bicker Fen the firm plant is small, so the same rule passed
unnoticed.

## 7. The plan years, on the metered peak (Holistic Transition, the planning cases)

| Year | Converges | Breaches | Worst line / transformer | Voltage (pu) | Import / export (MW) |
|---|---|---|---|---|---|
| 2026 | yes | none | 92.8% / 85.0% | 1.008–1.029 | 70.8 / 161.8 |
| 2027 | yes | none | 92.8 / 87.7 | 1.006–1.029 | 79.1 / 161.8 |
| 2028 | yes | 1: Tuxford 134% | 92.8 / 134.0 | 1.005–1.029 | 90.7 / 161.8 |
| 2029 | yes | 1: Tuxford 171% | 92.8 / 170.8 | 1.004–1.029 | 103.9 / 161.8 |
| 2030 | yes | 1: Tuxford 176% | 92.8 / 176.4 | 1.005–1.029 | 117.9 / 161.8 |
| 2031 | yes | 1: Tuxford 185% | 92.8 / 184.6 | 0.990–1.029 | 133.4 / 161.8 |
| 2032 | yes | 6 transformers | 92.8 / 196.9 | 0.990–1.029 | 150.8 / 161.8 |
| 2033 | yes | 6 transformers | 92.8 / 258.1 | 0.951–1.029 | 168.4 / 161.8 |
| 2034 | no valid operating point (the solver's solution is a voltage collapse) | — | — | — | — |
| 2035 | no (winter peak) | — | — | — | — |

- **The B–C circuits** (lines 131, 133, 134; 600 A) carry 9.1 / 8.8 / 2.8% at winter peak and 38.1 / 36.9 / 11.7% at
  summer minimum in 2026. Since the connector rule, the twin shares equally with its partner, as NGED's model has it.
- **2034 and 2035 are not a failure of the method.** They are what the growth asks of this network:
  - DFES Holistic Transition grows several primaries steeply: Tuxford ×5.2 by 2035, two other primaries ×5.3 and
    ×3.7, the rest mostly ×1.5–2.9.
  - With the winter-peak load at Tuxford, Westborough and the Hawton group several times their 2026 figure, the 33 kV
    network behind Tuxford reaches voltage collapse.
  - The 2034 winter-peak solve converges to the low-voltage solution of the equations (Tuxford 11 kV at 0.26 pu): a
    voltage collapse, not an operating point. No loading or breach count from it means anything, so none is quoted.
    Since Work 18 the engine reports it as such: "no valid operating point", below the 0.5 pu collapse floor.
  - *Corrected:* the 0.05 pu quoted earlier was the summer-minimum case. It was solved after the collapse, starting from
    the collapsed winter state's voltages and tap positions. That shows how such a solution contaminates what follows
    it.
  - Read 2034 and 2035 as "no valid operating point under that growth".
  - *An observation about the engine, not a change:* nothing in it tells a collapsed solution from a valid one, so a
    plan year could report breaches from one. At Bicker Fen it has not arisen (the owner's list).
- **Westborough:** within its rating to 2033 (64.5% in 2026, 79.2% in 2030), then over.

## 8. The grown years, on Staythorpe's own 2025 flows (uniform multipliers, as at Bicker Fen)

| | 2025 measured | 2030 HT | 2035 HT |
|---|---|---|---|
| Half-hours solved | 17,520 (100%) | 17,520 (100%) | 17,372 (99.2%) |
| Reliable elements over rating (hours) | Tuxford 166 h | Tuxford 4,911 h (344%); Hawton GT1/GT2 618/614 h (136%); Westborough 15.5 h; Hallcroft Road ×2 5.5/4.5 h; Bevercotes–Tuxford 1.5 h | Tuxford 7,485 h (871%); Hawton GTs 4,152/4,139 h (226%); Westborough 3,019 h; Bevercotes–Tuxford 2,498 h; Hallcroft Road ×2 2,247/2,216 h; Bingham T2 646 h; Hawton 11 kV 3T0 ×2 611/523 h; Checkerhouse GTs 501/495 h |
| Busbars out of band | none | none | Tuxford 33 kV 293 h, 11 kV 278 h (down to 0.73 pu); Cobb Farm tee ×2 133 h; Pole 89ZTXA41 96 h; Swinderby, Carlton-on-Trent ×2 about 10 h |
| Above firm capacity (primaries that publish one) | Hawton 11 kV 0.5 h | Hawton 11 kV 1,785 h; Hallcroft Road 626 h; Newark Junction 1.5 h; Southwell 0.5 h | Hawton 11 kV 5,744 h; Hallcroft Road 5,094 h; Newark Junction 1,373 h; Southwell 977 h |
| Import peak / export peak | 142.3 / 97.8 MW | 211.5 / 81.2 | 316.0 / 65.8 |
| Import above the seasonal limit, both SGTs (one SGT out) | 0 h (0) | 0 h (496 h) | 0.5 h (3,458 h) |

- **Unsolved half-hours in 2035** (148): winter mornings, 07:00–10:00 mostly, January most (78), then February and
  November (29 each) and December (12). This is the same collapse behind Tuxford. Not forced.
- **Labels** are judged on Staythorpe's 2025 reference. The Hawton and Checkerhouse GTs carry "flow differs" (Section
  5).
- **Runs:**
  - `grown-2030-ht.npz`, sha256 `3906496589d61fc35d56acf506578905da6c861ce1343ff1ce91af437b298d84`;
  - `grown-2035-ht.npz`, sha256 `15fece6e830cb080a3d98d824488ab01abc69ad54ac65b126ff2ea678088e38a`.
  - Both were solved before the mapper stopped matching the one connector column; the injections differ by 0.01 MW
    at most.
- The same limits as Bicker Fen's grown years apply: 2025's shape at a future demand; one weather year; hours as an
  order of magnitude.

## 9. The three shared substations, from both sides, and what joining would need

- **Grantham North 132 kV** (Bicker Fen and Staythorpe): one board in four sections, split by two couplers.
  - *Bicker Fen's half:* MAIN1 and MAIN2B. It carries the two circuits from Grantham 132 kV and the two 132/25 kV
    railway transformers (24 MVA each). NGED's flows show the railway drawing exactly what the Grantham circuits bring
    (mean 0.15 MW, at most 3.6 MW).
  - *Staythorpe's half:* MAIN2A and MAIN3. It carries the 132/11 kV GT3 (fed from the Cotham Grange tee) and GT4 (fed
    from Staythorpe B), about 3.3 MW each on average.
  - *The couplers:* MAIN1–MAIN2A is in Bicker Fen's LTDS rows and MAIN2B–MAIN3 in Staythorpe's. Neither half's flows
    cross them; both are open in normal running.
- **Boston 132 kV and Tattershall 33 kV** are shared with Walpole, not Staythorpe. Seen only from Bicker Fen's side: its
  sections end at open couplers, and Walpole's sections are filed under Walpole. A connector row between two of
  Bicker Fen's own Boston sections is now a connector (Section 4).

**Joining two supply points into one model would need:**
- the two halves of each shared board in one network, with their couplers as switches (open in normal running);
- two infeeds, one per supply point. Closing a coupler then parallels two GSPs through the 132 kV, and the flow
  through it is set by the transmission network between Bicker Fen's and Staythorpe's 400 kV substations: their
  voltage angle and the impedance between them.

That transmission equivalent is not in the open data. Without it, a joined model is only valid with the couplers open,
which is the same as two models side by side. A transfer or outage study across the coupler needs the transmission
equivalent first.

## 10. What it took, as a method for a third supply point

**The fourteen Bicker-Fen-specific items, at Staythorpe:**

| Item | Needed an entry? |
|---|---|
| LTDS group name; Table 5 and ECR spellings; flows and bus-map name; loading resource ids | Yes: held exactly ("Staythorpe  C  132Kv S Stn", two spaces) |
| Supergrid transformer limits | Yes, from its own Td Limits |
| Map centre, OSM search box | Yes, from its published ECR coordinates (positions only) |
| Supply-point peak | Yes, and a different kind: NESO's figure failed the coincidence guard; NGED's metered peak, tested at Bicker Fen first |
| `REMOVED_IN_ERROR` | No: its Removed rows (Asfordby 132 kV, Carlton-on-Trent T1) are consistent with NGED's flows |
| `GENERATION_SITES` | No (not studied: no Table 5 total was split onto feeders) |
| `ECR_ADDITIONS` | No |
| `HELD_AT_ZERO` | No |
| `YEAR_SHAPES` | No (no branch years run at Staythorpe) |
| `TRANSMISSION_PROJECTS` | No (none recorded) |
| Run catalogue | Not added (the owner's decision) |

**Three new kinds of entry it needed:** the infeed node, a BSP alias and a normally-open point.

**Five general changes it prompted**, each shown neutral or bounded at Bicker Fen:
- the DFES name rule (RD as ROAD, search on the first token);
- the infeed from the published site;
- unreachable elements recorded, not dropped unseen;
- the coincidence guard;
- the connector rule.

Plus one screen, `possible_bsp_aggregate`.

**The commissioning steps, in the order they turned out to be needed:**
1. Fetch the snapshot with the record's exact spellings, keeping it apart from the bundled one.
2. Before solving anything:
   - where the published limits table puts the infeed;
   - whether the build is one island from it, with what it would drop listed;
   - whether any circuit leaving the group carries flow in NGED's own files.
3. Build with an empty exceptions record. The guards stop a peak that cannot describe the group. The aggregate
   screen points at BSP rows counted as demand.
4. If the published peak fails: NGED's metered coincident peak, valid only once checked at a supply point where the
   answer is known.
5. The measured year against NGED's flows:
   - the radial rule and closure first, since they catch mapping errors;
   - then the zero-flow criterion for open points the LTDS does not publish;
   - then the rule-2 and rule-3 residue, which is model differences, not mapping.
6. Each exception goes into the record only with a published row or file behind it. Everything else is listed.

## Files

- **Code:** `nged_points.py` (STAYTHORPE), `nged.py` (infeed, guards, alias, open points, connectors, the screen),
  `nged_flows.py` (connectors not compared), `runs.py` and `network.line_loadings` (out-of-service lines carry
  nothing), `gridmodel.py` (connectors drawn as joined); pipeline `defs/supply_points.py` (`staythorpe_snapshot`).
- **Report scripts, in this folder:**
  - `topology_facts.py`, `build_and_plan.py`, `metered_peak.py`;
  - `run_2025.py`, `commission.py` and `rules.py`, `l0_experiment.py`;
  - `grown.py`, `grown_analyse.py`;
  - each writes its JSON beside it.
- **Runs**, in `apps/pipeline/warehouse/supply-points/staythorpe/`: the reference and its two predecessors (`-run1`,
  `-run2`), the L0 experiment, and the two grown years.
