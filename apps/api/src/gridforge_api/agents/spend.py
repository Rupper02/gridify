"""What the agents have spent, per project and day (the credits OpenRouter billed, tokens, power-flow solves), and the
operator's pause switch.

Nothing here limits a run: whoever runs GridForge pays with their own OpenRouter key, so spend is recorded and shown,
never capped. Plain SQL over the scenarios store (table `agent_budgets`, named when it held daily caps).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import NamedTuple

from ..config import now
from ..store import ScenarioStore


class SpendState(NamedTuple):
    day: str
    credits: float  # what OpenRouter billed today (its credits are US dollars)
    tokens: int
    solves: int
    total_credits: float  # every day so far
    paused: bool
    paused_reason: str

    def as_dict(self) -> dict:
        return {"day": self.day, "credits": round(self.credits, 4), "tokens": self.tokens, "solves": self.solves,
                "total_credits": round(self.total_credits, 4), "paused": self.paused, "paused_reason": self.paused_reason}


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class SpendMeter:
    def __init__(self, store: ScenarioStore):
        self._store = store

    def _row(self, con, project_id: str, day: str) -> tuple:
        r = con.execute("SELECT credits, tokens, solves FROM agent_budgets WHERE project_id = ? AND day = ?",
                        [project_id, day]).fetchone()
        return r if r else (0.0, 0, 0)

    def _pause_flag(self, con, project_id: str) -> tuple[bool, str]:
        """The pause switch is per project, not per day: the latest row that set it wins."""
        r = con.execute("SELECT paused, paused_reason FROM agent_budgets WHERE project_id = ? ORDER BY day DESC LIMIT 1", [project_id]).fetchone()
        return (bool(r[0]), r[1] or "") if r else (False, "")

    def _ensure_today(self, con, project_id: str, day: str) -> None:
        """Today's row, carrying the pause switch over from the latest day."""
        if not con.execute("SELECT 1 FROM agent_budgets WHERE project_id = ? AND day = ?", [project_id, day]).fetchone():
            paused, reason = self._pause_flag(con, project_id)
            con.execute("INSERT INTO agent_budgets (project_id, day, credits, tokens, solves, paused, paused_reason, updated_at) "
                        "VALUES (?, ?, 0, 0, 0, ?, ?, ?)", [project_id, day, paused, reason, now()])

    def check(self, project_id: str) -> SpendState:
        day = today()
        with self._store.cursor() as con:
            credits, tokens, solves = self._row(con, project_id, day)
            total = con.execute("SELECT COALESCE(SUM(credits), 0) FROM agent_budgets WHERE project_id = ?", [project_id]).fetchone()[0]
            paused, reason = self._pause_flag(con, project_id)
        return SpendState(day, float(credits), int(tokens), int(solves), float(total), paused, reason)

    def charge(self, project_id: str, *, tokens: int = 0, cost_credits: float | None = None, solves: int = 0) -> SpendState:
        """Add a run's spend to today's row."""
        day = today()
        with self._store.cursor() as con:
            self._ensure_today(con, project_id, day)
            con.execute("UPDATE agent_budgets SET credits = credits + ?, tokens = tokens + ?, solves = solves + ?, updated_at = ? "
                        "WHERE project_id = ? AND day = ?", [float(cost_credits or 0.0), int(tokens), int(solves), now(), project_id, day])
        return self.check(project_id)

    def set_paused(self, project_id: str, paused: bool, reason: str = "") -> SpendState:
        with self._store.cursor() as con:
            self._ensure_today(con, project_id, today())
            # every day's row carries the switch, so the latest row is the truth
            con.execute("UPDATE agent_budgets SET paused = ?, paused_reason = ?, updated_at = ? WHERE project_id = ?",
                        [paused, reason if paused else "", now(), project_id])
        return self.check(project_id)
