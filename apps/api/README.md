# Gridify API

FastAPI on http://localhost:8000 (`pnpm --filter @gridify/api dev` from the repo root). Interactive documentation of every endpoint and schema is served at http://localhost:8000/docs.

## Endpoints

| Method | Path | What |
|---|---|---|
| GET | `/health` | Liveness, and whether the warehouse exists |
| GET | `/model` | The geolocated grid for the map, with its name and snapshot |
| GET | `/boundary` | The GSP's export limit and today's export |
| GET | `/forecasts` | The demand pathways, the plan years and the intake limits |
| GET | `/assumptions` | What the model assumes (builder fallbacks and planning assumptions) |
| GET | `/registry` | The not-yet-built projects NGED publishes |
| GET, POST | `/branches` | List the branches; open one from another (`{name, from_branch}`) |
| GET | `/branches/{id}` | One branch |
| GET, POST | `/branches/{id}/connections` | A branch's connections; place one (by hand, or `from_registry`) |
| PATCH, DELETE | `/branches/{id}/connections/{rid}` | Change one (bus, size, control, year) or remove it |
| POST | `/branches/{id}/profile` | The demand pathway (`fb`, `ht`, `ee`, or `custom` with both anchors) |
| POST | `/branches/{id}/run` | Run as a background job (every plan year, `view_year` first); joins a run of the same inputs |
| POST | `/branches/{id}/simulate` | Run and wait (scripts, tests) |
| GET | `/branches/{id}/result` | The result for what the branch holds now, never solving (409 `not_solved` until run) |
| GET | `/branches/{id}/diff` | The branch against its parent, year by year |
| POST | `/branches/{id}/merge`, `/discard` | Merge into the parent, or discard |
| GET | `/jobs/{id}` | A job's status, progress, partial result (`partial=true`) and result; `POST /jobs/{id}/cancel` stops it |
| GET | `/runs` | The measured and grown years (2024 as published and screened; 2030 and 2035 grown on Holistic Transition, Electric Engagement and Falling Behind; 2030 with Warth Lane at NGED's LTDS forecast; the branch examples): whether each run file exists, how to make it, its limits |
| GET | `/runs/{id}` | A run's summary: every line and transformer (peak, hours at or above 80/90 % and above 100 %, its agreement with NGED's model), busbars out of band, substations above firm capacity. Read-only: a year is made offline (about 16 minutes) |
| GET | `/runs/{id}/grid/{kind}/{element_id}` | When one line, transformer or busbar is over in a run: hours per month and hour of day |
| POST | `/branches/{id}/year-run` | Run a branch's year (body: `year`, `pathway`) as a job (`GET /jobs/{job_id}`); its result is a run `branch-…` served by the endpoints above, compared with the catalogued run of that year and pathway. A run already on file finishes at once |
| GET | `/runs/{id}/compare` | A branch's year against its "before": the lines and transformers whose hours above rating or peak change, the MVAh above rating on the worst, busbars and firm capacity that change, the GSP exchange, the connections in service, and any on the slack bus |

`main` refuses connection edits, merges and discards (409): it changes only by merging into it. Its demand profile stays editable.
