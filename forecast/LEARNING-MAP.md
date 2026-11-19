# Learning Map

## Current Project
The forecast experiment (`README.md`): day-ahead half-hourly demand at Newmarket Primary. The learner writes the code;
Claude mentors. Exception on 2026-10-21: the learner ran out of time and asked Claude to finish `load.py` and document it.

## Learner Goal
Write the experiment's Python/pandas code themselves, coming from C and OOP, and understand every line.

## Current Slice
`load.py` is done; every target in section 6 matches (2023–2025):

| Check | Result |
|---|---|
| Half-hours on the grid | 52,608 |
| With both transformers | 48,411 (92.0%) |
| Gaps | 867, longest 53 half-hours = 26.5 h (29–30 Jun 2024) |
| Demand | mean 9.93 MW (README corrected from 9.8), min 4.40, max 18.67 |
| Clock-change days | 3 × 46 half-hours (March), 3 × 50 (October), 1,090 × 48 |

`load.py` has two functions: `load_demand(path)`, which reads top to bottom as the pipeline (one named variable and
one comment per step), and `list_gaps(series)`. The one-off checks live in `__main__`. (It was split into one function
per step first; collapsed on 2026-10-21 because one-line wrappers used once only added jumps.) The steps:

1. `read_csv` with `parse_dates=["timestamp"]` → 105,939 rows, long format (one row per transformer per
   half-hour), timestamps typed as UTC.
2. `pivot` → 53,866 rows × 2 columns (t1, t2). Both kinds of missing (no row; row with empty MW) become NaN.
3. `sum(axis=1, min_count=2)` → NaN unless both transformers reported (without `min_count` a missing one
   counts as 0 and gives a fake 2.68 MW minimum).
4. `date_range` + `reindex` onto every half-hour, so half-hours with no row at all show up as NaN
   (65,712 rows; 10,176 of the new NaNs are January–July 2026, which UKPN doesn't publish).
5. `tz_convert("Europe/London")`. Converting a gap-free UTC grid relabels the same instants; no hours are
   invented or lost, which is why the clock-change days come out at 46 and 50.

`list_gaps`: a gap starts where a half-hour is missing and the one before is not (`shift`); `cumsum` numbers the gaps;
`groupby` gives each one's start, end and length. `__main__` picks the span, prints the share, the gaps and the
half-hours per local day.

Design lesson: a function earns its name when it's reused or hides something complicated behind a clear contract.

## Last Stopping Point
The learner wrote steps 1–4; Claude restructured on request, wrote the local-time step, `list_gaps` and the
clock-change check, then collapsed the file into two functions (2026-10-21). Next session: the learner explains these back, line by line.

## Concepts Practiced
- Names point to objects; rebinding a parameter inside a function doesn't change the caller's (like a C pointer copy)
- Functions without `return` give `None`; type hints aren't checked at runtime
- Attribute vs method: `shape` vs `mean()` (and `<bound method ...>` when the `()` is missing)
- Keyword arguments, lists, `parse_dates` (`True` parses the index only, silently)
- pandas methods return new objects (`pivot`, `reindex`): assign the result
- Whole-column operations (`isna().sum()`, `sum(axis=1)`, boolean mean) instead of loops; pandas method vs built-in `sum`
- `.loc` label slicing includes the end; `axis=0` vs `axis=1`
- Element-wise `~` / `&` (not `not` / `and`), `shift`, `cumsum`, boolean indexing `s[mask]`, `groupby` + `min/max/size`,
  dict literals into `pd.DataFrame`, `.to_numpy()` to align by position
- Reading tracebacks bottom-up, then finding the last line in your own file
- `__main__` wires and prints; logic lives in importable functions
- Leakage: the start/end label convention (one row past the cut-off); interpolating gaps pulls future readings in

## Known Weak Spots
- Forgetting `return` (three times), and when to use `()`
- Nested calls and chains: reading them inside-out / left-to-right
- Telling apart "missing" from "outlier"; why gaps stay NaN instead of being filled

## Next Question
`list_gaps` explained and understood on 2026-10-21 (shift → starts, cumsum → gap numbers, boolean indexing, groupby
like SQL GROUP BY / a C loop over buckets). Next: the learner explains `load_demand` back line by line. Then: the full data audit (repeats, missingness pattern) with the
exploratory-data-analysis skill, and settle the start/end label convention.
