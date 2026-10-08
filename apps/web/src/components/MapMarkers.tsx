// HTML on top of the map, re-projected on every move: project markers (all states), substation
// names, loading / diff tags on lines and planned-outage tags. Clicking a marker selects it.

import { Wrench } from "@phosphor-icons/react";
import type { CSSProperties, ReactNode } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { type FeatureKey, lineFeature, shows } from "../lib/mapFeatures";
import { effYearOf, isAccepted, outageSel, outageStudyOf, trafoRatio, trafoSub } from "../lib/derive";
import { NEED, needOf, needYear, roomColor, roomText } from "../lib/capacity";
import { fromText } from "../lib/limits";
import { VERDICTS, outageTag, verdictColor } from "../lib/maintenance";
import { type MapDelta, deltaTag, diffColor } from "../lib/diff";
import {
  type Box,
  GEN_OUTAGE_DY,
  MARKER_DX,
  type Project,
  type SubSite,
  TRAFO_TAG_DY,
  fanOffset,
  lineTagShown,
  markerBox,
  midpoint,
  outagePoint,
  overlaps,
  subLabelBox,
  substationSites,
  tagBox,
  worstTrafoPerSite,
} from "../lib/placement";
import { C, ST, loadColor } from "../theme";
import type { QueueItem, RegistryItem } from "../types";
import { TechIcon } from "./ui";

export type MapMarkersPlanner = PlannerSlice<
  "diff" | "diffMode" | "layer" | "model" | "outages" | "result" | "sel" | "showDeferred" | "visible" | "year",
  "select",
  "bindIx" | "branchOnly" | "diffDeltas" | "hue" | "ix" | "onMain" | "prelim" | "q" | "rooms" | "tiers" | "yr"
>;

interface MarkerItem {
  id: string;
  tech: string | null;
  status: keyof typeof ST;
  lon: number;
  lat: number;
  bus: number | null;
  future: boolean;
}

