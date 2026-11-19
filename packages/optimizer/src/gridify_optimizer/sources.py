"""Where a grid comes from: the `GridSource` seam.

Everything the engine needs from a network is behind one small Protocol: a fresh solvable pandapower net (`build_net`,
what every engine function takes as `net_factory`), the geolocated model for the map (`model`), the optional registry
of not-yet-built projects (`candidates`), the GSP boundary card (`boundary`), a content fingerprint (`fingerprint`,
the cache baseline), the demand pathways (`forecasts`) and what the model had to assume (`assumptions`). NGED's
open-data builder is the one source today (`NgedSource`); another grid is another implementation.
"""

from __future__ import annotations

from functools import lru_cache
from typing import NamedTuple, Protocol, runtime_checkable

from .config import FORECASTS, MAX_CONNECTION_MW
from .types import GridModel, ModelAssumption


class Pathway(NamedTuple):
    """One demand pathway a grid plans on: its network-wide multiplier per plan year, its label, where it comes from."""

    curve: dict[int, float]
    label: str
    source: str
    cited: bool  # a published or named source


@runtime_checkable
class GridSource(Protocol):
    """A grid the engine can plan on. Implementations must be substitutable: the engine, the API and the pipeline
    call only what is here."""

    id: str
    name: str
    kind: str

    def build_net(self): ...  # a fresh, solvable pandapower net (callers may mutate it)
    def model(self) -> GridModel: ...
    def candidates(self) -> list[dict]: ...  # the registry of optional projects (may be empty)
    def boundary(self) -> dict | None: ...  # the GSP boundary card, or None when the source models none
    def fingerprint(self) -> str: ...  # the content identity results are cached under
    def forecasts(self) -> dict[str, Pathway] | None: ...  # the grid's demand pathways by FORECASTS id; None: the FES anchors
    def assumptions(self) -> list[ModelAssumption]: ...
    def measured_year(self, folder, net, reactive: str = "published"): ...  # a year of measured half-hours mapped onto `net` (MeasuredYear), or raise if the source has none
    def run_catalogue(self): ...  # the year runs its measured data supports (runs.RunCatalogue), or None when it has none


class NgedSource:
    """One NGED Grid Supply Point (its `nged_points.SupplyPoint` record; Bicker Fen by default) from its tables, Bicker
    Fen's bundled LTDS/ECR/OSM snapshot when none are passed: the builder in `nged.py` behind the seam."""

    kind = "nged"

    def __init__(self, tables=None, point=None):
        from . import nged
        from .nged_points import BICKER_FEN
        self._nged = nged
        self.tables = tables
        self.point = point or BICKER_FEN
        self.edition = nged.EDITION_CURRENT
        self.id, self.name = self.point.source_id, self.point.source_name

    def build_net(self):
        return self._nged.build_nged_net(self.tables, self.edition, self.point)

    def model(self) -> GridModel:
        return GridModel.model_validate(self._nged.nged_model(self.tables, self.edition, self.point))

    def candidates(self) -> list[dict]:
        return self._nged.nged_candidates(MAX_CONNECTION_MW, self.tables, self.point)

    def boundary(self) -> dict | None:
        return self._nged.gsp_boundary(self.tables, self.point)

    def fingerprint(self) -> str:
        return self._nged.tables_hash(self.tables if self.tables is not None else self._nged.load_bundled_tables()) + f":{self.edition}"

    def assumptions(self) -> list[ModelAssumption]:
        return self._nged.builder_assumptions(self.tables, self.edition, self.point) + list(self._nged.PLANNING_ASSUMPTIONS)

    def forecasts(self) -> dict[str, Pathway] | None:
        own = {fid: Pathway(curve, FORECASTS[fid]["label"], self._nged.DFES_SOURCE, True) for fid, curve in self._nged.dfes_pathways(self.tables, self.point).items()}
        return own or None  # no DFES rows bundled: the FES anchors as they stand

    def measured_year(self, folder, net, reactive: str = "published"):
        """NGED's half-hourly flows in `folder` (the pipeline's `nged_flows` asset) mapped onto `net`, a net this source
        built; `reactive` picks the published MVAr, the screened one or unity power factor (nged_flows.REACTIVE_MODES)."""
        from .nged_flows import map_year
        ctx = self._nged._ctx(self.tables, self.edition, self.point)
        busid, uf = ctx["busid"], ctx["uf"]
        return map_year(net, lambda code: busid.get(uf.find(code)) if code in busid else None, folder, reactive,
                        held_at_zero=self.point.held_at_zero, year_shapes=self.point.year_shapes)

    def run_catalogue(self):
        """The supply point's year runs (Bicker Fen's: `nged_runs.CATALOGUE`), or None while it has none."""
        return self.point.run_catalogue

    @property
    def cgmes_meta(self):
        return self.point.cgmes


@lru_cache(maxsize=1)
def default_source() -> NgedSource:
    """The grid the engine runs on when no other is named: NGED's bundled snapshot."""
    return NgedSource()


__all__ = ["GridSource", "Pathway", "NgedSource", "default_source"]
