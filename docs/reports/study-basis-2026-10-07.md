# Study basis: what the standards and the DNOs do, and what GridForge does

*7 October 2026. Sources read in full where the host allowed an automated fetch (NESO, Ofgem, Electricity North West, SSEN's curtailment note, NGED's open-data portal). SP Energy Networks, SSEN's plan pages and NGED's document pages block automated fetches; the ENA's own P2/8 and EREP 130 texts are behind a login, so those rest on Ofgem's decision documents.*

This note exists so the engine's study basis is defensible to a DNO reader, and so a change to it needs a source first (AGENTS.md rule 4). The README's *Sources and assumptions* register carries the one-line citations; this is the long form.

## 1. The two planning conditions

**What the SQSS says** (NETS Security and Quality of Supply Standard v2.13, NESO, 2 October 2026):

- Table 6 (b), *Voltages to be Achievable at Interfaces to Distribution Networks and Non-Embedded Customers*: "1.05pu at forecast Group Demand, 1.00pu at forecast Minimum Demand or as otherwise agreed with the relevant network operator".
- *Forecast Minimum Demand*: "the minimum demand level expected at a GSP ... Unless more specific data are available, this is the expected demand at the time of the annual minimum demand on the national electricity transmission system as provided under the Grid Code."
- Generation connections (2.5): the loss of power infeed is the generation lost "less the forecast minimum demand disconnected from the system by the same event".
- *Security Planned Transfer Conditions*: "Generation powered by intermittent sources (e.g. wind, wave, solar) and imports from external systems are not included in this condition."
- The economy condition scales plant instead (ETYS 2025 Appendix H, Table H1.2): interconnectors importing 100 %, nuclear 85 %, CCS 85 %, wind 70 %, tidal and wave 70 %, pumped storage 50 %.

**What the DNOs do** (Electricity North West, Network Headroom Report, August 2021; NDP methodology, May 2026):

- Demand headroom: "The forecast peak demand for each year up to 2034/2035 ... is compared to the existing firm capacity of each EHV substation"; interventions "when thermal capacity exceeds existing firm capacity ratings", aligned with Ofgem's Load Index 5; the network is located where "network parameters exceed limits including thermal, voltage and fault level"; fault levels are studied "for each future year"; "the transmission system is assumed to remain constant".
- Generation headroom: "reverse power thermal assessments which consider the network when all DG is operating when our customers are consuming the least amount at the time of minimum demand", plus a fault-level headroom per technology (inverter, synchronous, battery).
- Security credit for generation: "An allowance for the contribution of local generation to security of supply is modelled following EREC P2/8 ... typically significantly less than the sum of the generators' rated capacity values."

**GridForge**: winter peak (grown demand, intermittent generation at nil, batteries charging) and summer minimum (measured minimum demand, everything at full output), plus the GSP export limit. This is the SQSS's pair of interface conditions and the DNOs' pair of headroom studies. No generation is credited towards firm capacity (conservative against EREP 130).

## 2. Minimum demand over the years

- Ofgem's LTDS Capacity Heatmaps Information Model (April 2024): `demandMinimum` is "a normalised value calculated using historic measured values during normal operating conditions. The data represents net demand corrected for any generation at the substation"; circuits and transformers carry `summerRating` and `winterRating`; a transformer's rating may differ by direction ("11->33 is different from 33->11 for reverse powerflow"); a substation carries `reversePowerFlowTotalCapacity` and `reversePowerFlowAvailableCapacity`.
- NGED's LTDS Table 3 publishes a "Minimum demand Scaling Factor (%)" per primary (47.64 % on Bicker Fen's rows) and a five-year maximum-demand forecast ("Forecast Year 1" to "Forecast Year 5").
- ENWL's Technical Limits curtailment forecast builds the year from "Previous year HH observed flow" and adds contracted generation on top: the demand baseline is last year's observation, not a grown figure.
- NESO's Summer Outlook 2025 expects transmission demand to fall below the 2020 lockdown record because of embedded solar.

**GridForge**: the summer minimum is each load's LTDS factor × its maximum, held flat over the plan years. The moving part of the export problem is the generation connected, which the queue and the branches model. Scaling the summer minimum with peak growth has no basis in these sources.

## 3. What generation to assume at minimum demand

| Source | PV | Wind | Batteries | Other |
|---|---|---|---|---|
| ENWL headroom report | all DG operating | all | all | all |
| SSEN Technical Limits (curtailment) | 1.0 in summer, 0.8 spring and autumn, 0.2 winter, 10:00 to 16:00 | full export | export 06 to 10 and 18 to 21, import 23 to 06 | full export all day and season |
| ESO factors as ENWL applies them (curtailment) | 0.84 at summer minimum with solar at its maximum, 0.33 with solar at its minimum, 0.2 at winter peak | 0.5 / 0.1 / 0.7 | 1 | waste and CHP 0.85, hydro 0, other 0.3 |

