"""The agent harness: long-lived, evidence-bound agents on the project (see AGENTS.md rule 2).

Stores and policies that need no runtime: `evidence` (the step ledger every figure an agent states is
bound to), `spend` (what the agents spent per project and day, and the pause switch; never a cap), `threads` (operator conversations).
The runtime itself (DBOS workflows, the roster, the tools) sits beside them.
"""
