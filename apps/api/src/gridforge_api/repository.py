"""Branches and the projects on them: reads, intake triage and the shapes the client sees.

Plain functions over a store cursor; no HTTP and no engine here (except the request/candidate types).
"""

import json
import uuid

from .errors import Conflict, Invalid, NotFound

from gridforge_optimizer import Candidate, Outage, Reinforcement
from gridforge_optimizer.config import IMPORT_ONLY_TECHS, MAX_CONNECTION_MW
from gridforge_optimizer.nged import commission_year

from . import rebase
from .config import ADDED_CANDIDATE_ID_BASE, MANUAL_READINESS_DEFAULT, MANUAL_STRATEGIC_DEFAULT, now
from .schemas import NewCandidate, OptimizeRequest, OutageCreate, ReinforcementCreate
from .store import ADDED_COLS, BRANCH_COLS, OUTAGE_COLS, PROFILE_COLS, REINFORCEMENT_COLS, Cursor


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
        raise NotFound(f"branch '{branch_id}' not found")
    return row


def pick(val, fallback):
    """Use `val` unless it is None, else fall back to the parent/branch value."""
    return fallback if val is None else val


def branch_params(row: dict) -> dict:
    """The scenario fields of a branch row (OptimizeRequest-shaped)."""
    return {c: row[c] for c in PROFILE_COLS}


def _set_profile(con: Cursor, branch_id: str, profile: dict) -> None:
    con.execute(f"UPDATE branches SET {', '.join(f'{c} = ?' for c in PROFILE_COLS)} WHERE branch_id = ?",
                [*(profile[c] for c in PROFILE_COLS), branch_id])


# a branch's rows: projects, works windows, reinforcements (one shape: `branch_id` plus the table's columns)
_PLAN_TABLES = {"projects": ("added_candidates", ADDED_COLS), "works": ("branch_outages", OUTAGE_COLS),
                "reinforcements": ("branch_reinforcements", REINFORCEMENT_COLS)}


def _insert_rows(con: Cursor, area: str, branch_id: str, rows: list[dict]) -> None:
    table, cols = _PLAN_TABLES[area]
    if rows:
        con.executemany(f"INSERT INTO {table} (branch_id, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))})",
                        [[branch_id, *(r.get(c) for c in cols)] for r in rows])


def _copy_rows(con: Cursor, from_branch: str, to_branch: str, areas=tuple(_PLAN_TABLES)) -> None:
    for area in areas:
        table, cols = _PLAN_TABLES[area]
        con.execute(f"INSERT INTO {table} (branch_id, {', '.join(cols)}) SELECT ?, {', '.join(cols)} FROM {table} WHERE branch_id = ?",
                    [to_branch, from_branch])


def _clear_rows(con: Cursor, branch_id: str, areas=tuple(_PLAN_TABLES)) -> None:
    for area in areas:
        con.execute(f"DELETE FROM {_PLAN_TABLES[area][0]} WHERE branch_id = ?", [branch_id])


def branch_request(row: dict) -> OptimizeRequest:
    """Resolve a branch row to an OptimizeRequest (scenario + growth + weights)."""
    return OptimizeRequest(**branch_params(row))


def branch_to_client(con: Cursor, row: dict) -> dict:
    """A branch shaped for the UI (params + added count + status + timestamps)."""
    n_added = con.execute(
        "SELECT count(*) FROM added_candidates WHERE branch_id = ?", [row["branch_id"]]
    ).fetchone()[0]
    # how many of its parent's changes since it was opened an open branch lacks (None: not known, see rebase_plan)
    plan = rebase_plan(con, row) if row["status"] == "open" else None
    return {
        "branch_id": row["branch_id"], "name": row["name"], "parent_id": row["parent_id"],
        **branch_params(row),
        "status": row["status"], "created_at": row["created_at"], "merged_at": row["merged_at"],
        "created_by": row.get("created_by") or "operator", "project_id": row.get("project_id"), "n_added": int(n_added),
        "behind": None if plan is None or plan.fork_kind == "none" else len(rebase.items(plan.behind)),
        "fork": None if plan is None else plan.fork_kind,
    }


