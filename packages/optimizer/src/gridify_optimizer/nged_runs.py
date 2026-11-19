"""NGED Bicker Fen's year runs: the catalogue the year view reads (`runs.RunCatalogue`), served by `NgedSource.run_catalogue`.

Grid-specific, so it lives beside `nged.py` and `nged_flows.py`: the run files and how each is made, the grown years a
branch's year can be run on, the measured flows they come from, and each run's limits in plain words. The machinery
that reads the files is general (`runs.py`). Supported by NGED Open Data.
"""

from __future__ import annotations

from .runs import RunCatalogue

_FLOWS = "<flows folder>"
_GROWN = ("2024's shape at this year's demand. The size of each substation's peak follows the engine's growth source (the "
          "DFES winter-peak ratio); when and for how long it is exceeded follows 2024's shape, which electrification will "
          "change (a sharper peak means fewer hours above a threshold, new load at quiet times means new ones), so the hour "
          "counts are indicative, not a bound in either direction. One weather year: the same 2035 year grown on 2025's "
          "flows instead of 2024's kept the total (9,212 hours over rating against 9,268, the same elements), but moved "
          "single elements' peaks by a median of 3 points (up to 34) and their hours by a factor of up to five (New Beacon "
          "Road T1 1,818 to 1,499 h; Skegness GT1 745 to 135 h): read an element's hours as an order of magnitude. No new "
          "generation; no outages; no reinforcement; no transfers between substations.")
_MEASURED = ("NGED's half-hourly flows for the run's year through the engine, on today's network. The check against NGED's own "
             "model did not pass in either measured year. Some 33 kV lines and 132/33 kV transformers carry an offset, "
             "shown on each; it has the same sign and a similar size in 2024 and 2025, so it is a difference between the two "
             "models, not an accident of one year. Every run's agreement labels are judged on the 2025 measured year, the one "
             "that closes best. Whether an "
             "element's input is reliable is judged on the run's own flows. Elements whose flow agrees with NGED's model are "
             "findings; the others show the engine's figure with its offset. No outages.")


def _grown(year: int, pathway: str, label: str, variant: str = "") -> tuple:
    v = f" {variant}" if variant else ""
    return (f"grown-{year}-{pathway}{'-' + variant if variant else ''}.npz", label, "grown", year, pathway,
            f"python docs/reports/grown-year-2026-11-13/run.py {year} {pathway}{v}   (from packages/optimizer)")


# run id -> (file, label, kind, year, pathway, how to make it)
_RUNS: dict[str, tuple] = {
    "2024-published": ("measured-year-2024.npz", "2024, NGED's flows as published", "measured", 2024, None,
                       f"python -m gridify_optimizer.timeseries {_FLOWS}/bicker-fen-2024 {_FLOWS}/measured-year-2024.npz published"),
    "2024-screened": ("measured-year-2024-screened.npz", "2024, reactive power screened", "measured", 2024, None,
                      f"python -m gridify_optimizer.timeseries {_FLOWS}/bicker-fen-2024 {_FLOWS}/measured-year-2024-screened.npz screened"),
    "2025-screened": ("measured-year-2025-screened.npz", "2025, reactive power screened", "measured", 2025, None,
                      f"python -m gridify_optimizer.timeseries {_FLOWS}/bicker-fen-2025 {_FLOWS}/measured-year-2025-screened.npz screened"),
    "2030-ht": _grown(2030, "ht", "2030, Holistic Transition (grown)"),
    "2035-ht": _grown(2035, "ht", "2035, Holistic Transition (grown)"),
    "2035-fb": _grown(2035, "fb", "2035, Falling Behind (grown)"),
    "2030-ee": _grown(2030, "ee", "2030, Electric Engagement (grown)"),
    "2035-ee": _grown(2035, "ee", "2035, Electric Engagement (grown)"),
    "2030-fb": _grown(2030, "fb", "2030, Falling Behind (grown)"),
    "2035-ht-flows-2025": _grown(2035, "ht", "2035, Holistic Transition, grown on 2025's flows", "flows-2025"),
    "2030-ht-warth-ltds": _grown(2030, "ht", "2030, Holistic Transition, Warth Lane at NGED's LTDS forecast", "warth-ltds"),
    "2030-ht-grantham": _grown(2030, "ht", "2030 HT + branch: 240 MW solar at Grantham 132 kV", "grantham"),
    "2030-ht-grantham-tied": _grown(2030, "ht", "2030 HT + branch: Grantham 240 MW, 132 kV sections tied", "grantham-tied"),
    "2030-ht-thorns": _grown(2030, "ht", "2030 HT + branch: 40 MW solar at Thorns Farm 33 kV", "thorns"),
}
_BRANCH = (" An example of one branch, not main: one registry project added to this grown year at the bus the registry gives, "
           "on its technology's 2024 shape (solar: Gorse Lane's, per unit). Its storage half, if any, is not modelled: the "
           "registry files it as solar. A battery would run on a placeholder daily rule. Voltage-controlled connections run "
           "at unity.")
