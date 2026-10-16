"""Editions: the previous LTDS edition is reconstructed from NGED's change flags, the change-set is
consistent with those flags, and the ECR diff is keyed on a site's published identity."""

import pytest

from gridify_optimizer.editions import change_rows, diff_ecr_editions, edition_changeset, status_counts
from gridify_optimizer.nged import (
    EDITION_CURRENT,
    EDITION_PREVIOUS,
    build_nged_net,
    load_bundled_tables,
    nged_model,
    tables_hash,
)


@pytest.fixture(scope="module")
def tables():
    return load_bundled_tables()


@pytest.fixture(scope="module")
def changeset(tables):
    return edition_changeset(tables)


def test_previous_edition_keeps_removed_rows_and_drops_new_ones(tables):
    counts = status_counts(tables)
    assert counts["t2a"].get("removed", 0) > 0 and counts["t2a"].get("new", 0) > 0  # the data has both
    cur = build_nged_net(tables, EDITION_CURRENT)
    prev = build_nged_net(tables, EDITION_PREVIOUS)
    # transformers NGED flagged Removed or New make the two editions' fleets differ
    assert sorted(prev.trafo.sn_mva.round(1)) != sorted(cur.trafo.sn_mva.round(1))
    # the editions' own demand differs (both are scaled to the same NESO GSP peak for the power flow)
    assert float(prev.load.peak_mw.sum()) != pytest.approx(float(cur.load.peak_mw.sum()))
    # both editions are solvable networks with today's fleet
    import pandapower as pp

    for net in (cur, prev):
        pp.runpp(net)
        assert net.converged


def test_tables_passed_in_are_what_gets_built(tables):
    # the pipeline passes its bronze tables through: dropping every demand row must show in the model
    no_demand = {**tables, "demand": []}
    assert nged_model(no_demand)["loads"] == []
    assert nged_model(tables)["loads"]  # the real tables do have demand
    assert tables_hash(no_demand) != tables_hash(tables)
    assert tables_hash(tables) == tables_hash(load_bundled_tables())  # content-stable


def test_changeset_is_consistent_with_ngeds_flags(tables, changeset):
    cs = changeset
    counts = cs["status_counts"]
    rows = cs["rows"]
    for table, col_counts in counts.items():
        for kind in ("new", "removed", "updated"):
            assert sum(1 for r in rows if r["table"] == table and r["change"] == kind) == col_counts.get(kind, 0)
    assert cs["n_changes"]["removed"] > 0 and cs["n_changes"]["new"] > 0
    m = cs["model"]
    assert m["current"]["buses"] > 0 and m["previous"]["buses"] > 0
    assert m["delta"]["demand_mw"] == pytest.approx(m["current"]["demand_mw"] - m["previous"]["demand_mw"], abs=1e-6)
    # a demand point NGED removed (Warth Lane, 18.61 MW) shows as a per-substation drop
    warth = [d for d in m["demand_changes"] if d["substation"].lower().startswith("warth")]
    assert warth and warth[0]["delta_mw"] < 0
    ph = cs["physics"]
    assert ph["current"]["feasible"] and ph["previous"]["feasible"]
    assert set(ph["delta"]) == {"worst_line_pct", "worst_trafo_pct", "min_vm_pu", "max_vm_pu", "gsp_export_mw"}
    assert cs["caveats"]


def test_changeset_is_deterministic(tables, changeset):
    # the row-level part is cheap to recompute; the physics part is memoised by the builder cache
    assert change_rows(tables) == change_rows(tables) == changeset["rows"]
    assert edition_changeset(tables)["model"] == changeset["model"]


def _site(name, status="Accepted to connect", mw=10.0, date="01/06/2028", lat=52.9, lon=-0.2, src="Solar"):
    return {
        "customer_site": name, "lat": lat, "lon": lon, "energy_source_1": src, "point_of_connection(poc)_voltage(kv)": "33",
        "connection_status": status, "accepted_change_to_maximum_export_capacity(mw)": mw if status != "Connected" else None,
        "connected_maximum_export_capacity(mw)": mw if status == "Connected" else None, "target_energisation_date": date,
    }


def test_ecr_diff_reports_added_withdrawn_connected_and_changed_sites():
    prev = [_site("A"), _site("B"), _site("C", mw=20), _site("D", date="01/01/2027"), _site("E")]
    cur = [_site("A"), _site("B", status="Connected"), _site("C", mw=25), _site("D", date="01/01/2029"), _site("F")]
    d = diff_ecr_editions(prev, cur)
    by = {(c["site"], c["change"]): c for c in d}
    assert ("B", "connected") in by and by[("B", "connected")]["detail"] == "Accepted to connect → Connected"
    assert by[("C", "capacity_changed")]["detail"] == "20 → 25 MW"
    assert by[("D", "date_changed")]["detail"] == "01/01/2027 → 01/01/2029"
    assert ("F", "added") in by and ("E", "withdrawn") in by
    assert all(c["site"] != "A" for c in d)  # unchanged sites are not listed
    assert [c["change"] for c in d] == sorted((c["change"] for c in d), key=["connected", "added", "withdrawn", "capacity_changed", "date_changed", "status_changed"].index)


def test_ecr_diff_of_an_edition_with_itself_is_empty(tables):
    assert diff_ecr_editions(tables["ecr"], tables["ecr"]) == []
