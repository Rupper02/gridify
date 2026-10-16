"""The read-only grid: the model for the map, the GSP boundary, the demand pathways, the assumptions and the registry
of not-yet-built projects."""

from fastapi import APIRouter

from gridforge_optimizer import PLAN_YEARS
from gridforge_optimizer.config import DEFAULT_SCENARIO, IMPORT_ONLY_TECHS, MAX_CONNECTION_MW

from ..deps import grid, scenarios, warehouse

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Liveness probe: reports whether the warehouse DB is present."""
    return {"ok": True, "warehouse_exists": warehouse.exists(), "scenarios_store": scenarios.dialect}


@router.get("/model")
def get_model() -> dict:
    """The geolocated grid model for the map, with the grid's name and snapshot."""
    return {"name": grid.name, "snapshot_id": grid.baseline(), **grid.model().model_dump()}


@router.get("/boundary")
def boundary() -> dict | None:
    """The GSP boundary: the export limit to transmission, the region's export today, and the transmission-registered
    projects behind the GSP."""
    return grid.boundary()


@router.get("/forecasts")
def forecasts() -> dict:
    """The demand pathways, the plan's years and the intake limits (single source of truth for the planner)."""
    return {"default": DEFAULT_SCENARIO, "forecasts": grid.pathways(), "plan_years": list(PLAN_YEARS),
            "max_connection_mw": MAX_CONNECTION_MW, "import_only_techs": list(IMPORT_ONLY_TECHS)}


@router.get("/assumptions")
def assumptions() -> list[dict]:
    """What the model assumes: the builder's fallbacks per element and the planning assumptions of the study basis."""
    return grid.assumptions()


@router.get("/registry")
def registry() -> list[dict]:
    """The not-yet-built projects the registry publishes: what a branch can pull on, never part of main until merged."""
    return grid.registry()
