# GridForge — data pipeline

The **`apps/pipeline`** slice of GridForge: a [Dagster](https://dagster.io) asset graph that turns NGED's open data for the Bicker Fen GSP into a validated, **versioned** warehouse, which the API serves. For the whole system see the [root README](../../README.md); for the engine see [`packages/optimizer`](../../packages/optimizer/README.md).

---

## Two asset groups

### `ltds` — the model (`src/grid_simulator/defs/nged.py`)

```
 ltds_tables ──┬─► nged_model_canonical ──┬─► served_nged ──► DuckDB warehouse
  (bronze:     │   buses/lines/trafos/     │                 buses · lines · transformers · loads · regions ·
   the pinned  │   loads/fleet/regions     │                 generators · candidate_projects ·
   snapshot)   ├─► nged_connection_queue ──┤                 ltds_changes · ltds_change_summary ·
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
| `nged_model_canonical` | `gridforge_optimizer.nged.nged_model(tables)`: today's network, geolocated. The bronze tables are **passed in**, so this is the real data path, not a decorative edge. |
| `nged_connection_queue` | `nged_candidates(max_mw, tables)`: the optional projects, each mapped to a bus. |
| `ltds_edition_changes` | `editions.edition_changeset(tables)`: what changed between NGED's previous LTDS edition and this one (see below). |
| `nged_model_cgmes` | The network as a CIM/CGMES 2.4.15 zip (EQ/TP/SSH/GL), written to `warehouse/exports/GridForge_<edition>_CGMES.zip`. Deterministic per edition. |
| `served_nged` | Writes the model tables (incl. `regions`: the demand groups, one per live LTDS Table 3 primary and one per BSP over its primaries (`level`), with their firm capacity, P2/8 class, demand today and the buses the engine places them at; `loads.region_id` ties each load to its primary group), the registry and the change-set to DuckDB, and **appends** a snapshot row when the network changed. `snapshot_id` is a content hash of the network tables (buses, lines, transformers, loads, generators, regions), so `network@<snapshot_id>` names a version of what exists; each row carries the edition it was built from and the registry's size when it was first written. The registry is not part of the id: a not-yet-built project counts only on a branch (whose candidate set is in every result's cache key), and the registry's own history is the ECR editions below. |

**One builder, one truth.** The pipeline and the optimizer's `build_base_net()` run the same `gridforge_optimizer.nged` builder on the same bundled snapshot, so the warehouse the map reads and the network the engine solves can't drift apart.

**What changed between editions.** NGED flags every LTDS row *New / Updated / Unchanged / Removed* against its previous publication. The change-set reconstructs the previous edition (drop the New rows, keep the Removed ones), builds both, and reports three levels of difference: the flagged rows themselves (e.g. a 6 MVA Great Hale transformer replaced by a 7.5 MVA one, the 18.6 MW Warth Lane demand point removed), the model delta (buses, circuits, transformers, demand MW) and the physics delta (today's power flow on each edition: worst loadings, voltage range, GSP export). Caveat: Updated rows carry their current values in both editions, because NGED doesn't publish the old ones. Served at `GET /editions/changes`.

### `registers` — the live sources (`src/grid_simulator/defs/registers.py`)

```
 ecr_register_fetch ──► ecr_editions ──► ecr_changes          job ecr_refresh · schedule monthly (2nd, 06:00 London)
 osm_substations_fetch ──► coords_editions                    job osm_refresh · schedule quarterly
 pin_ecr_edition · pin_osm_coords                              MANUAL: promote an edition into the pinned snapshot
 pin_nged_published                                            MANUAL: fetch LTDS Table 4 fault levels and the DFES projections into data/nged/{fault,dfes}.json
```

The two external registers change on their own clock, so they are fetched on a schedule and stored as **append-only editions** in the warehouse (`ecr_editions` / `ecr_edition_rows`, `coords_editions` / `coords_edition_rows`): one row per fetch whose content differs from the last, with the fetch time, the source's own `last_modified` (CKAN), the resource id, the row count and a content hash as the edition id. The bundled snapshot is seeded as the first edition, so the first live fetch has a baseline. `ecr_changes` diffs the latest two editions site by site (added, withdrawn, connected, capacity or target date changed) and is served at `GET /registry/changes`.

Nothing here changes the model the engine runs on. That stays pinned to the bundled snapshot until someone runs `pin_ecr_edition` or `pin_osm_coords`, which write the latest edition into `packages/optimizer/src/gridforge_optimizer/data/nged/` as a reviewable git diff. Then re-materialise `ltds_tables*` and commit.

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

## Notes

- **WARN vs ERROR is deliberate.** ERROR means the model is wrong (it won't solve, or it references things that don't exist): both checks are `blocking`, so `served_nged` is skipped and the API keeps reading the previous warehouse. WARN flags a concern without blocking, including a limit breach in today's grid, which is a real finding to serve, not a broken model. A check blocks only when it runs in the same run, as `'ltds_tables*'` does.
- **Telling the API about a new edition.** After `served_nged` writes a new snapshot, `POST /projects/nged-bickerfen/events` with `{"type": "edition.changed", "payload": {"ltds_edition": "<edition>"}}` (deduplicated by the edition) records it for the agents' audit trail; the API also notices a new snapshot by itself the next time it starts, and main's next run gets its engineer's note on the new data.
- **DuckDB today.** The warehouse path is one config value (`src/grid_simulator/config.py`). DuckDB allows one writer per file, so the writer assets carry a retry policy; the API only ever opens it read-only.
- **Tests live with the logic.** The model and edition rules are tested in `packages/optimizer/tests/` (`test_nged.py`, `test_editions.py`); this package has no unit tests of its own. The asset checks are the pipeline's runtime gate.
