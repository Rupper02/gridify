"""The evidence ledger: every tool an agent calls is a recorded step, and every figure an agent files
comes from one of those steps, copied by the server.

An agent never types a number into a finding. It names a step and an item index; `bind_findings`
loads the study the step produced (from the durable result cache, by key) and copies the item's
value, limit, element, case and year into the ledger, so a finding is replayable: the step says which
study, with which parameters, on which snapshot and engine, gave the figure. `check_numbers` is the
soft guard on free text: digit figures in an answer that appear in no step output are flagged, matched
by value. It does not check plan years, counts up to 12 or numbers written as words (a "3" would match
any 3 in the outputs), and a flag never stops the text being shown.
"""

from __future__ import annotations

import json
import re
from typing import NamedTuple

from pydantic import BaseModel

from gridforge_optimizer import Finding, StudyResult

from .. import ledger
from ..cache import ResultCache
from ..store import STEP_COLS, ScenarioStore

INLINE_LIMIT = 8_000  # a step's result is stored inline up to this many characters, else by cache key only


class AgentFinding(BaseModel):
    """What an agent may say about a study item: which item, and its words. Never the figures."""

    step_id: str
    item_index: int
    message: str
    action: str = ""


class StepRecord(NamedTuple):
    step_id: str
    run_id: str
    tool: str
    args: dict
    cache_key: str | None
    result: dict | list | None
    study: StudyResult | None


