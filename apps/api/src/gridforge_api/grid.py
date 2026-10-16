"""The grid GridForge plans on: NGED Bicker Fen, read from the pipeline's warehouse so the lineage is real.

`Grid` is the one place the API reads a network through: the `GridSource`, the model for the map, the bus ids a
connection is checked against, the boundary card, the demand pathways, the registry of not-yet-built projects and
the assumptions. Its read-through caches live here, per baseline, each computed once under its own lock."""

from __future__ import annotations

import threading

from gridforge_optimizer import GridModel, ModelAssumption
from gridforge_optimizer.config import FORECASTS
from gridforge_optimizer.naming import name_model
from gridforge_optimizer.network import band_at, build_base_net
from gridforge_optimizer.nged import gsp_boundary
from gridforge_optimizer.sources import NgedSource, Pathway

from .warehouse import Warehouse


class WarehouseNgedSource:
    """NGED as the API sees it: the model, the registry and the snapshot id from the pipeline's warehouse, the network,
    the boundary, the pathways and the assumptions from the engine's builder."""

    kind = "nged"
    id = "nged-bickerfen"
    name = "NGED Bicker Fen 132 kV GSP"

    def __init__(self, warehouse: Warehouse):
        self._warehouse = warehouse
        self._engine = NgedSource()

    def build_net(self):
        return build_base_net()

    def model(self) -> GridModel:
        """The warehouse's model, each bus with the band the engine judges it against and every element named by place."""
        m = self._warehouse.baseline_model()
        for b in m["buses"]:
            b["vmin_pu"], b["vmax_pu"] = band_at(float(b["vn_kv"]))
        model = GridModel.model_validate(m)
        name_model(model)
        return model

    def candidates(self) -> list[dict]:
        return self._warehouse.registry_rows()

    def boundary(self) -> dict | None:
        return gsp_boundary()

    def fingerprint(self) -> str:
        return self._warehouse.baseline_id()

    def assumptions(self) -> list[ModelAssumption]:
        return self._engine.assumptions()

    def forecasts(self) -> dict[str, Pathway] | None:
        return self._engine.forecasts()


class Grid:
    """The grid behind every branch (a `GridSource`), with per-baseline caches."""

    def __init__(self, source):
        self.source = source
        self._models: dict[str, GridModel] = {}
        self._boundaries: dict[str, dict | None] = {}
        # one computation per cache, however many requests ask at once (the boundary is a full power flow)
        self._locks = {"model": threading.Lock(), "boundary": threading.Lock()}

    @property
    def name(self) -> str:
        return self.source.name

    def baseline(self) -> str:
        """The content identity results are cached under (the warehouse snapshot)."""
        return self.source.fingerprint()

    def build_net(self):
        return self.source.build_net()

    def model(self) -> GridModel:
        key = self.baseline()
        with self._locks["model"]:
            if key not in self._models:
                self._models = {key: self.source.model()}
            return self._models[key]

    def bus_coords(self) -> dict[int, tuple[float, float]]:
        return {b.bus_id: (b.lon, b.lat) for b in self.model().buses}

    def bus_ids(self) -> set[int]:
        return {b.bus_id for b in self.model().buses}

    def boundary(self) -> dict | None:
        key = self.baseline()
        with self._locks["boundary"]:
            if key not in self._boundaries:
                self._boundaries = {key: self.source.boundary()}
            return self._boundaries[key]

    def registry(self) -> list[dict]:
        """The not-yet-built projects the registry publishes, shaped as connections (their requested year as the year),
        with the facts they come with."""
        return [
            {"request_id": r["request_id"], "name": r.get("applicant") or r["request_id"], "bus_id": r.get("bus_id"),
             "technology": r.get("technology"), "rating_mw": r.get("rating_mw"), "import_mw": r.get("import_mw"),
             "year": r.get("commissioning_year"), "note": r.get("readiness_rationale") or "",
             "complete": r.get("status") == "auto_accept", "review_reasons": r.get("review_reasons") or ""}
            for r in self.source.candidates()
        ]

    def forecasts(self) -> dict[str, Pathway] | None:
        return self.source.forecasts()

    def pathways(self) -> list[dict]:
        """The demand picker's pathways, each with its network-wide multiplier per year where the grid has its own."""
        own = self.forecasts() or {}
        out = []
        for fid, f in FORECASTS.items():
            if not f.get("selectable", True):
                continue
            pw = own.get(fid)
            out.append({"id": fid, "label": f["label"], "short": f["short"], "description": f["description"],
                        "source": pw.source if pw else f["source"],
                        "curve": {str(y): m for y, m in sorted(pw.curve.items())} if pw else None})
        return out

    def assumptions(self) -> list[dict]:
        return [a.model_dump() for a in self.source.assumptions()]
