# Reports

The studies behind the engine's choices. Each is a dated record, kept as written: a specification is fixed before its
results, and a report states what was run, what it found and what it cannot tell you. Where a report and the root
README's *Sources and assumptions* register disagree, the register is current.

Internal labels ("Step 1", "Work 4", "Work 8.2") are the order the studies were run in. "The owner" is the project's
author; "the guide session" and "the reviewing session" are separate AI-assisted working sessions, one writing a study's
specification before it ran, the other recomputing its results independently.

## Foundations

| Document | What it is |
|---|---|
| [`study-basis-2026-10-07.md`](study-basis-2026-10-07.md) | What the SQSS, the ESQCR and the DNOs' published methods require, and how Gridify's two study cases follow them |

## A measured year (Bicker Fen)

| Document | What it is |
|---|---|
| [`timeseries-step1-spec-2026-11-12.md`](timeseries-step1-spec-2026-11-12.md) | Specification: NGED's 2024 half-hourly flows through the engine, and the reconciliation of NGED's series |
| [`measured-year-2024/report.md`](measured-year-2024/report.md) | Result: the engine against NGED's own load flow, utilisation, what an intact network leaves out |
| [`measured-year-2024/second-year-2025.md`](measured-year-2024/second-year-2025.md) | 2025 beside 2024 |
| [`grown-year-2026-11-13/spec.md`](grown-year-2026-11-13/spec.md), [`report.md`](grown-year-2026-11-13/report.md) | 2024's shape at 2030 and 2035 demand, on three DFES pathways |
| [`grown-year-2026-11-13/branch-examples.md`](grown-year-2026-11-13/branch-examples.md) | Two registry projects on a branch, through a grown 2030 |
| [`firm-capacity-2026-11-13/report.md`](firm-capacity-2026-11-13/report.md) | Each substation against its own peak and firm capacity, 2026 to 2035 |
| [`grown-year-2026-11-13/data-note-dfes-shape.md`](grown-year-2026-11-13/data-note-dfes-shape.md), [`dfes-shape-2026-11-13/`](dfes-shape-2026-11-13/spec.md) | Whether NGED's DFES can change the *shape* of demand, not only its size. The pre-registered gate failed ([`result.md`](dfes-shape-2026-11-13/result.md)), so no shaped year is built |

## A second supply point (Staythorpe)

| Document | What it is |
|---|---|
| [`scoping-second-supply-point-2026-11-13.md`](scoping-second-supply-point-2026-11-13.md), [`probe-staythorpe-builder-2026-11-13.md`](probe-staythorpe-builder-2026-11-13.md) | Scoping, and the builder run unchanged on a second GSP |
| [`staythorpe-2026-11-13/report.md`](staythorpe-2026-11-13/report.md) | Staythorpe built and commissioned the way Bicker Fen was |

## Design notes and open decisions

| Document | What it is |
|---|---|
| [`grown-year-2026-11-13/design-year-view.md`](grown-year-2026-11-13/design-year-view.md), `scoping-*.md` | Design and scoping notes for the planner's year view and for connections in a year |
| [`overnight-decisions-2026-11-13.md`](overnight-decisions-2026-11-13.md) | A log of modelling decisions taken during the measured-year work. They are applied in the code and the register; **they await the author's final review** |

Scripts in each folder regenerate its figures from the git-ignored flows (fetching them is in the root README,
*Refreshing the data*).
