// Where the map's HTML overlay goes: project markers fanned out at a shared bus, label boxes that must not
// overlap, which lines and transformers get a loading tag, and the point a planned outage is drawn at.
// Pure: screen positions in, positions and boxes out (MapMarkers and RegionLabels only draw them).

import type { Line, Outage, Transformer } from "../types";
import type { ModelIndex } from "./derive";

/** Lon/lat to screen pixels (null: off the projection). */
export type Project = (lon: number, lat: number) => [number, number] | null;
/** A label's screen box: [left, top, right, bottom]. */
export type Box = [number, number, number, number];
export const overlaps = (b: Box, o: Box): boolean => b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1];

/** A line's midpoint (lon, lat): where its tag, its open point and the camera go. */
export const midpoint = (l: Pick<Line, "from_lon" | "from_lat" | "to_lon" | "to_lat">): [number, number] => [(l.from_lon + l.to_lon) / 2, (l.from_lat + l.to_lat) / 2];

// label widths are estimated from the character count (no text measuring on every map move)
export const ID_CHAR_PX = 6.6; // a project id, and a demand region's name
export const SUB_CHAR_PX = 6.8; // a substation name (bold)
const SUB_MIN_W = 60;
export const MARKER_DX = 14; // markers and substation names sit right of their point
const FAN_STEP_PX = 30; // projects at one bus fan out vertically, alternately below and above

/** Loading tags: a line or transformer below this is not tagged in the loading layer (a selected line always is). */
export const TAG_MIN_PCT = 60;
/** Over its rating: a transformer above this is tagged in every layer. */
export const OVERLOAD_PCT = 100;
export const TRAFO_TAG_DY = -24; // a transformer's tag sits above its icon
export const GEN_OUTAGE_DY = -18; // a generator's works tag sits above its marker

/** The vertical offset of the n-th project at one bus (0, -30, +30, -60, …). */
export const fanOffset = (n: number): number => (n % 2 ? 1 : -1) * Math.ceil(n / 2) * FAN_STEP_PX;

/** A project marker's box: its tile and its id to the right. */
export const markerBox = (x: number, y: number, id: string): Box => [x - 13, y - 14, x + 13 + id.length * ID_CHAR_PX + 6, y + 14];

/** A substation name's box, right of its point. */
export const subLabelBox = (x: number, y: number, name: string): Box => [x, y - 12, x + Math.max(name.length * SUB_CHAR_PX, SUB_MIN_W), y + 12];

export interface SubSite {
  lon: number;
  lat: number;
  ratios: Set<string>;
  hv: number;
}

/** One site per substation with a transformer (named by `subName`), with every ratio it has. */
export function substationSites(transformers: Transformer[], subName: (t: Transformer) => string, ratio: (t: Transformer) => string): Map<string, SubSite> {
  const seen = new Map<string, SubSite>();
  transformers.forEach((t) => {
    const name = subName(t);
    const e = seen.get(name) ?? { lon: t.hv_lon, lat: t.hv_lat, ratios: new Set<string>(), hv: t.hv_bus };
    e.ratios.add(ratio(t));
    seen.set(name, e);
  });
  return seen;
}

/** Whether a line's loading is tagged in the loading layer. */
export const lineTagShown = (pct: number, selected: boolean): boolean => pct >= TAG_MIN_PCT || selected;

export interface SiteTag {
  pct: number;
  lon: number;
  lat: number;
  id: number;
}

/** The most loaded transformer at each site worth a tag: in the loading layer from TAG_MIN_PCT, otherwise only overloads. */
export function worstTrafoPerSite(loading: Record<string, number>, ix: ModelIndex, loadingLayer: boolean): SiteTag[] {
  const atSite = new Map<string, SiteTag>();
  Object.entries(loading).forEach(([id, pct]) => {
    const t = ix.trafo.get(+id);
    if (!t || (!loadingLayer && pct <= OVERLOAD_PCT) || (loadingLayer && pct < TAG_MIN_PCT)) return;
    const k = `${t.hv_lon},${t.hv_lat}`;
    if ((atSite.get(k)?.pct ?? -1) < pct) atSite.set(k, { pct, lon: t.hv_lon, lat: t.hv_lat, id: +id });
  });
  return [...atSite.values()];
}

/** Where a planned outage is drawn (lon, lat): a line's midpoint, a transformer's HV side, a generator's site. */
export function outagePoint(o: Outage, ix: ModelIndex): [number, number] | null {
  if (o.element_kind === "line") {
    const l = ix.line.get(Number(o.element_id));
    return l ? midpoint(l) : null;
  }
  if (o.element_kind === "trafo") {
    const t = ix.trafo.get(Number(o.element_id));
    return t ? [t.hv_lon, t.hv_lat] : null;
  }
  const g = ix.gen.get(o.element_id);
  return g ? [g.lon, g.lat] : null;
}
