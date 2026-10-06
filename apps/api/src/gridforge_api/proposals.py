"""What merging a branch changes in its base's proposals. Merge copies the branch's planned works
and simulated reinforcements over the base's (routers.branches.merge_branch), so the base gains the
ones the branch added and loses the ones the branch removed. Pure: rows in, the difference out.

Rows match by id: a branch starts with copies of its parent's rows, ids included
(repository.open_branch), and a row is never edited in place, only removed and re-added."""

from __future__ import annotations

_DROP = ("created_at",)


def _changes(base: list[dict], head: list[dict], id_col: str) -> tuple[list[dict], list[dict]]:
    clean = lambda r: {k: v for k, v in r.items() if k not in _DROP}
    on_base = {r[id_col] for r in base}
    on_head = {r[id_col] for r in head}
    return ([clean(r) for r in head if r[id_col] not in on_base],
            [clean(r) for r in base if r[id_col] not in on_head])


def on_merge(base_works: list[dict], head_works: list[dict],
             base_reinforcements: list[dict], head_reinforcements: list[dict]) -> dict:
    """The planned works and reinforcements merging the head into the base adds and removes."""
    works_added, works_removed = _changes(base_works, head_works, "outage_id")
    reinf_added, reinf_removed = _changes(base_reinforcements, head_reinforcements, "reinforcement_id")
    return {"works_added": works_added, "works_removed": works_removed,
            "reinforcements_added": reinf_added, "reinforcements_removed": reinf_removed}
