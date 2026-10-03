"""Branches and the projects on them: reads, intake triage and the shapes the client sees.

Plain functions over a store cursor; no HTTP and no engine here (except the request/candidate types).
"""

import uuid

from fastapi import HTTPException

from gridforge_optimizer import Outage, Reinforcement
from gridforge_optimizer.config import IMPORT_ONLY_TECHS, MAX_CONNECTION_MW
from gridforge_optimizer.nged import commission_year

from .config import ADDED_CANDIDATE_ID_BASE, now
from .schemas import NewCandidate, OptimizeRequest, OutageCreate, ReinforcementCreate
from .store import ADDED_COLS, BRANCH_COLS, OUTAGE_COLS, REINFORCEMENT_COLS, Cursor


# --- branches ----------------------------------------------------------------
def branch_row(con: Cursor, branch_id: str) -> dict | None:
    """One branch as a dict keyed by BRANCH_COLS, or None if it doesn't exist."""
    r = con.execute(
        f"SELECT {', '.join(BRANCH_COLS)} FROM branches WHERE branch_id = ?", [branch_id]
    ).fetchone()
    return dict(zip(BRANCH_COLS, r)) if r else None


def require_branch(con: Cursor, branch_id: str) -> dict:
    row = branch_row(con, branch_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"branch '{branch_id}' not found")
    return row


def pick(val, fallback):
    """Use `val` unless it is None, else fall back to the parent/branch value."""
    return fallback if val is None else val


def branch_params(row: dict) -> dict:
    """The scenario fields of a branch row (OptimizeRequest-shaped)."""
    return {
        "scenario": row["scenario"],
        "growth_2030": row["growth_2030"],
        "growth_2035": row["growth_2035"],
        "w_readiness": row["w_readiness"],
        "w_need": row["w_need"],
        "w_strategic": row["w_strategic"],
    }


def branch_request(row: dict) -> OptimizeRequest:
    """Resolve a branch row to an OptimizeRequest (scenario + growth + weights)."""
    return OptimizeRequest(with_justification=False, **branch_params(row))


def branch_to_client(con: Cursor, row: dict) -> dict:
    """A branch shaped for the UI (params + added count + status + timestamps)."""
    n_added = con.execute(
        "SELECT count(*) FROM added_candidates WHERE branch_id = ?", [row["branch_id"]]
    ).fetchone()[0]
    return {
        "branch_id": row["branch_id"], "name": row["name"], "parent_id": row["parent_id"],
        **branch_params(row),
        "status": row["status"], "created_at": row["created_at"], "merged_at": row["merged_at"],
        "created_by": row.get("created_by") or "operator", "n_added": int(n_added),
    }


def open_branch(con: Cursor, parent: dict, name: str, *, created_by: str, overrides: dict | None = None) -> str:
    """Open a branch off `parent` (copy-on-create: its projects, works and reinforcements come along),
    with the parent's parameters unless `overrides` names a value. `created_by` is `operator` or
    `agent:<name>`. Returns the new branch id."""
    o = overrides or {}
    bid = "br-" + uuid.uuid4().hex[:8]
    con.execute(
        "INSERT INTO branches (branch_id, name, parent_id, scenario, growth_2030, growth_2035, "
        "w_readiness, w_need, w_strategic, status, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
        [bid, name, parent["branch_id"],
         pick(o.get("scenario"), parent["scenario"]), pick(o.get("growth_2030"), parent["growth_2030"]),
         pick(o.get("growth_2035"), parent["growth_2035"]), pick(o.get("w_readiness"), parent["w_readiness"]),
         pick(o.get("w_need"), parent["w_need"]), pick(o.get("w_strategic"), parent["w_strategic"]), now(), created_by],
    )
    copy_projects(con, parent["branch_id"], bid)
    copy_branch_extras(con, parent["branch_id"], bid)
    return bid


# --- projects on a branch ----------------------------------------------------
def candidate_rows(con: Cursor, branch_id: str = "main") -> list[dict]:
    """Projects IN a branch's plan = the ones added to it. 'main' has none until something is merged
    into it: it is the as-is plan of record; projects are pulled onto branches from the registry."""
    cur = con.execute("SELECT * FROM added_candidates WHERE branch_id = ?", [branch_id])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def project_on_branch(con: Cursor, branch_id: str, request_id: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM added_candidates WHERE branch_id = ? AND request_id = ?", [branch_id, request_id]
    ).fetchone())


def to_client(r: dict) -> dict:
    """Shape a candidate for the UI: valid/rejected status, non-null applicant."""
    return {
        **r,
        "applicant": r.get("applicant") or "",
        "status": "valid" if r.get("status") == "auto_accept" else "rejected",
    }


