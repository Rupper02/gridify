"""NGED data rules: the base network is what exists TODAY; everything else is an optional project."""

import pytest

from gridforge_optimizer.config import MAX_CONNECTION_MW
from gridforge_optimizer.nged import DEMAND_DIVERSITY, _load, _num, build_nged_net, nged_candidates


def _live(rows, col):
    return [r for r in rows if str(r.get(col) or "").strip().lower() != "removed"]


def test_ltds_removed_equipment_is_not_in_todays_network():
    net = build_nged_net()
    mw = lambda rows: sum(_num(d["Current Year Max Demand"]) or 0.0 for d in rows)
    live_mw, all_mw = mw(_live(_load("demand"), "Status")), mw(_load("demand"))
    assert all_mw > live_mw  # the data does flag some demand as Removed…
    # …none of it is modelled, and every live MW is (incl. rows naming several busbars)
    assert float(net.load.p_mw.sum()) == pytest.approx(live_mw * DEMAND_DIVERSITY, rel=1e-6)
    removed_trafos = [t for t in _load("t2a") if str(t.get("Status")).lower() == "removed"]
    assert removed_trafos and len(net.trafo) <= len(_live(_load("t2a"), "Status"))


def test_projects_not_built_yet_are_registry_only():
    net = build_nged_net()
    registry = nged_candidates(MAX_CONNECTION_MW)
    tec = [c for c in registry if c["request_id"].startswith("TEC-")]
    assert tec, "the GSP-embedded transmission project is offered in the registry"
    # …but nothing from the registry is pre-loaded into today's network (only the existing fleet)
    names = set(net.sgen.name.astype(str))
    assert not any(c["request_id"] in names for c in registry)
    assert all(n.startswith("EX-") for n in names)