/** `top`: the header's bottom edge; nothing is drawn under the header (its glass is nearly opaque, so a label there only shows through). */
export function MapMarkers({ planner, project, tick, width, height, top }: { planner: MapMarkersPlanner; project: Project; tick: number; width: number; height: number; top: number }) {
  const { s, actions, derived } = planner;
  const { q, prelim, ix, branchOnly, hue, diffDeltas, yr } = derived;
  void tick; // re-render on map moves
  if (!s.model || !ix) return null;
  const diffOn = s.diffMode && !derived.onMain;
  const added = new Set((s.diff?.projects ?? []).filter((p) => p.change === "added").map((p) => p.request_id));
  const sel = s.sel;
  const inView = (x: number, y: number) => x > -60 && y > top + 12 && x < width + 60 && y < height + 30;
  const on = (k: FeatureKey) => shows(s.visible, k);
  const headroom = s.layer === "headroom" && !diffOn;
  const lineOn = (id: number) => {
    const l = ix.line.get(id);
    return !!l && on(lineFeature(l.voltage_kv, derived.tiers));
  };

  // ---- projects --------------------------------------------------------------------------------
  const items: MarkerItem[] = [];
  if (on("projects")) q.forEach((x: QueueItem) => {
    if (x.lon == null || x.lat == null) return;
    const hidden = (x.status === "Deferred" || x.status === "Rejected") && !s.showDeferred && !(sel?.kind === "project" && sel.id === x.request_id);
    if (hidden) return;
    const eff = effYearOf(x);
    items.push({ id: x.request_id, tech: x.technology, status: x.status, lon: x.lon, lat: x.lat, bus: x.bus_id, future: isAccepted(x) && eff != null && eff > s.year });
  });
  if (on("projects")) prelim.forEach((p: RegistryItem) => {
    const b = p.bus_id != null ? ix.bus.get(p.bus_id) : undefined;
    if (b) items.push({ id: p.request_id, tech: p.technology, status: "Prelim", lon: b.lon, lat: b.lat, bus: p.bus_id, future: false });
  });
  // projects at the same bus fan out vertically instead of stacking on one point
  const atBus = new Map<number, number>();
  const boxes: Box[] = [];
  const projectEls = items.map((m) => {
    const pt = project(m.lon, m.lat);
    if (!pt) return null;
    const k = m.bus ?? -1;
    const n = atBus.get(k) ?? 0;
    atBus.set(k, n + 1);
    const x = pt[0] + MARKER_DX;
    const y = pt[1] + fanOffset(n);
    if (!inView(x, y)) return null;
    boxes.push(markerBox(x, y, m.id));
    const st = ST[m.status];
    const dashed = m.status === "Deferred" || m.status === "Prelim" || m.status === "Rejected";
    const onlyHere = branchOnly.has(m.id);
    const isSel = sel?.kind === "project" && sel.id === m.id;
    const op = diffOn ? (onlyHere || added.has(m.id) ? 1 : 0.28) : m.future ? 0.4 : 1;
    const ring = onlyHere && !derived.onMain ? `0 0 0 2px ${C.night}, 0 0 0 3.5px ${hue}` : dashed ? "none" : "0 4px 12px rgba(0,0,0,0.45)";
    const tile: CSSProperties = {
      background: dashed ? "rgba(11,17,26,0.75)" : st.c,
      borderStyle: dashed ? "dashed" : "solid",
      borderColor: dashed ? st.c : "rgba(255,255,255,0.7)",
      boxShadow: ring + (isSel ? ", 0 0 0 6px rgba(124,227,255,0.45)" : ""),
    };
    const pick = () => actions.select({ kind: "project", id: m.id });
    return (
      <div key={`p${m.id}`} className="mk" style={{ left: x, top: y, opacity: op }}>
        <button className="mk-tile" style={tile} onClick={pick} aria-label={`${m.id}, ${st.label}`}>
          {diffOn && added.has(m.id) && <span className="mk-plus" style={{ background: hue }}>+</span>}
          <TechIcon tech={m.tech} size={14} color={dashed ? st.c : C.night} weight={dashed ? "regular" : "bold"} />
        </button>
        <span className="mk-id" style={{ color: st.c }} onClick={pick} aria-hidden="true">{/* the tile button above is its keyboard and screen-reader twin */}
          {m.id}
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
    const room = headroom ? derived.rooms.get(name) : undefined;
    return (
      <div key={`s${name}`} className="sub-label" style={{ left: x, top: y }}>
        <b>{name}</b>
        {room ? (
          <span title="Room to connect today: generation at summer minimum, demand at winter peak">
            {room.gen && <>gen <b style={{ color: roomColor(room.gen.mw) }}>{roomText(room.gen)}</b></>}
            {room.gen && room.dem && " · "}
            {room.dem && <>dem <b style={{ color: roomColor(room.dem.mw) }}>{roomText(room.dem)}</b></>} MW
          </span>
        ) : (
          <span>{v != null ? `${v.toFixed(3)} pu` : [...e.ratios].join(" · ")}</span>
        )}
      </div>
    );
  });

  // ---- line tags: loading % (loading layer) or the change vs main in the viewed year (diff mode) ---
  const tagEls: ReactNode[] = [];
  if (diffOn && diffDeltas) {
    const diffTag = (key: string, at: [number, number] | null, d: MapDelta, prefix = "", dy = 0) => {
      if (!at || !inView(at[0], at[1])) return;
      const c = diffColor(d);
      tagEls.push(
        <span key={key} className="line-tag diff-tag" style={{ left: at[0], top: at[1] + dy, borderColor: c, color: c }}>
          {prefix}
          {deltaTag(d)}
        </span>,
      );
    };
    diffDeltas.lines.forEach((d, id) => {
      const l = ix.line.get(id);
      if (l && lineOn(id)) diffTag(`d${id}`, project(...midpoint(l)), d);
    });
    diffDeltas.trafos.forEach((d, id) => {
      const t = ix.trafo.get(id);
      if (t && on("transformers")) diffTag(`dt${id}`, project(t.hv_lon, t.hv_lat), d, "T ", TRAFO_TAG_DY);
    });
  } else if (s.layer === "loading" && yr) {
    Object.entries(yr.line_loading ?? {}).forEach(([id, pct]) => {
      if (!lineTagShown(pct, sel?.kind === "line" && sel.id === +id) || !lineOn(+id)) return;
      const l = ix.line.get(+id);
      if (!l) return;
      const pt = project(...midpoint(l));
      if (!pt || !inView(pt[0], pt[1])) return;
      const c = loadColor(pct);
      tagEls.push(
        <span key={`l${id}`} className="line-tag" style={{ left: pt[0], top: pt[1], borderColor: c, color: c }}>
          {Math.round(pct)}%
        </span>,
      );
    });
  } else if (headroom) {
    // every element that breaches or comes near its limit, tagged with the year it first does; the
    // earliest wins where tags would overlap (the rest are in the Capacity tab's timeline)
    const placed: Box[] = [];
    [...derived.bindIx.values()]
      .map((b) => ({ b, n: needOf(b, s.year), year: needYear(b) }))
      .filter((x) => x.n !== "holds" && x.year != null)
      .sort((x, y) => x.year! - y.year! || (x.b.first_breach_year == null ? 1 : 0) - (y.b.first_breach_year == null ? 1 : 0))
      .forEach(({ b, n, year }) => {
        const l = b.kind === "line" && lineOn(b.element_id) ? ix.line.get(b.element_id) : undefined;
        const t = b.kind === "trafo" && on("transformers") ? ix.trafo.get(b.element_id) : undefined;
        const bus = b.kind === "bus" && on("buses") ? ix.bus.get(b.element_id) : undefined;
        const at = l ? project(...midpoint(l)) : t ? project(t.hv_lon, t.hv_lat) : bus ? project(bus.lon, bus.lat) : null;
        if (!at || !inView(at[0], at[1])) return;
        const text = `${t ? "T " : bus ? "V " : ""}${year}`;
        const y = at[1] + (t ? TRAFO_TAG_DY : 0);
        const box = tagBox(at[0], y, text);
        if (placed.some((o) => overlaps(box, o))) return;
        placed.push(box);
        const c = NEED[n].c;
        tagEls.push(
          <span key={`n${b.kind}${b.element_id}`} className="line-tag" style={{ left: at[0], top: y, borderColor: c, color: c }} title={`${b.name}: ${fromText(b)}`}>
            {text}
          </span>,
        );
      });
  }
  // transformers: the most loaded one at each substation, tagged above its icon (loading layer, or
  // whenever one is over 100 %)
  if (yr && !diffOn && !headroom && on("transformers")) {
    worstTrafoPerSite(yr.trafo_loading ?? {}, ix, s.layer === "loading").forEach((v) => {
      const pt = project(v.lon, v.lat);
      if (!pt || !inView(pt[0], pt[1])) return;
      const c = loadColor(v.pct);
      tagEls.push(
        <span key={`t${v.id}`} className="line-tag" style={{ left: pt[0], top: pt[1] + TRAFO_TAG_DY, borderColor: c, color: c }}>
          T {Math.round(v.pct)}%
        </span>,
      );
    });
  }

  // ---- planned outages in the viewed year ------------------------------------------------------
  const outEls = (on("works") ? s.outages : [])
    .filter((o) => o.year === s.year)
    .map((o) => {
      const at = outagePoint(o, ix);
      const pt = at && project(at[0], at[1]);
      if (!pt || !inView(pt[0], pt[1])) return null;
      const { state, study } = outageStudyOf(o, s.result);
      const vc = verdictColor(study?.verdict);
      return (
        <button
          key={`o${o.outage_id}`}
          className={`out-tag${state === "unstudied" ? " fresh" : ""}`}
          style={{ left: pt[0], top: pt[1] + (o.element_kind === "gen" ? GEN_OUTAGE_DY : 0), borderColor: vc ?? undefined, borderStyle: vc ? "solid" : undefined }}
          title={study ? VERDICTS[study.verdict]?.label : "Not studied yet"}
          onClick={() => actions.select(outageSel(o))}
        >
          <Wrench size={11} color={vc ?? undefined} />
          {outageTag(o)}
        </button>
      );
    });

  return (
    <div className="markers">
      {subEls}
      {tagEls}
      {outEls}
      {projectEls}
    </div>
  );
}
