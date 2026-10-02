// The MapLibre map plus everything drawn over it: timeline, stats, GSP card, legend, controls,
// tooltip, detail card, run overlay and the HTML label layer.

import type { FeatureCollection } from "geojson";
import maplibregl, { type LayerSpecification, type Map as MLMap, type MapMouseEvent } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

import type { PlannerSlice, WithMap, WithPatch } from "../hooks/planner/slice";
import type { ProjView } from "../lib/derive";
import { GEO_SOURCES, type Geo } from "../lib/geo";
import { addIcons } from "../lib/icons";
import { placeLabels } from "../lib/labels";
import type { Hit, HitKind, QueueItem } from "../types";
import { BoundaryCard, StatsBar, TimelineBox } from "./MapOverlays";
import type { BoundaryCardPlanner, StatsBarPlanner, TimelineBoxPlanner } from "./MapOverlays";
import { DetailCard } from "./DetailCard";
import type { DetailCardPlanner } from "./DetailCard";
import { Legend } from "./Legend";
import { RunOverlay } from "./RunOverlay";
import type { RunOverlayPlanner } from "./RunOverlay";
import { Tooltip } from "./Tooltip";
import type { TooltipPlanner } from "./Tooltip";

const HIT_LAYERS: [string, HitKind][] = [
  ["proj-icons", "project"],
  ["existing-gen", "existing"],
  ["trafos", "trafo"],
  ["buses-hit", "bus"],
  ["loads", "load"],
  ["lines-hit", "line"],
];

type Expr = unknown[];
const zw = (f: number): Expr => ["interpolate", ["linear"], ["zoom"], 9, ["*", ["get", "w"], 0.6 * f], 12, ["*", ["get", "w"], 1 * f], 16, ["*", ["get", "w"], 1.8 * f]];
// casing = line width + 2px at every zoom. The +2 is baked into each stop: a "zoom" expression may
// only sit at the top level of an interpolate, never nested inside arithmetic.
const zwCasing: Expr = ["interpolate", ["linear"], ["zoom"], 9, ["+", ["*", ["get", "w"], 0.6], 2], 12, ["+", ["*", ["get", "w"], 1], 2], 16, ["+", ["*", ["get", "w"], 1.8], 2]];
const zr = (key: string, f: number): Expr => ["interpolate", ["linear"], ["zoom"], 9, ["*", ["get", key], 0.7 * f], 12, ["*", ["get", key], f], 16, ["*", ["get", key], 1.8 * f]];

