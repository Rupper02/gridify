# Gridify — data pipeline

The **`apps/pipeline`** slice of Gridify: a [Dagster](https://dagster.io) asset graph that turns NGED's open data for the Bicker Fen GSP into a validated, **versioned** warehouse, which the API serves.

The warehouse tables (buses, lines, transformers, loads, generators, the registry) are the grid-agnostic format the API
reads, and the asset checks are the gate a network must pass before it is served: it references only what exists, it is
one connected network, and its power flow converges. NGED is the one source wired in today; another operator's grid
would be another asset group writing the same tables through the same checks (see the root README's roadmap). For the whole system see the [root README](../../README.md); for the engine see [`packages/optimizer`](../../packages/optimizer/README.md).

---

## Two asset groups

### `ltds` — the model (`src/grid_simulator/defs/nged.py`)

```
 ltds_tables ──┬─► nged_model_canonical ──┬─► served_nged ──► DuckDB warehouse
  (bronze:     │   buses/lines/trafos/     │                 buses · lines · transformers · loads · regions ·
   the pinned  │   loads/fleet/regions     │                 generators · candidate_projects ·
   snapshot)   ├─► nged_registry ──┤                 ltds_changes · ltds_change_summary ·
               │   the optional registry   │                 snapshots (append-only history)
               └─► ltds_edition_changes ───┘
                   previous vs current edition

 asset checks on nged_model_canonical:
   power_flow_converges      ERROR  both study cases solve (blocking); WARN if today's grid breaches a limit via the engine's `feasibility` (band, overload, GSP)
   referential_integrity     ERROR  every line/trafo/load/generator endpoint and every valid registry bus exists (blocking)
   single_connected_network  WARN   one island, across lines AND transformers
```

| Asset | What it does |
|---|---|
| `ltds_tables` | Loads the pinned snapshot: LTDS circuit, transformer (`t2a`), demand, node and generation tables, the Embedded Capacity Register (`ecr`) and the OSM substation coordinates. Records row counts and the **edition** (a content hash of all the inputs). |
| `nged_model_canonical` | `gridify_optimizer.nged.nged_model(tables)`: today's network, geolocated. The bronze tables are **passed in**, so this is the real data path, not a decorative edge. |
| `nged_registry` | `nged_candidates(max_mw, tables)`: the optional projects, each mapped to a bus. |
| `ltds_edition_changes` | `editions.edition_changeset(tables)`: what changed between NGED's previous LTDS edition and this one (see below). |
| `nged_model_cgmes` | The network as a CIM/CGMES 2.4.15 zip (EQ/TP/SSH/GL), written to `warehouse/exports/Gridify_<edition>_CGMES.zip`. Deterministic per edition. |
| `served_nged` | Writes the model tables (`regions` is kept for the schema and is empty: the engine no longer derives demand groups; `loads.region_id` still ties each load to its LTDS Table 3 group), the registry and the change-set to DuckDB, and **appends** a snapshot row when the network changed. `snapshot_id` is a content hash of the network tables (buses, lines, transformers, loads, generators, regions), so `network@<snapshot_id>` names a version of what exists; each row carries the edition it was built from and the registry's size when it was first written. The registry is not part of the id: a not-yet-built project counts only on a branch (whose candidate set is in every result's cache key), and the registry's own history is the ECR editions below. |

**One builder, one truth.** The pipeline and the optimizer's `build_base_net()` run the same `gridify_optimizer.nged` builder on the same bundled snapshot, so the warehouse the map reads and the network the engine solves can't drift apart.

**What changed between editions.** NGED flags every LTDS row *New / Updated / Unchanged / Removed* against its previous publication. The change-set reconstructs the previous edition (drop the New rows, keep the Removed ones), builds both, and reports three levels of difference: the flagged rows themselves (e.g. a 6 MVA Great Hale transformer replaced by a 7.5 MVA one, the 18.6 MW Warth Lane demand row marked Removed, which the model keeps as `BICKER_FEN.removed_in_error` (`nged_points`)), the model delta (buses, circuits, transformers, demand MW) and the physics delta (today's power flow on each edition: worst loadings, voltage range, GSP export). Caveat: Updated rows carry their current values in both editions, because NGED doesn't publish the old ones. Stored in the warehouse (`ltds_changes`, `ltds_change_summary`); the API does not serve it.

### `registers` — the live sources (`src/grid_simulator/defs/registers.py`)

```
 ecr_register_fetch ──► ecr_editions ──► ecr_changes          job ecr_refresh · schedule monthly (2nd, 06:00 London)
 osm_substations_fetch ──► coords_editions                    job osm_refresh · schedule quarterly
 pin_ecr_edition · pin_osm_coords                              MANUAL: promote an edition into the pinned snapshot
 pin_nged_published                                            MANUAL: fetch LTDS Table 4 fault levels and the DFES projections into data/nged/{fault,dfes}.json
 nged_flows                                                    MANUAL: fetch NGED's 2024 half-hourly substation and branch loading for Bicker Fen into warehouse/nged-flows/ (git-ignored; src/grid_simulator/defs/flows.py)
 nged_flows_2025                                               MANUAL: the same for 2025 (NGED's "2025 Connected Export (ID 1124)"), rewritten to 2024's header layout, values unchanged, into warehouse/nged-flows/bicker-fen-2025/ (flows.py)
 staythorpe_snapshot                                           MANUAL: a second supply point's LTDS tables, ECR, DFES rows, limits and half-hourly loading into the git-ignored warehouse/supply-points/staythorpe/ (supply_points.py); studied as a report, not served
 nged_dfes_detail                                              MANUAL: fetch NGED's DFES 2025 profiles, splits, scaling, power projections and supply-area volumes whole into warehouse/nged-flows/dfes-2025/ (git-ignored; flows.py)
```

`nged_flows` writes the files the engine's measured year reads (`gridify_optimizer.timeseries`), a `NOTICE.txt` with the
licence and the attribution "Supported by NGED Open Data", and `fetched.json` (resource ids, URLs, last-modified dates,
sizes). The files are about 23 MB, so they are fetched, not committed. The DFES pin includes the demand rows the model
keeps although the LTDS marks them Removed (`BICKER_FEN.removed_in_error` (`nged_points`): Warth Lane).

The two external registers change on their own clock, so they are fetched on a schedule and stored as **append-only editions** in the warehouse (`ecr_editions` / `ecr_edition_rows`, `coords_editions` / `coords_edition_rows`): one row per fetch whose content differs from the last, with the fetch time, the source's own `last_modified` (CKAN), the resource id, the row count and a content hash as the edition id. The bundled snapshot is seeded as the first edition, so the first live fetch has a baseline. `ecr_changes` diffs the latest two editions site by site (added, withdrawn, connected, capacity or target date changed) and stores it in the warehouse table `ecr_changes` (a summary is in the asset's metadata in the Dagster UI); the API does not serve it.

Nothing here changes the model the engine runs on. That stays pinned to the bundled snapshot until someone runs `pin_ecr_edition` or `pin_osm_coords`, which write the latest edition into `packages/optimizer/src/gridify_optimizer/data/nged/` as a reviewable git diff. Then re-materialise `ltds_tables*` and commit.

Privacy: the register's customer-name, address, postcode and MPAN/MSID columns are dropped at the fetch boundary (`ECR_KEEP`; each fetch records the dropped columns in its metadata). `customer_site` and the site's lat/lon are kept as NGED publishes them; for small sites the site name is often a property name or an address, sometimes with a postcode.

Schedules are defined but start **stopped**; turn them on in the Dagster UI. The `ltds` group makes no network calls.

---

## Run

From `apps/pipeline/`:

```bash
uv sync
uv run dagster asset materialize -m grid_simulator.definitions --select 'ltds_tables*'        # the model (offline)
uv run dagster asset materialize -m grid_simulator.definitions --select 'ecr_register_fetch,ecr_editions,ecr_changes'   # live ECR fetch
uv run dagster asset materialize -m grid_simulator.definitions --select 'osm_substations_fetch,coords_editions'        # live OSM fetch
#   ...or the UI: uv run dg dev  → http://localhost:3000 (lineage, checks, schedules)
```

Keep the quotes around `'ltds_tables*'`: it selects the root asset and everything downstream. Don't select `pin_*` unless you mean to replace the pinned snapshot.

## Refreshing the data

The bundled data is a **pinned snapshot**. The live registers are fetched by scheduled Dagster assets (`registers` group: the ECR monthly, OpenStreetMap quarterly), stored as append-only editions in the warehouse and diffed edition-to-edition. Adopting a new edition into the model is a deliberate step:

```bash
uv run dagster asset materialize -m grid_simulator.definitions --select 'ecr_register_fetch,ecr_editions,ecr_changes'   # fetch + diff
uv run dagster asset materialize -m grid_simulator.definitions --select 'pin_ecr_edition'                               # promote it into data/nged/ecr.json
uv run dagster asset materialize -m grid_simulator.definitions --select 'ltds_tables*'                                  # rebuild the model from it
```

Review the git diff of the bundled file, then commit. `osm_substations_fetch` / `coords_editions` / `pin_osm_coords` do the same for substation positions.

NGED's half-hourly flows for the measured year (about 23 MB) are fetched, not bundled. Fetch them into the git-ignored
`apps/pipeline/warehouse/nged-flows/`, then run the year:

```bash
uv run dagster asset materialize -m grid_simulator.definitions --select nged_flows        # 2024; nged_flows_2025 for 2025 (bicker-fen-2025)
cd ../../packages/optimizer && uv run python -m gridify_optimizer.timeseries ../../apps/pipeline/warehouse/nged-flows/bicker-fen-2024 <out.npz> screened
```

The LTDS tables (`circuit`, `t2a`, `demand`, `node`, `gen`) were pulled from the Connected Data Portal's `datastore_search` API. The GSP limits and transmission projects are recorded, with their resource ids, in `nged.py` (`BICKER_FEN.boundary`, `BICKER_FEN.transmission_projects`).

## Notes

- **WARN vs ERROR is deliberate.** ERROR means the model is wrong (it won't solve, or it references things that don't exist): both checks are `blocking`, so `served_nged` is skipped and the API keeps reading the previous warehouse. WARN flags a concern without blocking, including a limit breach in today's grid, which is a real finding to serve, not a broken model. A check blocks only when it runs in the same run, as `'ltds_tables*'` does.
- **DuckDB today.** The warehouse path is one config value (`src/grid_simulator/config.py`). DuckDB allows one writer per file, so the writer assets carry a retry policy; the API only ever opens it read-only.
- **Tests live with the logic.** The model and edition rules are tested in `packages/optimizer/tests/` (`test_nged.py`, `test_editions.py`); this package has no unit tests of its own. The asset checks are the pipeline's runtime gate.
