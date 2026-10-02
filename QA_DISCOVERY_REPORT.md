# GridForge: QA Discovery & Critical Backlog

**Date:** October 2, 2026  
**Scope:** Read-only discovery, installation verification, architecture mapping, UX flow testing, and critical issue identification  
**Status:** ✅ COMPLETE

---

## Executive Summary

GridForge is a **pull-request workflow for grid connections** targeting DSO-style Queue Reform use cases. It models one real UK network (NGED's Bicker Fen 132 kV GSP in Lincolnshire) using only open data, with a deterministic pandapower AC power-flow engine at its core. Users can branch the baseline grid, add generation projects, run physics-based feasibility checks, review consequences against `main`, and merge or discard changes.

### Key Findings

**✅ STRENGTHS:**
- Clean architecture with clear separation of concerns (pipeline, optimizer, API, web)
- Deterministic physics engine with comprehensive test coverage (53 tests, grid-agnostic)
- Professional React 19 + TypeScript frontend with MapLibre visualization
- Sophisticated branch-based workflow (like Git for grid planning)
- Real data from open sources (LTDS, ECR, OSM)
- Application loads and runs successfully with no blocking issues

**⚠️ CONCERNS FOR MVP FITNESS:**
1. **No year-over-year simulation over timeline** — timeline slider is a VIEW filter, not a simulation driver
2. **Demand growth is binary (2030/2035)** — no granular year-by-year build-up
3. **Missing core DSO planner features** — no cost analysis, no alternative reinforcement ranking, no multi-year cashflow
4. **Project urgency is opaque** — ranking formula (50% readiness + 35% grid need + 15% strategic fit) not exposed to user
5. **No export/reporting** — planners need PDFs, CSVs, or dashboards for stakeholders
6. **Baseline vs branch UX is confusing** — `main` is precomputed on API startup but not obvious to user
7. **Half-baked features** — suggestions (Copilot) work but results are first-order approximations only
8. **No data lineage UI** — warehouse editions/changes are tracked but not shown to user

---

## 1. Repository Structure Map

### 1.1 Monorepo Layout

```
gridforge/
├── packages/optimizer/          # Core engine (Python, pandapower)
│   ├── src/gridforge_optimizer/
│   │   ├── nged.py              # NGED network builder (LTDS → pandapower)
│   │   ├── network.py           # Physics: growth, dispatch, feasibility, N-1
│   │   ├── greedy.py            # Optimizer: ranking + greedy feasibility loop
│   │   ├── suggest.py           # "What would it take" reinforcement analysis
│   │   ├── diff.py              # Consequence diff (base vs head)
│   │   ├── types.py             # Pydantic contracts
│   │   ├── config.py            # All tunables (weights, limits, FES pathways)
│   │   ├── readiness.py         # Readiness rubric (land/planning/finance/timeline)
│   │   ├── scoring.py           # Grid need scoring from power flow
│   │   ├── cim.py               # CIM/CGMES export (ENTSO-E standard)
│   │   ├── editions.py          # LTDS edition changeset + ECR diff
│   │   └── llm.py               # Optional LLM narration (OpenRouter)
│   ├── tests/                   # 53 tests, grid-agnostic, ~2 min on 4 workers
│   └── data/nged/               # Bundled open data (LTDS, ECR, OSM coords)
│
├── apps/pipeline/               # Dagster: data → warehouse (Python)
│   ├── src/grid_simulator/defs/
│   │   ├── nged.py              # Asset graph: ltds_tables → model → checks → DuckDB
│   │   └── registers.py         # Live fetches: ECR (monthly), OSM (quarterly)
│   ├── warehouse/
│   │   └── gridforge.duckdb     # Read-only baseline (2.6 MB)
│   └── scripts/                 # fetch_nged_ecr.py, fetch_osm_substations.py
│
├── apps/api/                    # FastAPI server (Python, port 8000)
│   ├── src/gridforge_api/
│   │   ├── main.py              # App assembly + CORS + error handling
│   │   ├── routers/             # HTTP: model, registry, optimize, branches
│   │   ├── service.py           # PlanService: engine runs + caching
│   │   ├── repository.py        # Branches/projects SQL
│   │   ├── store.py             # ScenarioStore: DuckDB or Postgres
│   │   ├── warehouse.py         # Warehouse: read-only DuckDB access
│   │   ├── cache.py             # ResultCache: durable + in-memory
│   │   ├── jobs.py              # JobRunner: background engine runs
│   │   ├── narration.py         # Narrator protocol (LLM or no-op)
│   │   ├── schemas.py           # Request bodies
│   │   └── deps.py              # Dependency injection root
│   ├── data/
│   │   └── scenarios.duckdb     # Mutable store: branches, added projects, schedules
│   └── tests/                   # 16 tests, temp scenarios DB per run
│
└── apps/web/                    # Vite + React 19 + TypeScript (port 3000)
    ├── src/
    │   ├── App.tsx              # Composition root: header, map, roadmap, panel
    │   ├── hooks/
    │   │   ├── usePlanner.ts    # Controller: composes 7 sub-hooks
    │   │   └── planner/         # useRun, useBranchFlows, useRegistry, etc.
    │   ├── components/          # MapView, QueueTab, AlertsTab, ReviewTab, etc.
    │   ├── lib/                 # Pure logic: derive.ts, geo.ts, reasons.ts
    │   ├── api.ts               # Typed client + normReason (engine → plain English)
    │   └── types.ts             # Wire types (matches API)
    └── tests/                   # 13 vitest: reason wording, timeline/queue derivations
```

### 1.2 Key Ownership

| Component | Owner | Responsibility |
|-----------|-------|----------------|
| **Physics & ranking** | `packages/optimizer` | Single source of truth: network build, feasibility, greedy loop, suggestions, diff |
| **Data pipeline** | `apps/pipeline` | LTDS/ECR/OSM → validated warehouse with append-only snapshots + checks |
| **API** | `apps/api` | Reads warehouse, runs engine, stores branches/projects in scenarios DB |
| **Frontend** | `apps/web` | MapLibre map, queue/alerts/review tabs, branch/timeline UX |

---

## 2. Installation & Local Setup

### 2.1 Prerequisites

- **Node 22** + **pnpm 10** (JS tooling)
- **Python 3.11+** with **uv** (Python package manager)
- No API keys required (optional: `OPENROUTER_API_KEY` for LLM narration)

### 2.2 Installation Steps (Verified)

```bash
# 1. Install JS dependencies
pnpm install  # from repo root

# 2. Install uv (if missing)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# 3. Build the warehouse (offline, from bundled data)
cd apps/pipeline
uv run dagster asset materialize -m grid_simulator.definitions --select 'ltds_tables*'
# Creates apps/pipeline/warehouse/gridforge.duckdb (2.6 MB)
cd ../..

# 4. Start the API (terminal 1)
pnpm --filter @gridforge/api dev
# Runs on http://localhost:8000
# Scenarios DB created on first request: apps/api/data/scenarios.duckdb

# 5. Start the web app (terminal 2)
pnpm --filter web dev
# Runs on http://localhost:3000
```

### 2.3 Verification

✅ **API health check:**
```bash
curl http://localhost:8000/health
# {"ok":true,"warehouse_exists":true,"scenarios_store":"duckdb"}
```

✅ **Web app loads:** Navigate to http://localhost:3000 → GridForge map appears with "NGED: Bicker Fen 132 kV GSP" header

✅ **Data counts:**
- Buses: 139
- Lines: 128
- Transformers: 44
- Loads: 49
- Generators (existing): 14
- Registry projects: 20

### 2.4 Installation Issues Found

❌ **None** — installation is clean and well-documented.

---

## 3. Data Model & Domain Rules

### 3.1 The Grid Model

**Source:** NGED Long Term Development Statement (LTDS) for Bicker Fen 132 kV GSP  
**Builder:** `packages/optimizer/src/gridforge_optimizer/nged.py`

```python
# Today's network (no future projects pre-loaded)
build_nged_net() → pandapower network
  - 139 buses (132 kV, 33 kV, 11 kV)
  - 128 lines
  - 44 transformers (with OLTC tap ranges)
  - 49 loads (170 MW demand, × 0.55 diversity factor)
  - 14 existing generators (376.5 MW)
  - GSP export limit: 527 MW (2 × 263.5 MW SGTs)
```

**Key constraint:** `main` = **only what physically exists today**. Anything not yet built sits in the registry (20 projects, 1,691.5 MW) and counts only when added to a branch.

### 3.2 The Registry

**Source:** NGED Embedded Capacity Register (ECR) via CKAN API  
**Projects:** 20 optional projects (solar, wind, battery, solar+storage)
- Largest: 248 MW battery at Bicker Fen 132 kV
- Smallest: 1 MW solar
- Total: 1,691.5 MW

**Fields per project:**
- `request_id` (e.g. ECR-04843)
- `bus_id` (connection point)
- `technology` (solar/wind/battery)
- `rating_mw` (export capacity)
- `readiness_score` (0–1, from rubric)
- `strategic_fit` (0–1, per-technology prior)
- `commissioning_year` (developer's target, nullable)

### 3.3 Feasibility Rules

Every project must pass **two study cases** + the **GSP export limit:**

| Case | Demand | Generation | Ratings | Critical for |
|------|--------|------------|---------|--------------|
| **winter_peak** | Max demand × FES growth | Solar 0, Wind 0, Battery **-1** (charging) | Winter | Demand-driven overloads, low voltage |
| **summer_min** | LTDS min-demand (~48% of max), **not grown** | Everything at 1 (full export) | Summer (90% of winter) | Generation export, high voltage |

**Voltage bands (statutory, GB ESQCR):**
- 132 kV and above: ±10% (0.90–1.10 pu)
- Below 132 kV: ±6% (0.94–1.06 pu)

**Thermal limits:** 100% loading for lines and transformers

**GSP boundary:** Export ≤ 527 MW (firm: 263.5 MW with one SGT out)

**Tap changers:** On-load tap changers (OLTC) regulate LV busbars to 1.0 pu (±0.01 pu deadband, 1.25% step, max 3 passes per solve). Taps persist on net, so trials normally need one solve.

### 3.4 Demand Growth

**Source:** NESO Future Energy Scenarios (FES) 2025 — peak demand pathways  
**Anchor:** Holistic Transition (HT) — firmly cited, aligned with Clean Power 2030
- 2030: 1.08× (60 GW → 65 GW GB peak)
- 2035: 1.35× (60 GW → 81 GW GB peak)

**Per-bus spreading:** Deterministic heterogeneity (seeded by scenario + bus) with:
- Load type (residential vs industrial, if labeled)
- Distance from GSP (feeder edge tilt)
- Hotspots (~20% of loads grow faster)
- **Constraint:** Total feeder growth still equals pathway multiplier exactly

**Critical gap:** Growth is **binary** (2030 or 2035). No year-by-year ramp from 2026 → 2030 → 2035.

### 3.5 Ranking Formula

```
rank_score = 0.5 × readiness + 0.35 × grid_need + 0.15 × strategic_fit
```

**Readiness rubric:**
- Land rights: 30%
- Planning consent: 30%
- Connection agreement: 20%
- Financing: 10%
- Commissioning timeline: 10%

**Grid need:** Derived from power flow (local demand + voltage depression at bus)

**Strategic fit:** Per-technology prior (e.g. storage scores higher at export-constrained GSPs)

**Critical gap:** Formula is **hardcoded** in `config.py`. User has no visibility or control over weights.

### 3.6 Branching Model

```
main (plan of record)
  ├── branch-A (user adds projects → optimize → diff vs main → merge or discard)
  ├── branch-B
  └── ...
```

**Lifecycle:**
1. Create branch off `main` (or another branch)
2. Add registry projects (or hand-enter new ones)
3. Run optimizer → Phase 1 (2027–2030), Phase 2 (2031–2035), Deferred, Rejected
4. Review diff (MW by phase, network impacts, who moved)
5. Merge (squash into parent) or discard

**Storage:**
- Warehouse (read-only): baseline grid + registry
- Scenarios DB (mutable): branches, added projects, scheduled years, result cache

---

## 4. Core UX Flows (Manual Testing)

### 4.1 Baseline Simulation (Main Branch)

**Test:** Load app, observe `main` branch

✅ **Observations:**
- App defaults to `main` branch ("Main - plan of record")
- Map shows existing network: buses, lines, transformers, 14 generators
- Timeline slider defaults to 2035
- No registry projects are pre-loaded (queue empty)
- GSP export today: ~224 MW (exporting to transmission)

**Critical gap:** `main` is precomputed on API startup (`_lifespan` in `main.py`) but this is **not surfaced to user**. User doesn't know if `main` reflects latest data or is stale.

### 4.2 Branch Creation

**Test:** Create branch "qa-test-branch"

✅ **Observations:**
- Review tab → "+ New branch" button
- Modal with fields: name, base branch, forecast (FES pathway)
- Branch created successfully, switches automatically
- Toast notification confirms

**UX issue:** No indication of what "base branch" means or why it matters. Git-like metaphor is powerful but assumes user knows Git.

### 4.3 Adding Projects from Registry

**Test:** Add 3 projects to branch

✅ **Observations:**
- "Browse registry" button opens drawer
- Registry shows 20 projects with search box
- Each project shows: ID, applicant, technology, capacity, connection bus
- "Add" button per project
- Projects added to branch immediately
- Queue tab updates (counters change)
- Projects appear on map as green markers

**Critical gap:** No bulk add. No filtering by technology, capacity, or readiness. Search is text-only (not faceted).

### 4.4 Running Optimization

**Test:** Click "Run simulation" button

⚠️ **Observations:**
- Button click triggers `/branches/{id}/optimize/jobs` (background job)
- Overlay shows: "Ranking candidates... 0%" → "Phase 1 trials... 35%" → etc.
- After ~15-20s, results appear: 1 Phase 1, 2 Deferred
- Queue tab shows projects with status badges (green = Phase 1, orange = Deferred)
- Map updates: Phase 1 project highlighted, deferred projects dimmed
- Alerts tab shows N-1 violations (4 alerts)

**Critical gap:** No indication of **why** Phase 1 project was accepted vs deferred. User must click into each deferred project to see reason ("overload line 16 to 253%").

### 4.5 Timeline Slider

**Test:** Drag timeline from 2026 → 2030 → 2035

✅ **Observations:**
- Slider moves smoothly
- Year label updates: "2026 as-is today" → "2030 Clean Power Isles" → "2035"
- Statistics update: "Online by {year}: X projects, Y MW"
- Projects appear/disappear based on recommended year
- Map updates (future projects shown as ghosts)

**CRITICAL DISCOVERY:** Timeline is **only a view filter**. It does NOT re-run the power flow. Moving from 2026 → 2030 does NOT grow demand incrementally. It's a post-optimization visualization tool, not a simulation driver.

**User confusion:** Engineers expect timeline to be the simulation horizon. Current UX implies "sliding forward in time runs physics year by year" but it doesn't.

### 4.6 Demand Growth & Overload Views

**Test:** Toggle loading/voltage modes, observe overload alerts

✅ **Observations:**
- Loading mode: lines color-coded by % utilization (green → yellow → red)
- Voltage mode: buses color-coded by pu voltage deviation
- Legend shows overloaded lines in red
- Alerts tab lists: Line overloads, transformer overloads, voltage violations
- Each alert shows: Element, value, limit, case (winter_peak / summer_min), year

**Critical gap:** Overloads are shown as **snapshots** (2030 or 2035), not as a year-by-year progression. User cannot see "in 2028, line X hits 95%; by 2029, it's overloaded."

### 4.7 Project Queue & Details

**Test:** Click on projects in queue, review details

✅ **Observations:**
- Queue table shows: Rank, Project ID, MW, Readiness %, Status
- Clicking project opens detail card with: Technology, phase, year, connection bus, readiness score, grid need, rank score
- Deferred projects show reason: "Connecting this would overload line 16 to 253%"
- Accepted projects show recommended year (e.g. 2029) and allow manual override via slider
- "Against recommendation" badge appears if scheduled < recommended

**UX issue:** Reason text is verbose and technical. Example: "Connecting this would overload line 16 to 253% (limit 100%) at summer_min." Better: "Line 16 overloaded: 253% (summer, generation case). Action: Upgrade line or defer to 2032."

### 4.8 Branch Diff / Review

**Test:** Compare branch against `main`

✅ **Observations:**
- Review tab → "Diff vs main" button
- Diff view shows:
  - Headline stats: MW by 2030/2035 (delta in green), connected/deferred counts
  - Network effects: Worst line utilization, voltage range, newly overloaded lines
  - "Who moved" table: All projects with status (Added/Accelerated/Slipped), grid impacts
- Clear and actionable

**Critical gap:** No diff of N-1 violations (base vs head). User must manually check Alerts tab on both branches.

### 4.9 Suggestions (Copilot)

**Test:** Click on deferred project → "Review + Suggestions"

⚠️ **Observations:**
- Suggestions appear for deferred projects only
- Each suggestion shows:
  - Lever: "Add parallel circuit to line 16" or "Absorb reactive power at 0.95 pf"
  - Freed MW: "≈ 150 MW by 2030, ≈ 200 MW by 2035"
  - Projects it would unblock: List of IDs
  - Caveat: "This is a feasible lever, not a least-cost design"
- First-order approximations only (knock-on effects not modeled)

**Critical gaps:**
1. No cost estimates for reinforcements
2. No ranking of levers (which is cheapest? quickest?)
3. "Freed MW" is approximate (shown as ≈) but no confidence interval
4. User cannot chain reinforcements (e.g. "upgrade line 16 AND add SGT")

### 4.10 Merge to Main

**Test:** Merge branch back to `main`

⚠️ **Could not verify** — "Merge to main" button exists in UI but flow was not tested in browser session.

**Expected behavior (from code):** Squashes branch into parent, last write wins.

---

## 5. Electrical Domain Gaps

### 5.1 Missing Physics Checks

| Check | Status | Impact |
|-------|--------|--------|
| Fault levels | ❌ Not checked | Breaker ratings not validated (NGED publishes fault levels but units undocumented) |
| 400 kV transmission | ❌ Context only | Wider transmission boundaries not modeled |
| N-1 security standard | ⚠️ Reported, not enforced | Single-outage screen covers 132 kV backbone at winter peak only; findings shown as alerts but don't gate connections |
| 33 kV N-1 | ❌ Not covered | Only 132 kV backbone screened |
| G99 protection | ❌ Not modeled | Generation protection relay settings not checked |

**Honesty:** README states limitations clearly. Users know what's out of scope.

### 5.2 Demand Growth Issues

| Issue | Status | Impact |
|-------|--------|--------|
| Year-by-year ramp | ❌ Missing | Growth is binary (2030 or 2035). No granular build-up 2026 → 2027 → ... → 2035 |
| Substation-level forecasts | ❌ Not used | LTDS has 5-year substation forecasts but they're ignored; FES pathway is spread per-bus with seeded heterogeneity |
| Load-type tagging | ❌ Assumed | LTDS doesn't label load types (residential vs industrial), so spreading uses distance + hotspots only |
| Flexibility | ❌ Not modeled | FES pathways include flexibility (demand-side response, storage), but optimizer uses underlying (unmanaged) peak |

**Critical for DSO:** Real planners need to see demand ramp year-by-year to time reinforcements. Current binary growth (2030/2035) is too coarse.

### 5.3 Generation Dispatch Assumptions

| Case | Dispatch | Assumption | Risk |
|------|----------|------------|------|
| winter_peak | Solar 0, Wind 0, Battery -1 (charging) | Winter evening peak, no sun/wind | Conservative for demand, but ignores flexible dispatch |
| summer_min | Everything at 1 (full export) | Minimum demand, max generation | Conservative for export, but assumes no curtailment |
| Unknown tech | Treated as firm (1.0 in both cases) | Biomass, 'other' | Risk: over-credits firm capacity if it's actually intermittent |

**Critical for DSO:** Real dispatch is probabilistic (P50/P90 generation curves, demand response). Current deterministic approach is simple but may miss real-world flexibility.

### 5.4 Network Topology Issues

| Issue | Status | Impact |
|-------|--------|--------|
| Switch states | ❌ Assumed closed | LTDS doesn't publish switch states; model assumes all are closed (meshed grid) |
| Open points | ❌ Derived | Tee-points with no coordinates sit between neighbors (interpolated); 29 of 68 substations have OSM coords, rest are derived |
| Line parameters | ⚠️ Converted from LTDS | Impedances from %Z on 100 MVA base; may not match real line data |

**Honesty:** README cites OSM as source for positions, states limitations. Users know precision limits.

---

## 6. Product/UX/Code Quality Issues

### 6.1 Missing MVP Features

| Feature | Status | Impact | Priority |
|---------|--------|--------|----------|
| **Year-over-year simulation** | ❌ Missing | Timeline is view-only; demand doesn't ramp year-by-year | **P0** |
| **Cost analysis** | ❌ Missing | No capex/opex for reinforcements; no NPV for projects | **P0** |
| **Alternative reinforcements ranking** | ❌ Missing | Suggestions propose levers but don't rank by cost/time | **P1** |
| **Multi-year cashflow** | ❌ Missing | No financing view for developers | P2 |
| **Export to PDF/CSV** | ❌ Missing | No reports for stakeholders | **P1** |
| **Data lineage UI** | ❌ Missing | Warehouse editions/changes tracked but not shown to user | P2 |
| **Bulk add from registry** | ❌ Missing | User must click "Add" 20 times for all projects | P2 |
| **Faceted search in registry** | ❌ Missing | No filter by tech/capacity/readiness | P2 |
| **N-1 diff** | ❌ Missing | Compare N-1 violations base vs head | P2 |
| **Reinforcement chaining** | ❌ Missing | User cannot combine levers (e.g. "upgrade line + add SGT") | P2 |

### 6.2 UX Confusion Points

| Issue | Impact | Priority |
|-------|--------|----------|
| **Timeline = view filter, not simulation driver** | Engineers expect timeline to re-run physics | **P0** |
| **`main` precompute not surfaced** | User doesn't know if `main` is stale | **P1** |
| **Branch base branch not explained** | Git metaphor assumes user knows Git | P2 |
| **Ranking formula hidden** | User can't see why project A outranks project B | **P1** |
| **Reason text is verbose** | "Connecting this would overload line 16 to 253%..." → needs actionable summary | P2 |
| **Deferred vs Rejected unclear** | Both are blocked, but Rejected = intake failure (off-network bus, >300 MW). Distinction is subtle | P2 |
| **GSP limit sign convention assumed** | README states "export = distribution → transmission" but NGED dataset doesn't document it | P2 |

### 6.3 Half-Baked Features

| Feature | Status | Issue | Priority |
|---------|--------|-------|----------|
| **Suggestions (Copilot)** | ⚠️ Working but limited | First-order only (≈ freed MW); no knock-on; no cost | **P1** |
| **Scheduled year override** | ⚠️ Works but flagged | User can override recommended year but it's marked "against recommendation" with no explanation of risk | P2 |
| **N-1 screen** | ⚠️ Reported, not enforced | Findings shown in Alerts tab but don't gate connections; 132 kV backbone only | P2 |
| **CGMES export** | ✅ Working | `GET /model/cgmes` serves CIM/CGMES 2.4.15 zip; tested with round-trip import; but no UI for it | P2 |
| **LLM narration** | ⚠️ Optional | Requires `OPENROUTER_API_KEY`; if not set, narration is empty (app works fully). Phrasing is verbose. | P2 |

### 6.4 Code Quality

✅ **SOLID principles applied:**
- Single responsibility: HTTP routing, SQL, caching, job scheduling, narration are separate modules
- Open/closed: Study cases, limit checks, reinforcers, normalisers are registries (data-driven)
- Liskov substitution: `Narrator` protocol (LLM or no-op)
- Interface segregation: Components take slices of planner state (not whole state)
- Dependency inversion: Warehouse, store, cache, narrator handed in at `deps.py`

✅ **Test coverage:**
- Engine: 53 tests, grid-agnostic, ~2 min on 4 workers (pytest-xdist)
- API: 16 tests, temp scenarios DB per run
- Web: 13 vitest (reason wording, timeline/queue derivations)

✅ **Grid-agnostic tests:**
- Fixtures derived from `build_base_net()` (no hardcoded bus IDs)
- NGED-specific rules in separate `test_nged.py`

⚠️ **Warnings found:**
- WebGL GPU ReadPixels performance warnings (MapLibre GL JS)
- Favicon.ico 404 (cosmetic)
- React DevTools prompt (cosmetic)

❌ **No CI/CD config found** — tests run locally but no GitHub Actions, CircleCI, etc.

---

## 7. Prioritized QA Backlog

### P0: MVP Blockers (Must Fix Before Launch to DSO)

| Issue | Area | Description | Acceptance Criteria |
|-------|------|-------------|---------------------|
| **1. Year-over-year simulation** | Engine + UX | Timeline slider should re-run power flow for each year from 2026–2035, growing demand incrementally. Currently it's view-only (filters projects by year). | - User drags timeline to 2028 → demand grows to 1.04× (interpolated from FES pathway) → power flow re-runs → overloads appear in 2028 - Line utilization chart shows year-by-year ramp (e.g. "Line 16: 85% in 2027, 95% in 2028, 102% in 2029") |
| **2. Cost analysis for reinforcements** | Engine + UX | Suggestions propose levers (parallel circuits, reactive power, SGT) but give no cost. DSO planners need capex/opex to prioritize. | - Each suggestion shows: Capex (£M), opex (£k/yr), payback period (yrs) - Levers ranked by total cost (or NPV) - Caveat: "Costs are industry averages (NGED DSO data), not project-specific" |
| **3. Timeline UX clarity** | UX | Engineers expect timeline to be simulation horizon. Current UX implies "sliding = re-simulating" but it doesn't. | - Timeline label says "View filter: show projects online by {year}" (not "Simulate to {year}") - Or: rename to "Project filter" and add separate "Simulate to year" control |

**Impact if not fixed:** DSO planners will misinterpret results (thinking they're seeing year-by-year build-up when they're not) and make wrong investment decisions.

---

### P1: MVP Gaps (Should Fix Before Launch)

| Issue | Area | Description | Acceptance Criteria |
|-------|------|-------------|---------------------|
| **4. Ranking formula visibility** | UX | User can't see why project A outranks B. Formula (50% readiness + 35% grid need + 15% strategic fit) is hardcoded in `config.py`. | - Queue table shows breakdown: "Rank score: 0.72 (Ready 0.6 + Need 0.8 + Fit 0.9)" - Tooltip explains each component |
| **5. Export to PDF/CSV** | UX | No reports for stakeholders. DSO planners need dashboards for board meetings. | - "Export" button in Review tab → generates PDF with: branch diff, network impacts, queue table, map snapshot - CSV download for queue (all columns) |
| **6. Main branch staleness indicator** | UX | `main` is precomputed on API startup but user doesn't know if it's stale. | - Header shows: "Main (last updated: 2 Oct 2026, 21:05 UTC)" - "Refresh" button re-runs optimizer on `main` |
| **7. Suggestions cost/ranking** | Engine | Suggestions propose levers but don't rank them. User doesn't know which is cheapest/quickest. | - Levers sorted by capex (lowest first) - Each lever shows: Cost, time to build, freed MW, projects unblocked |
| **8. Alternative reinforcement comparison** | Engine + UX | User can see one lever at a time but can't compare "upgrade line 16" vs "add SGT" side-by-side. | - Suggestions tab shows table: Lever, Cost, Time, Freed MW 2030/2035, Projects unblocked - User can select multiple levers to chain (e.g. "upgrade line 16 + add SGT → 450 MW freed") |

---

### P2: Polish & Nice-to-Haves

| Issue | Area | Description | Acceptance Criteria |
|-------|------|-------------|---------------------|
| **9. Bulk add from registry** | UX | User must click "Add" 20 times to add all projects. | - "Select all" checkbox + "Add selected" button |
| **10. Faceted search in registry** | UX | Text search only; no filter by tech/capacity/readiness. | - Filters: Technology (solar/wind/battery/all), Capacity (0-50 MW / 50-100 / 100+), Readiness (0-25% / 25-50% / 50-75% / 75-100%) |
| **11. N-1 diff** | UX | Compare N-1 violations base vs head. Currently user must check Alerts tab on both branches manually. | - Diff view shows: "N-1 violations: 4 in main, 8 in branch (+4 new: line 16, trafo 30, ...)" |
| **12. Data lineage UI** | UX | Warehouse editions/changes tracked but not shown to user. | - Settings → Data → "LTDS edition: 2024-09-15 (previous: 2024-06-10, +3 transformers, -1 demand point)" - "ECR edition: 2024-10-01 (previous: 2024-09-01, +2 projects, 1 withdrawn)" |
| **13. Reason text actionability** | UX | Verbose: "Connecting this would overload line 16 to 253% (limit 100%) at summer_min." | - Short: "Line 16 overloaded: 253%" - Why: "Summer generation case (full export)" - Action: "Upgrade line 16 (parallel circuit) or defer to 2032" |
| **14. Deferred vs Rejected clarity** | UX | Both are blocked but distinction is subtle. | - Rejected badge tooltip: "Failed intake (off-network bus, >300 MW, or invalid data)" - Deferred badge tooltip: "Grid can't host yet (line/voltage/GSP limit); see reason below" |
| **15. WebGL performance warnings** | Frontend | MapLibre GL JS emits GPU ReadPixels warnings (multiple instances in console). | - Investigate MapLibre config for GPU optimization - Test on low-end hardware (e.g. integrated GPU) |
| **16. Favicon** | Frontend | favicon.ico 404 (cosmetic). | - Add favicon.ico to `apps/web/public/` |
| **17. CI/CD** | DevOps | No GitHub Actions, CircleCI, etc. | - `.github/workflows/test.yml` runs: `pnpm test` + API tests + optimizer tests - Pre-commit hook runs `pnpm --filter web typecheck` |
| **18. Scheduled year override risk** | UX | User can override recommended year but "against recommendation" badge has no explanation. | - Tooltip: "Scheduling before {recommended_year} may overload grid. Review Alerts tab." |
| **19. CGMES export UI** | UX | `GET /model/cgmes` works but no UI button for it. | - Header → "Export" → "CGMES (CIM/CGMES 2.4.15 zip)" downloads file |
| **20. LLM narration verbosity** | UX | Narration (when enabled) is verbose and sometimes redundant. | - Shorten prompts in `llm.py` (justify, narrate_diff, narrate_suggestion) - Or: make narration collapsible ("Show AI summary") |

---

## 8. Hypotheses to Verify

**Unverified claims from manual testing (need deeper code/data probes):**

1. **Main is precomputed on API startup** → ✅ **VERIFIED** in `main.py` `_lifespan` function (calls `plans.optimize_payload` during warm-up)

2. **Demand growth is spread deterministically per-bus** → ✅ **VERIFIED** in `network.per_bus_growth()` (uses `hashlib.md5` seeded by scenario + horizon + bus_id)

3. **Tap changers settle in ≤3 passes** → ✅ **VERIFIED** in `network._solve()` (OLTC_MAX_PASSES = 3)

4. **N-1 screen covers 132 kV backbone only** → ✅ **VERIFIED** in `network.n1_screen()` (filters by `vn_kv >= N1_MIN_KV` where `N1_MIN_KV = 132.0`)

5. **Suggestions are first-order only (no knock-on)** → ✅ **VERIFIED** in `suggest.py` (applies one lever, measures freed MW, does NOT re-run greedy loop to see if newly-unblocked projects then block others)

6. **Result cache keys include engine fingerprint** → ✅ **VERIFIED** in `cache.py` `ResultCache.engine` (imports source of `gridforge_optimizer/__init__.py` and hashes it → survives code changes)

7. **Warehouse is append-only** → ✅ **VERIFIED** in `apps/pipeline/src/grid_simulator/defs/nged.py` `served_nged` asset (checks content hash, only inserts if changed)

8. **Scenarios DB is DuckDB or Postgres** → ✅ **VERIFIED** in `store.py` `ScenarioStore` (translates `?`→`%s` and `DOUBLE`→`DOUBLE PRECISION` for Postgres; uses `GRIDFORGE_SCENARIOS_URL` env var)

---

## 9. Installation & Run Instructions (Final)

### 9.1 Fresh Clone Setup

```bash
# 1. Prerequisites
- Node 22 + pnpm 10
- Python 3.11+ with uv (install: `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Add uv to PATH: `export PATH="$HOME/.local/bin:$PATH"`

# 2. Install dependencies
pnpm install  # from repo root

# 3. Build warehouse (offline, from bundled data)
cd apps/pipeline
uv run dagster asset materialize -m grid_simulator.definitions --select 'ltds_tables*'
# Creates apps/pipeline/warehouse/gridforge.duckdb (2.6 MB)
cd ../..

# 4. Run tests (optional)
pnpm test  # all tests via Turborepo (~4 min total)
# or individually:
cd packages/optimizer && uv run pytest -q  # 53 tests, ~2 min
cd apps/api && uv run --with pytest pytest tests -q  # 16 tests, ~2 min
cd apps/web && pnpm test && pnpm typecheck  # 13 tests + tsc, ~1 min

# 5. Start API (terminal 1)
pnpm --filter @gridforge/api dev
# http://localhost:8000

# 6. Start web app (terminal 2)
pnpm --filter web dev
# http://localhost:3000

# 7. Verify
curl http://localhost:8000/health
# {"ok":true,"warehouse_exists":true,"scenarios_store":"duckdb"}
# Navigate to http://localhost:3000 → GridForge map loads
```

### 9.2 Optional: Live Data Refresh

```bash
# Fetch latest ECR (Embedded Capacity Register) from CKAN
cd apps/pipeline
uv run dagster asset materialize -m grid_simulator.definitions --select 'ecr_register_fetch,ecr_editions,ecr_changes'

# Fetch latest OSM substation coordinates from Overpass API
uv run dagster asset materialize -m grid_simulator.definitions --select 'osm_substations_fetch,coords_editions'

# Pin new edition into bundled snapshot (MANUAL STEP)
uv run dagster asset materialize -m grid_simulator.definitions --select 'pin_ecr_edition'
uv run dagster asset materialize -m grid_simulator.definitions --select 'pin_osm_coords'

# Re-build warehouse from new snapshot
uv run dagster asset materialize -m grid_simulator.definitions --select 'ltds_tables*'

# Review git diff, commit
git diff packages/optimizer/src/gridforge_optimizer/data/nged/
git add . && git commit -m "Data refresh: ECR 2024-10-01, OSM 2024-10-01"
```

### 9.3 Optional: Postgres for Scenarios Store

```bash
# Set env var before starting API
export GRIDFORGE_SCENARIOS_URL=postgresql://user:pass@host:5432/dbname
pnpm --filter @gridforge/api dev
# Tables created on first request
```

### 9.4 Optional: LLM Narration

```bash
# Add to apps/pipeline/.env (API loads from there)
echo "OPENROUTER_API_KEY=sk-..." >> apps/pipeline/.env
# Restart API
# Narration appears in: justify (queue item rationale), narrate_diff (diff summary), narrate_suggestion (lever explanation)
```

---

## 10. Conclusion

### 10.1 Fitness for DSO MVP

**Current state:** GridForge is a **technically excellent prototype** with clean architecture, deterministic physics, and professional UX. It successfully demonstrates:
- Branch-based workflow (like Git for grid planning)
- AC power-flow gating (pandapower, two study cases)
- Real data from open sources (LTDS, ECR, OSM)
- MapLibre visualization with queue/alerts/review tabs

**However, it is NOT MVP-ready for a DSO planner** because:

1. ❌ **Timeline is view-only** (not a simulation driver) → engineers will misinterpret results
2. ❌ **No cost analysis** → planners can't prioritize reinforcements
3. ❌ **No year-by-year demand ramp** → growth is binary (2030/2035), too coarse for timing investments
4. ❌ **Ranking formula is opaque** → users can't see why project A outranks B
5. ❌ **No export/reporting** → planners need PDFs/CSVs for stakeholders

**Recommendation:** Fix P0 issues (1–3) before launch. P1 issues (4–8) should follow immediately after.

### 10.2 Next Steps

**For the team:**
1. Address P0 backlog (year-over-year simulation, cost analysis, timeline UX)
2. Add export/reporting (PDF/CSV) for stakeholder reviews
3. Expose ranking formula in UI (breakdown per project)
4. Add CI/CD (GitHub Actions)
5. Document data refresh cadence (ECR monthly, OSM quarterly)
6. Add cost database for reinforcements (industry averages or NGED DSO data)

**For QA:**
- Re-test after P0 fixes (year-over-year simulation will be a major behavior change)
- Add Playwright E2E tests for core flows (branch → add → run → diff → merge)
- Test with larger datasets (100+ projects, 500+ buses)
- Cross-browser testing (Chrome, Firefox, Safari)
- Mobile/responsive layout testing

---

## Appendix: Screenshots

(Captured during manual testing by computerUse subagent)

1. **Main view on load** — `/tmp/computer-use/2de8c.webp`
2. **Registry drawer open** — `/tmp/computer-use/87ac6.webp`
3. **Timeline at 2030 with projects** — `/tmp/computer-use/d48f2.webp`
4. **Queue tab with project details** — `/tmp/computer-use/7119b.webp`
5. **Map with tooltip** — `/tmp/computer-use/f5f69.webp`
6. **Alerts tab showing N-1 violations** — `/tmp/computer-use/e64a8.webp`
7. **Review/diff view (main → branch)** — `/tmp/computer-use/4da81.webp`

---

## Appendix: Test Results

### Engine Tests (packages/optimizer)

```bash
cd packages/optimizer && uv run pytest -q
53 tests passed in ~2 min (4 xdist workers)
```

**Coverage:**
- CGMES export (well-formed, deterministic, round-trips)
- Trial cache (exact reuse, progress reporting)
- Voltage bands (statutory by level)
- Tap changers (regulate to setpoint)
- Per-case dispatch (solar 0 in winter, battery -1)
- Summer minimum (generation case)
- GSP limit binding (and SGT relieving it)
- N-1 screen (reports without gating)
- Greedy outcomes (deterministic)
- Suggestions (proposes concrete levers)
- Diff (classifies moves, headline counts)
- Editions (previous reconstructed, changeset consistent)
- NGED data rules (removed equipment excluded, registry not pre-loaded)

### API Tests (apps/api)

```bash
cd apps/api && uv run --with pytest pytest tests -q
16 tests passed in ~2 min (temp scenarios DB per run)
```

**Coverage:**
- Health endpoint
- Model endpoint (buses/lines/trafos/loads/generators)
- Registry endpoint
- Branches CRUD
- Optimize sync + job
- Diff
- Suggestions
- Merge/discard
- (+ 1 Postgres store test if `GRIDFORGE_TEST_PG_URL` set)

### Web Tests (apps/web)

```bash
cd apps/web && pnpm test
13 tests passed in ~1 s (vitest)
```

**Coverage:**
- Reason normalization (line/trafo/voltage/gsp → plain English)
- Timeline rollup (online by year, fresh this year)
- Binding sets (deferred projects → blocked elements)
- Queue sorting (by rank/ID/MW/readiness/status)
- Alert derivation (overloads, voltage violations, N-1)

---

**Report prepared by:** Autonomous QA Agent (Cloud Agent bc-aac8)  
**Date:** October 2, 2026  
**Repository:** https://github.com/user/gridforge (assumed; not in files)  
**Commit:** `main` branch at time of discovery
