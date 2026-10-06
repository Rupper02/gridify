"""The read-only baseline of the built-in project: the grid model, its versions, the GSP boundary and the
forecasts. `/model`, `/model/cgmes` and `/boundary` are the NGED project's reads (`routers/projects.py`
serves every project); the versions and change-sets come from the pipeline's warehouse."""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from gridforge_optimizer import PLAN_YEARS
from gridforge_optimizer.config import DEFAULT_SCENARIO, FORECASTS, HORIZONS, MAX_CONNECTION_MW
from gridforge_optimizer.editions import ECR_DIFF_CAVEATS

from ..config import NGED_PROJECT_ID
from ..deps import projects, scenarios, warehouse
from ..warehouse import has_table, rows
from .projects import project_cgmes

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Liveness probe: reports whether the warehouse DB is present."""
    return {"ok": True, "warehouse_exists": warehouse.exists(), "scenarios_store": scenarios.dialect}


@router.get("/model")
def get_model() -> dict:
    """The built-in project's geolocated grid model for the map (= GET /projects/nged-bickerfen/model)."""
    return projects.model_dict(NGED_PROJECT_ID)


@router.get("/model/cgmes")
def model_cgmes() -> Response:
    """The built-in project's network as a CIM/CGMES exchange (= GET /projects/nged-bickerfen/model/cgmes)."""
    return project_cgmes(NGED_PROJECT_ID)


@router.get("/boundary")
def boundary() -> dict:
    """The GSP boundary: the export limit to transmission, the region's export today, and the
    transmission-registered projects behind the GSP (not-yet-built ones at the GSP are optional
    registry projects, flagged with their registry id)."""
    return projects.boundary(NGED_PROJECT_ID)


# --- versions: snapshot history + what changed between editions -----------------------------
@router.get("/snapshots")
def snapshots() -> dict:
    """The model's version history: one row per content-distinct materialisation of the warehouse
    (`network@<snapshot_id>`), newest first, with the LTDS edition each was built from."""
    found = warehouse.read("route:snapshots", lambda con: rows(
        con, "SELECT snapshot_id, created_at, ltds_edition, buses, lines, transformers, loads, candidates "
             "FROM snapshots ORDER BY created_at DESC") if has_table(con, "snapshots") else [])
    return {"current": found[0]["snapshot_id"] if found else None, "snapshots": found}


@router.get("/editions/changes")
def ltds_edition_changes() -> dict:
    """What changed between NGED's previous LTDS edition and the one the model is built from: the
    flagged rows (new / removed / updated circuits, transformers, demand points, busbars), the model
    delta and the physics delta. Computed by the pipeline (`ltds_edition_changes`)."""
    def read(con):  # the summary and its rows from one committed version
        if not has_table(con, "ltds_change_summary"):
            return None
        head = rows(con, "SELECT * FROM ltds_change_summary ORDER BY computed_at DESC LIMIT 1")[0]
        return head, rows(con, "SELECT \"table\", change, \"key\", description, value FROM ltds_changes WHERE ltds_edition = ? "
                               "ORDER BY \"table\", change, \"key\"", [head["ltds_edition"]])
    found = warehouse.read("route:editions/changes", read)
    if found is None:
        raise HTTPException(status_code=404, detail="no edition change-set in the warehouse: re-materialise the pipeline")
    head, change_rows = found
    summary = json.loads(head["summary_json"])
    return {
        "ltds_edition": head["ltds_edition"], "computed_at": head["computed_at"],
        "n_changes": {"new": head["n_new"], "removed": head["n_removed"], "updated": head["n_updated"]},
        "status_counts": summary["status_counts"], "model": summary["model"], "physics": summary["physics"],
        "caveats": summary["caveats"], "rows": change_rows,
    }


@router.get("/registry/changes")
def registry_changes() -> dict:
    """What changed in NGED's Embedded Capacity Register between the last two fetched editions
    (sites added / withdrawn / connected / re-rated). Empty until the `ecr_refresh` job has run."""
    def read(con):  # the editions and their diff from one committed version
        if not has_table(con, "ecr_editions"):
            return [], []
        return (rows(con, "SELECT edition_id, fetched_at, source, source_last_modified, row_count, note FROM ecr_editions "
                          "ORDER BY fetched_at DESC"),
                rows(con, "SELECT edition_id, prev_edition_id, computed_at, change, site, energy_source, status, export_mw, "
                          "target_energisation_date, detail FROM ecr_changes ORDER BY computed_at DESC, change, site")
                if has_table(con, "ecr_changes") else [])
    editions, changes = warehouse.read("route:registry/changes", read)
    latest = editions[0]["edition_id"] if editions else None
    return {"editions": editions, "changes": [c for c in changes if c["edition_id"] == latest], "caveats": ECR_DIFF_CAVEATS}


@router.get("/forecasts")
def get_forecasts() -> dict:
    """The FES 2025 demand pathways, the plan's years and the policy horizons its two phases end at
    (single source of truth for the UI)."""
    # Only expose selectable forecasts to the UI picker
    forecasts = [{"id": fid, **f} for fid, f in FORECASTS.items() if f.get("selectable", True)]
    return {"default": DEFAULT_SCENARIO, "forecasts": forecasts, "plan_years": list(PLAN_YEARS), "horizons": HORIZONS,
            "max_connection_mw": MAX_CONNECTION_MW}
