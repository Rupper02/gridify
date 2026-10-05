# AGENTS.md — packages/optimizer (`gridforge_optimizer`)

The engine. Read the root `AGENTS.md` first (domain rules, design, testing stance); this file adds what is specific to
the engine. The spec is `packages/optimizer/README.md`.

## What it owns

The **single source of truth** for:
- the network build (`nged.py`) and the physics (`network.py` feasibility);
- ranking and the greedy loop (`greedy.py`), the per-year fixed-plan evaluation (`years.py`);
- planned works windows with their verdict and curtailment search (`maintenance.py`), the best window for a work
  (`windows.py`);
- the demand side per region and year (`demand.py`: firm headroom, simplified P2/8-style class and alerts);
- "what would it take" (`suggest.py`), the diff (`diff.py`), editions (`editions.py`);
- what elements are called (`naming.py`: a bus's place, a line's and a transformer's name, served on `GridModel` and the
  only names the planner and the agents use: tool outputs and narration summaries go through `name_text` /
  `name_payload`, so an agent reads "Bicker Fen to Boston 132 kV, circuit 2 (line 1)", never a bare index);
- the CIM/CGMES export (`cim.py`, grid-agnostic: `CgmesMeta` + a bus `substation` column);
- **where a grid comes from** (`sources.py`: the `GridSource` Protocol and the `SOURCES` registry (`nged`, `cgmes`,
  `pandapower_json`, `matpower`), `normalise_net` / `apply_import_meta` / `inspect_net` / `validate_net`; `geometry.py`
  positions, `gridmodel.py` the `GridModel`);
- the pydantic contract (`types.py`) and every tunable (`config.py`).

`network.build_base_net()` is `sources.default_source().build_net()` (NGED); every engine function takes `net_factory=`
for any other source. Bundled open data lives in `src/gridforge_optimizer/data/nged/`.

## Conventions

- Engine functions (`optimize`, `evaluate_years`, `suggest_unblock`, `diff_results`) make no network calls; keep it that
  way. Network/LLM calls belong in `llm.py` and the API only.
- New engine code takes `net_factory=` rather than calling `build_base_net()` directly.
- Re-materialise the pipeline after changing `nged.py` or bundled data, and restart the API: it caches optimize results
  and the GSP boundary in memory.
- pandapower gotchas:
  - embedded generation and new connections are PQ `sgen` (fixed power factor, as a DNO runs them), so voltage problems
    show; an imported grid's voltage-controlled units stay `gen` (setpoint within their reactive limits, solved with
    `enforce_q_lims`) and its power stations follow the merit order (`dispatch.py`). Code that touches the fleet goes
    through `network.FLEET_TABLES` (both tables); a grid with no `gen` takes NGED's path unchanged;
  - use `pandapower.toolbox.drop_buses`;
  - avoid `deepcopy` of nets in hot loops (build once per phase, inject/roll back);
  - in pandapower 3 a transformer's taps are inert unless `tap_changer_type="Ratio"` is set;
  - the LTDS tap ranges (e.g. -12..+4) are HV-winding taps where a lower tap raises the LV voltage, so model them with
    `tap_side="hv"`;
  - `sgen` rows carry `p_rated_mw` and `import_mw` (set by `inject_sgen`) that `dispatch_for_case` reads.
- If a test is ever needed (see the root testing stance), it works on any grid: derive fixtures from `build_base_net()`
  via `tests/_grid.py` (`stiff_bus`, `weak_buses`, `saturating_candidates`, `grid_deferred`, `invalid_bus`), never hardcode
  bus ids, and keep NGED data rules in `tests/test_nged.py`.
