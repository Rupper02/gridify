// HTML on top of the map, re-projected on every move: the branch's connections (in service by the viewed year solid,
// later ones faint), substation names, and loading or compare tags on lines and transformers.

import type { CSSProperties, ReactNode } from "react";

import type { Planner } from "../hooks/usePlanner";
import { type MapDelta, deltaTag, diffColor } from "../lib/geo";
import { type FeatureKey, lineFeature, shows } from "../lib/mapFeatures";
import { trafoRatio, trafoSub } from "../lib/model";
import {
  type Box,
  MARKER_DX,
  type Projector,
  type SubSite,
  TRAFO_TAG_DY,
  fanOffset,
  lineTagShown,
  markerBox,
  midpoint,
  overlaps,
  subLabelBox,
  substationSites,
  worstTrafoPerSite,
} from "../lib/placement";
import { C, loadColor } from "../theme";
import { TechIcon } from "./ui";

/** `top`: the header's bottom edge; nothing is drawn under the header. */
export function MapMarkers({ planner, project, tick, width, height, top }: { planner: Planner; project: Projector; tick: number; width: number; height: number; top: number }) {
  const { s, actions, derived } = planner;
  const { ix, yr, diffMap, hue } = derived;
  void tick; // re-render on map moves
  if (!s.model || !ix) return null;
  const sel = s.sel;
  const inView = (x: number, y: number) => x > -60 && y > top + 12 && x < width + 60 && y < height + 30;
  const on = (k: FeatureKey) => shows(s.visible, k);
  const lineOn = (id: number) => {
    const l = ix.line.get(id);
    return !!l && on(lineFeature(l.voltage_kv, derived.tiers));
  };

  // ---- connections -----------------------------------------------------------------------------
  const atBus = new Map<number, number>();
  const boxes: Box[] = [];
  const connEls = (on("connections") ? s.connections : []).map((c) => {
    const b = ix.bus.get(c.bus_id);
    const pt = b && project(b.lon, b.lat);
    if (!pt) return null;
    const n = atBus.get(c.bus_id) ?? 0;
    atBus.set(c.bus_id, n + 1);
    const x = pt[0] + MARKER_DX;
    const y = pt[1] + fanOffset(n);
    if (!inView(x, y)) return null;
    boxes.push(markerBox(x, y, c.request_id));
    const live = c.year <= s.year;
    const isSel = sel?.kind === "connection" && sel.id === c.request_id;
    const tile: CSSProperties = {
      background: live ? hue : "rgba(11,17,26,0.75)",
      borderStyle: live ? "solid" : "dashed",
      borderColor: live ? "rgba(255,255,255,0.7)" : hue,
      boxShadow: (live ? "0 4px 12px rgba(0,0,0,0.45)" : "none") + (isSel ? ", 0 0 0 6px rgba(124,227,255,0.45)" : ""),
    };
    const pick = () => actions.select({ kind: "connection", id: c.request_id });
    return (
      <div key={`c${c.request_id}`} className="mk" style={{ left: x, top: y, opacity: live ? 1 : 0.6 }}>
        <button className="mk-tile" style={tile} onClick={pick} aria-label={`${c.request_id}, from ${c.year}`}>
          <TechIcon tech={c.technology} size={14} color={live ? C.night : hue} weight={live ? "bold" : "regular"} />
        </button>
        <span className="mk-id" style={{ color: hue }} onClick={pick} aria-hidden="true">
          {c.request_id}
          {!live && <span className="mute"> · {c.year}</span>}
        </span>
      </div>
    );
  });

  // ---- substation names (one per substation with a transformer) ---------------------------------
  const sites = on("substations") ? substationSites(s.model.transformers, trafoSub, trafoRatio) : new Map<string, SubSite>();
  const subEls = [...sites.entries()].map(([name, e]) => {
    const pt = project(e.lon, e.lat);
    if (!pt || !inView(pt[0], pt[1])) return null;
    const x = pt[0] + MARKER_DX;
    const y = pt[1];
    const box = subLabelBox(x, y, name);
    if (boxes.some((o) => overlaps(box, o))) return null;
    boxes.push(box);
    const v = s.layer === "voltage" ? yr?.bus_vm?.[e.hv] : undefined;
    return (
      <div key={`s${name}`} className="sub-label" style={{ left: x, top: y }}>
        <b>{name}</b>
        <span>{v != null ? `${v.toFixed(3)} pu` : [...e.ratios].join(" · ")}</span>
      </div>
    );
  });

  // ---- tags: loading % (loading layer) or the change against the parent in the viewed year (compare) ---
  const tagEls: ReactNode[] = [];
  const tag = (key: string, at: [number, number] | null, text: string, c: string, dy = 0) => {
    if (!at || !inView(at[0], at[1])) return;
    tagEls.push(
      <span key={key} className="line-tag" style={{ left: at[0], top: at[1] + dy, borderColor: c, color: c }}>
        {text}
      </span>,
    );
  };
  if (diffMap) {
    diffMap.lines.forEach((d: MapDelta, id) => {
      const l = ix.line.get(id);
      if (l && lineOn(id)) tag(`d${id}`, project(...midpoint(l)), deltaTag(d), diffColor(d));
    });
    diffMap.trafos.forEach((d: MapDelta, id) => {
      const t = ix.trafo.get(id);
      if (t && on("transformers")) tag(`dt${id}`, project(t.hv_lon, t.hv_lat), `T ${deltaTag(d)}`, diffColor(d), TRAFO_TAG_DY);
    });
  } else if (yr) {
    if (s.layer === "loading")
      Object.entries(yr.line_loading ?? {}).forEach(([id, pct]) => {
        if (!lineTagShown(pct, sel?.kind === "line" && sel.id === +id) || !lineOn(+id)) return;
        const l = ix.line.get(+id);
        if (l) tag(`l${id}`, project(...midpoint(l)), `${Math.round(pct)}%`, loadColor(pct));
      });
    // transformers: the most loaded one at each substation (loading layer, or whenever one is over 100 %)
    if (on("transformers"))
      worstTrafoPerSite(yr.trafo_loading ?? {}, ix, s.layer === "loading").forEach((v) =>
        tag(`t${v.id}`, project(v.lon, v.lat), `T ${Math.round(v.pct)}%`, loadColor(v.pct), TRAFO_TAG_DY),
      );
  }

  return (
    <div className="markers">
      {subEls}
      {tagEls}
      {connEls}
    </div>
  );
}
