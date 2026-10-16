// Map data -> GeoJSON for MapLibre. Pure: given the model, the viewed year's result and the view state, build the
// feature collections the map layers read. Rebuilt only when its inputs change.

import type { Feature, FeatureCollection, LineString, Point } from "geojson";

import { C, loadColor, voltColor } from "../theme";
import type { LoadingDelta, MapLayer, Model, Sel, YearDelta, YearResult } from "../types";
import { type FeatureKey, type LineTier, type LineTiers, lineFeature, shows, tierOf } from "./mapFeatures";
import { midpoint } from "./placement";

/** Compare mode: a loading change smaller than this (points) is not drawn as a change. */
export const MAP_DELTA_MIN = 1;

export interface MapDelta {
  delta: number;
  head: number;
}
/** Compare mode on the map: the loading change against the parent per line and transformer (changed ones only). */
export interface DiffMap {
  lines: Map<number, MapDelta>;
  trafos: Map<number, MapDelta>;
}
const changed = (xs: LoadingDelta[]): Map<number, MapDelta> =>
  new Map(xs.filter((t) => Math.abs(t.delta) >= MAP_DELTA_MIN).map((t) => [t.element_id, { delta: t.delta, head: t.head_pct ?? 0 }]));
export const diffMapFor = (yd: YearDelta | null): DiffMap => ({ lines: changed(yd?.top_line_deltas ?? []), trafos: changed(yd?.top_trafo_deltas ?? []) });
/** A changed element by where it lands: red over 100%, amber when it rises, green when it eases. */
export const diffColor = (d: MapDelta): string => (d.head > 100 ? C.red : d.delta > 0 ? C.amber : C.phase1);
/** A map tag's text: the change, and the loading it reaches when that is over 100%. */
export const deltaTag = (d: MapDelta): string => `${d.delta > 0 ? "+" : ""}${Math.round(d.delta)}%${d.head > 100 ? ` · ${Math.round(d.head)}%` : ""}`;

export interface GeoInputs {
  model: Model;
  yr: YearResult | null;
  layer: MapLayer;
  sel: Sel | null;
  /** Compare mode: the viewed year's loading change against the parent, or null when compare is off. */
  diff: DiffMap | null;
  visible: readonly FeatureKey[];
  /** The grid's own line voltages in tiers: what is drawn heavy, medium and thin. */
  tiers: LineTiers;
}

export interface Geo {
  lines: FeatureCollection;
  buses: FeatureCollection;
  loads: FeatureCollection;
  openpts: FeatureCollection;
  trafos: FeatureCollection;
  existing: FeatureCollection;
}

export const GEO_SOURCES = ["lines", "buses", "loads", "openpts", "trafos", "existing"] as const;

const FC = (features: Feature[]): FeatureCollection => ({ type: "FeatureCollection", features });
const pt = (lo: number, la: number, props: Record<string, unknown>): Feature<Point> => ({
  type: "Feature",
  geometry: { type: "Point", coordinates: [lo, la] },
  properties: props,
});

/** Line width and colour by the grid's voltage tier: its highest level heavy and light, the next medium, lower thin. */
const LINE_STYLE: Record<LineTier, { w: number; c: string }> = {
  high: { w: 2.8, c: C.lineHigh },
  mid: { w: 1.8, c: C.lineMid },
  low: { w: 1.2, c: C.lineLow },
};
/** A busbar's dot by its voltage tier (radius on the flow layer, on the voltage layer, colour). */
const BUS_STYLE: Record<LineTier, { r: number; rVolt: number; c: string }> = {
  high: { r: 3.6, rVolt: 5, c: C.lineHigh },
  mid: { r: 2.8, rVolt: 5, c: "#9fb3c9" },
  low: { r: 2, rVolt: 3.5, c: "#9fb3c9" },
};