# a run's own caveat, added to its kind's limits
_Y2024 = (" In 2024 the engine's infeed differs from NGED's by about 2 MW typically (up to 4 points of loading on a backbone "
          "circuit); NGED's 2024 reactive power at Spilsby is unreliable.")
_NOTES = {"2024-published": _Y2024, "2024-screened": _Y2024,
          "2025-screened": (
    " In 2025 the infeed differs by about 0.3 MW typically (94% of half-hours within the check's tolerance, against 60% in "
    "2024); NGED's model behind the 2025 flows is a newer edition. Spilsby's reactive power is usable in 2025, so its "
    "transformers and substation are findings here. NGED's 2025 series at Wrangle 11 kV is zero for 99% of the year, so Wrangle's transformer shows almost nothing. "
    "Ash Farm's spur is in NGED's 2025 model at Bicker Fen 132 kV but carries nothing all year."),
          "2030-ht-grantham": _BRANCH,
          "2030-ht-grantham-tied": _BRANCH + (" This variant joins Grantham 132 kV's sections 303 and 403 with a zero-impedance "
                                               "tie for this run only, to show how much of the answer is the coupler the model lacks."),
          "2030-ht-thorns": _BRANCH,
          "2035-ht-flows-2025": (
    " This run is the exception: 2025's shape, not 2024's, to measure what one weather year moves. Not comparable with "
    "the 2024-based run at Wrangle (its 2025 series is zero), at Spilsby (usable reactive power, but its injection is "
    "derived in 2025 and so not grown: shown as a finding here, at its 2025 size) and on the Manor Farm tee (its solar flows only in 2025)."),
          "2030-ht-warth-ltds": (
    " A sensitivity: Warth Lane's 2024 series is scaled by NGED's LTDS forecast for 2030 (81.6 MW, 4.38 times its "
    "current maximum) instead of the DFES ratio. That forecast most likely reflects one specific new connection of "
    "unknown shape, so scaling 2024's shape is a placeholder for its size only: the hours depend on a shape nobody has "
    "published.")}
# the saved files before the connector rule (README register "A connector published as a circuit")
_CONNECTOR_NOTE = (" Solved with six connector rows (Boston 132 kV, Tower 91ZB9G9, Skillington, RAF Cranwell) as short lines on "
                   "fallback ratings, before the connector rule; rerunning 2025 under the rule left every rule and label unchanged, "
                   "the largest move 1.7 points on a line at 4.9% beside the RAF Cranwell connectors.")
for _r in _RUNS:
    if _r != "2025-screened":
        _NOTES[_r] = _NOTES.get(_r, "") + _CONNECTOR_NOTE
_BRANCH_YEAR = (" A branch's year, run from the planner: its connections in service by this year are added to the grown year "
                "at their buses, each on its technology's 2024 shape x its capacity, from one site each (README register: "
                "Year shape); these are planning assumptions. A battery, or a hybrid's storage half, follows a placeholder "
                "daily rule (charge 11:00-14:00, export 16:30-19:30, in the file's fixed clock): its worst case is the "
                "branch's own study cases, shown beside each changed element. Voltage-controlled connections run at unity. "
                "A connection at the slack bus moves only the GSP exchange and loads no circuit in this model. Demand follows "
                "this run's pathway, not the branch's demand profile, so the difference from the run it is compared with is "
                "the connections alone.")

CATALOGUE = RunCatalogue(
    runs=_RUNS,
    # the grown years a branch's year can be run on, each its "before": 2030 and 2035 on the planner's three pathways
    bases=("2030-ht", "2035-ht", "2030-ee", "2035-ee", "2030-fb", "2035-fb"),
    measured_flows="bicker-fen-2024",
    # agreement with NGED's model, a property of the network: judged on the best-closing year (rule 1 on 94% of half-hours,
    # against 60% for 2024). NGED's 2025 file compares every element its 2024 file did, and six more
    reference="2025-screened",
    # input reliability is each run's own (its file's screen flags); this file predates the screen: the same flows' flags
    screen_from={"2024-published": "2024-screened"},
    source="NGED",
    measured_limits=_MEASURED,
    grown_limits=_GROWN,
    branch_year_limits=_BRANCH_YEAR,
    notes=_NOTES,
)