def branch_ids(con: Cursor, project_id: str | None = None) -> list[str]:
    """Branch ids, a project's main first then newest-created; every project's when `project_id` is None."""
    where = "WHERE project_id = ?" if project_id else ""
    cur = con.execute(f"SELECT branch_id FROM branches {where} ORDER BY (parent_id IS NULL) DESC, created_at", [project_id] if project_id else [])
    return [r[0] for r in cur.fetchall()]


def open_branch(con: Cursor, parent: dict, name: str, *, created_by: str, overrides: dict | None = None) -> str:
    """Open a branch off `parent` (copy-on-create: its projects, works and reinforcements come along),
    with the parent's parameters unless `overrides` names a value. `created_by` is `operator` or
    `agent:<name>`. Returns the new branch id."""
    o = overrides or {}
    bid = "br-" + uuid.uuid4().hex[:8]
    con.execute(
        f"INSERT INTO branches (branch_id, name, parent_id, {', '.join(PROFILE_COLS)}, status, created_at, created_by, project_id) "
        f"VALUES (?, ?, ?, {', '.join('?' * len(PROFILE_COLS))}, 'open', ?, ?, ?)",
        [bid, name, parent["branch_id"], *(pick(o.get(c), parent[c]) for c in PROFILE_COLS), now(), created_by, parent["project_id"]],
    )
    _copy_rows(con, parent["branch_id"], bid)
    set_fork(con, bid, branch_state(con, parent["branch_id"]))
    return bid


# --- the fork point and rebase (rebase.py decides; this reads and writes) ------------------------------
def branch_state(con: Cursor, branch_id: str) -> dict:
    """A branch's whole plan as `rebase` reads it: its projects, works windows, reinforcements and demand profile."""
    row = require_branch(con, branch_id)
    return {
        "projects": {r["request_id"]: {c: r.get(c) for c in ADDED_COLS[1:]} for r in candidate_rows(con, branch_id)},
        "works": {r["outage_id"]: r for r in outage_rows(con, branch_id)},
        "reinforcements": {r["reinforcement_id"]: r for r in reinforcement_rows(con, branch_id)},
        "profile": branch_params(row),
    }


def fork_point(con: Cursor, head: dict, parent: dict) -> tuple[dict | None, str]:
    """The parent's state when the branch was opened or last rebased, and where it comes from:
    - `recorded`: stored when the branch was opened (or rebased);
    - `rebuilt` (a branch older than fork points, opened from a project's main): a main changes only by merges and a
      merged branch is frozen, so main's state then is the last branch merged into it before the branch was opened, or
      the empty seed. Main's demand profile can be changed on main itself and is not logged, so it is left unknown
      (None): a difference in it is a conflict the operator picks;
    - `none` (an older branch opened from another branch, whose past is not kept): (None, "none"), every difference
      between the two is a conflict (git's rebase without a common ancestor)."""
    if head.get("fork_json"):
        return json.loads(head["fork_json"]), "recorded"
    if parent.get("parent_id"):
        return None, "none"
    r = con.execute("SELECT branch_id FROM merges WHERE into_branch = ? AND outcome = 'merged' AND created_at < ? "
                    "ORDER BY created_at DESC LIMIT 1", [parent["branch_id"], head["created_at"]]).fetchone()
    if r is None:  # merges from before the audit table: the merged branches themselves say when
        r = con.execute("SELECT branch_id FROM branches WHERE parent_id = ? AND status = 'merged' AND merged_at < ? "
                        "ORDER BY merged_at DESC LIMIT 1", [parent["branch_id"], head["created_at"]]).fetchone()
    state = branch_state(con, r[0]) if r else {"projects": {}, "works": {}, "reinforcements": {}}
    return {**state, "profile": None}, "rebuilt"


def set_fork(con: Cursor, branch_id: str, state: dict) -> None:
    con.execute("UPDATE branches SET fork_json = ? WHERE branch_id = ?", [json.dumps(state), branch_id])


def rebase_plan(con: Cursor, head: dict) -> rebase.Plan | None:
    """The rebase of a branch onto its parent as it is now; None for a main, or when the parent it forked from is gone."""
    parent = branch_row(con, head["parent_id"]) if head.get("parent_id") else None
    if parent is None:
        return None
    fork, kind = fork_point(con, head, parent)
    return rebase.plan(fork, branch_state(con, parent["branch_id"]), branch_state(con, head["branch_id"]), fork_kind=kind)


