// Map data -> GeoJSON for MapLibre. Pure: given the model, the year's result and the view state,
// build the feature collections the map layers read. Rebuilt only when its inputs change.

import type { Feature, FeatureCollection, LineString, Point } from "geojson";

import { C, loadColor, voltColor } from "../theme";
import type { MapLayer, Model, Sel, YearResult } from "../types";
import { voltageBand } from "./derive";

export interface GeoInputs {
  model: Model;
  yr: YearResult | null;
  layer: MapLayer;
  sel: Sel | null;
  /** Lines named as the binding constraint by a deferred project. */
  bindLines: Set<number>;
  /** Lines out of service (or derated) by a studied planned outage in the viewed year. */
  outLines: Set<number>;
  /** Diff mode: per-line loading change vs main (only changed lines), or null when diff is off. */
  diffDeltas: Map<number, { delta: number; head: number }> | null;
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

/** Line width and colour by voltage: 132 kV heavy and light, 33 kV medium, lower thin. */
export const lineStyle = (kv: number): { w: number; c: string } =>
  kv >= 132 ? { w: 2.8, c: C.line132 } : kv >= 33 ? { w: 1.8, c: C.line33 } : { w: 1.2, c: C.lineLow };

export function buildGeo(g: GeoInputs): Geo {
  const { model: m, yr, layer, sel, diffDeltas } = g;
  const ll = yr?.line_loading ?? {};
  const over = new Set(yr?.overloaded_line_ids ?? []);
  const vv = new Set(yr?.voltage_violation_bus_ids ?? []);

  const lines: Feature[] = m.lines.map((l) => {
    const id = l.line_id;
    const base = lineStyle(l.voltage_kv);
    const pct = ll[id] ?? null;
    const isOver = over.has(id);
    const isTie = l.in_service === false;
    const isOut = g.outLines.has(id);
    let color = base.c;
    if (layer === "loading" && pct != null) color = loadColor(pct);
    if (isOver) color = C.red;
    const dl = diffDeltas?.get(id);
    let op = layer === "voltage" ? 0.45 : 0.92;
    if (diffDeltas) {
      color = dl ? (dl.head > 100 ? C.red : C.amber) : C.dimmed;
      op = dl ? 1 : 0.5;
    }
    const kind = isTie ? "tie" : isOut ? "maint" : isOver ? "over" : g.bindLines.has(id) && !diffDeltas ? "bind" : "solid";
    const isSel = sel?.kind === "line" && sel.id === id;
    const f: Feature<LineString> = {
      type: "Feature",
      geometry: { type: "LineString", coordinates: [[l.from_lon, l.from_lat], [l.to_lon, l.to_lat]] },
      properties: {
        id,
        kind,
        color,
        w: base.w + (isSel ? 1.6 : 0),
        op,
        glow: isOver ? C.red : C.amber,
        flow: isOver ? "#ffd0d0" : "#bff2ff",
        sel: isSel ? 1 : 0,
      },
    };
    return f;
  });

  const buses: Feature[] = m.buses
    .filter((b) => b.lon != null)
    .map((b) => {
      const v = yr?.bus_vm?.[b.bus_id] ?? null;
      const [lo, hi] = voltageBand(b.vn_kv);
      const vMode = layer === "voltage";
      return pt(b.lon, b.lat, {
        id: b.bus_id,
        r: vMode ? (b.vn_kv >= 33 ? 5 : 3.5) : b.vn_kv >= 132 ? 3.6 : b.vn_kv >= 33 ? 2.8 : 2,
        color: vMode ? voltColor(v, lo, hi) : b.vn_kv >= 132 ? C.line132 : "#9fb3c9",
        ring: vMode && vv.has(b.bus_id) ? 1 : 0,
      });
    });

  const maxLoad = m.loads.length ? Math.max(...m.loads.map((l) => l.p_mw)) : 1;
  const loads: Feature[] = m.loads.map((l) => pt(l.lon, l.lat, { id: l.load_id, size: 0.5 + (l.p_mw / maxLoad) * 0.5 }));
  const openpts: Feature[] = m.lines
    .filter((l) => l.in_service === false)
    .map((l) => pt((l.from_lon + l.to_lon) / 2, (l.from_lat + l.to_lat) / 2, { id: l.line_id }));
  // transformers carry their loading: a ring in the loading layer, and a red glow when over 100 % in any
  const tl = yr?.trafo_loading ?? {};
  const trafos: Feature[] = m.transformers.map((t) => {
    const pct = tl[t.trafo_id] ?? null;
    return pt(t.hv_lon, t.hv_lat, {
      id: t.trafo_id,
      sel: sel?.kind === "trafo" && sel.id === t.trafo_id ? 1 : 0,
      pct: pct ?? 0,
      ring: pct != null && (layer === "loading" || pct > 100) && !diffDeltas ? 1 : 0,
      over: pct != null && pct > 100 ? 1 : 0,
      ringColor: loadColor(pct),
    });
  });
  // the existing connected fleet: teal circles sized by √MW, on main and every branch
  const existing: Feature[] = (m.generators ?? [])
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
