import dagster as dg
import pandas as pd


@dg.asset
def canonical_buses(
    context: dg.AssetExecutionContext,
    raw_network: dict[str, pd.DataFrame],
    raw_geojson: pd.DataFrame
) -> pd.DataFrame:

    # bus table is indexed by bus id -> pull the id into a real column
    buses = raw_network['bus'].reset_index(names='bus_id')

    # the GIS layer only contributes coordinates; take just those
    # (avoids clashing with name/vn_kv that already exist on the bus table)
    coords = raw_geojson[['bus_id', 'lon', 'lat']]

    # left join keeps ALL buses; the 5 with no GIS entry get NaN lon/lat
    merged = buses.merge(coords, on='bus_id', how='left')

    missing = int(merged['lon'].isna().sum())
    context.add_output_metadata(
        {'buses': len(merged), 'missing_coords': missing})
    return merged


@dg.asset
def canonical_lines(
    context: dg.AssetExecutionContext,
    raw_network: dict[str, pd.DataFrame],
    raw_register: pd.DataFrame
) -> pd.DataFrame:

    lines = raw_network['line'].reset_index(names='line_id')
    lines = lines[['line_id', 'from_bus', 'to_bus', 'length_km']]

    reg = raw_register.copy()

    reg['line_name'] = reg['line_name'].str.strip()

    reg['voltage_kv'] = (
        reg['voltage'].str.lower().str.replace(
            'kv', '', regex=False).str.strip().astype(float)
    )

    reg['rating_a'] = pd.to_numeric(
        reg['rating_a'].str.replace(r"[^0-9.-]", '', regex=True), errors='coerce'
    )

    reg = reg.drop_duplicates(subset='line_id', keep='first')

    reg_cols = reg[['line_id', 'line_name', 'voltage_kv', 'rating_a']]

    merged = lines.merge(reg_cols, on='line_id', how='left')

    orphans = int((~reg["line_id"].isin(lines["line_id"])).sum())
    context.add_output_metadata(
        {'lines': len(merged), 'orphan_register_rows': orphans})
    return merged


@dg.asset
def canonical_transformers(
    context: dg.AssetExecutionContext,
    raw_network: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    trafos = raw_network["trafo"].reset_index(names="trafo_id")
    trafos = trafos[["trafo_id", "name", "hv_bus",
                     "lv_bus", "sn_mva", "vn_hv_kv", "vn_lv_kv"]]
    context.add_output_metadata({'transformers': len(trafos)})
    return trafos
