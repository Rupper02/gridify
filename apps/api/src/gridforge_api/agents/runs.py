"""Agent runs, run notes and proposal approvals: plain SQL over the scenarios store."""

from __future__ import annotations

import json
import uuid

from ..config import now
from ..store import APPROVAL_COLS, NOTE_COLS, RUN_COLS, Cursor

_JSON = {"digest_json": "digest", "flags_json": "flags", "args_json": "args", "result_json": "result"}


def _row(cols, values) -> dict:
    out = dict(zip(cols, values))
    for col, key in _JSON.items():
        if col in out:
            raw = out.pop(col)
            out[key] = json.loads(raw) if raw else None
    return out


# --- runs ----------------------------------------------------------------------------------------------
def start_run(con: Cursor, *, run_id: str, project_id: str, kind: str, agent: str, workflow_id: str | None, branch_id: str | None = None,
              thread_id: str | None = None, event_id: str | None = None, parent_run_id: str | None = None, model: str | None = None,
              status: str = "running") -> dict:
    row = {"run_id": run_id, "project_id": project_id, "kind": kind, "agent": agent, "workflow_id": workflow_id, "branch_id": branch_id,
           "thread_id": thread_id, "event_id": event_id, "parent_run_id": parent_run_id, "status": status, "started_at": now(),
           "finished_at": None, "model": model, "input_tokens": 0, "output_tokens": 0, "cost_credits": None, "solves": 0, "summary": "", "error": None}
    con.execute(
        f"INSERT INTO agent_runs ({', '.join(RUN_COLS)}) VALUES ({', '.join('?' * len(RUN_COLS))}) "
        "ON CONFLICT (run_id) DO UPDATE SET status = EXCLUDED.status, workflow_id = EXCLUDED.workflow_id",
        [row[c] for c in RUN_COLS],
    )
    return row


def finish_run(con: Cursor, run_id: str, *, status: str, summary: str = "", error: str | None = None, input_tokens: int = 0,
               output_tokens: int = 0, cost_credits: float | None = None, solves: int = 0) -> None:
    con.execute(
        "UPDATE agent_runs SET status = ?, finished_at = ?, summary = ?, error = ?, input_tokens = ?, output_tokens = ?, cost_credits = ?, solves = ? "
        "WHERE run_id = ?",
        [status, now(), summary, error, int(input_tokens), int(output_tokens), cost_credits, int(solves), run_id],
    )


def run_row(con: Cursor, run_id: str) -> dict | None:
    r = con.execute(f"SELECT {', '.join(RUN_COLS)} FROM agent_runs WHERE run_id = ?", [run_id]).fetchone()
    return dict(zip(RUN_COLS, r)) if r else None


def list_runs(con: Cursor, project_id: str, *, kind: str | None = None, limit: int = 50) -> list[dict]:
    where, params = ["project_id = ?"], [project_id]
    if kind:
        where.append("kind = ?")
        params.append(kind)
    params.append(int(limit))
    cur = con.execute(f"SELECT {', '.join(RUN_COLS)} FROM agent_runs WHERE {' AND '.join(where)} ORDER BY started_at DESC LIMIT ?", params)
    return [dict(zip(RUN_COLS, r)) for r in cur.fetchall()]


def running_count(con: Cursor, project_id: str) -> int:
    return int(con.execute("SELECT count(*) FROM agent_runs WHERE project_id = ? AND status IN ('queued', 'running')", [project_id]).fetchone()[0])


def open_runs(con: Cursor, project_id: str | None = None) -> list[tuple[str, str | None]]:
    """(run_id, workflow_id) of every run still marked queued or running, in one project or all of them."""
    where, params = "status IN ('queued', 'running')", []
    if project_id:
        where += " AND project_id = ?"
        params.append(project_id)
    return [(r[0], r[1]) for r in con.execute(f"SELECT run_id, workflow_id FROM agent_runs WHERE {where}", params).fetchall()]


def open_runs_of(con: Cursor, branch_id: str, kind: str) -> list[tuple[str, str | None]]:
    """(run_id, workflow_id) of the runs of one kind still queued or running on a branch."""
    cur = con.execute("SELECT run_id, workflow_id FROM agent_runs WHERE branch_id = ? AND kind = ? AND status IN ('queued', 'running')", [branch_id, kind])
    return [(r[0], r[1]) for r in cur.fetchall()]


def close_run(con: Cursor, run_id: str, *, status: str, error: str) -> None:
    """End a run its workflow never finished (DBOS ended it first); what it already recorded is kept."""
    con.execute("UPDATE agent_runs SET status = ?, finished_at = ?, error = ? WHERE run_id = ? AND status IN ('queued', 'running')",
                [status, now(), error, run_id])


# --- run notes: the engineer's note on a branch's current run --------------------------------------------
def supersede_notes(con: Cursor, branch_id: str, run_key: str) -> int:
    rows = con.execute("SELECT note_id FROM run_notes WHERE branch_id = ? AND run_key <> ? AND status = 'current'", [branch_id, run_key]).fetchall()
    con.executemany("UPDATE run_notes SET status = 'superseded' WHERE note_id = ?", [[r[0]] for r in rows])
    return len(rows)


def insert_note(con: Cursor, *, project_id: str, branch_id: str, run_key: str, run_id: str, body: str, digest: dict, flags: list) -> dict:
    nid = "nt-" + uuid.uuid4().hex[:8]
    row = {"note_id": nid, "project_id": project_id, "branch_id": branch_id, "run_key": run_key, "run_id": run_id, "body": body,
           "digest_json": json.dumps(digest, default=str), "flags_json": json.dumps(flags, default=str), "status": "current", "created_at": now()}
    con.execute(f"INSERT INTO run_notes ({', '.join(NOTE_COLS)}) VALUES ({', '.join('?' * len(NOTE_COLS))})", [row[c] for c in NOTE_COLS])
    return _row(NOTE_COLS, [row[c] for c in NOTE_COLS])


