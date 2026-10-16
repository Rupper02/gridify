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


class NgedSource:
    """NGED's Bicker Fen GSP from the bundled LTDS/ECR/OSM snapshot (or the tables the pipeline passes): the builder
    in `nged.py` behind the seam."""

    kind = "nged"
    id = "nged-bickerfen"
    name = "NGED Bicker Fen 132 kV GSP"

    def __init__(self, tables=None):
        from . import nged
        self._nged = nged
        self.tables = tables
        self.edition = nged.EDITION_CURRENT

    def build_net(self):
        return self._nged.build_nged_net(self.tables, self.edition)

    def model(self) -> GridModel:
        return GridModel.model_validate(self._nged.nged_model(self.tables, self.edition))

    def candidates(self) -> list[dict]:
        return self._nged.nged_candidates(MAX_CONNECTION_MW, self.tables)

    def boundary(self) -> dict | None:
        return self._nged.gsp_boundary(self.tables)

    def fingerprint(self) -> str:
        return self._nged.tables_hash(self.tables if self.tables is not None else self._nged.load_bundled_tables()) + f":{self.edition}"

    def assumptions(self) -> list[ModelAssumption]:
        return self._nged.builder_assumptions(self.tables, self.edition) + list(self._nged.PLANNING_ASSUMPTIONS)

    def forecasts(self) -> dict[str, Pathway] | None:
        own = {fid: Pathway(curve, FORECASTS[fid]["label"], self._nged.DFES_SOURCE, True) for fid, curve in self._nged.dfes_pathways(self.tables).items()}
        return own or None  # no DFES rows bundled: the FES anchors as they stand

    @property
    def cgmes_meta(self):
        return self._nged.NGED_CGMES_META


@lru_cache(maxsize=1)
def default_source() -> NgedSource:
    """The grid the engine runs on when no other is named: NGED's bundled snapshot."""
    return NgedSource()


__all__ = ["GridSource", "Pathway", "NgedSource", "default_source"]
