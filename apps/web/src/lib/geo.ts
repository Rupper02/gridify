// Map data → GeoJSON for MapLibre. Pure: given the model, the run and the UI state, build the seven
// feature collections the map layers read. Rebuilt only when its inputs change (useMemo in App).

import type { Feature, FeatureCollection, LineString, Point } from "geojson";

import { ORDER, mix } from "../theme";
import type { Hit, Model, Sel } from "../types";
import type { ProjView } from "./derive";

export interface GeoInputs {
  model: Model;
  projList: ProjView[];
  sel: Sel | null;
  hov: Hit | null;
  selEl: { line_id?: number; bus_id?: number } | null;
  bindLines: Set<number>;
  bindBuses: Set<number>;
  over: Set<number>;
  lineLoading: Record<string, number>;
  busVm: Record<string, number>;
  voltageViolations: Set<number>;
  pickMode: boolean;
  loadingMode: boolean;
  voltageMode: boolean;
  drawerBus: string; // the bus picked in the add-project form while the drawer is open ('' otherwise)
  weightByRating: boolean;
}

export interface Geo {
  lines: FeatureCollection;
  buses: FeatureCollection;
  loads: FeatureCollection;
  openpts: FeatureCollection;
  trafos: FeatureCollection;
  existing: FeatureCollection;
  projects: FeatureCollection;
}

export const GEO_SOURCES = ["lines", "buses", "loads", "openpts", "trafos", "existing", "projects"] as const;

const FC = (features: Feature[]): FeatureCollection => ({ type: "FeatureCollection", features });
const pt = (lo: number, la: number, props: Record<string, unknown>): Feature<Point> => ({
  type: "Feature",
  geometry: { type: "Point", coordinates: [lo, la] },
  properties: props,
});

/** Voltage heat colour for a per-unit voltage. */
export const vHeat = (v: number | null | undefined): string =>
  v == null ? "#475569" : v > 1.05 ? "#dc2626" : v > 1.02 ? "#f97316" : v < 0.95 ? "#2563eb" : v < 0.98 ? "#60a5fa" : "#9ca3af";

export function buildGeo(g: GeoInputs): Geo {
  const { model: m, sel, hov, selEl, over, bindLines, bindBuses, lineLoading: ll, busVm, voltageViolations: vv } = g;

  const lines: Feature[] = m.lines.map((l) => {
    const id = l.line_id;
    const isOver = over.has(id);
    const isBind = bindLines.has(id);
    const isTie = l.in_service === false;
    const isSel = (sel?.kind === "line" && sel.id === id) || selEl?.line_id === id;
    const isHov = hov?.kind === "line" && hov.id === id;
    let color = "#64748b";
    let w = g.weightByRating ? (l.rating_a >= 645 ? 3.6 : l.rating_a >= 421 ? 2.7 : 2) : 2.4;
    if (g.loadingMode && ll[id] != null) {
      const t = Math.min(1, ll[id] / 100);
      color = mix("#cbd5e1", "#0f172a", Math.pow(t, 1.3));
      w = 1.6 + t * 3.6;
    }
    if (isTie) w = 1.6;
    if (isBind) w = 3.6;
    if (isOver) w = 4.6;
    if (isSel || isHov) {
      w += 1.4;
      if (!isOver && !isBind) color = "#111827";
    }
    const f: Feature<LineString> = {
      type: "Feature",
      geometry: { type: "LineString", coordinates: [[l.from_lon, l.from_lat], [l.to_lon, l.to_lat]] },
      properties: {
        id,
        color,
        w,
        kind: isOver ? "over" : isBind ? "bind" : isTie ? "tie" : "solid",
        halo: isSel || isOver ? 1 : 0,
        haloColor: isOver ? "#dc2626" : isBind ? "#d97706" : "#111827",
      },
    };
    return f;
  });

  const buses: Feature[] = m.buses
    .filter((b) => b.lon != null)
    .map((b) => {
      const id = b.bus_id;
      const isV = vv.has(id);
      const isB = bindBuses.has(id);
      const isSel = (sel?.kind === "bus" && sel.id === id) || selEl?.bus_id === id || (g.drawerBus !== "" && String(id) === g.drawerBus);
      const isHov = hov?.kind === "bus" && hov.id === id;
      const pk = g.pickMode;
      const vMode = g.voltageMode && !pk && !isSel && busVm[id] != null;
      const ring = isV ? "#dc2626" : isB ? "#d97706" : isSel ? "#111827" : null;
      const fill = pk ? (isHov ? "#1d4ed8" : "#3b82f6") : isSel ? "#111827" : vMode ? vHeat(busVm[id]) : "#475569";
      const rad = pk ? (isHov ? 5.5 : 3.6) : isHov || isSel ? 3.8 : vMode ? 3.4 : 2.6;
      return pt(b.lon, b.lat, {
        id,
        r: rad,
        fill,
        hasRing: ring ? 1 : 0,
        ring: ring ?? "#000",
        ringR: isV || isB ? 8 : 6.5,
        ringFill: isV ? "rgba(220,38,38,0.12)" : isB ? "rgba(217,119,6,0.14)" : "rgba(0,0,0,0)",
        hitR: pk ? 10 : 7,
      });
    });

  const maxLoad = m.loads.length ? Math.max(...m.loads.map((l) => l.p_mw)) : 1;
  const loads: Feature[] = m.loads.map((l) =>
    pt(l.lon, l.lat, {
      id: l.load_id,
      icon: hov?.kind === "load" && hov.id === l.load_id ? "load-h" : "load",
      size: 0.5 + (l.p_mw / maxLoad) * 0.5,
    }),
  );
  const openpts: Feature[] = m.lines
    .filter((l) => l.in_service === false)
    .map((l) => pt((l.from_lon + l.to_lon) / 2, (l.from_lat + l.to_lat) / 2, { id: l.line_id }));
  const trafos: Feature[] = m.transformers.map((t) => pt(t.hv_lon, t.hv_lat, { id: t.trafo_id }));

  const projects: Feature[] = g.projList.map((p) =>
    pt(p.x.lon!, p.x.lat!, {
      id: p.x.request_id,
      icon: `${p.x.technology ?? "solar"}-${p.variant}`,
      size: p.size,
      sort: ORDER[p.x.status] === 3 ? -1 : p.size * 10,
      newYear: p.isNew ? 1 : 0,
      dim: p.blocked ? 1 : 0,
      warn: p.offRec ? 1 : 0,
      sel: sel?.kind === "project" && sel.id === p.x.request_id ? 1 : 0,
    }),
  );
  // existing connected fleet: one bold teal colour, sized by MW; shown on main and every branch so
  // the as-is grid is unmistakable next to the phase-coloured queue
  const existing: Feature[] = (m.generators ?? [])
    .filter((x) => x.lon != null && x.lat != null)
    .map((x) =>
      pt(x.lon, x.lat, {
        id: x.request_id,
        gr: 5 + Math.sqrt(Math.max(1, x.rating_mw || 1)) * 1.0,
        fill: "#0d9488",
        rating: x.rating_mw,
        tech: x.technology,
        applicant: x.applicant,
        bus: x.bus_id,
      }),
    );

  return { lines: FC(lines), buses: FC(buses), loads: FC(loads), openpts: FC(openpts), trafos: FC(trafos), existing: FC(existing), projects: FC(projects) };
}
