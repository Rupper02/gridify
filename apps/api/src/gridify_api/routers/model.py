"""The read-only grid: the model for the map, the plan's years and intake limit, the assumptions and the registry of
not-yet-built projects."""

from fastapi import APIRouter

from gridify_optimizer import PLAN_YEARS
from gridify_optimizer.config import MAX_CONNECTION_MW

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


@router.get("/forecasts")
def forecasts() -> dict:
    """The plan's years and the largest connection a branch can place (the planner reads both from here)."""
    return {"plan_years": list(PLAN_YEARS), "max_connection_mw": MAX_CONNECTION_MW}


@router.get("/assumptions")
def assumptions() -> list[dict]:
    """What the model assumes: the builder's fallbacks per element and the planning assumptions of the study basis."""
    return grid.assumptions()


@router.get("/registry")
def registry() -> list[dict]:
    """The not-yet-built projects the registry publishes: what a branch can pull on, never part of main until merged."""
    return grid.registry()