export function buildGeo(g: GeoInputs): Geo {
  const { model: m, yr, layer, sel, diff, tiers } = g;
  const on = (k: FeatureKey) => shows(g.visible, k);
  const mLines = m.lines.filter((l) => on(lineFeature(l.voltage_kv, tiers)));
  const ll = yr?.line_loading ?? {};
  const over = new Set(yr?.overloaded_line_ids ?? []);
  const vv = new Set(yr?.voltage_violation_bus_ids ?? []);

  const lines: Feature[] = mLines.map((l) => {
    const id = l.line_id;
    const base = LINE_STYLE[tierOf(l.voltage_kv, tiers)];
    const pct = ll[id] ?? null;
    const isOver = over.has(id);
    const isTie = l.in_service === false;
    let color = base.c;
    if (layer === "loading" && pct != null) color = loadColor(pct);
    if (isOver) color = C.red;
    let op = layer === "voltage" ? 0.45 : 0.92;
    const dl = diff?.lines.get(id);
    if (diff) {
      color = dl ? diffColor(dl) : C.dimmed;
      op = dl ? 1 : 0.5;
    }
    const isSel = sel?.kind === "line" && sel.id === id;
    const f: Feature<LineString> = {
      type: "Feature",
      geometry: { type: "LineString", coordinates: [[l.from_lon, l.from_lat], [l.to_lon, l.to_lat]] },
      properties: {
        id,
        kind: isTie ? "tie" : isOver ? "over" : "solid",
        color,
        w: base.w + (isSel ? 1.6 : 0),
        op,
        glow: C.red,
        flow: isOver ? "#ffd0d0" : "#bff2ff",
        sel: isSel ? 1 : 0,
      },
    };
    return f;
  });

  const buses: Feature[] = (on("buses") ? m.buses : [])
    .filter((b) => b.lon != null)
    .map((b) => {
      const v = yr?.bus_vm?.[b.bus_id] ?? null;
      const vMode = layer === "voltage";
      const style = BUS_STYLE[tierOf(b.vn_kv, tiers)];
      return pt(b.lon, b.lat, {
        id: b.bus_id,
        r: vMode ? style.rVolt : style.r,
        color: vMode ? voltColor(v, b.vmin_pu, b.vmax_pu) : style.c,
        ring: vv.has(b.bus_id) && (vMode || !diff) ? 1 : 0,
        sel: sel?.kind === "bus" && sel.id === b.bus_id ? 1 : 0,
      });
    });

  const maxLoad = m.loads.length ? Math.max(...m.loads.map((l) => l.p_mw)) : 1;
  const loads: Feature[] = (on("loads") ? m.loads : []).map((l) => pt(l.lon, l.lat, { id: l.load_id, size: 0.5 + (l.p_mw / maxLoad) * 0.5 }));
  const openpts: Feature[] = mLines.filter((l) => l.in_service === false).map((l) => pt(...midpoint(l), { id: l.line_id }));
  // transformers carry their loading: a ring in the loading layer, and a red glow when over 100 % in any;
  // in compare mode only the changed ones are ringed, coloured like the changed lines
  const tl = yr?.trafo_loading ?? {};
  const trafos: Feature[] = (on("transformers") ? m.transformers : []).map((t) => {
    const pct = tl[t.trafo_id] ?? null;
    const dt = diff?.trafos.get(t.trafo_id);
    return pt(t.hv_lon, t.hv_lat, {
      id: t.trafo_id,
      sel: sel?.kind === "trafo" && sel.id === t.trafo_id ? 1 : 0,
      pct: pct ?? 0,
      ring: diff ? (dt ? 1 : 0) : pct != null && (layer === "loading" || pct > 100) ? 1 : 0,
      over: pct != null && pct > 100 ? 1 : 0,
      ringColor: dt ? diffColor(dt) : loadColor(pct),
    });
  });
  // the existing connected fleet: teal circles sized by √MW
  const existing: Feature[] = (on("generation") ? m.generators : [])
    .filter((x) => x.lon != null && x.lat != null)
    .map((x) =>
      pt(x.lon, x.lat, {
        id: x.request_id,
        r: 4 + Math.sqrt(Math.max(1, x.rating_mw || 1)) * 0.55,
        sel: sel?.kind === "gen" && sel.id === x.request_id ? 1 : 0,
      }),
    );

  return { lines: FC(lines), buses: FC(buses), loads: FC(loads), openpts: FC(openpts), trafos: FC(trafos), existing: FC(existing) };
}

/** The flow animation: a dash pattern stepped every 70 ms so the cyan dashes appear to travel. */
export const FLOW_DASH_SEQ: number[][] = [
  [0, 4, 3], [0.5, 4, 2.5], [1, 4, 2], [1.5, 4, 1.5], [2, 4, 1], [2.5, 4, 0.5], [3, 4, 0],
  [0, 0.5, 3, 3.5], [0, 1, 3, 3], [0, 1.5, 3, 2.5], [0, 2, 3, 2], [0, 2.5, 3, 1.5], [0, 3, 3, 1], [0, 3.5, 3, 0.5],
];
