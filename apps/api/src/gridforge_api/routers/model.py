"""The read-only baseline of the built-in project: the grid model, its versions, the GSP boundary and the
forecasts. `/model`, `/model/cgmes` and `/boundary` are the NGED project's reads (`routers/projects.py`
serves every project); the versions and change-sets come from the pipeline's warehouse."""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from gridforge_optimizer.config import DEFAULT_SCENARIO, FORECASTS, HORIZONS, MAX_CONNECTION_MW

from ..config import NGED_PROJECT_ID
from ..deps import cache, projects, scenarios, warehouse

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
    """Today's network as a CIM/CGMES 2.4.15 exchange (EQ, TP, SSH, GL profiles in one zip), the
    common model standard GB networks exchange planning models in. Deterministic ids: the same
    snapshot always serialises to the same bytes. Re-imports with pandapower's CGMES importer, and
    as a project through POST /projects."""
    sid = projects.baseline(NGED_PROJECT_ID)
    return Response(
        content=projects.cgmes_zip(NGED_PROJECT_ID, cache.engine), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="GridForge_{sid}_CGMES.zip"'},
    )


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
    rows = warehouse.query(
        "SELECT snapshot_id, created_at, ltds_edition, buses, lines, transformers, loads, candidates "
        "FROM snapshots ORDER BY created_at DESC"
    ) if warehouse.table_exists("snapshots") else []
    return {"current": rows[0]["snapshot_id"] if rows else None, "snapshots": rows}


@router.get("/editions/changes")
def ltds_edition_changes() -> dict:
    """What changed between NGED's previous LTDS edition and the one the model is built from: the
    flagged rows (new / removed / updated circuits, transformers, demand points, busbars), the model
    delta and the physics delta. Computed by the pipeline (`ltds_edition_changes`)."""
    if not warehouse.table_exists("ltds_change_summary"):
        raise HTTPException(status_code=404, detail="no edition change-set in the warehouse: re-materialise the pipeline")
    head = warehouse.query("SELECT * FROM ltds_change_summary ORDER BY computed_at DESC LIMIT 1")[0]
    rows = warehouse.query(
        "SELECT \"table\", change, \"key\", description, value FROM ltds_changes WHERE ltds_edition = ? "
        "ORDER BY \"table\", change, \"key\"",
        [head["ltds_edition"]],
    )
    summary = json.loads(head["summary_json"])
    return {
        "ltds_edition": head["ltds_edition"], "computed_at": head["computed_at"],
        "n_changes": {"new": head["n_new"], "removed": head["n_removed"], "updated": head["n_updated"]},
        "status_counts": summary["status_counts"], "model": summary["model"], "physics": summary["physics"],
        "caveats": summary["caveats"], "rows": rows,
    }


@router.get("/registry/changes")
def registry_changes() -> dict:
    """What changed in NGED's Embedded Capacity Register between the last two fetched editions
    (sites added / withdrawn / connected / re-rated). Empty until the `ecr_refresh` job has run."""
    if not warehouse.table_exists("ecr_editions"):
        return {"editions": [], "changes": []}
    editions = warehouse.query(
        "SELECT edition_id, fetched_at, source, source_last_modified, row_count, note FROM ecr_editions ORDER BY fetched_at DESC"
    )
    changes = warehouse.query(
        "SELECT edition_id, prev_edition_id, computed_at, change, site, energy_source, status, export_mw, "
        "target_energisation_date, detail FROM ecr_changes ORDER BY computed_at DESC, change, site"
    ) if warehouse.table_exists("ecr_changes") else []
    latest = editions[0]["edition_id"] if editions else None
    return {"editions": editions, "changes": [c for c in changes if c["edition_id"] == latest]}


@router.get("/forecasts")
def get_forecasts() -> dict:
    """The FES 2025 demand pathways + policy horizons (single source of truth for the UI)."""
    # Only expose selectable forecasts to the UI picker
    forecasts = [{"id": fid, **f} for fid, f in FORECASTS.items() if f.get("selectable", True)]
    return {"default": DEFAULT_SCENARIO, "forecasts": forecasts, "horizons": HORIZONS,
            "max_connection_mw": MAX_CONNECTION_MW}
