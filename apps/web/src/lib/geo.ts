// Map data -> GeoJSON for MapLibre. Pure: given the model, the year's result and the view state,
// build the feature collections the map layers read. Rebuilt only when its inputs change.

import type { Feature, FeatureCollection, LineString, Point } from "geojson";

import { C, loadColor, voltColor } from "../theme";
import type { ElementBinding, MapLayer, Model, Sel, YearResult } from "../types";
import { NEED, bindingKey, needOf } from "./capacity";
import { regionFeatures } from "./demand";
import { type DiffMap, diffColor } from "./diff";
import { type FeatureKey, type LineTier, type LineTiers, lineFeature, shows, tierOf } from "./mapFeatures";
import { midpoint } from "./placement";

export interface GeoInputs {
  model: Model;
  yr: YearResult | null;
  layer: MapLayer;
  sel: Sel | null;
  /** Lines named as the binding constraint by a deferred project. */
  bindLines: Set<number>;
  /** Lines out of service (or derated) by a studied planned outage in the viewed year. */
  outLines: Set<number>;
  /** Diff mode: the viewed year's loading change vs main per line and transformer (changed ones
   * only), or null when diff is off. */
  diffDeltas: DiffMap | null;
  /** The kinds of element the map shows (lib/mapFeatures.ts); the rest are left out entirely. */
  visible: readonly FeatureKey[];
  /** The grid's own line voltages in tiers: what is drawn heavy, medium and thin. */
  tiers: LineTiers;
  /** The binding set by element (lib/capacity.bindingIndex) and the viewed year: the Headroom layer's colours. */
  bindIx: Map<string, ElementBinding>;
  year: number;
}

export interface Geo {
  lines: FeatureCollection;
  buses: FeatureCollection;
  loads: FeatureCollection;
  openpts: FeatureCollection;
  trafos: FeatureCollection;
  existing: FeatureCollection;
  /** Demand groups: a halo per region site (when "Demand groups" is shown). */
  regions: FeatureCollection;
}

export const GEO_SOURCES = ["lines", "buses", "loads", "openpts", "trafos", "existing", "regions"] as const;

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
  const { model: m, yr, layer, sel, diffDeltas, tiers } = g;
  const on = (k: FeatureKey) => shows(g.visible, k);
  const mLines = m.lines.filter((l) => on(lineFeature(l.voltage_kv, tiers)));
  const ll = yr?.line_loading ?? {};
  const over = new Set(yr?.overloaded_line_ids ?? []);
  const vv = new Set(yr?.voltage_violation_bus_ids ?? []);
  // the Headroom layer: every element by when it needs reinforcement, the ones that hold dimmed so the rest stand out
  const headroom = layer === "headroom" && !diffDeltas;
  const need = (kind: string, id: number) => needOf(g.bindIx.get(bindingKey(kind, id)), g.year);

  const lines: Feature[] = mLines.map((l) => {
    const id = l.line_id;
    const base = LINE_STYLE[tierOf(l.voltage_kv, tiers)];
    const pct = ll[id] ?? null;
    const isOver = over.has(id);
    const isTie = l.in_service === false;
    const isOut = g.outLines.has(id);
    let color = base.c;
    if (layer === "loading" && pct != null) color = loadColor(pct);
    const n = headroom && !isTie ? need("line", id) : null;
    if (n) color = NEED[n].c;
    if (isOver) color = C.red;
    const dl = diffDeltas?.lines.get(id);
    let op = layer === "voltage" || layer === "demand" ? 0.45 : n === "holds" ? 0.5 : 0.92;
    if (diffDeltas) {
      color = dl ? diffColor(dl) : C.dimmed;
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
    .filter(() => on("buses"))
    .filter((b) => b.lon != null)
    .map((b) => {
      const v = yr?.bus_vm?.[b.bus_id] ?? null;
      const [lo, hi] = [b.vmin_pu, b.vmax_pu]; // the engine's band for this bus
      const vMode = layer === "voltage";
      const style = BUS_STYLE[tierOf(b.vn_kv, tiers)];
      const n = headroom ? need("bus", b.bus_id) : null;
      const bound = n != null && n !== "holds"; // a busbar that holds keeps its own colour: the circuits carry the picture
      return pt(b.lon, b.lat, {
        id: b.bus_id,
        r: vMode || bound ? style.rVolt : style.r,
        color: vMode ? voltColor(v, lo, hi) : bound ? NEED[n].c : style.c,
        ring: (vMode && vv.has(b.bus_id)) || n === "now" ? 1 : 0,
      });
    });

  const maxLoad = m.loads.length ? Math.max(...m.loads.map((l) => l.p_mw)) : 1;
  const loads: Feature[] = (on("loads") ? m.loads : []).map((l) => pt(l.lon, l.lat, { id: l.load_id, size: 0.5 + (l.p_mw / maxLoad) * 0.5 }));
  const openpts: Feature[] = mLines
    .filter((l) => l.in_service === false)
    .map((l) => pt(...midpoint(l), { id: l.line_id }));
  // transformers carry their loading: a ring in the loading layer, and a red glow when over 100 % in any;
  // in diff mode only the changed ones are ringed, coloured like the changed lines
  const tl = yr?.trafo_loading ?? {};
  const trafos: Feature[] = (on("transformers") ? m.transformers : []).map((t) => {
    const pct = tl[t.trafo_id] ?? null;
    const dt = diffDeltas?.trafos.get(t.trafo_id);
    const n = headroom ? need("trafo", t.trafo_id) : null;
    return pt(t.hv_lon, t.hv_lat, {
      id: t.trafo_id,
      sel: sel?.kind === "trafo" && sel.id === t.trafo_id ? 1 : 0,
      pct: pct ?? 0,
      ring: diffDeltas ? (dt ? 1 : 0) : n || (pct != null && (layer === "loading" || pct > 100)) ? 1 : 0,
      over: pct != null && pct > 100 ? 1 : 0,
      ringColor: dt ? diffColor(dt) : n ? NEED[n].c : loadColor(pct),
    });
  });
  // the existing connected fleet: teal circles sized by √MW, on main and every branch
  const existing: Feature[] = (on("generation") ? (m.generators ?? []) : [])
    .filter((x) => x.lon != null && x.lat != null)
    .map((x) =>
      pt(x.lon, x.lat, {
        id: x.request_id,
        r: 4 + Math.sqrt(Math.max(1, x.rating_mw || 1)) * 0.55,
        sel: sel?.kind === "gen" && sel.id === x.request_id ? 1 : 0,
      }),
    );

  const regions: Feature[] = on("demand") ? regionFeatures(m, yr, sel) : [];

  return { lines: FC(lines), buses: FC(buses), loads: FC(loads), openpts: FC(openpts), trafos: FC(trafos), existing: FC(existing), regions: FC(regions) };
}

/** The flow animation: a dash pattern stepped every 70 ms so the cyan dashes appear to travel. */
export const FLOW_DASH_SEQ: number[][] = [
  [0, 4, 3], [0.5, 4, 2.5], [1, 4, 2], [1.5, 4, 1.5], [2, 4, 1], [2.5, 4, 0.5], [3, 4, 0],
  [0, 0.5, 3, 3.5], [0, 1, 3, 3], [0, 1.5, 3, 2.5], [0, 2, 3, 2], [0, 2.5, 3, 1.5], [0, 3, 3, 1], [0, 3.5, 3, 0.5],
];
