# AGENTS.md — packages/optimizer (`gridforge_optimizer`)

The engine. Read the root `AGENTS.md` first (domain rules, design, testing stance); this file adds what is specific to
the engine. The spec is `packages/optimizer/README.md`.

## What it owns

The **single source of truth** for:
- the network build (`nged.py`) and the physics (`network.py`: growth, dispatch per case, taps, `feasibility`);
- the plan years (`years.py`: `evaluate_year`, `simulate`, the per-year cache key `year_signature`) and the comparison
  (`diff.py`);
- what elements are called (`naming.py`: a bus's place, a line's and a transformer's name, served on `GridModel`);
- the CIM/CGMES export (`cim.py`), editions (`editions.py`) and the registry's readiness rubric (`readiness.py`), all used
  by the pipeline;
- **where a grid comes from** (`sources.py`: the `GridSource` Protocol and `NgedSource`; `geometry.py` positions,
  `gridmodel.py` the `GridModel`);
- the pydantic contract (`types.py`) and every tunable (`config.py`).

`network.build_base_net()` is `sources.default_source().build_net()` (NGED); every engine function takes `net_factory=`
for any other source. Bundled open data lives in `src/gridforge_optimizer/data/nged/`.

## Conventions

- Engine functions make no network calls; keep it that way.
- New engine code takes `net_factory=` rather than calling `build_base_net()` directly.
- A new input to a year's result must go into `years.year_signature`, or the API's per-year cache serves a stale year.
- Re-materialise the pipeline after changing `nged.py` or bundled data, and restart the API.
- pandapower gotchas:
  - embedded generation and new connections are PQ `sgen` (unity or a fixed power factor, as a DNO runs them), so voltage
    problems show; a voltage-controlled connection is a `gen` (setpoint within its reactive limits, solved with
    `enforce_q_lims`). Code that touches the fleet goes through `network.FLEET_TABLES` (both tables);
  - use `pandapower.toolbox.drop_buses`;
  - avoid `deepcopy` of nets in hot loops (build once, inject);
  - in pandapower 3 a transformer's taps are inert unless `tap_changer_type="Ratio"` is set;
  - the LTDS tap ranges (e.g. -12..+4) are HV-winding taps where a lower tap raises the LV voltage, so model them with
    `tap_side="hv"`;
  - `sgen` rows carry `p_rated_mw` and `import_mw` (set by `inject_sgen`) that `dispatch_for_case` reads.
- If a test is ever needed (see the root testing stance), it works on any grid: derive fixtures from `build_base_net()`
  via `tests/_grid.py` (`stiff_bus`, `weak_buses`, `invalid_bus`), never hardcode bus ids, and keep NGED data rules in
  `tests/test_nged.py`.
