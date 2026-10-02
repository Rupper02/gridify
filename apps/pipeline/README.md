# GridForge — data pipeline

The **`apps/pipeline`** slice of GridForge: a [Dagster](https://dagster.io) asset graph that turns NGED's open data for the Bicker Fen GSP into a validated, versioned warehouse, which the API serves. For the whole system see the [root README](../../README.md); for the engine see [`packages/optimizer`](../../packages/optimizer/README.md).

---

## The asset graph (`src/grid_simulator/defs/nged.py`)

```
 ltds_tables ──┬─► nged_model_canonical ──┬─► served_nged ──► DuckDB warehouse
  (bronze)     │   buses/lines/trafos/     │                 (apps/pipeline/warehouse/gridforge.duckdb)
               │   loads/existing fleet    │
               └─► nged_connection_queue ──┘
                   the optional registry
                   (ECR accepted + GSP-embedded TEC)

 asset checks on nged_model_canonical:
   power_flow_converges      ERROR  AC power flow solves, voltages in [0.9, 1.1] pu
   referential_integrity     ERROR  every line/trafo/load endpoint and every valid registry bus exists
   single_connected_network  WARN   one island, across lines AND transformers
```

| Asset | What it does |
|---|---|
| `ltds_tables` | Loads the bundled snapshots: LTDS circuit, transformer (`t2a`), demand, node and generation tables, plus NGED's Embedded Capacity Register (`ecr`). Row counts are recorded as metadata. |
| `nged_model_canonical` | `gridforge_optimizer.nged.nged_model()`: today's network, geolocated. |
| `nged_connection_queue` | `nged_candidates()`: the optional projects, each mapped to a bus. |
| `served_nged` | Writes `buses`, `lines`, `transformers`, `loads`, `generators`, `candidate_projects` and a `snapshots` row (a SHA-256 content fingerprint) to DuckDB. |

**One builder, one truth.** The pipeline and the optimizer's `build_base_net()` both use `gridforge_optimizer.nged`, so the warehouse the map reads and the network the engine solves can't drift apart.

**Today only.** Rows the LTDS marks *Removed* are dropped, and nothing that isn't built yet enters the network. Future projects are only in `candidate_projects`, and they enter a study only when someone adds them to a branch.

---

## Run

From `apps/pipeline/`:

```bash
uv sync
uv run dagster asset materialize -m grid_simulator.definitions --select 'ltds_tables*'
#   ...or the UI: uv run dg dev  → http://localhost:3000 → Materialize all
```

Keep the quotes around `'ltds_tables*'`: it selects the root asset and everything downstream. The pipeline makes **no LLM or network calls**; it reads only the bundled data.

## Refreshing the bundled data

| Script | Writes |
|---|---|
| `scripts/fetch_nged_ecr.py` | `ecr.json`: the Embedded Capacity Register for Bicker Fen, via the NGED CKAN API. Customer names, addresses and MPANs are **not** kept. |
| `scripts/fetch_osm_substations.py` | `coords.csv`: substation positions from OpenStreetMap (© OpenStreetMap contributors, ODbL), matched to network substation names |

Run them with the API's environment, e.g. `cd ../api && uv run python ../pipeline/scripts/fetch_nged_ecr.py`. Then re-materialise.

## Notes

- **WARN vs ERROR is deliberate.** ERROR means the model is wrong (it won't solve, or it references things that don't exist). WARN flags a structural concern without blocking.
- **DuckDB today.** The warehouse path is one config value (`src/grid_simulator/config.py`); moving to Postgres is a change confined to `served_nged`.
- **Tests live with the logic.** The model rules are tested in `packages/optimizer/tests/test_nged.py`; this package has no unit tests of its own. The asset checks are the pipeline's runtime gate.