function addLayers(map: MLMap): void {
  const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
  GEO_SOURCES.forEach((id) => map.addSource(id, { type: "geojson", data: empty }));
  const L = (spec: Record<string, unknown>) => map.addLayer(spec as unknown as LayerSpecification);
  L({ id: "lines-halo", type: "line", source: "lines", filter: ["==", ["get", "halo"], 1], layout: { "line-cap": "round" }, paint: { "line-color": ["get", "haloColor"], "line-width": 14, "line-opacity": 0.22, "line-blur": 2 } });
  L({ id: "lines-casing", type: "line", source: "lines", filter: ["!=", ["get", "kind"], "tie"], layout: { "line-cap": "round" }, paint: { "line-color": "#ffffff", "line-width": zwCasing, "line-opacity": 0.8 } });
  L({ id: "lines-solid", type: "line", source: "lines", filter: ["==", ["get", "kind"], "solid"], layout: { "line-cap": "round" }, paint: { "line-color": ["get", "color"], "line-width": zw(1) } });
  L({ id: "lines-tie", type: "line", source: "lines", filter: ["==", ["get", "kind"], "tie"], paint: { "line-color": "#94a3b8", "line-width": zw(1), "line-dasharray": [2, 2] } });
  L({ id: "lines-bind", type: "line", source: "lines", filter: ["==", ["get", "kind"], "bind"], paint: { "line-color": "#d97706", "line-width": zw(1), "line-dasharray": [2.2, 1.4] } });
  L({ id: "lines-over", type: "line", source: "lines", filter: ["==", ["get", "kind"], "over"], layout: { "line-cap": "round" }, paint: { "line-color": "#dc2626", "line-width": zw(1) } });
  L({ id: "lines-hit", type: "line", source: "lines", paint: { "line-color": "#000", "line-width": 12, "line-opacity": 0 } });
  L({ id: "openpts", type: "symbol", source: "openpts", layout: { "icon-image": "openpt", "icon-allow-overlap": true, "icon-ignore-placement": true } });
  L({ id: "loads", type: "symbol", source: "loads", layout: { "icon-image": ["get", "icon"], "icon-size": ["get", "size"], "icon-anchor": "top", "icon-allow-overlap": true, "icon-ignore-placement": true } });
  L({ id: "bus-ring", type: "circle", source: "buses", filter: ["==", ["get", "hasRing"], 1], paint: { "circle-radius": zr("ringR", 1), "circle-color": ["get", "ringFill"], "circle-stroke-color": ["get", "ring"], "circle-stroke-width": 2 } });
  L({ id: "buses", type: "circle", source: "buses", paint: { "circle-radius": zr("r", 1), "circle-color": ["get", "fill"], "circle-stroke-color": "#ffffff", "circle-stroke-width": 1 } });
  L({ id: "buses-hit", type: "circle", source: "buses", paint: { "circle-radius": ["get", "hitR"], "circle-color": "#000", "circle-opacity": 0 } });
  L({ id: "trafos", type: "symbol", source: "trafos", layout: { "icon-image": "trafo", "icon-allow-overlap": true, "icon-ignore-placement": true } });
  // existing connected fleet (from model.generators): persistent on main and every branch
  L({ id: "existing-gen-halo", type: "circle", source: "existing", paint: { "circle-radius": zr("gr", 1.5), "circle-color": "#0d9488", "circle-opacity": 0.18 } });
  L({ id: "existing-gen", type: "circle", source: "existing", paint: { "circle-radius": zr("gr", 1), "circle-color": ["get", "fill"], "circle-stroke-color": "#ffffff", "circle-stroke-width": 2, "circle-opacity": 1 } });
  L({ id: "proj-new", type: "circle", source: "projects", filter: ["==", ["get", "newYear"], 1], paint: { "circle-radius": ["+", ["*", ["get", "size"], 18], 7], "circle-color": "rgba(245,158,11,0.12)", "circle-stroke-color": "#f59e0b", "circle-stroke-width": 2.4 } });
  L({ id: "proj-warn", type: "circle", source: "projects", filter: ["==", ["get", "warn"], 1], paint: { "circle-radius": ["+", ["*", ["get", "size"], 18], 6], "circle-color": "rgba(220,38,38,0.10)", "circle-stroke-color": "#dc2626", "circle-stroke-width": 2, "circle-stroke-opacity": 0.9 } });
  L({ id: "proj-sel", type: "circle", source: "projects", filter: ["==", ["get", "sel"], 1], paint: { "circle-radius": ["+", ["*", ["get", "size"], 18], 5], "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#111827", "circle-stroke-width": 2 } });
  L({ id: "proj-icons", type: "symbol", source: "projects", layout: { "icon-image": ["get", "icon"], "icon-size": ["get", "size"], "icon-allow-overlap": true, "icon-ignore-placement": true, "symbol-sort-key": ["get", "sort"] }, paint: { "icon-opacity": ["case", ["==", ["get", "dim"], 1], 0.5, 1] } });
}

function collapseAttribution(map: MLMap): void {
  const a = map.getContainer().querySelector(".maplibregl-ctrl-attrib");
  if (a) {
    a.classList.remove("maplibregl-compact-show");
    a.removeAttribute("open");
  }
}

/** The map's own reads, plus every overlay and card it renders. */
export type MapViewPlanner = PlannerSlice<
  "boundary" | "hover" | "legendHidden" | "loadingMode" | "model" | "pickMode" | "result" | "running" | "sel"
  | "showBoundary" | "showLabels" | "showLoads" | "size" | "voltageMode",
  "pick" | "zoomFit" | "zoomIn" | "zoomOut"
> &
  WithPatch &
  WithMap &
  TimelineBoxPlanner &
  StatsBarPlanner &
  BoundaryCardPlanner &
  DetailCardPlanner &
  TooltipPlanner &
  RunOverlayPlanner;

