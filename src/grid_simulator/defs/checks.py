import dagster as dg
import pandas as pd
import networkx as nx
import pandapower as pp

from grid_simulator.config import VOLTAGE_MIN_PU, VOLTAGE_MAX_PU


@dg.asset_check(asset='canonical_buses')
def buses_have_coords(canonical_buses: pd.DataFrame) -> dg.AssetCheckResult:
    missing = int(canonical_buses[['lon', 'lat']].isna().any(axis=1).sum())
    return dg.AssetCheckResult(
        passed=(missing == 0),
        # missing GIS coords: surface it, don't block
        severity=dg.AssetCheckSeverity.WARN,
        metadata={"missing_coords": missing},
    )


@dg.asset_check(asset='canonical_lines')
def ratings_positive(canonical_lines: pd.DataFrame) -> dg.AssetCheckResult:
    rating = canonical_lines['rating_a']
    wrong = int((rating.isna() | (rating <= 0)).sum())
    return dg.AssetCheckResult(
        passed=(wrong == 0),
        severity=dg.AssetCheckSeverity.ERROR,
        metadata={"bad_ratings": wrong},
    )


@dg.asset_check(
    asset="canonical_lines",
    additional_ins={"canonical_buses": dg.AssetIn(
        "canonical_buses"), "canonical_transformers": dg.AssetIn("canonical_transformers")},
)
def network_connected(canonical_lines: pd.DataFrame, canonical_buses: pd.DataFrame, canonical_transformers: pd.DataFrame) -> dg.AssetCheckResult:
    g = nx.Graph()
    g.add_nodes_from(canonical_buses["bus_id"])
    g.add_edges_from(
        canonical_lines[["from_bus", "to_bus"]].itertuples(index=False))
    g.add_edges_from(
        canonical_transformers[["hv_bus", "lv_bus"]].itertuples(index=False))
    components = nx.number_connected_components(g)
    islanded = sum(1 for _, deg in g.degree() if deg == 0)
    return dg.AssetCheckResult(
        passed=(components == 1),
        metadata={"connected_components": components,
                  "island_buses": islanded},
    )


@dg.asset_check(
    asset="canonical_lines",
    additional_ins={"raw_register": dg.AssetIn("raw_register")}
)
def no_phanton_lines(
    canonical_lines: pd.DataFrame,
    raw_register: pd.DataFrame,
) -> dg.AssetCheckResult:
    real_ids = set(canonical_lines["line_id"])
    phantom = int(raw_register.loc[~raw_register["line_id"].isin(
        real_ids), "line_id"].nunique())
    return dg.AssetCheckResult(
        passed=(phantom == 0),
        severity=dg.AssetCheckSeverity.WARN,
        metadata={"phantom_line_ids": phantom},
    )


@dg.asset_check(asset="raw_network")
def power_flow_converges(raw_network: dict[str, pd.DataFrame]) -> dg.AssetCheckResult:
    net = pp.networks.mv_oberrhein()
    pp.runpp(net)
    v = net.res_bus["vm_pu"]
    buses_match = len(net.bus) == len(raw_network["bus"])
    ok = bool(net.converged and buses_match and v.between(VOLTAGE_MIN_PU, VOLTAGE_MAX_PU).all())
    return dg.AssetCheckResult(
        passed=ok,
        severity=dg.AssetCheckSeverity.WARN,
        metadata={
            "converged": bool(net.converged),
            "v_min_pu": round(float(v.min()), 4),
            "v_max_pu": round(float(v.max()), 4),
            "buses_match_ingested": buses_match,
        }
    )
