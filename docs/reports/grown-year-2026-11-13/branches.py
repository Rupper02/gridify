"""Work 6b: the two worked examples, each one branch on a grown year. Shared by `run.py` and `analyse.py`.

Each example is a registry project as the registry gives it (`GridSource.candidates`: its bus, technology, capacities and
target energisation year), as one `types.Connection`, the contract the plan years take. Supported by NGED Open Data.
"""

import pandapower as pp

from gridify_optimizer import network
from gridify_optimizer.sources import default_source
from gridify_optimizer.types import Connection


def _registry(match) -> Connection:
    c = next(x for x in default_source().candidates() if match(x))
    return Connection(request_id=c["request_id"], bus_id=int(c["bus_id"]), technology=c["technology"],
                      rating_mw=float(c["rating_mw"]), import_mw=c.get("import_mw"), year=int(c["commissioning_year"]))


def grantham() -> list[Connection]:
    """The largest accepted-to-connect generation project: 240 MW of solar + storage at Grantham 132 kV (section 303)."""
    return [_registry(lambda x: x["rating_mw"] == 240.0 and "Grantham 132kV 303" in _bus_name(x["bus_id"]))]


def thorns() -> list[Connection]:
    """The largest accepted-to-connect generation project below 132 kV in service by 2030: Thorns Farm, 40 MW of solar at
    the Whitecross Lane solar park 33 kV tee. (Pasture Farm, 45 MW at Grantham 33 kV, is larger but energises in 2032.)"""
    return [_registry(lambda x: x["rating_mw"] == 40.0 and "Thorns farm" in x["applicant"])]


def grantham_tied_net():
    """The engine's network with Grantham 132 kV's two sections (303 and 403) joined by a zero-impedance tie, for this run
    only: how much of the answer is the coupler the model does not have."""
    net = network.build_base_net()
    a, b = (int(net.bus.index[net.bus.name == n][0]) for n in ("Grantham 132kV 303", "Grantham 132kV 403"))
    pp.create_switch(net, a, b, et="b", closed=True, name="Grantham 132 kV section tie (Work 6b variant)")
    return net


_NAMES: dict[int, str] = {}


def _bus_name(b: int) -> str:
    if not _NAMES:
        _NAMES.update({int(i): str(n) for i, n in network.build_base_net().bus.name.items()})
    return _NAMES[int(b)]


# variant -> (the branch's connections, a net factory or None for the engine's own)
EXAMPLES = {
    "grantham": (grantham, None),
    "grantham-tied": (grantham, grantham_tied_net),
    "thorns": (thorns, None),
}
