"""Operator conversations with the project's agents: threads and their messages (plain SQL)."""

from __future__ import annotations

import json
import uuid

from ..config import now
from ..store import MESSAGE_COLS, THREAD_COLS, Cursor

_JSON = {"tool_trace_json": "tool_trace", "usage_json": "usage", "flags_json": "flags", "evidence_json": "evidence", "model_json": "model_messages"}


def _row(cols, values) -> dict:
    out = dict(zip(cols, values))
    for col, key in _JSON.items():
        if col in out:
            raw = out.pop(col)
            out[key] = json.loads(raw) if raw else None
    return out


def create_thread(con: Cursor, project_id: str, branch_id: str | None, title: str, kind: str = "ask") -> dict:
    tid = "th-" + uuid.uuid4().hex[:8]
    at = now()
    con.execute(f"INSERT INTO threads ({', '.join(THREAD_COLS)}) VALUES ({', '.join('?' * len(THREAD_COLS))})",
                [tid, project_id, branch_id, title, kind, at, at])
    return thread_row(con, tid)


def thread_row(con: Cursor, thread_id: str) -> dict | None:
    r = con.execute(f"SELECT {', '.join(THREAD_COLS)} FROM threads WHERE thread_id = ?", [thread_id]).fetchone()
    return dict(zip(THREAD_COLS, r)) if r else None


def list_threads(con: Cursor, project_id: str, branch_id: str | None = None, kind: str | None = None) -> list[dict]:
    where, params = ["project_id = ?"], [project_id]
    if branch_id is not None:
        where.append("branch_id = ?")
        params.append(branch_id)
    if kind is not None:
        where.append("kind = ?")
        params.append(kind)
    cur = con.execute(f"SELECT {', '.join(THREAD_COLS)} FROM threads WHERE {' AND '.join(where)} ORDER BY updated_at DESC", params)
    return [dict(zip(THREAD_COLS, r)) for r in cur.fetchall()]


def add_message(con: Cursor, thread_id: str, role: str, content: str, *, status: str = "done", workflow_id: str | None = None,
                run_id: str | None = None, tool_trace: list | None = None, model_messages: list | None = None, usage: dict | None = None,
                cost_credits: float | None = None, flags: list | None = None, evidence: dict | None = None) -> dict:
    n = con.execute("SELECT count(*) FROM messages WHERE thread_id = ?", [thread_id]).fetchone()[0]
    mid = "msg-" + uuid.uuid4().hex[:8]
    at = now()
    row = {"message_id": mid, "thread_id": thread_id, "seq": int(n) + 1, "role": role, "content": content, "status": status,
           "workflow_id": workflow_id, "run_id": run_id, "tool_trace_json": json.dumps(tool_trace, default=str) if tool_trace is not None else None,
           "model_json": json.dumps(model_messages, default=str) if model_messages is not None else None,
           "usage_json": json.dumps(usage, default=str) if usage is not None else None, "cost_credits": cost_credits,
           "flags_json": json.dumps(flags, default=str) if flags is not None else None,
           "evidence_json": json.dumps(evidence, default=str) if evidence is not None else None, "created_at": at}
    con.execute(f"INSERT INTO messages ({', '.join(MESSAGE_COLS)}) VALUES ({', '.join('?' * len(MESSAGE_COLS))})", [row[c] for c in MESSAGE_COLS])
    con.execute("UPDATE threads SET updated_at = ? WHERE thread_id = ?", [at, thread_id])
    return message_row(con, mid)


def message_row(con: Cursor, message_id: str) -> dict | None:
    r = con.execute(f"SELECT {', '.join(MESSAGE_COLS)} FROM messages WHERE message_id = ?", [message_id]).fetchone()
    return _row(MESSAGE_COLS, r) if r else None


def messages(con: Cursor, thread_id: str) -> list[dict]:
    cur = con.execute(f"SELECT {', '.join(MESSAGE_COLS)} FROM messages WHERE thread_id = ? ORDER BY seq", [thread_id])
    return [_row(MESSAGE_COLS, r) for r in cur.fetchall()]


def set_message(con: Cursor, message_id: str, **fields) -> dict | None:
    """Update a message's columns (JSON fields by their plain names: tool_trace, usage, flags, evidence, model_messages)."""
    back = {v: k for k, v in _JSON.items()}
    sets, params = [], []
    for k, v in fields.items():
        col = back.get(k, k)
        sets.append(f"{col} = ?")
        params.append(json.dumps(v, default=str) if col in _JSON and v is not None else v)
    if not sets:
        return message_row(con, message_id)
    params.append(message_id)
    con.execute(f"UPDATE messages SET {', '.join(sets)} WHERE message_id = ?", params)
    return message_row(con, message_id)


def history(con: Cursor, thread_id: str, before_seq: int | None = None) -> list:
    """The model-side message history of a thread (what the answerer continues from): the stored model messages of the
    latest finished assistant turn. Each turn stores its run's whole conversation (`all_messages()`: the history it was
    given plus its own), so the latest one already holds every earlier turn; concatenating them would repeat each."""
    out: list = []
    for m in messages(con, thread_id):
        if before_seq is not None and m["seq"] >= before_seq:
            break
        if m["role"] == "assistant" and m.get("model_messages"):
            out = m["model_messages"]
    return list(out)


def history_runs(con: Cursor, thread_id: str, before_seq: int) -> list[str]:
    """The runs whose tool outputs are in `history(con, thread_id, before_seq)`: what the model read before it answers."""
    return [m["run_id"] for m in messages(con, thread_id)
            if m["seq"] < before_seq and m["role"] == "assistant" and m.get("model_messages") and m.get("run_id")]


def streaming_in(con: Cursor, thread_id: str) -> bool:
    return bool(con.execute("SELECT 1 FROM messages WHERE thread_id = ? AND status IN ('queued', 'streaming')", [thread_id]).fetchone())
