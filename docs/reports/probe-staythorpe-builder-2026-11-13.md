# Probe: the network builder on Staythorpe, unchanged

*13 November 2026, Work 14. Decided by the guide session overnight, for the owner to confirm. A probe, not a build: a
throwaway script in the session's scratch folder, outside the repository and git. Nothing from it enters the product,
the bundled snapshot or the pipeline's data. The first step of `scoping-second-supply-point-2026-11-13.md`. Supported by
NGED Open Data.*

**The question.** Does `nged._build` (the builder, as it stands) build a network from another supply point's LTDS tables?

**The finding that matters most: a silent wrong answer.** Before it failed, the builder scaled Staythorpe's demand to
**Bicker Fen's** supply-point peak (`GSP_PEAK_DEMAND_MW`, 149.2 MW; NESO gives 258–264 MW for Staythorpe). It gave no
warning. Had the hard failure below not stopped it, the result would have been a plausible network with demand about
40% too low.

**Answer: no.** It fails partway, on one of the Bicker-Fen-specific items, and the brief was to stop at the first
failure. Everything before that step ran without error.

## What was fetched

The same NGED resources as Bicker Fen's bundled snapshot, filtered by Staythorpe's own spellings. The ECR kept only the
pipeline's `ECR_KEEP` columns (no names, addresses, postcodes or MPANs). DFES rows were matched by name with the engine's
own `dfes_esa`.

| Table | Rows | Note |
|---|---|---|
| Table 1 circuits (`GSP Group` "Staythorpe 132kV") | 432 | |
| Table 2a two-winding transformers | 40 | |
| Table 2b three-winding transformers | 0 | the builder does not read Table 2b; it did not matter here |
| Table 3 demand | 50 | 21 Unchanged, 18 New, 8 Updated, 3 Removed |
| Attachment 8 nodes | 422 | |
| Table 4 fault levels | 264 | |
| Table 5 generation ("Staythorpe  C  132 kV S Stn") | 15 | |
| ECR ("Staythorpe  C  132Kv S Stn") | 143 | |
| DFES power projections | 1,292 rows | **17 of 35** Table 3 names matched a supply area |

**The DFES matching is the first gap.** Of the 18 names that did not match, 14 are generation sites with their own
demand rows (solar farms, the Daneshill and Bowbridge sites, Hawton Wind Farm, Low Farm AD). Four are demand primaries:
Carlton-on-Trent, Hallcroft Road, Ordsall Road and Asfordby Colliery. Without a supply area they would grow by the
fallback, not by NGED's DFES. At Bicker Fen every demand primary matched; this is the name matcher meeting new names.

## What happened, step by step

| Builder step (`_build`) | Result |
|---|---|
| Node merging, buses | ran |
| Lines (Table 1), seasonal ratios | ran |
| Transformers (Table 2a) | ran |
| Loads (Table 3), DFES growth, BSP coincidence | ran, **using Bicker Fen's GSP peak** (`GSP_PEAK_DEMAND_MW` = 149.2 MW; NESO's figure for Staythorpe, STAY_1, is 258–264 MW): wrong silently |
| Existing fleet (Table 5, with `GENERATION_SITES`) | ran; no Bicker Fen site matched, so harmless |
| Small embedded generation (ECR) | ran |
| **ECR additions (`ECR_ADDITIONS`)** | **failed**: `KeyError: 'BICF1_MAIN1'` in `nged._bus_of` (`nged.py` line 758, called from `_add_ecr_additions`, line 765). Ash Farm is placed at a Bicker Fen 132 kV node that Staythorpe's tables do not have |
| GSP infeed and boundary | not reached; it would have labelled the net "Bicker Fen GSP" with Bicker Fen's limits |
| Planning cases | not reached |

So the counts of buses, lines, transformers, loads and generators, and the two planning cases, are not available: the
builder returns nothing until every step has run.

## The fourteen Bicker-Fen-specific items, against this probe

| Item | Bit? |
|---|---|
| `ECR_ADDITIONS` (Ash Farm) | **Yes: the hard failure** |
| `GSP_PEAK_DEMAND_MW` | **Yes, silently**: Staythorpe's demand would be scaled to Bicker Fen's peak, about 40% too low |
| DFES name matching (general code, new names) | **Partly**: 4 demand primaries unmatched |
| `GSP_BOUNDARY` | Would have (not reached): wrong name and limits on the net |
| `GENERATION_SITES` | No: keyed by Bicker Fen's BSPs, so nothing matched (Staythorpe's own split of Table 5 onto feeders is simply absent) |
| `REMOVED_IN_ERROR` | No: keyed by a Bicker Fen node. Whether any of Staythorpe's 3 Removed demand rows is live would only show in its half-hourly flows |
| `LTDS_GSP_GROUP`, `ECR_GSP`, the Table 5 spelling | Bit at the fetch (three spellings), not in the builder |
| `GSP_CENTER`, `OSM_BBOX`, coordinates | Not reached; positions only, no effect on physics |
| `TRANSMISSION_PROJECTS` | Not reached; context only |
| `YEAR_SHAPES`, `HELD_AT_ZERO` | Not used by the builder (half-hourly work only) |
| Bundled snapshot directory, `NgedSource`, `nged_runs.CATALOGUE` | Not used: the probe passed tables in directly |
| The slack (`_add_gsp_infeed`) | Not reached |

## What it says

- The builder's general machinery reads another supply point's tables without complaint: nodes, lines, transformers,
  loads and Table 5 fleet.
- It is stopped by a named exception written for Bicker Fen, applied unconditionally.
- Had it not been, it would have scaled demand to the wrong supply point's peak without a word, which is the more
  dangerous of the two.
- Both point the same way as the scoping note: these items belong in a per-supply-point record that the builder reads,
  not in module constants. That is the parameterised source the note describes.
- No step of the probe was made to work around the failure.
- The probe script and its tables stay in the session's scratch folder.
