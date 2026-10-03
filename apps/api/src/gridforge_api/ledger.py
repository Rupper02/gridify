"""The findings ledger and the merge audit: plain functions over a store cursor.

Findings come from the engine (`gridforge_optimizer.extract_findings`, after every run) or, later,
from agents filing them against a recorded study step; `source` and the `evidence_*` columns say
which. A finding's id is stable per branch and fingerprint, so a re-run upserts what is still there
and `resolve_missing` closes what is gone. Merges, refused or done, are recorded with their verdict.
No HTTP and no engine here.
"""

from __future__ import annotations

import hashlib
import json

from gridforge_optimizer import Finding

from .store import FINDING_COLS, MERGE_COLS, Cursor

STATUSES = ("open", "acknowledged", "resolved")
_SEVERITY_SQL = "CASE severity WHEN 'breach' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END"
_JSON_COLS = {"context_json": "context", "evidence_json": "evidence"}
_RENAMED = {"limit_value": "limit", "study_case": "case"}  # SQL-safe column names -> the Finding field names


def finding_id(branch_id: str, fingerprint: str) -> str:
    """Stable per branch and finding identity: the same problem on the same branch is one row."""
    return "f-" + hashlib.sha1(f"{branch_id}|{fingerprint}".encode()).hexdigest()[:16]


def _row(cols: list[str], values) -> dict:
    out = dict(zip(cols, values))
    for col, key in _JSON_COLS.items():
        if col in out:
            out[key] = json.loads(out.pop(col) or "{}")
    for col, key in _RENAMED.items():
        if col in out:
            out[key] = out.pop(col)
    if "verdict_json" in out:
        out["verdict"] = json.loads(out.pop("verdict_json") or "{}")
    return out


# --- findings ----------------------------------------------------------------------------------
def upsert_findings(con: Cursor, branch_id: str, findings: list[Finding], evidence: dict, at: str,
                    *, source: str = "engine", evidence_kind: str = "result_cache") -> None:
    """Insert new findings and refresh the ones already there (figures, message, evidence, last
    seen). A finding that had been resolved and is back reopens; an acknowledged one stays so."""
    rows = []
    for f in findings:
        rows.append([
            finding_id(branch_id, f.fingerprint), branch_id, f.fingerprint, source, f.kind, f.severity, f.year, f.case,
            f.element_kind, f.element_id, f.value, f.limit, f.message, json.dumps(f.context, default=str),
            "open", "", evidence_kind, evidence.get("years_key") or evidence.get("step_id") or "",
            json.dumps(evidence, default=str), evidence.get("snapshot_id"), evidence.get("engine"),
            at, at, None, None,
        ])
    con.executemany(
        f"INSERT INTO findings ({', '.join(FINDING_COLS)}) VALUES ({', '.join('?' * len(FINDING_COLS))}) "
        "ON CONFLICT (finding_id) DO UPDATE SET "
        "severity = EXCLUDED.severity, year = EXCLUDED.year, study_case = EXCLUDED.study_case, "
        "element_kind = EXCLUDED.element_kind, element_id = EXCLUDED.element_id, value = EXCLUDED.value, "
        "limit_value = EXCLUDED.limit_value, message = EXCLUDED.message, context_json = EXCLUDED.context_json, "
        "evidence_kind = EXCLUDED.evidence_kind, evidence_ref = EXCLUDED.evidence_ref, evidence_json = EXCLUDED.evidence_json, "
        "snapshot_id = EXCLUDED.snapshot_id, engine = EXCLUDED.engine, last_seen_at = EXCLUDED.last_seen_at, "
        "status = CASE WHEN status = 'resolved' THEN 'open' ELSE status END, "
        "resolved_at = CASE WHEN status = 'resolved' THEN NULL ELSE resolved_at END",
        rows,
    )


