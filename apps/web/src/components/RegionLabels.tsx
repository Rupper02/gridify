// The Demand layer's names: one label per demand region ("name", then "demand / firm MW · class"),
// left of its centre so substation names (right of their point) stay readable. Breaches are placed
// first; a label that would overlap one already placed is skipped. Clicking selects the region.

import type { PlannerSlice } from "../hooks/planner/slice";
import { REGION_STATE, labelOrder, regionCentroid, regionFigure, regionRows } from "../lib/demand";
import { type Box, ID_CHAR_PX, type Project, overlaps } from "../lib/placement";

export type RegionLabelsPlanner = PlannerSlice<"model" | "sel", "select", "yr">;

/** `top`: the header's bottom edge; a label that would sit under the header is not drawn. */
export function RegionLabels({ planner, project, tick, width, height, top }: { planner: RegionLabelsPlanner; project: Project; tick: number; width: number; height: number; top: number }) {
  const { s, actions, derived } = planner;
  void tick; // re-render on map moves
  if (!s.model) return null;
  const at = new Map(s.model.buses.map((b) => [b.bus_id, b]));
  const placed: Box[] = [];
  const els = labelOrder(regionRows(s.model, derived.yr)).map((r) => {
    const c = regionCentroid(r.buses, at);
    const pt = c && project(c[0], c[1]);
    if (!pt) return null;
    const fig = regionFigure(r);
    const w = Math.max(r.name.length * ID_CHAR_PX, fig.length * 5.9) + 8;
    const right = pt[0] - 12;
    const box: Box = [right - w, pt[1] - 14, right, pt[1] + 14];
    if (box[2] < -20 || box[0] > width + 20 || box[1] < top || box[1] > height) return null;
    const isSel = s.sel?.kind === "region" && s.sel.id === r.region_id;
    if (!isSel && placed.some((o) => overlaps(box, o))) return null;
    placed.push(box);
    const st = REGION_STATE[r.state];
    return (
      <button
        key={r.region_id}
        className={`region-label${isSel ? " on" : ""}`}
        style={{ left: right, top: pt[1] }}
        onClick={() => actions.select({ kind: "region", id: r.region_id })}
        title={`${r.name}: ${st.label.toLowerCase()}`}
      >
        <b>{r.name}</b>
        <span style={{ color: r.state === "breach" || r.state === "warn" ? st.c : undefined }}>{fig}</span>
      </button>
    );
  });
  return <div className="markers">{els}</div>;
}
