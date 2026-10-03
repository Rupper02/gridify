"""Per-project daily budgets for the agents (credits, tokens, power-flow solves) and the pause switch.

A run that would exceed the day's budget is not started (recorded `skipped_budget`); the operator
can pause and resume the agents on a project at any time. Plain SQL over the scenarios store.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import NamedTuple

from ..config import AGENT_BUDGET_DAILY, now
from ..store import ScenarioStore


class BudgetState(NamedTuple):
    day: str
    credits: float
    tokens: int
    solves: int
    limits: dict
    paused: bool
    paused_reason: str
    exhausted: bool

    def as_dict(self) -> dict:
        return {"day": self.day, "credits": round(self.credits, 4), "tokens": self.tokens, "solves": self.solves,
                "limits": self.limits, "paused": self.paused, "paused_reason": self.paused_reason, "exhausted": self.exhausted}


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class BudgetMeter:
    def __init__(self, store: ScenarioStore, daily: dict | None = None):
        self._store = store
        self.daily = dict(daily or AGENT_BUDGET_DAILY)

    def _row(self, con, project_id: str, day: str) -> tuple:
        r = con.execute("SELECT credits, tokens, solves, paused, paused_reason FROM agent_budgets WHERE project_id = ? AND day = ?",
                        [project_id, day]).fetchone()
        return r if r else (0.0, 0, 0, False, "")

    def _pause_flag(self, con, project_id: str) -> tuple[bool, str]:
        """The pause switch is per project, not per day: the latest row that set it wins."""
        r = con.execute("SELECT paused, paused_reason FROM agent_budgets WHERE project_id = ? ORDER BY day DESC LIMIT 1", [project_id]).fetchone()
        return (bool(r[0]), r[1] or "") if r else (False, "")

    def check(self, project_id: str) -> BudgetState:
        day = today()
        with self._store.cursor() as con:
            credits, tokens, solves, _, _ = self._row(con, project_id, day)
            paused, reason = self._pause_flag(con, project_id)
        over = (credits >= self.daily.get("credits", float("inf")) or tokens >= self.daily.get("tokens", float("inf"))
                or solves >= self.daily.get("solves", float("inf")))
        if over and not paused:
            paused, reason = True, "budget"
        return BudgetState(day, float(credits), int(tokens), int(solves), self.daily, paused, reason, over)

    def charge(self, project_id: str, *, tokens: int = 0, cost_credits: float | None = None, solves: int = 0) -> BudgetState:
        """Add a run's usage to today's row (created on first use; the pause flag is kept)."""
        day = today()
        with self._store.cursor() as con:
            credits0, tokens0, solves0, paused, reason = self._row(con, project_id, day)
            if not con.execute("SELECT 1 FROM agent_budgets WHERE project_id = ? AND day = ?", [project_id, day]).fetchone():
                paused, reason = self._pause_flag(con, project_id)
                con.execute("INSERT INTO agent_budgets (project_id, day, credits, tokens, solves, paused, paused_reason, updated_at) "
                            "VALUES (?, ?, 0, 0, 0, ?, ?, ?)", [project_id, day, bool(paused), reason or "", now()])
            con.execute("UPDATE agent_budgets SET credits = ?, tokens = ?, solves = ?, updated_at = ? WHERE project_id = ? AND day = ?",
                        [float(credits0) + float(cost_credits or 0.0), int(tokens0) + int(tokens), int(solves0) + int(solves), now(), project_id, day])
        return self.check(project_id)

    def set_paused(self, project_id: str, paused: bool, reason: str = "") -> BudgetState:
        day = today()
        with self._store.cursor() as con:
            if not con.execute("SELECT 1 FROM agent_budgets WHERE project_id = ? AND day = ?", [project_id, day]).fetchone():
                con.execute("INSERT INTO agent_budgets (project_id, day, credits, tokens, solves, paused, paused_reason, updated_at) "
                            "VALUES (?, ?, 0, 0, 0, ?, ?, ?)", [project_id, day, paused, reason, now()])
            # every day's row carries the switch, so the latest row is the truth
            con.execute("UPDATE agent_budgets SET paused = ?, paused_reason = ?, updated_at = ? WHERE project_id = ?",
                        [paused, reason if paused else "", now(), project_id])
        return self.check(project_id)