def resolve_missing(con: Cursor, branch_id: str, present: set[str], at: str, *, source: str = "engine") -> int:
    """Resolve this source's findings on the branch that the latest run no longer reports."""
    rows = con.execute(
        "SELECT finding_id, fingerprint FROM findings WHERE branch_id = ? AND source = ? AND status <> 'resolved'",
        [branch_id, source],
    ).fetchall()
    gone = [[at, fid] for fid, fp in rows if fp not in present]
    con.executemany("UPDATE findings SET status = 'resolved', resolved_at = ? WHERE finding_id = ?", gone)
    return len(gone)


def list_findings(con: Cursor, branch_id: str, *, status: str | None = None, year: int | None = None) -> list[dict]:
    """A branch's findings, breaches first, then by year and kind."""
    where, params = ["branch_id = ?"], [branch_id]
    if status is not None:
        where.append("status = ?")
        params.append(status)
    if year is not None:
        where.append("year = ?")
        params.append(year)
    cur = con.execute(
        f"SELECT {', '.join(FINDING_COLS)} FROM findings WHERE {' AND '.join(where)} "
        f"ORDER BY {_SEVERITY_SQL}, COALESCE(year, 0), kind, COALESCE(element_kind, ''), COALESCE(element_id, '')",
        params,
    )
    return [_row(FINDING_COLS, r) for r in cur.fetchall()]


def counts(con: Cursor, branch_id: str) -> dict:
    """How many findings a branch has per status, and the open ones by severity."""
    rows = con.execute(
        "SELECT status, severity, count(*) FROM findings WHERE branch_id = ? GROUP BY status, severity", [branch_id]
    ).fetchall()
    out = {"open": 0, "acknowledged": 0, "resolved": 0, "breach_open": 0, "warn_open": 0}
    for status, severity, n in rows:
        out[status] = out.get(status, 0) + int(n)
        if status == "open" and severity in ("breach", "warn"):
            out[f"{severity}_open"] += int(n)
    return out


def finding_row(con: Cursor, fid: str) -> dict | None:
    r = con.execute(f"SELECT {', '.join(FINDING_COLS)} FROM findings WHERE finding_id = ?", [fid]).fetchone()
    return _row(FINDING_COLS, r) if r else None


def set_status(con: Cursor, fid: str, status: str, note: str, at: str) -> dict | None:
    """The operator's call on a finding: acknowledge it, resolve it, or reopen it."""
    if finding_row(con, fid) is None:
        return None
    acked = at if status == "acknowledged" else None
    resolved = at if status == "resolved" else None
    con.execute(
        "UPDATE findings SET status = ?, note = ?, acked_at = COALESCE(?, acked_at), resolved_at = ? WHERE finding_id = ?",
        [status, note, acked, resolved, fid],
    )
    return finding_row(con, fid)


# --- merges -------------------------------------------------------------------------------------
def record_merge(con: Cursor, *, merge_id: str, branch_id: str, into: str, outcome: str, verdict: dict,
                 acknowledged: bool, evidence: dict, at: str) -> None:
    """One row per merge attempt, refused or done, with the verdict it was judged on."""
    row = {
        "merge_id": merge_id, "branch_id": branch_id, "into_branch": into, "outcome": outcome,
        "ok": bool(verdict.get("ok")), "n_blockers": len(verdict.get("blockers", [])),
        "n_warnings": len(verdict.get("warnings", [])), "acknowledged": acknowledged,
        "verdict_json": json.dumps(verdict, default=str), "head_key": evidence.get("head_years_key"),
        "base_key": evidence.get("base_years_key"), "snapshot_id": evidence.get("snapshot_id"),
        "engine": evidence.get("engine"), "created_at": at,
    }
    con.execute(
        f"INSERT INTO merges ({', '.join(MERGE_COLS)}) VALUES ({', '.join('?' * len(MERGE_COLS))})",
        [row[c] for c in MERGE_COLS],
    )


def merge_rows(con: Cursor, branch_id: str) -> list[dict]:
    cur = con.execute(f"SELECT {', '.join(MERGE_COLS)} FROM merges WHERE branch_id = ? ORDER BY created_at", [branch_id])
    return [_row(MERGE_COLS, r) for r in cur.fetchall()]