**GridForge**: full output, the headroom test. The ESO factors are the recognised softer view for an expected-flow or curtailment estimate; they would be a third, informational case, not a replacement of the verdict.

## 4. Fault level

- Ofgem's Form of LTDS, Table 4 *Fault Level Information*: system impedance (R, X, % on 100 MVA), existing system fault currents (peak make, rms break, kA) and the rating (make, break, kA), "for nodes with switchgear installed"; "Calculated fault currents should include all relevant contributions from synchronous and induction machines as well as other parts of the distribution network and other connected networks"; the method must describe "the application of engineering recommendation G74".
- NGED publishes Table 4 (resource `3bd0243c-71dd-4cdd-9ca9-57e6eb79d61f`): 268 rows for the Bicker Fen group, 47 busbars at 132, 33, 25 and 11 kV, with NGED's own make and break currents and the published ratings. Make ratings are 38.25 kA at 132 kV and 32.75 kA at 33 and 11 kV on most rows; break ratings are published on 159 of 268 rows. On several busbars the published current already sits above the published rating (Skegness 33 kV, 19.1 kA break against 13.1; Sleaford 33 kV, 15.8 against 11.4; Bicker Fen 132 kV, 14.1 against 10.0): reported as published, flagged as a data caveat, never silently corrected.

**GridForge**: a fault-level screen is the one DNO check the engine lacked; it is built in this pass as an informational study (IEC 60909 via pandapower, the transmission infeed from the published 132 kV system impedance, inverter generation as current sources, synchronous generation by a stated sub-transient reactance), validated against NGED's own Table 4 currents and reported with its headroom per busbar.

## 5. Forecasts

- The DFES is scenario work per supply area, not network work: NGED's DFES scope note says "the DFES does not include analysis of network loads, load profiles or peak demand etc. This network load analysis is run by WPD network strategy and planning teams." ENWL runs its network impact assessments on DFES forecasts per substation, year by year.
- NGED publishes DFES 2025 *Power Projections* per Electricity Supply Area (one per primary) and scenario (Counterfactual, Holistic Transition, Electric Engagement, Hydrogen Evolution), winter peak MW for every year 2025 to 2040 then 2045 and 2050. Summed over Bicker Fen's 21 primaries (non-coincident): Holistic Transition ×1.21 by 2030 and ×1.82 by 2035 on 2026; Counterfactual ×1.10 and ×1.31; Electric Engagement ×1.22 and ×1.79; Hydrogen Evolution ×1.18 and ×1.73.
- The GB-level FES multipliers the engine used until now (×1.08 by 2030, ×1.35 by 2035) sit at the DFES Counterfactual, and the per-bus shape was a seeded heuristic.

**GridForge**: the four demand profiles become NGED's four DFES scenarios per primary; the seeded per-bus shape goes. Loads with no supply area (customer connections, the BSP aggregates) follow the LTDS five-year forecast, then hold.

## 6. Observed flows (NGED half-hourly series, 2024, Bicker Fen)

NGED publishes derived half-hourly net flows per substation node and branch ("calculated using the substation loading and sensitivity factors ... PSS/E"). Against the engine's two cases:

| Quantity | Observed 2024 | Engine, planning case |
|---|---|---|
| Net flow at the Bicker Fen 132 kV busbar | 278 MW export max, 49 MW import max | 301 MW export at summer minimum, 138 MW import at winter peak |
| Bicker Fen to Boston circuit, flow towards the GSP | 85 MW max | 106 MW at summer minimum |
| Bicker Fen to Boston circuit, flow towards Boston | 27 MW max | 26 MW at winter peak |

The demand side matches the observation almost exactly. The export side is the planning extreme, every generator at full output at the measured minimum, 8 % above the observed GSP maximum and 25 % above the observed circuit maximum. The winter import figure is the SQSS security condition (no wind credited), not an observation: with 180 MW of wind on the group, the observed net import at peak is a third of the planning figure.

## 7. Tools

