# forecast: learning how the grid actually behaves

A side project inside the Gridify repo, kept apart from the backbone (`packages/optimizer`, `apps/*`) until it earns its
place. **Status: not started.** This brief states the problem, the data that exists and the open questions. It does not
answer them: the first session does, and rewrites this file with the decisions and their reasons.

## The problem

Gridify judges a plan on two assumed snapshots per year (winter peak, summer minimum), built from published growth
factors and planning dispatch rules. Planners already have that picture. What they lack is **how the grid really behaves**:
when an element is close to its limit, how often, why, and how that changes as connections land and demand grows.

The idea is a model that learns those patterns from observed data. It is only worth building if a prediction **changes a
decision**, so start from the decision, not the model.

## Open question 1: what do we forecast, for whom, and what decision does it change?

Candidate targets (not exclusive; pick a first one):

| Target | Who decides | Decision it changes | How it could be validated |
|---|---|---|---|
| Hours each circuit / transformer is near or over its limit, year ahead | DNO planner | Where and when to reinforce | Year-ahead backtest (GSP level only today, see below) |
| Curtailment hours for a new connection on a flexible offer | Developer, DNO connections team | Connect now on a flexible offer vs wait for reinforcement | Indirect: the flows it is computed from |
| Hidden demand and generation behind a net flow (disaggregation) | Planner, DFES | What drives the peaks; growth masked by rooftop solar | The live feed's solar / demand split |
| Next-day net flow at a substation | Control room | Operations, not planning (crowded field) | Easy, but low novelty |

Ground rules that hold whatever is chosen: the model produces **inputs or estimates with uncertainty**; network feasibility
stays deterministic power flow (Gridify); every figure states its training window; real data, sources cited.

## The data (checked on NGED's Connected Data Portal, 2026-10-16)

| Dataset | Span | Resolution | Nature | CKAN |
|---|---|---|---|---|
| Substation loading, every node of the Bicker Fen group | 2024 only | half-hourly | Derived by NGED (PSS/E + sensitivity factors), cleansed, outages imputed; MW and MVAr per bus; demand +, generation − | dataset `substation-loading`, resource `c95d6700-9728-42b3-ac99-f8762b17954c` (CSV download) |
| Branch loading, 164 circuits | 2024 only | half-hourly | Derived from the substation loading | dataset `branch-loading`, resource `d82aeab2-25f2-4157-98ac-ae0412a8b97d` |
| Bus index (bus numbers ↔ LTDS names) | n/a | n/a | | dataset `curtailment_buses`, resource `6ba4ccd6-a9f8-405e-a3cf-45c79de9f16e` |
| Supergrid transformer flows, Bicker Fen GSP | 31 Mar 2022 to 31 Mar 2023 | half-hourly | Per transformer: import, generation, demand, voltage. The download URL is redacted; read it through `datastore_search` | dataset `super-grid-transformer-flows-east-midlands`, resource `9ab7426c-e0a9-49bd-9e9e-611ff902b5a6` |
| Live GSP data, Bicker Fen | rolling last ~6 hours | 5-minute | Net demand, generation, import, solar, wind, STOR | dataset `live-gsp-data-east-midlands`, resource `6808c948-f326-43a4-9095-85a1f31fd123` |
| Generic generator profiles, Bicker Fen | 2024 | half-hourly | NGED's own per-unit profiles (wind, PV, BESS, other): an assumption, not an observation | dataset `generic-generator-profiles`, resource `29fcc7f5-cea6-4b8f-8b50-57b61e2b8939` |
| LTDS, ECR, DFES | editions | | Already bundled in Gridify (`gridify_optimizer.nged`) | |

The same curtailment datasets exist for 45 GSP groups; the live and SGT datasets for the 15 East Midlands GSPs. Guidance:
https://dso.nationalgrid.co.uk/downloads/15104/nged-curtailment-analysis-data-usage-guidance.pdf. Not yet looked for:
weather history (Open-Meteo, ERA5, Met Office), NESO GSP-level or national demand and embedded-generation estimates, older
NGED editions.

## Open question 2: how do we validate?

What the data allows, honestly:
- **Across years, at node level: not with open data.** Substation and branch loading cover 2024 only.
- **Across years, at the GSP: yes.** Train on the SGT flows (2022/23), predict 2024, with the ECR telling what connected in
  between: a true year-ahead backtest. Caveat: metered transformer flow vs NGED's derived series are not the same quantity,
  so reconcile them first.
- **Across places:** the same datasets for 45 GSPs. Train elsewhere, test on Bicker Fen (and the reverse): does the model
  learn grids, or memorise one?
- **Within 2024:** blocked by month (leave-one-month-out), never random half-hours (neighbouring half-hours leak).
- **Going forward:** archive the live 5-minute feed from now on; in a year it is a genuine out-of-sample test set.
- **Against baselines:** last year's profile (what DNOs use) and NGED's generic profiles. Error measured where planning
  cares (peaks, minimums, hours over a threshold), not only on average.

## The other open questions

3. **Inputs.** Calendar, weather, the connected fleet per substation (ECR), lags; what is knowable at forecast time.
4. **Model.** Baselines first; anything richer only if it beats them on the chosen metric.
5. **Output.** Follows from question 1: a number, a profile, a distribution, hours over a limit.
6. **Structure.** Where the code lives under `forecast/` and how it is run; whether it ever joins the pipeline or the
   engine is a later decision.