def apply_rebase(con: Cursor, head: dict, p: rebase.Plan, picks: dict, valid_bus_ids: set[int]) -> int:
    """Write the rebase `p` with the operator's `picks` (rebase.PicksError when they do not answer its conflicts): a
    project row mixed from both sides is triaged again, and the fork point moves to the parent's current state. Returns
    how many of the parent's changes the branch took in."""
    state = rebase.resolve(p, picks)
    for row in state["projects"].values():
        if row.pop("_retriage", False):
            row["status"], row["review_reasons"] = triage_row(row, head["branch_id"], valid_bus_ids)
    write_rebased(con, head["branch_id"], state, p.parent)
    return rebase.taken(p, state, picks)


def write_rebased(con: Cursor, branch_id: str, state: dict, fork: dict) -> None:
    """Replace a branch's plan with a rebased state and move its fork point to the parent's current state."""
    _replace_plan(con, branch_id, state)
    set_fork(con, branch_id, fork)


def _replace_plan(con: Cursor, branch_id: str, state: dict) -> None:
    """A branch's plan becomes `state` (a `branch_state`): its projects, works, reinforcements and profile."""
    _clear_rows(con, branch_id)
    _insert_rows(con, "projects", branch_id, [{**row, "request_id": rid} for rid, row in state["projects"].items()])
    for area in ("works", "reinforcements"):
        _insert_rows(con, area, branch_id, list(state[area].values()))
    _set_profile(con, branch_id, state["profile"])


# --- projects on a branch ----------------------------------------------------
def candidate_rows(con: Cursor, branch_id: str) -> list[dict]:
    """Projects IN a branch's plan = the ones added to it. 'main' has none until something is merged
    into it: it is the as-is plan of record; projects are pulled onto branches from the registry."""
    cur = con.execute("SELECT * FROM added_candidates WHERE branch_id = ?", [branch_id])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def project_on_branch(con: Cursor, branch_id: str, request_id: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM added_candidates WHERE branch_id = ? AND request_id = ?", [branch_id, request_id]
    ).fetchone())


def control_of(r: dict) -> dict | None:
    """A stored project's control mode (types.Control as a dict), or None when it states none."""
    raw = r.get("control_json")
    return json.loads(raw) if raw else r.get("control")