- PowerFactory Contingency Analysis: "n-1, n-2, n-k", "single and multiple time phase consideration" with "thermal (short-term) ratings", "Remedial Action Schemes", "time-sweep calculation", "planned outages, Network Variations and Expansion Stages". Quasi-Dynamic Simulation: "a series of load flow calculations carried out at specified time intervals ... particularly suitable for planning studies in which long term load and generation profiles are defined".
- PowerFactory hosting capacity (ICA): per node, the maximum additional generation or load, "the limiting component (node, line, transformer,...) is reported, as well as the violated constraint"; scenarios such as "different switch states or seasonal conditions".
- Siemens PSS SINCAL ICA: "special operation points, such as minimum loading while maximum generation is effective, or maximum loading while minimum generation", or profiles with min and max days; checks thermal loading, voltage limits, voltage fluctuation and short-circuit withstand.
- California ICA: 576 hourly profiles (a peak and a minimum day per month), results with reverse flow allowed to the substation busbar and with none; FERC's small-generator process adds a 100 % of minimum load screen.
- ENWL: IPSA for 132 and 33 kV, a bespoke tool for HV and LV.

**GridForge**: the same two snapshots per year, an N-1 screen with post-fault re-regulation and emergency ratings, a binding set with the limiting element and the violated constraint. Time series would only be needed for a curtailment estimate.

## Decisions taken in this pass

1. Keep the summer minimum at the LTDS factor, never scaled with peak; say so in the product.
2. Keep full output as the verdict case; the ESO factors stay an optional view.
3. Keep N-1 informational for generation (a generation connection is non-firm under an outage by default).
4. Build the fault-level screen as informational, validated against NGED's Table 4.
5. Replace the GB-level multipliers and the seeded per-bus shape with NGED's DFES per primary; keep the LTDS five-year forecast for loads without a supply area.

## Links

NETS SQSS v2.13: https://www.neso.energy/document/388176/download (code page: https://www.neso.energy/industry-information/codes/security-and-quality-supply-standard-sqss/sqss-code-documents). ETYS 2025 Appendix H: https://www.neso.energy/document/383971/download. Ofgem LTDS direction: https://www.ofgem.gov.uk/publications/long-term-development-statement-direction; Form of LTDS: https://www.ofgem.gov.uk/sites/default/files/2024-04/Form%20of%20Long%20Term%20Development%20Statement%20300424.pdf; Capacity Heatmaps Appendix 1: https://www.ofgem.gov.uk/sites/default/files/2024-04/Capacity%20Heatmaps%20Appendix%201%20-%20Information%20Model.pdf. Ofgem on P2/8: https://www.ofgem.gov.uk/sites/default/files/2023-02/FINAL_DCRP2203%20Engineering%20Recommendation%20P2.pdf; on EREP 130: https://www.ofgem.gov.uk/publications/dcrpmp1902-revision-engineering-report-erep-130-guidance-application-p2-security-supply. ENWL Technical Limits: https://enwl.co.uk/globalassets/get-connected/connections-gif-images/technical-limits-enwl-methodology.pdf; ENWL Network Headroom Report 2021: https://www.enwl.co.uk/globalassets/get-connected/network-information/dfes/archive/network-headroom-report-2021.pdf; ENWL NDP methodology 2026: https://www.enwl.co.uk/globalassets/get-connected/network-information/network-development-plan/ndp/sp-enw-ndp-methodology-2026.pdf. SSEN curtailment methodology: https://ssen.co.uk/globalassets/ssen-curtailment-methodology-for-technical-limits.pdf. NGED open data (CKAN): LTDS tabular model `ltds-tabular-model` (Table 4 resource `3bd0243c-71dd-4cdd-9ca9-57e6eb79d61f`), DFES `dfes` (Power Projections resource `7686c0a8-bde8-4a4b-8f26-50a3317882ee`), Bicker Fen substation loading `c95d6700-9728-42b3-ac99-f8762b17954c`, branch loading `d82aeab2-25f2-4157-98ac-ae0412a8b97d`, bus index `6ba4ccd6-a9f8-405e-a3cf-45c79de9f16e`; DFES scope note: https://nationalgrid.co.uk/downloads-view-reciteme/228130. NESO Summer Outlook 2025: https://neso.energy/news/preparing-low-electricity-demand-2025-summer-outlook. DIgSILENT: https://www.digsilent.de/en/contingency-analysis.html, https://www.digsilent.de/en/quasi-dynamic-simulation.html, https://www.digsilent.de/en/paper-reader-pf-en/indicative-capacity-analysis-automated-calculation-of-hosting-capacity-of-distribution-networks-for-distributed-energy-resources-and-additional-loads.html. Siemens PSS SINCAL ICA datasheet: https://assets.new.siemens.com/siemens/assets/api/uuid:d30d49557176528d935ec035d8499ac26d083822/11-ica-module-datasheet-sincal-ag.pdf. CPUC ICA: https://docs.cpuc.ca.gov/PublishedDocs/Published/G000/M196/K747/196747754.PDF.
