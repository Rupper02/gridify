// HTML on top of the map, re-projected on every move: project markers (all states), substation
// names, loading / diff tags on lines and planned-outage tags. Clicking a marker selects it.

import { Wrench } from "@phosphor-icons/react";
import type { CSSProperties, ReactNode } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { type FeatureKey, lineFeature, shows } from "../lib/mapFeatures";
import { effYearOf, isAccepted, outageSel, outageStudyOf, trafoRatio, trafoSub } from "../lib/derive";
import { VERDICTS, outageTag, verdictColor } from "../lib/maintenance";
import { type MapDelta, deltaTag, diffColor } from "../lib/diff";
import { C, ST, loadColor } from "../theme";
import type { Outage, QueueItem, RegistryItem } from "../types";
import { TechIcon } from "./ui";

export type MapMarkersPlanner = PlannerSlice<
  "diff" | "diffMode" | "layer" | "model" | "outages" | "result" | "sel" | "showDeferred" | "visible" | "year",
  "select",
  "branchOnly" | "diffDeltas" | "hue" | "ix" | "onMain" | "prelim" | "q" | "yr"
>;

type Project = (lon: number, lat: number) => [number, number] | null;
type Box = [number, number, number, number];
const overlaps = (b: Box, o: Box) => b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1];

interface MarkerItem {
  id: string;
  tech: string | null;
  status: keyof typeof ST;
  lon: number;
  lat: number;
  bus: number | null;
  future: boolean;
}

export function MapMarkers({ planner, project, tick, width, height }: { planner: MapMarkersPlanner; project: Project; tick: number; width: number; height: number }) {
  const { s, actions, derived } = planner;
  const { q, prelim, ix, branchOnly, hue, diffDeltas, yr } = derived;
  void tick; // re-render on map moves
  if (!s.model || !ix) return null;
  const diffOn = s.diffMode && !derived.onMain;
  const added = new Set((s.diff?.projects ?? []).filter((p) => p.change === "added").map((p) => p.request_id));
  const sel = s.sel;
  const inView = (x: number, y: number) => x > -60 && y > -30 && x < width + 60 && y < height + 30;
  const on = (k: FeatureKey) => shows(s.visible, k);
  const lineOn = (id: number) => {
    const l = ix.line.get(id);
    return !!l && on(lineFeature(l.voltage_kv));
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
    const x = pt[0] + 14;
    const y = pt[1] + (n % 2 ? 1 : -1) * Math.ceil(n / 2) * 30;
    if (!inView(x, y)) return null;
    boxes.push([x - 13, y - 14, x + 13 + m.id.length * 6.6 + 6, y + 14]);
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
        <span className="mk-id" style={{ color: st.c }} onClick={pick}>
          {m.id}
        </span>
      </div>
    );
  });

  // ---- substation names (one per substation with a transformer) ---------------------------------
  const seen = new Map<string, { lon: number; lat: number; ratios: Set<string>; hv: number }>();
  s.model.transformers.forEach((t) => {
    const name = trafoSub(t);
    const e = seen.get(name) ?? { lon: t.hv_lon, lat: t.hv_lat, ratios: new Set<string>(), hv: t.hv_bus };
    e.ratios.add(trafoRatio(t));
    seen.set(name, e);
  });
  const subEls = (on("substations") ? [...seen.entries()] : []).map(([name, e]) => {
    const pt = project(e.lon, e.lat);
    if (!pt || !inView(pt[0], pt[1])) return null;
    const x = pt[0] + 14;
    const y = pt[1];
    const w = Math.max(name.length * 6.8, 60);
    const box: Box = [x, y - 12, x + w, y + 12];
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
      if (l && lineOn(id)) diffTag(`d${id}`, project((l.from_lon + l.to_lon) / 2, (l.from_lat + l.to_lat) / 2), d);
    });
    diffDeltas.trafos.forEach((d, id) => {
      const t = ix.trafo.get(id);
      if (t && on("transformers")) diffTag(`dt${id}`, project(t.hv_lon, t.hv_lat), d, "T ", -24);
    });
  } else if (s.layer === "loading" && yr) {
    Object.entries(yr.line_loading ?? {}).forEach(([id, pct]) => {
      if ((pct < 60 && !(sel?.kind === "line" && sel.id === +id)) || !lineOn(+id)) return;
      const l = ix.line.get(+id);
      if (!l) return;
      const pt = project((l.from_lon + l.to_lon) / 2, (l.from_lat + l.to_lat) / 2);
      if (!pt || !inView(pt[0], pt[1])) return;
      const c = loadColor(pct);
      tagEls.push(
        <span key={`l${id}`} className="line-tag" style={{ left: pt[0], top: pt[1], borderColor: c, color: c }}>
          {Math.round(pct)}%
        </span>,
      );
    });
  }
  // transformers: the most loaded one at each substation, tagged above its icon (loading layer, or
  // whenever one is over 100 %)
  if (yr && !diffOn && on("transformers")) {
    const atSite = new Map<string, { pct: number; lon: number; lat: number; id: number }>();
    Object.entries(yr.trafo_loading ?? {}).forEach(([id, pct]) => {
      const t = ix.trafo.get(+id);
      if (!t || (s.layer !== "loading" && pct <= 100) || (s.layer === "loading" && pct < 60)) return;
      const k = `${t.hv_lon},${t.hv_lat}`;
      if ((atSite.get(k)?.pct ?? -1) < pct) atSite.set(k, { pct, lon: t.hv_lon, lat: t.hv_lat, id: +id });
    });
    atSite.forEach((v) => {
      const pt = project(v.lon, v.lat);
      if (!pt || !inView(pt[0], pt[1])) return;
      const c = loadColor(v.pct);
      tagEls.push(
        <span key={`t${v.id}`} className="line-tag" style={{ left: pt[0], top: pt[1] - 24, borderColor: c, color: c }}>
          T {Math.round(v.pct)}%
        </span>,
      );
    });
  }

  // ---- planned outages in the viewed year ------------------------------------------------------
  const outEls = (on("works") ? s.outages : [])
    .filter((o: Outage) => o.year === s.year)
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
          style={{ left: pt[0], top: pt[1] + (o.element_kind === "gen" ? -18 : 0), borderColor: vc ?? undefined, borderStyle: vc ? "solid" : undefined }}
          title={study ? VERDICTS[study.verdict]?.label : "Not studied yet"}
          onClick={() => actions.select(outageSel(o))}
        >
          <Wrench size={11} color={vc ?? undefined} />
          {outageTag(o)}
        </button>
      );
    });

  return (
    <div className="markers" aria-hidden={false}>
      {subEls}
      {tagEls}
      {outEls}
      {projectEls}
    </div>
  );
}

function outagePoint(o: Outage, ix: NonNullable<MapMarkersPlanner["derived"]["ix"]>): [number, number] | null {
  if (o.element_kind === "line") {
    const l = ix.line.get(Number(o.element_id));
    return l ? [(l.from_lon + l.to_lon) / 2, (l.from_lat + l.to_lat) / 2] : null;
  }
  if (o.element_kind === "trafo") {
    const t = ix.trafo.get(Number(o.element_id));
    return t ? [t.hv_lon, t.hv_lat] : null;
  }
  const g = ix.gen.get(o.element_id);
  return g ? [g.lon, g.lat] : null;
}