export interface MapViewProps {
  planner: MapViewPlanner;
  geo: Geo | null;
  projList: ProjView[];
  selQ: QueueItem | null;
  selEl: { line_id?: number; bus_id?: number } | null;
  bindLines: Set<number>;
  busProjects: Record<number, QueueItem[]>;
  over: Set<number>;
  vv: Set<number>;
}

export function MapView(props: MapViewProps) {
  const { planner, geo, projList } = props;
  const { s, patch, actions, mapApi } = planner;
  const elRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const fitZoom = useRef<number | undefined>(undefined);
  const [ready, setReady] = useState(false);
  const [tick, setTick] = useState(0); // bumps on every map move so the HTML labels re-project
  // latest props/state for the (stable) map event handlers
  const live = useRef({ pickMode: s.pickMode, hover: s.hover, model: s.model, pick: actions.pick });
  live.current = { pickMode: s.pickMode, hover: s.hover, model: s.model, pick: actions.pick };

  // ---- map lifecycle -------------------------------------------------------------------------
  useEffect(() => {
    const el = elRef.current;
    if (!el) return;
    const map = new maplibregl.Map({
      container: el,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      center: [-0.18, 52.85],
      zoom: 9,
      maxZoom: 18,
      style: "https://tiles.openfreemap.org/styles/positron",
    });
    mapRef.current = map;
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    map.touchZoomRotate.disableRotation();
    let raf = 0;
    const hitAt = (point: { x: number; y: number }): Hit | null => {
      if (!map.getSource("lines")) return null;
      const fs = map.queryRenderedFeatures([point.x, point.y], { layers: HIT_LAYERS.map((h) => h[0]) });
      for (const [layer, kind] of HIT_LAYERS) {
        const f = fs.find((x) => x.layer.id === layer);
        if (f) return { kind, id: f.properties.id as number | string };
      }
      return null;
    };
    map.on("load", () => {
      collapseAttribution(map);
      setTimeout(() => collapseAttribution(map), 50);
      (map.getStyle().layers ?? []).forEach((l) => {
        if (l.type === "symbol") {
          map.setPaintProperty(l.id, "text-opacity", 0.55);
          map.setPaintProperty(l.id, "icon-opacity", 0.4);
        }
      });
      map.resize();
      addIcons(map);
      addLayers(map);
      setReady(true);
    });
    map.on("move", () => {
      if (!raf) raf = requestAnimationFrame(() => {
        raf = 0;
        setTick((t) => t + 1);
      });
    });
    map.on("mousemove", (e: MapMouseEvent) => {
      const h = hitAt(e.point);
      const { pickMode, hover } = live.current;
      map.getCanvas().style.cursor = pickMode ? (h?.kind === "bus" ? "pointer" : "crosshair") : h && h.kind !== "load" ? "pointer" : "";
      if (!h && !hover) return;
      patch({ hover: h, mouse: { x: e.point.x, y: e.point.y } });
    });
    map.on("mouseout", () => {
      if (live.current.hover) patch({ hover: null });
    });
    map.on("click", (e: MapMouseEvent) => live.current.pick(hitAt(e.point)));
    const ro = new ResizeObserver((es) => {
      const r = es[0].contentRect;
      patch({ size: { w: Math.round(r.width), h: Math.round(r.height) } });
      map.resize();
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(raf);
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, [patch]);

  // ---- the imperative handle the controller uses (fit / zoom / focus) -------------------------
  useEffect(() => {
    mapApi.current = {
      fit(anim) {
        const map = mapRef.current;
        const m = live.current.model;
        if (!map || !m || !m.buses.length) return;
        const b = new maplibregl.LngLatBounds();
        m.buses.forEach((x) => b.extend([x.lon, x.lat]));
        const opts = { padding: { top: 96, bottom: 40, left: 60, right: 60 } };
        const cam = map.cameraForBounds(b, opts);
        if (cam?.zoom != null) fitZoom.current = cam.zoom;
        map.fitBounds(b, { ...opts, duration: anim ? 600 : 0 });
      },
      zoomBy(d) {
        const map = mapRef.current;
        if (map) map.easeTo({ zoom: map.getZoom() + d, duration: 250 });
      },
      focusOn(ll, kMin) {
        const map = mapRef.current;
        if (!ll || !map) return;
        const z = Math.max(map.getZoom(), (fitZoom.current ?? 11) + Math.log2(kMin ?? 1));
        map.easeTo({ center: ll, zoom: z, duration: 650 });
      },
      zoomedIn() {
        const map = mapRef.current;
        return !!map && map.getZoom() > (fitZoom.current ?? 11) + 0.3;
      },
    };
    return () => {
      mapApi.current = null;
    };
  }, [mapApi]);

  // frame the network once the map and the model are both there
  const framed = useRef(false);
  useEffect(() => {
    if (ready && s.model && !framed.current) {
      framed.current = true;
      mapApi.current?.fit(false);
    }
  }, [ready, s.model, mapApi]);

  // ---- push data into the sources -------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !geo) return;
    GEO_SOURCES.forEach((k) => (map.getSource(k) as maplibregl.GeoJSONSource | undefined)?.setData(geo[k]));
    map.setLayoutProperty("loads", "visibility", s.showLoads ? "visible" : "none");
  }, [ready, geo, s.showLoads]);

  // ---- HTML labels (screen space via map.project, with collision avoidance) --------------------
  const labels = useMemo(() => {
    const map = mapRef.current;
    if (!ready || !map || !s.model) return [];
    void tick;
    const showBus = s.showLabels || map.getZoom() >= (fitZoom.current ?? 11) + 2;
    return placeLabels({
      project: (lo, la) => {
        const p = map.project([lo, la]);
        return [p.x, p.y];
      },
      width: s.size.w,
      height: s.size.h,
      projList,
      transformers: s.model.transformers,
      buses: s.model.buses,
      showBusLabels: showBus,
    });
  }, [ready, tick, s.model, s.showLabels, s.size, projList]);

  return (
    <div className="map-wrap">
      <div ref={elRef} className="map" />
      <div className="map-labels">
        {labels.map((t) => (
          <div key={t.key} className="map-label" style={{ left: t.sx, top: t.sy, fontFamily: t.font, fontSize: t.fs, fontWeight: t.fw, color: t.color }}>
            <div>{t.text}</div>
            {t.sub && <div className="sub">{t.sub}</div>}
          </div>
        ))}
      </div>

      <div className="overlay-col">
        <TimelineBox planner={planner} />
        <StatsBar planner={planner} />
        {s.showBoundary && s.boundary && <BoundaryCard planner={planner} />}
      </div>

      {s.pickMode && (
        <div className="pick-banner">
          Click a bus to set the point of connection
          <button onClick={() => patch({ pickMode: false })}>Cancel</button>
        </div>
      )}

      {s.sel && s.result && <DetailCard planner={planner} selQ={props.selQ} over={props.over} vv={props.vv} busProjects={props.busProjects} />}

      {s.legendHidden ? (
        <button className="legend-btn" onClick={() => patch({ legendHidden: false })}>Legend</button>
      ) : (
        <Legend onClose={() => patch({ legendHidden: true })} />
      )}

      <div className="map-ctrls">
        <div className="modes">
          <button className={`toggle${s.loadingMode ? " on" : ""}`} onClick={() => patch({ loadingMode: !s.loadingMode, voltageMode: false })}>Loading heat</button>
          <button className={`toggle${s.voltageMode ? " on" : ""}`} onClick={() => patch({ voltageMode: !s.voltageMode, loadingMode: false })}>Voltage heat</button>
          <button className={`toggle${s.showLoads ? " on" : ""}`} onClick={() => patch({ showLoads: !s.showLoads })}>Loads</button>
          <button className={`toggle${s.showLabels ? " on" : ""}`} onClick={() => patch({ showLabels: !s.showLabels })}>Bus labels</button>
        </div>
        <div className="zoom">
          <button onClick={actions.zoomIn}>+</button>
          <button onClick={actions.zoomOut}>−</button>
          <button onClick={actions.zoomFit}>FIT</button>
        </div>
      </div>

      {s.hover && !s.running && <Tooltip planner={planner} bindLines={props.bindLines} busProjects={props.busProjects} />}
      {s.running && <RunOverlay planner={planner} />}
    </div>
  );
}
