"""Branches and the connections on them: plain functions over a store cursor. No HTTP and no engine here (except the
engine's input type)."""

import json
import uuid

from gridify_optimizer import Connection
from gridify_optimizer.config import IMPORT_ONLY_TECHS

from .config import now
from .errors import Conflict, Invalid, NotFound
from .store import BRANCH_COLS, CONNECTION_COLS, PROFILE_COLS, Cursor


# --- branches ----------------------------------------------------------------
def branch_row(con: Cursor, branch_id: str) -> dict | None:
    r = con.execute(f"SELECT {', '.join(BRANCH_COLS)} FROM branches WHERE branch_id = ?", [branch_id]).fetchone()
    return dict(zip(BRANCH_COLS, r)) if r else None


def require_branch(con: Cursor, branch_id: str) -> dict:
    row = branch_row(con, branch_id)
    if not row:
        raise NotFound(f"branch '{branch_id}' not found")
    return row


def is_main(row: dict) -> bool:
    """Whether a branch is main, the plan of record: the one branch with no parent."""
    return not row.get("parent_id")


def require_open(con: Cursor, branch_id: str, *, allow_main: bool = True) -> dict:
    """The branch exists (404) and is open (409). With allow_main=False main is refused too (409): the plan of record
    changes only by merging into it."""
    row = require_branch(con, branch_id)
    if not allow_main and is_main(row):
        raise Conflict("main is read-only: open a branch to change the plan")
    if row["status"] != "open":
        raise Conflict(f"branch is '{row['status']}', not open")
    return row


def branch_to_client(con: Cursor, row: dict) -> dict:
    n = con.execute("SELECT count(*) FROM connections WHERE branch_id = ?", [row["branch_id"]]).fetchone()[0]
    return {**{c: row[c] for c in BRANCH_COLS}, "n_connections": int(n)}


def list_branches(con: Cursor) -> list[dict]:
    """Every branch, main first, then oldest first."""
    rows = con.execute(f"SELECT {', '.join(BRANCH_COLS)} FROM branches ORDER BY (parent_id IS NULL) DESC, created_at").fetchall()
    return [branch_to_client(con, dict(zip(BRANCH_COLS, r))) for r in rows]


def open_branch(con: Cursor, parent: dict, name: str) -> dict:
    """Open a branch off `parent`: its demand profile and connections come along (copy-on-create)."""
    bid = "br-" + uuid.uuid4().hex[:8]
    con.execute(
        f"INSERT INTO branches (branch_id, name, parent_id, {', '.join(PROFILE_COLS)}, status, created_at) "
        f"VALUES (?, ?, ?, {', '.join('?' * len(PROFILE_COLS))}, 'open', ?)",
        [bid, name, parent["branch_id"], *(parent[c] for c in PROFILE_COLS), now()],
    )
    _copy_connections(con, parent["branch_id"], bid)
    return require_branch(con, bid)


def set_profile(con: Cursor, branch_id: str, profile: dict) -> None:
    con.execute(f"UPDATE branches SET {', '.join(f'{c} = ?' for c in PROFILE_COLS)} WHERE branch_id = ?",
                [*(profile[c] for c in PROFILE_COLS), branch_id])


def set_status(con: Cursor, branch_id: str, status: str, merged_at: str | None = None) -> None:
    con.execute("UPDATE branches SET status = ?, merged_at = ? WHERE branch_id = ?", [status, merged_at, branch_id])


def merge_into(con: Cursor, head: dict, into: dict) -> None:
    """`into` adopts the head's demand profile and connections (replacing its own), and the head is marked merged."""
    con.execute("DELETE FROM connections WHERE branch_id = ?", [into["branch_id"]])
    _copy_connections(con, head["branch_id"], into["branch_id"])
    set_profile(con, into["branch_id"], {c: head[c] for c in PROFILE_COLS})
    set_status(con, head["branch_id"], "merged", now())


# --- connections on a branch -------------------------------------------------
def _copy_connections(con: Cursor, from_branch: str, to_branch: str) -> None:
    con.execute(f"INSERT INTO connections (branch_id, {', '.join(CONNECTION_COLS)}) SELECT ?, {', '.join(CONNECTION_COLS)} "
                f"FROM connections WHERE branch_id = ?", [to_branch, from_branch])


def connection_rows(con: Cursor, branch_id: str) -> list[dict]:
    cur = con.execute(f"SELECT {', '.join(CONNECTION_COLS)} FROM connections WHERE branch_id = ? ORDER BY year, created_at", [branch_id])
    return [dict(zip(CONNECTION_COLS, r)) for r in cur.fetchall()]