def triage(body: NewCandidate, valid_bus_ids: set[int]) -> tuple[str, str]:
    """Intake triage for a manually added project -> (status, review_reasons)."""
    reasons = []
    if body.bus_id is None:
        reasons.append("missing a bus")
    elif int(body.bus_id) not in valid_bus_ids:
        reasons.append("bus is not in model")
    if (body.technology or "").lower() in IMPORT_ONLY_TECHS:  # demand / electrolyser: judged on what it draws
        if body.import_mw is None:
            reasons.append("missing import capacity")
        elif not (0 < body.import_mw <= MAX_CONNECTION_MW):
            reasons.append("import capacity is out of range")
    elif body.rating_mw is None:
        reasons.append("missing rating")
    elif not (0 < body.rating_mw <= MAX_CONNECTION_MW):
        reasons.append("rating is out of range")
    if not body.technology:
        reasons.append("missing technology")
    return ("auto_accept" if not reasons else "needs_review"), ", ".join(reasons)


def insert_candidate(con: Cursor, branch_id: str, body: NewCandidate, valid_bus_ids: set[int]) -> dict:
    """Validate + insert a project on a branch; returns the stored row (client fields)."""
    if (body.technology or "").lower() in IMPORT_ONLY_TECHS and body.rating_mw is None:
        body = body.model_copy(update={"rating_mw": 0.0})  # exports nothing
    status, review = triage(body, valid_bus_ids)
    n = con.execute("SELECT count(*) FROM added_candidates").fetchone()[0]
    request_id = f"CR-{ADDED_CANDIDATE_ID_BASE + n}"
    year = body.commissioning_year or commission_year(
        body.readiness_score, body.technology, body.rating_mw, request_id)
    con.execute(
        f"INSERT INTO added_candidates ({ADDED_COLS}, branch_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [request_id, body.applicant, body.bus_id, body.technology, body.rating_mw,
         body.readiness_score, body.strategic_fit, body.readiness_rationale, status, review,
         year, None, body.import_mw, branch_id],
    )
    return {
        "request_id": request_id, "applicant": body.applicant, "bus_id": body.bus_id,
        "technology": body.technology, "rating_mw": body.rating_mw,
        "readiness_score": body.readiness_score, "strategic_fit": body.strategic_fit,
        "readiness_rationale": body.readiness_rationale, "status": status,
        "review_reasons": review, "commissioning_year": year, "import_mw": body.import_mw, "branch_id": branch_id,
    }


def copy_projects(con: Cursor, from_branch: str, to_branch: str) -> None:
    """Snapshot one branch's projects onto another (copy-on-create and squash-merge)."""
    con.execute(
        f"INSERT INTO added_candidates ({ADDED_COLS}, branch_id) "
        f"SELECT {ADDED_COLS}, ? FROM added_candidates WHERE branch_id = ?",
        [to_branch, from_branch],
    )


def add_registry_row(con: Cursor, branch_id: str, row: dict) -> None:
    """Pull one registry project onto a branch (no-op if it is already there)."""
    if project_on_branch(con, branch_id, row["request_id"]):
        return
    con.execute(
        f"INSERT INTO added_candidates ({ADDED_COLS}, branch_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [row["request_id"], row.get("applicant"), row.get("bus_id"), row.get("technology"),
         row.get("rating_mw"), row.get("readiness_score"), row.get("strategic_fit"),
         row.get("readiness_rationale"), row.get("status"), row.get("review_reasons"),
         row.get("commissioning_year"), None, row.get("import_mw"), branch_id],
    )


# --- planned outages and simulated reinforcements on a branch ---------------
def _rows(con: Cursor, table: str, cols: list[str], branch_id: str) -> list[dict]:
    cur = con.execute(f"SELECT {', '.join(cols)} FROM {table} WHERE branch_id = ? ORDER BY created_at", [branch_id])
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def outage_rows(con: Cursor, branch_id: str) -> list[dict]:
    return _rows(con, "branch_outages", OUTAGE_COLS, branch_id)


def outages(con: Cursor, branch_id: str) -> list[Outage]:
    return [Outage(**{k: v for k, v in r.items() if k != "created_at"} | {"work": r["work"] or "maintenance"})
            for r in outage_rows(con, branch_id)]


def insert_outage(con: Cursor, branch_id: str, body: OutageCreate) -> dict:
    row = {"outage_id": "mw-" + uuid.uuid4().hex[:8], **body.model_dump(), "created_at": now()}
    con.execute(
        f"INSERT INTO branch_outages (branch_id, {', '.join(OUTAGE_COLS)}) VALUES (?, {', '.join('?' * len(OUTAGE_COLS))})",
        [branch_id, *(row[c] for c in OUTAGE_COLS)],
    )
    return row


