"""The agent harness: long-lived, evidence-bound agents on the project (see AGENTS.md rule 2).

Stores and policies that need no runtime: `evidence` (the step ledger every figure an agent states is
bound to), `budget` (per-project daily caps and the pause switch), `threads` (operator conversations).
The runtime itself (DBOS workflows, the roster, the tools) sits beside them.
"""