def to_client(r: dict) -> dict:
    out = {k: v for k, v in r.items() if k != "control_json"}
    return {**out, "control": json.loads(r["control_json"]) if r.get("control_json") else None}


def connections(con: Cursor, branch_id: str) -> list[Connection]:
    """The engine's view of a branch's connections."""
    return [Connection(request_id=r["request_id"], bus_id=int(r["bus_id"]), technology=r["technology"], rating_mw=float(r["rating_mw"] or 0.0),
                       import_mw=None if r["import_mw"] is None else float(r["import_mw"]),
                       control=json.loads(r["control_json"]) if r.get("control_json") else None, year=int(r["year"]))
            for r in connection_rows(con, branch_id)]


def validate(row: dict, bus_ids: set[int]) -> dict:
    """A connection the engine can simulate, or Invalid with what is missing. A demand or electrolyser connection
    exports nothing: it is judged on what it draws (`import_mw`), its rating 0."""
    tech = (row.get("technology") or "").lower()
    missing = []
    if row.get("bus_id") is None:
        missing.append("a bus")
    elif int(row["bus_id"]) not in bus_ids:
        raise Invalid(f"bus {row['bus_id']} is not in the network model")
    if not tech:
        missing.append("a technology")
    if tech in IMPORT_ONLY_TECHS:
        if not row.get("import_mw"):
            missing.append("its import capacity (MW)")
        row = {**row, "rating_mw": 0.0}
    elif not row.get("rating_mw"):
        missing.append("its rating (MW)")
    if row.get("year") is None:
        missing.append("the year it energises")
    if missing:
        raise Invalid("the connection needs " + ", ".join(missing))
    return row


def _next_request_id(con: Cursor) -> str:
    """A new connection's id: one past the highest `CR-` number ever stored."""
    nums = [int(r[0][3:]) for r in con.execute("SELECT DISTINCT request_id FROM connections WHERE request_id LIKE 'CR-%'").fetchall()
            if r[0][3:].isdigit()]
    return f"CR-{max(nums, default=1000) + 1}"


def insert_connection(con: Cursor, branch_id: str, fields: dict, bus_ids: set[int], *, source: str, request_id: str | None = None) -> dict:
    """Validate and store a connection on a branch; Conflict when a registry project is already on it."""
    if request_id is not None and con.execute("SELECT 1 FROM connections WHERE branch_id = ? AND request_id = ?", [branch_id, request_id]).fetchone():
        raise Conflict(f"{request_id} is already on this branch")
    row = validate({**fields, "request_id": request_id or _next_request_id(con)}, bus_ids)
    control = row.get("control")
    row = {**row, "control_json": json.dumps(control) if control else None, "source": source, "created_at": now()}
    con.execute(f"INSERT INTO connections (branch_id, {', '.join(CONNECTION_COLS)}) VALUES (?, {', '.join('?' * len(CONNECTION_COLS))})",
                [branch_id, *(row.get(c) for c in CONNECTION_COLS)])
    return to_client({c: row.get(c) for c in CONNECTION_COLS})


def update_connection(con: Cursor, branch_id: str, request_id: str, changes: dict, bus_ids: set[int]) -> dict:
    current = next((r for r in connection_rows(con, branch_id) if r["request_id"] == request_id), None)
    if current is None:
        raise NotFound(f"{request_id} is not on branch '{branch_id}'")
    merged = {**to_client(current), **changes}
    row = validate(merged, bus_ids)
    control = row.get("control")
    row = {**row, "control_json": json.dumps(control) if control else None}
    cols = [c for c in CONNECTION_COLS if c not in ("request_id", "source", "created_at")]
    con.execute(f"UPDATE connections SET {', '.join(f'{c} = ?' for c in cols)} WHERE branch_id = ? AND request_id = ?",
                [*(row.get(c) for c in cols), branch_id, request_id])
    return to_client({c: row.get(c) for c in CONNECTION_COLS})


def delete_connection(con: Cursor, branch_id: str, request_id: str) -> None:
    if not con.execute("SELECT 1 FROM connections WHERE branch_id = ? AND request_id = ?", [branch_id, request_id]).fetchone():
        raise NotFound(f"{request_id} is not on branch '{branch_id}'")
    con.execute("DELETE FROM connections WHERE branch_id = ? AND request_id = ?", [branch_id, request_id])