def current_note(con: Cursor, branch_id: str) -> dict | None:
    """The note on the branch's current run, or None (never written, or superseded by a newer run)."""
    r = con.execute(f"SELECT {', '.join(NOTE_COLS)} FROM run_notes WHERE branch_id = ? AND status = 'current' ORDER BY created_at DESC LIMIT 1",
                    [branch_id]).fetchone()
    return _row(NOTE_COLS, r) if r else None


def note_exists(con: Cursor, branch_id: str, run_key: str) -> bool:
    return bool(con.execute("SELECT 1 FROM run_notes WHERE branch_id = ? AND run_key = ?", [branch_id, run_key]).fetchone())


# --- approvals -----------------------------------------------------------------------------------------
def add_approval(con: Cursor, *, project_id: str, thread_id: str, message_id: str, run_id: str, tool_call_id: str, tool: str, args: dict) -> dict:
    aid = "ap-" + uuid.uuid4().hex[:8]
    row = {"approval_id": aid, "project_id": project_id, "thread_id": thread_id, "message_id": message_id, "run_id": run_id,
           "tool_call_id": tool_call_id, "tool": tool, "args_json": json.dumps(args, default=str), "status": "pending", "decided_at": None,
           "decided_by": None, "note": "", "result_json": None, "created_at": now()}
    con.execute(f"INSERT INTO approvals ({', '.join(APPROVAL_COLS)}) VALUES ({', '.join('?' * len(APPROVAL_COLS))})", [row[c] for c in APPROVAL_COLS])
    return _row(APPROVAL_COLS, [row[c] for c in APPROVAL_COLS])


def approval_row(con: Cursor, approval_id: str) -> dict | None:
    r = con.execute(f"SELECT {', '.join(APPROVAL_COLS)} FROM approvals WHERE approval_id = ?", [approval_id]).fetchone()
    return _row(APPROVAL_COLS, r) if r else None


def approvals_for_message(con: Cursor, message_id: str) -> list[dict]:
    """Every proposal one reply made, in the order it made them (the reply resumes once all are decided)."""
    cur = con.execute(f"SELECT {', '.join(APPROVAL_COLS)} FROM approvals WHERE message_id = ? ORDER BY created_at", [message_id])
    return [_row(APPROVAL_COLS, r) for r in cur.fetchall()]


def list_approvals(con: Cursor, project_id: str, *, status: str | None = "pending", thread_id: str | None = None) -> list[dict]:
    where, params = ["project_id = ?"], [project_id]
    if status:
        where.append("status = ?")
        params.append(status)
    if thread_id:
        where.append("thread_id = ?")
        params.append(thread_id)
    cur = con.execute(f"SELECT {', '.join(APPROVAL_COLS)} FROM approvals WHERE {' AND '.join(where)} ORDER BY created_at", params)
    return [_row(APPROVAL_COLS, r) for r in cur.fetchall()]


def decide_approval(con: Cursor, approval_id: str, status: str, note: str, decided_by: str = "operator") -> dict | None:
    con.execute("UPDATE approvals SET status = ?, note = ?, decided_at = ?, decided_by = ? WHERE approval_id = ?",
                [status, note, now(), decided_by, approval_id])
    return approval_row(con, approval_id)


def set_approval_result(con: Cursor, approval_id: str, status: str, result: dict | None) -> None:
    con.execute("UPDATE approvals SET status = ?, result_json = ? WHERE approval_id = ?",
                [status, json.dumps(result, default=str) if result is not None else None, approval_id])


# --- events and project state ----------------------------------------------------------------------------
def event_by_dedup(con: Cursor, project_id: str, dedup_id: str) -> dict | None:
    r = con.execute("SELECT event_id, workflow_ids FROM project_events WHERE project_id = ? AND dedup_id = ?", [project_id, dedup_id]).fetchone()
    return {"event_id": r[0], "workflow_ids": (r[1] or "").split(",") if r[1] else []} if r else None


def insert_event(con: Cursor, *, event_id: str, project_id: str, type_: str, dedup_id: str, payload: dict) -> None:
    con.execute("INSERT INTO project_events (event_id, project_id, type, dedup_id, payload_json, created_at, workflow_ids) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [event_id, project_id, type_, dedup_id, json.dumps(payload, default=str), now(), ""])


def set_event_workflows(con: Cursor, event_id: str, workflow_ids: list[str]) -> None:
    con.execute("UPDATE project_events SET workflow_ids = ? WHERE event_id = ?", [",".join(workflow_ids), event_id])


def recent_events(con: Cursor, project_id: str, limit: int = 5) -> list[dict]:
    cur = con.execute("SELECT event_id, type, dedup_id, created_at, workflow_ids FROM project_events WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                      [project_id, int(limit)])
    return [{"event_id": r[0], "type": r[1], "dedup_id": r[2], "created_at": r[3], "workflow_ids": (r[4] or "").split(",") if r[4] else []}
            for r in cur.fetchall()]


def state_get(con: Cursor, project_id: str, key: str) -> str | None:
    r = con.execute("SELECT value FROM project_state WHERE project_id = ? AND key = ?", [project_id, key]).fetchone()
    return r[0] if r else None


def state_set(con: Cursor, project_id: str, key: str, value: str) -> None:
    con.execute("INSERT INTO project_state (project_id, key, value, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (project_id, key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
                [project_id, key, value, now()])