def to_client(r: dict) -> dict:
    """Shape a candidate for the UI: valid / incomplete status (triage's `needs_review`: something to complete or
    correct before it can be assessed), non-null applicant, its control mode (None: not stated)."""
    out = {k: v for k, v in r.items() if k != "control_json"}
    return {
        **out,
        "applicant": r.get("applicant") or "",
        "status": "valid" if r.get("status") == "auto_accept" else "incomplete",
        "control": control_of(r),
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
        elif body.import_mw <= 0:
            reasons.append("import capacity must be above 0 MW")
        elif body.import_mw > MAX_CONNECTION_MW:
            reasons.append(f"import capacity is over the {MAX_CONNECTION_MW:g} MW connection cap")
    elif body.rating_mw is None:
        reasons.append("missing rating")
    elif body.rating_mw <= 0:
        reasons.append("rating must be above 0 MW")
    elif body.rating_mw > MAX_CONNECTION_MW:
        reasons.append(f"rating is over the {MAX_CONNECTION_MW:g} MW connection cap")
    if not body.technology:
        reasons.append("missing technology")
    return ("auto_accept" if not reasons else "needs_review"), ", ".join(reasons)


def triage_row(row: dict, branch_id: str, valid_bus_ids: set[int]) -> tuple[str, str]:
    """Triage a stored project row again (after an edit, or a rebase that mixed both sides' fields)."""
    body = NewCandidate(
        applicant=row.get("applicant"), bus_id=row.get("bus_id"), technology=row.get("technology"), rating_mw=row.get("rating_mw"),
        readiness_score=float(row["readiness_score"]) if row.get("readiness_score") is not None else MANUAL_READINESS_DEFAULT,
        strategic_fit=float(row["strategic_fit"]) if row.get("strategic_fit") is not None else MANUAL_STRATEGIC_DEFAULT,
        readiness_rationale=row.get("readiness_rationale") or "", commissioning_year=row.get("commissioning_year"),
        import_mw=row.get("import_mw"), branch_id=branch_id,
    )
    return triage(body, valid_bus_ids)


def _next_request_id(con: Cursor) -> str:
    """A new project's id: one past the highest `CR-` number ever stored (a count would repeat a live id once rows are
    deleted, and rebase, the proposals and the branch state all match projects by id)."""
    nums = [int(r[0][3:]) for r in con.execute("SELECT DISTINCT request_id FROM added_candidates WHERE request_id LIKE 'CR-%'").fetchall()
            if r[0][3:].isdigit()]
    return f"CR-{max(nums, default=ADDED_CANDIDATE_ID_BASE - 1) + 1}"


def insert_candidate(con: Cursor, branch_id: str, body: NewCandidate, valid_bus_ids: set[int]) -> dict:
    """Validate + insert a project on a branch; returns the stored row (client fields)."""
    if (body.technology or "").lower() in IMPORT_ONLY_TECHS and body.rating_mw is None:
        body = body.model_copy(update={"rating_mw": 0.0})  # exports nothing
    status, review = triage(body, valid_bus_ids)
    request_id = _next_request_id(con)
    year = body.commissioning_year or commission_year(
        body.readiness_score, body.technology, body.rating_mw, request_id)
    _insert_rows(con, "projects", branch_id, [{
        **body.model_dump(include=set(ADDED_COLS)), "request_id": request_id, "status": status, "review_reasons": review,
        "commissioning_year": year, "control_json": body.control.model_dump_json() if body.control else None}])
    return {
        "request_id": request_id, "applicant": body.applicant, "bus_id": body.bus_id,
        "technology": body.technology, "rating_mw": body.rating_mw,
        "readiness_score": body.readiness_score, "strategic_fit": body.strategic_fit,
        "readiness_rationale": body.readiness_rationale, "status": status,
        "review_reasons": review, "commissioning_year": year, "import_mw": body.import_mw, "branch_id": branch_id,
        "control": body.control.model_dump() if body.control else None,
    }


_CANDIDATE_EDITS = ("bus_id", "rating_mw", "import_mw", "commissioning_year", "control")


def update_candidate(con: Cursor, branch_id: str, request_id: str, changes: dict, valid_bus_ids: set[int]) -> dict:
    """Change a project's point of connection, export rating, import capacity or requested year on a
    branch (an agent's approved proposal or the operator's edit), re-triaged like a new entry; returns
    the stored row (client fields). A new export rating without an import of its own scales the import
    along (`Candidate.import_at`), so a resized battery charges at its new size. KeyError when the project
    is not on the branch."""
    current = next((r for r in candidate_rows(con, branch_id) if r["request_id"] == request_id), None)
    if current is None:
        raise KeyError(request_id)
    edits = {k: v for k, v in changes.items() if k in _CANDIDATE_EDITS and v is not None}
    if "control" in edits:  # stored as JSON (types.Control, validated by the request body)
        edits["control_json"] = json.dumps(edits.pop("control"))
    if "rating_mw" in edits and "import_mw" not in edits and current.get("import_mw") is not None:
        scaled = Candidate(request_id=request_id, rating_mw=current.get("rating_mw"),
                           import_mw=current["import_mw"]).import_at(float(edits["rating_mw"]))
        if scaled is not None:
            edits["import_mw"] = round(scaled, 3)
    row = {**current, **edits}
    status, review = triage_row(row, branch_id, valid_bus_ids)
    con.execute(
        "UPDATE added_candidates SET bus_id = ?, rating_mw = ?, import_mw = ?, commissioning_year = ?, control_json = ?, status = ?, "
        "review_reasons = ? WHERE branch_id = ? AND request_id = ?",
        [row.get("bus_id"), row.get("rating_mw"), row.get("import_mw"), row.get("commissioning_year"), row.get("control_json"), status, review,
         branch_id, request_id],
    )
    return to_client({**row, "status": status, "review_reasons": review, "branch_id": branch_id})


def add_registry_row(con: Cursor, branch_id: str, row: dict) -> None:
    """Pull one registry project onto a branch (no-op if it is already there)."""
    if project_on_branch(con, branch_id, row["request_id"]):
        return
    _insert_rows(con, "projects", branch_id, [{**row, "scheduled_year": None, "control_json": None}])  # the registry states no control mode


# --- planned outages and simulated reinforcements on a branch ---------------
def _rows(con: Cursor, table: str, cols: list[str], branch_id: str) -> list[dict]:
    cur = con.execute(f"SELECT {', '.join(cols)} FROM {table} WHERE branch_id = ? ORDER BY created_at", [branch_id])
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def outage_rows(con: Cursor, branch_id: str) -> list[dict]:
    return _rows(con, "branch_outages", OUTAGE_COLS, branch_id)


def outages(con: Cursor, branch_id: str) -> list[Outage]:
    return [Outage(**{k: v for k, v in r.items() if k != "created_at"} | {"work": r["work"] or "maintenance"})
            for r in outage_rows(con, branch_id)]


class UnknownElement(Invalid):
    """A works window or a reinforcement on an element the project's network does not have."""


_ELEMENT_SETS = {"line": "lines", "trafo": "trafos", "gen": "generators"}  # element kind -> `Projects.element_ids` key


def _require_known(kind: str, element_id, element_ids: dict[str, set]) -> None:
    key = _ELEMENT_SETS.get(kind)  # a GSP reinforcement names no element
    if key is not None and str(element_id) not in element_ids[key]:
        raise UnknownElement(f"{kind} '{element_id}' is not in the network model")


def insert_outage(con: Cursor, branch_id: str, body: OutageCreate, element_ids: dict[str, set]) -> dict:
    """Store a works window; UnknownElement when its element is not in the network (`Projects.element_ids`)."""
    _require_known(body.element_kind, body.element_id, element_ids)
    row = {"outage_id": "mw-" + uuid.uuid4().hex[:8], **body.model_dump(), "created_at": now()}
    _insert_rows(con, "works", branch_id, [row])
    return row


def reinforcement_rows(con: Cursor, branch_id: str) -> list[dict]:
    return _rows(con, "branch_reinforcements", REINFORCEMENT_COLS, branch_id)


def reinforcements(con: Cursor, branch_id: str) -> list[Reinforcement]:
    return [Reinforcement(kind=r["kind"], element_id=int(r["element_id"]), action=r["action"], factor=float(r["factor"]))
            for r in reinforcement_rows(con, branch_id)]


def insert_reinforcement(con: Cursor, branch_id: str, body: ReinforcementCreate, element_ids: dict[str, set]) -> dict:
    """Store a simulated reinforcement; UnknownElement when its line or transformer is not in the network."""
    _require_known(body.kind, body.element_id, element_ids)
    row = {"reinforcement_id": "rf-" + uuid.uuid4().hex[:8], **body.model_dump(), "created_at": now()}
    _insert_rows(con, "reinforcements", branch_id, [row])
    return row


def delete_branch_row(con: Cursor, table: str, id_col: str, branch_id: str, row_id: str) -> bool:
    found = con.execute(f"SELECT 1 FROM {table} WHERE branch_id = ? AND {id_col} = ?", [branch_id, row_id]).fetchone()
    if found:
        con.execute(f"DELETE FROM {table} WHERE branch_id = ? AND {id_col} = ?", [branch_id, row_id])
    return bool(found)


# --- guards and writes the routers share --------------------------------------
def is_main(row: dict) -> bool:
    """Whether a branch is its project's main, the plan of record: the one branch with no parent (NGED's or an import's)."""
    return not row.get("parent_id")


def require_open(con: Cursor, branch_id: str, *, allow_main: bool = True) -> dict:
    """The branch exists (404) and is open (409). With allow_main=False, any project's main (the branch with no parent)
    is refused too (409): the plan of record is changed only by merging into it."""
    row = require_branch(con, branch_id)
    if not allow_main and is_main(row):
        raise Conflict("main is read-only: open a branch to propose this")
    if row["status"] != "open":
        raise Conflict(f"branch is '{row['status']}', not open")
    return row


def base_of(con: Cursor, head: dict) -> dict | None:
    """The branch a head is compared with and merges into: its parent. A project's main has none (None): it is the
    plan of record, which branches merge into and which merges nowhere. A branch whose parent is gone falls back to
    its own project's main, never another project's."""
    if is_main(head):
        return None
    parent = branch_row(con, head["parent_id"])
    if parent is not None:
        return parent
    r = con.execute("SELECT main_id FROM projects WHERE project_id = ?", [head.get("project_id")]).fetchone()
    return branch_row(con, r[0]) if r else None


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
    _replace_plan(con, into, branch_state(con, head["branch_id"]))
    set_branch_status(con, head["branch_id"], "merged", now())
