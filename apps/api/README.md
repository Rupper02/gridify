# Gridify API

The FastAPI service behind the planner: the grid, branches and their connections, plan-year runs as background jobs, the
result cache and the comparison. Start it with `pnpm --filter @gridify/api dev` from the repo root; the running service
documents every endpoint and schema interactively at `/docs`.

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
| POST | `/branches/{id}/run` | Run every plan year as a background job (`view_year` first); joins a run of the same inputs |
| POST | `/branches/{id}/simulate` | Run and wait (scripts, tests) |
| GET | `/branches/{id}/result` | The result for what the branch holds now, never solving (409 `not_solved` until run) |
| GET | `/branches/{id}/diff` | The branch against its parent, year by year |
| POST | `/branches/{id}/merge`, `/discard` | Merge into the parent, or discard |
| GET | `/jobs/{id}` | A job's status, progress, partial result (`partial=true`) and result; `POST /jobs/{id}/cancel` stops it |
| GET | `/runs` | The catalogue of measured and grown years: whether each run file exists, how to make it, its limits |
| GET | `/runs/{id}` | A run's summary: each line and transformer's peak and hours above rating, busbars out of band, substations above firm capacity |
| GET | `/runs/{id}/grid/{kind}/{element_id}` | When one element is over in a run: hours per month and hour of day |
| POST | `/branches/{id}/year-run` | Run a branch through a whole year (`year`, `pathway`) as a job; the result is a run served by the endpoints above |
| GET | `/runs/{id}/compare` | A branch's year against the same year without its connections |

`main` refuses connection edits, merges and discards (409): it changes only by merging into it. Its demand profile stays
editable.
