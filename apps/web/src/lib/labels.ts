// HTML label overlay for the map: screen-space placement with simple collision avoidance.

import { ORDER } from "../theme";
import type { Bus, Transformer } from "../types";
import { trafoRatio, trafoSub, type ProjView } from "./derive";
import { fmtMw } from "../theme";

export interface MapLabel {
  key: string;
  sx: number;
  sy: number;
  text: string;
  sub: string;
  font: string;
  fs: number;
  fw: number;
  color: string;
}

type Box = [number, number, number, number];
const overlaps = (b: Box, o: Box) => b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1];

export interface LabelInputs {
  project: (lon: number, lat: number) => [number, number];
  width: number;
  height: number;
  projList: ProjView[];
  transformers: Transformer[];
  buses: Bus[];
  showBusLabels: boolean;
}

/**
 * Place transformer, project and (optionally) bus labels. Each label tries its anchor row, then
 * alternates one row up/down, and is dropped after four attempts; project markers reserve their
 * own box first so labels never cover an icon.
 */
export function placeLabels(inp: LabelInputs): MapLabel[] {
  const out: MapLabel[] = [];
  const boxes: Box[] = [];
  const { width: W, height: H } = inp;
  const place = (lab: MapLabel, w: number, h: number) => {
    if (lab.sx < -50 || lab.sy < -20 || lab.sx > W + 10 || lab.sy > H + 20) return;
    for (let i = 0; i < 4; i++) {
      const y = lab.sy + i * (h + 1) * (i % 2 ? 1 : -1) * Math.ceil(i / 2);
      const b: Box = [lab.sx, y - h / 2, lab.sx + w, y + h / 2];
      if (!boxes.some((o) => overlaps(b, o))) {
        boxes.push(b);
        out.push({ ...lab, sy: y });
        return;
      }
    }
  };
  inp.projList.forEach((p) => {
    const [sx, sy] = inp.project(p.x.lon!, p.x.lat!);
    const R = p.size * 17;
    boxes.push([sx - R, sy - R, sx + R, sy + R]);
  });
  inp.transformers.forEach((t, i) => {
    const [sx, sy] = inp.project(t.hv_lon, t.hv_lat);
    place(
      { key: "t" + i, sx: sx + 17, sy, text: trafoSub(t), sub: `${trafoRatio(t)} · ${fmtMw(t.sn_mva)} MVA`, font: "'Geist', sans-serif", fs: 11.5, fw: 600, color: "#111827" },
      120,
      28,
    );
  });
  [...inp.projList]
    .sort((a, b) => ORDER[a.x.status] - ORDER[b.x.status] || (b.x.rating_mw ?? 0) - (a.x.rating_mw ?? 0))
    .forEach((p) => {
      const [sx, sy] = inp.project(p.x.lon!, p.x.lat!);
      const R = p.size * 17;
      place(
        { key: "p" + p.x.request_id, sx: sx + R + 4, sy, text: p.label, sub: "", font: "'Geist Mono', monospace", fs: 10.5, fw: 600, color: p.fg },
        p.label.length * 6.4,
        13,
      );
    });
  if (inp.showBusLabels)
    inp.buses.forEach((b) => {
      if (b.vn_kv > 20) return;
      const [sx, sy] = inp.project(b.lon, b.lat);
      const t = String(b.bus_id);
      place({ key: "b" + b.bus_id, sx: sx + 5, sy: sy - 7, text: t, sub: "", font: "'Geist Mono', monospace", fs: 9, fw: 400, color: "#475569" }, t.length * 5.6, 10);
    });
  return out;
}
