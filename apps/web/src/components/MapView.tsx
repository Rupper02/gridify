// The MapLibre map (CARTO dark, no labels) and its layers: voltage-weighted lines with binding /
// overloaded / open-point / outage styles, the animated flow layer, buses, loads, transformers and
// the existing fleet. Projects, substation names and tags are HTML on top (MapMarkers).

import type { FeatureCollection } from "geojson";
import maplibregl, { type LayerSpecification, type Map as MLMap, type MapMouseEvent } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import type { PlannerSlice, WithMap } from "../hooks/planner/slice";
import { FLOW_DASH_SEQ, GEO_SOURCES, type Geo } from "../lib/geo";
import { addIcons } from "../lib/icons";
import { shows } from "../lib/mapFeatures";
import type { Layout } from "../lib/layout";
import { C } from "../theme";
import type { Sel } from "../types";
import { MapMarkers } from "./MapMarkers";
import type { MapMarkersPlanner } from "./MapMarkers";
import { RegionLabels, type RegionLabelsPlanner } from "./RegionLabels";

const STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-nolabels-gl-style/style.json";
const CLICK_LAYERS: [string, Sel["kind"]][] = [
  ["existing", "gen"],
  ["trafos", "trafo"],
  ["line-hit", "line"],
  ["region-halo", "region"],
];

type Expr = unknown[];
const zw = (add = 0): Expr => ["interpolate", ["linear"], ["zoom"], 8, ["+", ["*", ["get", "w"], 0.8], add], 11, ["+", ["get", "w"], add], 15, ["+", ["*", ["get", "w"], 1.8], add]];

