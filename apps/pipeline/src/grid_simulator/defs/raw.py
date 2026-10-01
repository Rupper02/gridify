import json

import dagster as dg
import pandas as pd
import pandapower as pp

from grid_simulator.config import DATA_DIR


@dg.asset
def raw_network(context: dg.AssetExecutionContext) -> dict[str, pd.DataFrame]:
    net = pp.networks.mv_oberrhein()
    bus_df = net.bus
    line_df = net.line
    load_df = net.load
    trafo_df = net.trafo
    context.add_output_metadata(
        {'buses': len(bus_df), 'lines': len(line_df), 'load': len(load_df), 'trafos': len(trafo_df)})
    return {'bus': bus_df, 'line': line_df, 'load': load_df, 'trafo': trafo_df}


@dg.asset
def raw_geojson(context: dg.AssetExecutionContext) -> pd.DataFrame:
    with open(DATA_DIR / 'substations.geojson') as f:
        gj = json.load(f)

    records = []
    for feature in gj['features']:
        props = feature['properties']
        lon, lat = feature['geometry']['coordinates']
        records.append(
            {
                'bus_id': props['bus_id'],
                'name': props['name'],
                'vn_kv': props['vn_kv'],
                'lon': lon,
                'lat': lat
            }
        )
    df = pd.DataFrame(records)
    context.add_output_metadata({'buses_with_coordinates': len(df)})
    return df


@dg.asset
def raw_register(context: dg.AssetExecutionContext) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / 'asset_register.csv')
    context.add_output_metadata({'rows': len(df)})
    return df