class EvidenceLedger:
    def __init__(self, store: ScenarioStore, cache: ResultCache):
        self._store = store
        self._cache = cache

    @property
    def engine(self) -> str:
        """The engine fingerprint evidence is recorded under."""
        return self._cache.engine

    def record_step(self, *, run_id: str, step_id: str, seq: int, tool: str, args: dict, cache_key: str | None = None,
                    result: dict | list | None = None, solves: int = 0, started_at: str, finished_at: str,
                    cost_credits: float | None = None, error: str | None = None) -> None:
        """Upsert one tool call (idempotent by step id: a replayed workflow step records nothing new)."""
        inline = None
        if result is not None:
            text = json.dumps(result, default=str)
            inline = text if len(text) <= INLINE_LIMIT else None
        row = {"step_id": step_id, "run_id": run_id, "seq": seq, "tool": tool, "args_json": json.dumps(args, default=str),
               "cache_key": cache_key, "result_json": inline, "solves": solves, "started_at": started_at,
               "finished_at": finished_at, "cost_credits": cost_credits, "error": error}
        with self._store.cursor() as con:
            con.execute(
                f"INSERT INTO agent_steps ({', '.join(STEP_COLS)}) VALUES ({', '.join('?' * len(STEP_COLS))}) "
                "ON CONFLICT (step_id) DO UPDATE SET finished_at = EXCLUDED.finished_at, result_json = EXCLUDED.result_json, "
                "cache_key = EXCLUDED.cache_key, solves = EXCLUDED.solves, cost_credits = EXCLUDED.cost_credits, error = EXCLUDED.error",
                [row[c] for c in STEP_COLS],
            )

    def steps(self, run_id: str) -> list[dict]:
        with self._store.cursor() as con:
            cur = con.execute(f"SELECT {', '.join(STEP_COLS)} FROM agent_steps WHERE run_id = ? ORDER BY seq", [run_id])
            rows = [dict(zip(STEP_COLS, r)) for r in cur.fetchall()]
        for r in rows:
            r["args"] = json.loads(r.pop("args_json") or "{}")
            r["result"] = json.loads(r.pop("result_json") or "null")
        return rows

    def load_step(self, step_id: str) -> StepRecord | None:
        """A step with its output: inline, or the study re-fetched from the durable cache by its key."""
        with self._store.cursor() as con:
            r = con.execute(f"SELECT {', '.join(STEP_COLS)} FROM agent_steps WHERE step_id = ?", [step_id]).fetchone()
        if r is None:
            return None
        row = dict(zip(STEP_COLS, r))
        result = json.loads(row["result_json"]) if row["result_json"] else None
        study = None
        if row["cache_key"]:
            cached = self._cache.get(row["cache_key"])
            if cached is not None:
                study = StudyResult.model_validate_json(cached)
        return StepRecord(step_id, row["run_id"], row["tool"], json.loads(row["args_json"] or "{}"), row["cache_key"], result, study)

    def bind_findings(self, run_id: str, branch_id: str, proposals: list[AgentFinding], *, snapshot_id: str, at: str) -> list[str]:
        """File the agent's findings: for each, the item it names is loaded from the recorded step and
        its figures are copied; the agent contributes the message and the action only. Returns the
        fingerprints filed. A step or item that does not exist is a ValueError (the caller retries the
        model with it)."""
        findings: list[Finding] = []
        evidence_by_fp: dict[str, dict] = {}
        for p in proposals:
            step = self.load_step(p.step_id)
            if step is None or step.study is None:
                raise ValueError(f"step {p.step_id} is not a recorded study of this run")
            if step.run_id != run_id:
                raise ValueError(f"step {p.step_id} belongs to another run")
            if not (0 <= p.item_index < len(step.study.items)):
                raise ValueError(f"step {p.step_id} has no item {p.item_index} (it has {len(step.study.items)})")
            item = step.study.items[p.item_index]
            findings.append(Finding(
                fingerprint=item.fingerprint, kind=step.study.kind, severity=item.severity, source="agent", year=item.year,
                case=item.case, element_kind=item.element_kind,
                element_id=None if item.element_id is None else str(item.element_id), value=item.value, limit=item.limit,
                message=p.message,
                context={"engine_message": item.message, "action": p.action, "unit": item.unit, "item_index": p.item_index,
                         "study_kind": step.study.kind, "extra": item.extra},
            ))
            evidence_by_fp[item.fingerprint] = {"step_id": p.step_id, "run_id": run_id, "cache_key": step.cache_key,
                                                "snapshot_id": snapshot_id, "engine": self._cache.engine,
                                                "study_kind": step.study.kind, "params": step.study.params, "item_index": p.item_index}
        with self._store.cursor() as con:
            for f in findings:  # one row at a time: each carries its own evidence
                ledger.upsert_findings(con, branch_id, [f], evidence_by_fp[f.fingerprint], at, source="agent", evidence_kind="tool_call")
        return [f.fingerprint for f in findings]

    def replay(self, step_id: str) -> dict | None:
        """The study behind a step, as the UI's evidence link shows it: the step, the study, and
        whether the engine has changed since (a stale study is still shown, flagged)."""
        step = self.load_step(step_id)
        if step is None:
            return None
        return {"step": {"step_id": step.step_id, "run_id": step.run_id, "tool": step.tool, "args": step.args, "cache_key": step.cache_key},
                "study": step.study.model_dump() if step.study else None, "result": step.result,
                "current_engine": self._cache.engine, "stale": step.study is None and step.cache_key is not None}


# --- the soft guard on free text ------------------------------------------------------------------------
_NUM = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?(?![\w.])")


def numbers_in(text: str) -> list[float]:
    out = []
    for m in _NUM.findall(text or ""):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def _numbers_of(obj, acc: set[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        acc.add(round(float(obj), 1))
        acc.add(round(float(obj)))
        return
    if isinstance(obj, str):
        for n in numbers_in(obj):
            acc.add(round(n, 1))
            acc.add(round(n))
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _numbers_of(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers_of(v, acc)


def check_numbers(text: str, outputs: list) -> list[float]:
    """Numbers in `text` that no step output contains (to one decimal or rounded to a whole number).
    Plan years and small counts are ignored: they are not figures."""
    seen: set[float] = set()
    for o in outputs:
        _numbers_of(o, seen)
    flagged = []
    for n in numbers_in(text):
        if 2020 <= n <= 2050 or 0 <= n <= 12 and float(n).is_integer():
            continue
        if round(n, 1) in seen or round(n) in seen:
            continue
        flagged.append(n)
    return flagged
