"""Projects over HTTP: list them, read a file's voltage levels before importing it, import one (a CGMES zip,
a pandapower JSON or a MATPOWER .mat as a multipart upload, with the limits the operator knows and the study
basis: the demand forecast, the N-1 scope and the voltage limits), read a project's model, boundary, registry,
assumptions and branches, run its main, export it as CGMES, delete it. The unprefixed routes in
`model.py`, `registry.py` and `optimize.py` are the same reads bound to the built-in NGED project."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError

from gridforge_optimizer import ImportMeta
from gridforge_optimizer.sources import import_formats, inspect_file, source_kind_for

from .. import repository
from ..agents import events
from ..config import MAX_IMPORT_BYTES
from ..deps import agents, cache, plans, projects, scenarios
from ..schemas import OptimizeRequest
from .optimize import ran

router = APIRouter()


@router.get("/projects")
def list_projects() -> dict:
    """Every project: the built-in NGED one first, then the imports (newest last)."""
    return {"projects": [projects.to_client(r) for r in projects.rows()]}


@router.get("/projects/formats")
def project_formats() -> dict:
    """What the import form offers: every source kind with its label and extensions (`offered`: a file of it can be
    imported today), and the upload size limit."""
    return {"formats": import_formats(), "max_bytes": MAX_IMPORT_BYTES}


@router.post("/projects")
async def import_project(
    file: UploadFile = File(...),
    name: str = Form(""),
    gsp_export_limit_mw: float | None = Form(None),
    gsp_name: str | None = Form(None),
    gsp_sgt_mw: float | None = Form(None),
    min_demand_factor: float | None = Form(None),
    summer_rating_ratio: float | None = Form(None),
    intermediate_rating_ratio: float | None = Form(None),
    forecasts: str | None = Form(None),
    forecast_source: str | None = Form(None),
    n1_min_kv: float | None = Form(None),
    voltage_bands: str | None = Form(None),
) -> dict:
    """Import a grid as a new project. The file's extension picks the importer (`sources.SOURCES`:
    .zip CGMES, .json pandapower, .mat MATPOWER); the optional form fields are what the operator knows
    and the file does not carry, recorded as operator-entered assumptions. 415 for another file type,
    413 over the size limit, 422 (with the validation report) when the engine cannot plan on it."""
    data = await file.read()
    filename = file.filename or "upload"
    entered = {"gsp_export_limit_mw": gsp_export_limit_mw, "gsp_name": gsp_name, "gsp_sgt_mw": gsp_sgt_mw, "min_demand_factor": min_demand_factor,
               "summer_rating_ratio": summer_rating_ratio, "intermediate_rating_ratio": intermediate_rating_ratio,
               "forecast_source": forecast_source, "n1_min_kv": n1_min_kv}
    try:  # the forecast and the bands are tables, sent as JSON fields of the form
        entered["forecasts"] = json.loads(forecasts) if forecasts else None
        entered["voltage_bands"] = json.loads(voltage_bands) if voltage_bands else None
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"the forecast or the voltage limits are not valid JSON: {e}") from None
    try:
        meta = ImportMeta(**entered) if any(v not in (None, "") for v in entered.values()) else None
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from None

    def create() -> dict:  # the importer and its validation power flow: off the event loop
        out = projects.create(name.strip() or Path(filename).stem, filename, data, meta)
        plans.edited()
        events.emit(agents, "project.imported", {"project_id": out["project_id"], "snapshot_id": out["snapshot_id"]})
        return out
    return await asyncio.to_thread(create)


@router.post("/projects/inspect")
async def inspect_project_file(file: UploadFile = File(...)) -> dict:
    """What the import form asks about a file before it is imported: its voltage levels (each with what an N-1
    screen from that level down covers) and the voltage-limit presets. Nothing is stored or simulated."""
    data = await file.read()
    filename = file.filename or "upload"
    try:
        source_kind_for(filename)
    except ValueError as e:
        raise HTTPException(status_code=415, detail=str(e)) from None
    try:
        return await asyncio.to_thread(inspect_file, filename, data)
    except Exception as e:  # a file the importer cannot read is the user's problem to see, not a 500
        raise HTTPException(status_code=422, detail={"code": "unreadable", "message": f"could not read the file: {type(e).__name__}: {e}"}) from None


@router.get("/projects/{pid}/forecasts")
def project_forecasts(pid: str) -> dict:
    """The demand pathways a project's branches run on: the FES pathways, or the forecast entered at import."""
    return {"project_id": pid, "forecasts": projects.pathways_for_client(pid)}


@router.get("/projects/{pid}")
def get_project(pid: str) -> dict:
    return projects.to_client(projects.row(pid))


@router.delete("/projects/{pid}")
def delete_project(pid: str) -> dict:
    """Remove an imported project with its branches, records, cached results and file (409 for the built-in one)."""
    out = projects.delete(pid)
    plans.edited()
    return out


@router.get("/projects/{pid}/model")
def project_model(pid: str) -> dict:
    """The project's geolocated grid for the map (`crs` says whether the positions are real or a synthetic layout)."""
    return projects.model_dict(pid)


@router.get("/projects/{pid}/model/cgmes")
def project_cgmes(pid: str) -> Response:
    """The project's network as a CIM/CGMES 2.4.15 exchange (EQ, TP, SSH, GL in one zip), deterministic per baseline."""
    sid = projects.baseline(pid)
    return Response(content=projects.cgmes_zip(pid, cache.engine), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="GridForge_{sid}_CGMES.zip"'})


@router.get("/projects/{pid}/boundary")
def project_boundary(pid: str) -> dict:
    """The project's transmission boundary card; 404 when the project models none (no limit was imported or entered)."""
    b = projects.boundary(pid)
    if b is None:
        raise HTTPException(status_code=404, detail="this project models no transmission boundary: export is reported, never limited")
    return b


@router.get("/projects/{pid}/registry")
def project_registry(pid: str) -> list[dict]:
    """The project's registry of optional projects (empty for an import: add projects by hand)."""
    return [repository.to_client(r) for r in projects.registry_rows(pid)]


@router.get("/projects/{pid}/assumptions")
def project_assumptions(pid: str) -> dict:
    """What the model assumes or could not provide: the builder's or importer's records and the planning assumptions."""
    return {"project_id": pid, "assumptions": projects.assumptions(pid)}


@router.get("/projects/{pid}/branches")
def project_branches(pid: str) -> dict:
    """The project's branches, its main first then newest-created."""
    projects.row(pid)
    with scenarios.cursor() as con:
        ids = repository.branch_ids(con, pid)
        return {"branches": [repository.branch_to_client(con, repository.branch_row(con, i)) for i in ids]}


@router.post("/projects/{pid}/optimize")
def optimize_project(pid: str, body: OptimizeRequest) -> dict:
    """Run the project's main (its plan of record) and return the enriched queue, phases and years."""
    main_id = projects.main_id(pid)
    return ran(main_id, plans.optimize_payload(body, main_id), is_main=True)