function addLayers(map: MLMap): void {
  const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
  GEO_SOURCES.forEach((id) => map.addSource(id, { type: "geojson", data: empty }));
  const L = (spec: Record<string, unknown>) => map.addLayer(spec as unknown as LayerSpecification);
  // demand regions sit under everything: soft halos sized by demand, coloured by their worst alert
  const zr = (add = 0): Expr => ["interpolate", ["linear"], ["zoom"], 8, ["+", ["*", ["get", "r"], 0.75], add], 11, ["+", ["get", "r"], add], 15, ["+", ["*", ["get", "r"], 2], add]];
  L({ id: "region-halo", type: "circle", source: "regions", paint: { "circle-radius": zr(), "circle-color": ["get", "color"], "circle-opacity": 0.2, "circle-blur": 0.2, "circle-stroke-color": ["get", "color"], "circle-stroke-width": 1.4, "circle-stroke-opacity": 0.7 } });
  L({ id: "region-sel", type: "circle", source: "regions", filter: ["==", ["get", "sel"], 1], paint: { "circle-radius": zr(5), "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": C.accent, "circle-stroke-width": 2 } });
  L({ id: "line-glow", type: "line", source: "lines", filter: ["in", ["get", "kind"], ["literal", ["bind", "over"]]], layout: { "line-cap": "round" }, paint: { "line-color": ["get", "glow"], "line-width": zw(9), "line-opacity": 0.22, "line-blur": 3 } });
  L({ id: "line-sel", type: "line", source: "lines", filter: ["==", ["get", "sel"], 1], layout: { "line-cap": "round" }, paint: { "line-color": C.accent, "line-width": zw(8), "line-opacity": 0.28, "line-blur": 2 } });
  L({ id: "line-solid", type: "line", source: "lines", filter: ["in", ["get", "kind"], ["literal", ["solid", "over"]]], layout: { "line-cap": "round" }, paint: { "line-color": ["get", "color"], "line-width": zw(), "line-opacity": ["get", "op"] } });
  L({ id: "line-bind", type: "line", source: "lines", filter: ["==", ["get", "kind"], "bind"], paint: { "line-color": C.amber, "line-width": zw(), "line-dasharray": [3, 2] } });
  L({ id: "line-tie", type: "line", source: "lines", filter: ["==", ["get", "kind"], "tie"], paint: { "line-color": C.line33, "line-width": 1.2, "line-dasharray": [2, 2] } });
  L({ id: "line-flow", type: "line", source: "lines", filter: ["!", ["in", ["get", "kind"], ["literal", ["tie", "maint"]]]], paint: { "line-color": ["get", "flow"], "line-width": zw(1), "line-blur": 0.6, "line-dasharray": [0, 4, 3] } });
  L({ id: "line-maint", type: "line", source: "lines", filter: ["==", ["get", "kind"], "maint"], layout: { "line-cap": "round" }, paint: { "line-color": C.mute, "line-width": zw(), "line-opacity": 0.75, "line-dasharray": [0.6, 1.4] } });
  L({ id: "line-hit", type: "line", source: "lines", filter: ["!=", ["get", "kind"], "tie"], paint: { "line-color": "#000", "line-opacity": 0, "line-width": 14 } });
  L({ id: "bus-ring", type: "circle", source: "buses", filter: ["==", ["get", "ring"], 1], paint: { "circle-radius": 12, "circle-color": "rgba(255,107,107,0.15)", "circle-stroke-color": C.red, "circle-stroke-width": 1.8 } });
  L({ id: "bus", type: "circle", source: "buses", paint: { "circle-radius": ["get", "r"], "circle-color": ["get", "color"], "circle-stroke-color": C.night, "circle-stroke-width": 1 } });
  L({ id: "loads", type: "symbol", source: "loads", layout: { "icon-image": "load", "icon-size": ["get", "size"], "icon-allow-overlap": true, "icon-ignore-placement": true, "icon-offset": [10, 10] } });
  L({ id: "openpts", type: "symbol", source: "openpts", layout: { "icon-image": "openpt", "icon-allow-overlap": true } });
  L({ id: "existing-sel", type: "circle", source: "existing", filter: ["==", ["get", "sel"], 1], paint: { "circle-radius": ["+", ["get", "r"], 6], "circle-color": "rgba(124,227,255,0.12)", "circle-stroke-color": C.accent, "circle-stroke-width": 2 } });
  L({ id: "existing", type: "circle", source: "existing", paint: { "circle-radius": ["get", "r"], "circle-color": C.existing, "circle-stroke-color": C.ink, "circle-stroke-width": 1.5, "circle-opacity": 0.95 } });
  L({ id: "trafo-glow", type: "circle", source: "trafos", filter: ["==", ["get", "over"], 1], paint: { "circle-radius": 22, "circle-color": C.red, "circle-opacity": 0.18, "circle-blur": 0.6 } });
  L({ id: "trafo-ring", type: "circle", source: "trafos", filter: ["==", ["get", "ring"], 1], layout: { "circle-sort-key": ["get", "pct"] }, paint: { "circle-radius": 15, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": ["get", "ringColor"], "circle-stroke-width": 2.4 } });
  L({ id: "trafo-sel", type: "circle", source: "trafos", filter: ["==", ["get", "sel"], 1], paint: { "circle-radius": 17, "circle-color": "rgba(124,227,255,0.12)", "circle-stroke-color": C.accent, "circle-stroke-width": 2 } });
  L({ id: "trafos", type: "symbol", source: "trafos", layout: { "icon-image": "trafo", "icon-allow-overlap": true, "icon-ignore-placement": true } });
}

export type MapViewPlanner = PlannerSlice<"layer" | "model" | "diffMode" | "sideOpen", "select"> & WithMap & MapMarkersPlanner & RegionLabelsPlanner;

export function MapView({ planner, geo, layout, reducedMotion }: { planner: MapViewPlanner; geo: Geo | null; layout: Layout; reducedMotion: boolean }) {
  const { s, actions, mapApi } = planner;
  const elRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const fitZoom = useRef<number | undefined>(undefined);
  const [ready, setReady] = useState(false);
  const [tick, setTick] = useState(0); // bumps on every map move so the HTML markers re-project
  const live = useRef({ model: s.model, select: actions.select, pad: layout.pad });
  live.current = { model: s.model, select: actions.select, pad: layout.pad };

  // ---- map lifecycle -------------------------------------------------------------------------
  useEffect(() => {
    const el = elRef.current;
    if (!el) return;
    const map = new maplibregl.Map({
      container: el,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      center: [-0.1, 52.98],
      zoom: 8.6,
      maxZoom: 16,
      style: STYLE,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "top-left");
    map.touchZoomRotate.disableRotation();
    let raf = 0;
    map.on("load", () => {
      map.resize();
      addIcons(map);
      addLayers(map);
      CLICK_LAYERS.forEach(([id]) => {
        map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
        map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
      });
      setReady(true);
    });
    map.on("move", () => {
      if (!raf)
        raf = requestAnimationFrame(() => {
          raf = 0;
          setTick((t) => t + 1);
        });
    });
    map.on("click", (e: MapMouseEvent) => {
      if (!map.getSource("lines")) return;
      const box: [[number, number], [number, number]] = [[e.point.x - 3, e.point.y - 3], [e.point.x + 3, e.point.y + 3]];
      const fs = map.queryRenderedFeatures(box, { layers: CLICK_LAYERS.map((c) => c[0]) });
      for (const [layer, kind] of CLICK_LAYERS) {
        const f = fs.find((x) => x.layer.id === layer);
        if (f) {
          const id = f.properties.id as number | string;
          live.current.select((kind === "gen" || kind === "region" ? { kind, id: String(id) } : { kind, id: Number(id) }) as Sel);
          return;
        }
      }
      live.current.select(null);
    });
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(raf);
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, []);

  // ---- the imperative handle the controller uses (fit / zoom / focus) -------------------------
  useEffect(() => {
    mapApi.current = {
      fit(anim) {
        const map = mapRef.current;
        const m = live.current.model;
        if (!map || !m || !m.buses.length) return;
        const b = new maplibregl.LngLatBounds();
        m.buses.forEach((x) => b.extend([x.lon, x.lat]));
        const opts = { padding: live.current.pad };
        const cam = map.cameraForBounds(b, opts);
        if (cam?.zoom != null) fitZoom.current = cam.zoom;
        map.fitBounds(b, { ...opts, duration: anim ? 450 : 0 });
      },
      zoomBy(d) {
        const map = mapRef.current;
        if (map) map.easeTo({ zoom: map.getZoom() + d, duration: 250 });
      },
      focusOn(ll, kMin) {
        const map = mapRef.current;
        if (!ll || !map) return;
        const z = Math.max(map.getZoom(), (fitZoom.current ?? 9) + Math.log2(kMin ?? 1));
        // land it left of the detail card that the selection opens (top right of the map)
        map.easeTo({ center: ll, zoom: z, duration: 600, offset: [-180, 40] });
      },
    };
    return () => {
      mapApi.current = null;
    };
  }, [mapApi]);

  // frame the network once the map and the model are both there, and again on every layout change
  const padKey = JSON.stringify(layout.pad);
  useEffect(() => {
    if (ready && s.model) mapApi.current?.fit(true);
  }, [ready, s.model, padKey, mapApi]);

  // ---- push data into the sources -------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !geo) return;
    GEO_SOURCES.forEach((k) => (map.getSource(k) as maplibregl.GeoJSONSource | undefined)?.setData(geo[k]));
  }, [ready, geo]);

  // ---- the flow layer: dashes stepped every 70 ms (off under reduced motion and in diff mode) ----
  const flowOn = s.layer === "flow" && !s.diffMode;
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map.setLayoutProperty("line-flow", "visibility", flowOn ? "visible" : "none");
    if (!flowOn || reducedMotion) return;
    let i = 0;
    const iv = window.setInterval(() => {
      i = (i + 1) % FLOW_DASH_SEQ.length;
      if (map.getLayer("line-flow")) map.setPaintProperty("line-flow", "line-dasharray", FLOW_DASH_SEQ[i]);
    }, 70);
    return () => window.clearInterval(iv);
  }, [ready, flowOn, reducedMotion]);

  const project = (lon: number, lat: number): [number, number] | null => {
    const map = mapRef.current;
    if (!map) return null;
    const p = map.project([lon, lat]);
    return [p.x, p.y];
  };

  return (
    <>
      <div ref={elRef} className="map" aria-label="Network map" />
      {ready && shows(s.visible, "demand") && <RegionLabels planner={planner} project={project} tick={tick} width={elRef.current?.clientWidth ?? 0} height={elRef.current?.clientHeight ?? 0} />}
      {ready && <MapMarkers planner={planner} project={project} tick={tick} width={elRef.current?.clientWidth ?? 0} height={elRef.current?.clientHeight ?? 0} />}
    </>
  );
}
