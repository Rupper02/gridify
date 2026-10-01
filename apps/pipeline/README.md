# GridForge — data pipeline

**A versioned, auditable "source of truth" pipeline for power-grid models — with an LLM edge that never bypasses it.**

> This is the **`apps/pipeline`** slice of GridForge. It produces the validated grid model *and* the scored candidate projects that the connection-queue optimizer consumes. For the whole system (optimizer, API, map UI) and how to run it, see the [root README](../../README.md); for the engine, [`packages/optimizer`](../../packages/optimizer/README.md).

GridForge ingests the mismatched, messy data that real distribution-network planning runs on — a planning-tool model export, a GIS layer, a field-team spreadsheet, and free-text connection requests — reconciles it into one validated canonical model, serves it to a queryable warehouse with a content-hashed snapshot, and uses an LLM only at the *messy edge*, where every extraction is checked against the canonical model before it's trusted.

Built with [Dagster](https://dagster.io), [pandapower](https://pandapower.readthedocs.io), DuckDB, and Claude Sonnet 5.5 (via OpenRouter). The sample network is `mv_oberrhein`, a real 20 kV distribution feeder (≈179 buses); after geolocation the served model exposes 174 buses, 170 lines, 2 transformers, and 142 loads.

---

## The thesis

Grid data is a spectrum: the electrical model is structured but comes from incompatible tools; the surrounding data (studies, applications, spreadsheets) is messy or free-text. The right architecture mirrors that:

- **The electrical core stays deterministic.** You never let a model *guess* a line impedance or a thermal rating — those are safety-critical. Ingestion, reconciliation, and validation are plain, testable code.
- **The LLM lives at the edges** — turning free-text connection requests into structured candidates — but its output is **validated against the canonical model**, not trusted on self-reported confidence. The deterministic model is the judge.

That single idea — *the model is the source of truth; the agent is checked against it* — drives every design decision below.

---

## Architecture

```
                      BRONZE                 SILVER                         CHECKS / SERVE
 pandapower net ─┐
 GeoJSON coords  ├─ raw_network ───┬──► canonical_buses ──┐
 messy CSV       ├─ raw_geojson    ├──► canonical_lines ──┼─► 5 asset checks
                 └─ raw_register   └──► canonical_transformers ─┘   │
                                                                    └─► served_model → DuckDB
                                                                         (buses/lines/transformers
                                                                          + content-hash snapshots)

                      LLM EDGE                                      OPTIMIZER INPUTS
 connection    raw_connection_requests ─► extracted_connections ─► triaged_connections
 request .txt                             (Sonnet 5.5, strict JSON  (validate vs canonical_buses →
                                           → typed + confidence)      auto_accept / needs_review)
                                                 │
                                                 └─► scored_connections ─► served_candidates
                                                     (deterministic readiness rubric +      → candidate_projects
                                                      Jev strategic fit, grounded in a          (warehouse)
                                                      power-flow grid signal)
```

Everything is a Dagster **software-defined asset**; dependencies (and the lineage graph in the UI) are inferred from function parameters.

---

## Pipeline

### Bronze — faithful ingestion
`raw_network` (pandapower `mv_oberrhein`), `raw_geojson` (substation coordinates, with 5 buses deliberately missing), `raw_register` (a line-rating spreadsheet seeded with realistic mess: duplicates, `"20 kV"`/`"20kv"` inconsistency, blank/`"362 A"`/zero/negative ratings, a phantom line). Raw assets copy sources verbatim — no cleaning.

### Silver — reconciliation
`canonical_buses` joins the authoritative topology with GIS coordinates (left join, so missing coords surface as nulls rather than vanishing). `canonical_lines` cleans the register (strip, normalize voltage, coerce ratings, dedupe) and joins it onto the real lines. `canonical_transformers` carries the HV/MV transformers.

### Validation — 5 asset checks
| Check | Severity | What it verifies |
|---|---|---|
| `buses_have_coords` | WARN | every bus has a GIS location |
| `ratings_positive` | ERROR | line ratings parse and are `> 0` |
| `no_phanton_lines` | WARN | register references only real lines (referential integrity) |
| `network_connected` | ERROR | the graph is one island — **across lines *and* transformers** |
| `power_flow_converges` | WARN | pandapower AC power flow solves, voltages within `[0.9, 1.1] pu` |

The last two are genuine power-systems checks. `network_connected` was the project's best lesson: a lines-only graph reports the network as *fragmented* (buses reachable only through a transformer look islanded) — modelling the transformers as edges fixes it. That's the kind of thing a naive pipeline silently gets wrong.

### Serve
`served_model` writes the canonical tables to a DuckDB warehouse and appends a row to a `snapshots` table — a SHA-256 **content fingerprint** of the whole model plus row counts and a timestamp. Same data → same id; any change → new id. A lightweight, honest "versioned source of truth."

### LLM edge — extraction + validation-grounded triage
`extracted_connections` sends each free-text request to **Sonnet 5.5** with a strict JSON schema, returning typed fields (`bus_id`, `technology`, `rating_mw`, `voltage_kv`) plus a confidence score. `triaged_connections` then routes each one by checking it **against the canonical model**:

| request | extracted | confidence | triage |
|---|---|---|---|
| 4.5 MW solar @ bus 120 | valid | 0.97 | ✅ auto_accept |
| "4,500 kW" battery @ bus 174 | 4.5 MW (unit-normalized) | 0.97 | ✅ auto_accept |
| 2 MW battery @ **bus 250** | bus absent from model | 0.97 | ⚠️ needs_review — *bus not in model* |
| vague "some solar, TBC" | nulls | 0.90 | ⚠️ needs_review — *missing bus, missing rating* |
| **850 MW** wind @ bus 42 | implausible rating | 0.95 | ⚠️ needs_review — *rating out of range* |

Note the confidences: the invalid requests scored **0.90–0.97**. Routing on confidence would have auto-accepted garbage. Routing on the *model* catches it — which is the whole point.

### Optimizer inputs — scored candidate projects

`scored_connections` turns each application into a ranked-ready candidate, keeping the right tool for each sub-question:

- **Readiness** is deterministic: the LLM extracts a Gate-2 checklist (land rights, planning, connection agreement, financing, commissioning year) and a rubric (`gridforge_optimizer.readiness`) scores it — auditable, with a per-milestone breakdown.
- **Strategic fit** is judged by the **Jev** decisions model, grounded in the local grid signal from a power-flow solve, and carries a **calibrated confidence**.

`served_candidates` writes the result to the warehouse `candidate_projects` table, which the API reads to run the queue. The engine lives in [`packages/optimizer`](../../packages/optimizer/README.md).

---

## Quickstart

Run these from `apps/pipeline/`:

```bash
# 1. install (uv)
uv sync

# 2. generate the sample source files
uv run python scripts/make_sources.py

# 3. for the LLM edge + scoring: create apps/pipeline/.env (gitignored)
#    OPENROUTER_API_KEY=sk-or-...

# 4. launch Dagster and click "Materialize all"
uv run dg dev                     # http://localhost:3000
#    …or headless:
uv run dagster asset materialize -m grid_simulator.definitions --select "*"
```

The deterministic pipeline (bronze → serve) needs no API key; the LLM edge + scoring make ~25 cheap OpenRouter/Jev calls per full materialize. `dg dev` loads `apps/pipeline/.env` automatically; the headless CLI reads the key from the environment.

> **Port note:** `dg dev` and the web app (`next dev`) both default to port **3000** — run them at different times.

---

## Design notes

- **Config in one place.** `src/grid_simulator/config.py` holds all paths, thresholds, and LLM settings — swapping the model or the DB target is a one-line change.
- **Return annotations are contracts.** Dagster type-checks each asset's output against its annotation, so the type hints double as free validation.
- **WARN vs ERROR** is deliberate: WARN surfaces a data-quality concern (missing coords, source junk) without blocking; ERROR marks a real correctness violation.
- **DuckDB today, Postgres tomorrow.** The warehouse target is a single config value; the serve layer is written so moving to Postgres/PostGIS for multi-user access is a localized change.

## Limitations & next steps

- The power-flow check runs against the source electrical model — the canonical layer stores topology and ratings, not impedances, so it can't be re-solved from the warehouse alone. A fuller version would persist impedances and rebuild the net.
- Extraction confidence is recorded but intentionally *not* the triage gate.
- The DB connection could be promoted to a Dagster **resource** (cleaner, and the natural seam for the Postgres swap).
- For bulk extraction, a cheaper model (e.g. Haiku) and request batching would cut cost.