def reinforcement_rows(con: Cursor, branch_id: str) -> list[dict]:
    return _rows(con, "branch_reinforcements", REINFORCEMENT_COLS, branch_id)


def reinforcements(con: Cursor, branch_id: str) -> list[Reinforcement]:
    return [Reinforcement(kind=r["kind"], element_id=int(r["element_id"]), action=r["action"], factor=float(r["factor"]))
            for r in reinforcement_rows(con, branch_id)]


def insert_reinforcement(con: Cursor, branch_id: str, body: ReinforcementCreate) -> dict:
    row = {"reinforcement_id": "rf-" + uuid.uuid4().hex[:8], **body.model_dump(), "created_at": now()}
    con.execute(
        f"INSERT INTO branch_reinforcements (branch_id, {', '.join(REINFORCEMENT_COLS)}) "
        f"VALUES (?, {', '.join('?' * len(REINFORCEMENT_COLS))})",
        [branch_id, *(row[c] for c in REINFORCEMENT_COLS)],
    )
    return row


def delete_branch_row(con: Cursor, table: str, id_col: str, branch_id: str, row_id: str) -> bool:
    found = con.execute(f"SELECT 1 FROM {table} WHERE branch_id = ? AND {id_col} = ?", [branch_id, row_id]).fetchone()
    if found:
        con.execute(f"DELETE FROM {table} WHERE branch_id = ? AND {id_col} = ?", [branch_id, row_id])
    return bool(found)


def copy_branch_extras(con: Cursor, from_branch: str, to_branch: str) -> None:
    """Snapshot a branch's planned outages and reinforcements onto another (create and merge)."""
    for table, cols in (("branch_outages", OUTAGE_COLS), ("branch_reinforcements", REINFORCEMENT_COLS)):
        con.execute(
            f"INSERT INTO {table} (branch_id, {', '.join(cols)}) SELECT ?, {', '.join(cols)} FROM {table} WHERE branch_id = ?",
            [to_branch, from_branch],
        )


def clear_branch_extras(con: Cursor, branch_id: str) -> None:
    for table in ("branch_outages", "branch_reinforcements"):
        con.execute(f"DELETE FROM {table} WHERE branch_id = ?", [branch_id])


# --- guards and writes the routers share --------------------------------------
def require_open(con: Cursor, branch_id: str, *, allow_main: bool = True) -> dict:
    """The branch exists (404) and is open (409). With allow_main=False, main is refused too (409):
    the plan of record is changed only by merging into it."""
    row = require_branch(con, branch_id)
    if not allow_main and branch_id == "main":
        raise HTTPException(status_code=409, detail="main is read-only: open a branch to propose this")
    if row["status"] != "open":
        raise HTTPException(status_code=409, detail=f"branch is '{row['status']}', not open")
    return row


def base_of(con: Cursor, head: dict) -> dict:
    """The branch a head is compared with and merges into by default: its parent, else main."""
    return branch_row(con, head["parent_id"] or "main") or branch_row(con, "main")


def set_schedule(con: Cursor, branch_id: str, request_id: str, year: int | None) -> None:
    con.execute("UPDATE added_candidates SET scheduled_year = ? WHERE branch_id = ? AND request_id = ?",
                [year, branch_id, request_id])


def update_scenario(con: Cursor, branch_id: str, scenario: str, growth_2030: float, growth_2035: float) -> None:
    con.execute("UPDATE branches SET scenario=?, growth_2030=?, growth_2035=? WHERE branch_id=?",
                [scenario, growth_2030, growth_2035, branch_id])


def set_branch_status(con: Cursor, branch_id: str, status: str, merged_at: str | None = None) -> None:
    con.execute("UPDATE branches SET status=?, merged_at=? WHERE branch_id=?", [status, merged_at, branch_id])


def merge_into(con: Cursor, head: dict, into: str) -> None:
    """Squash-merge: `into` adopts the head's scenario, projects, planned works and reinforcements
    (replacing its own), and the head is marked merged."""
    con.execute(
        "UPDATE branches SET scenario=?, growth_2030=?, growth_2035=?, w_readiness=?, w_need=?, w_strategic=? WHERE branch_id=?",
        [head["scenario"], head["growth_2030"], head["growth_2035"], head["w_readiness"], head["w_need"], head["w_strategic"], into],
    )
    con.execute("DELETE FROM added_candidates WHERE branch_id = ?", [into])
    copy_projects(con, head["branch_id"], into)
    clear_branch_extras(con, into)
    copy_branch_extras(con, head["branch_id"], into)
    set_branch_status(con, head["branch_id"], "merged", now())
