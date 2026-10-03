// What is selected (a project opens the project card; a line, transformer or generator the element
// card), and where the map looks.

import { useCallback } from "react";

import { regionCentroid } from "../../lib/demand";
import type { Sel } from "../../types";
import type { Core } from "./core";

export function useSelection({ patch, ref, mapApi }: Core) {
  const pointOf = useCallback(
    (t: Sel): [number, number] | null => {
      const st = ref.current;
      const m = st.model;
      if (!m) return null;
      if (t.kind === "line") {
        const l = m.lines.find((x) => x.line_id === t.id);
        return l ? [(l.from_lon + l.to_lon) / 2, (l.from_lat + l.to_lat) / 2] : null;
      }
      if (t.kind === "trafo") {
        const x = m.transformers.find((y) => y.trafo_id === t.id);
        return x ? [x.hv_lon, x.hv_lat] : null;
      }
      if (t.kind === "region") {
        const r = (m.regions ?? []).find((y) => y.region_id === t.id);
        return r ? regionCentroid(r.buses, new Map(m.buses.map((b) => [b.bus_id, b]))) : null;
      }
      if (t.kind === "gen") {
        const g = m.generators.find((y) => y.request_id === t.id);
        return g ? [g.lon, g.lat] : null;
      }
      const q = st.result?.queue.find((x) => x.request_id === t.id);
      return q && q.lon != null && q.lat != null ? [q.lon, q.lat] : null;
    },
    [ref],
  );

  /** Select something (null clears). An element selection seeds the maintenance form's year. */
  const select = useCallback(
    (sel: Sel | null) => {
      if (sel && sel.kind !== "project" && sel.kind !== "region") patch((st) => ({ sel, maintDraft: { ...st.maintDraft, year: Math.max(2026, st.year) } }));
      else patch({ sel });
    },
    [patch],
  );

  const selectProject = useCallback((id: string) => select({ kind: "project", id }), [select]);

  /** Select and bring into view (from a list row). */
  const focusSel = useCallback(
    (sel: Sel, kMin = 2.4) => {
      select(sel);
      mapApi.current?.focusOn(pointOf(sel), kMin);
    },
    [mapApi, pointOf, select],
  );

  return { select, selectProject, focusSel };
}
