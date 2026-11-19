# AGENTS.md — apps/pipeline (`grid_simulator`)

Dagster. Read the root `AGENTS.md` first; this file adds what is specific to the pipeline. The spec is
`apps/pipeline/README.md`.

## What it owns

- `defs/nged.py` (group `ltds`): `ltds_tables` (pinned snapshot, passed INTO the builder) → `nged_model_canonical` +
  `nged_registry` + `ltds_edition_changes` → 3 asset checks → `served_nged` → DuckDB warehouse
  `apps/pipeline/warehouse/gridify.duckdb` with an append-only `snapshots` history.
- `defs/registers.py` (group `registers`): scheduled fetches of the ECR (monthly) and OSM coords (quarterly) into
  append-only edition tables + `ecr_changes`; `pin_*` assets promote an edition into the bundled snapshot (manual).
- `defs/flows.py` and `defs/supply_points.py` (group `registers`, manual): NGED's half-hourly flows and DFES detail into
  the git-ignored `warehouse/nged-flows/`, and a second supply point's data (Staythorpe) into `warehouse/supply-points/`.
- Warehouse writers carry a retry policy (DuckDB = one writer).

## Commands

```bash
cd apps/pipeline
uv run dagster asset materialize -m grid_simulator.definitions --select 'ltds_tables*'   # keep the quotes; offline
uv run dagster asset materialize -m grid_simulator.definitions --select 'ecr_register_fetch,ecr_editions,ecr_changes'  # live ECR fetch + diff
# never select 'pin_*' unless you mean to replace the pinned snapshot in packages/optimizer/.../data/nged/
```

- `uv run dg dev` (Dagster UI) also binds **port 3000**: don't run it alongside the web app.
- `--select '*'` can still shell-expand on Git Bash; use `'ltds_tables*'`, which already selects the full graph.

## Data refresh

- Bundled snapshots live in `packages/optimizer/src/gridify_optimizer/data/nged/` (LTDS tables, `ecr.json`,
  `coords.csv`) and are the pinned edition the engine runs on.
- Live fetches are Dagster assets in `defs/registers.py` (ECR via CKAN, OSM via Overpass) that store editions in the
  warehouse and diff them; `pin_ecr_edition` / `pin_osm_coords` promote the latest edition into the bundled files; `pin_nged_published` fetches the LTDS fault-level table and the DFES projections straight into them.
- After pinning: re-materialise `ltds_tables*`, review the git diff of the bundled file, commit.
- Every builder entry point in `gridify_optimizer.nged` takes `tables=` (and `edition=` current/previous); the pipeline
  passes its bronze tables through so lineage is real.
- The ECR fetch drops the customer-name, address, postcode and MPAN/MSID columns (`ECR_KEEP`); `customer_site` is kept as
  published and can name a property (root `AGENTS.md` Domain rule 5).
- OSM data is ODbL: keep the "© OpenStreetMap contributors" credit wherever positions are shown or documented.
- NGED's own substation-location datasets are access-restricted; don't add a dependency on them.
