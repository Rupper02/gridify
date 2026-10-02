// What is selected on the map, and where the map looks. Also the add-project form's field setter,
// because picking a bus on the map fills the form.

import { useCallback } from "react";

import { readyFromForm } from "../../lib/derive";
import type { FormState, Hit, Sel } from "../../types";
import type { Core } from "./core";

export function useSelection({ patch, ref, mapApi }: Core) {
  const elementPt = useCallback((t: Sel | null): [number, number] | null => {
    const m = ref.current.model;
    if (!m || !t) return null;
    if (t.kind === "bus") {
      const b = m.buses.find((x) => x.bus_id === t.id);
      return b ? [b.lon, b.lat] : null;
    }
    if (t.kind === "line") {
      const l = m.lines.find((x) => x.line_id === t.id);
      return l ? [(l.from_lon + l.to_lon) / 2, (l.from_lat + l.to_lat) / 2] : null;
    }
    if (t.kind === "project") {
      const q = ref.current.result?.queue.find((x) => x.request_id === t.id);
      return q && q.lon != null && q.lat != null ? [q.lon, q.lat] : null;
    }
    return null;
  }, [ref]);

  const selectProject = useCallback(
    (id: string, zoom?: boolean) => {
      patch({ sel: { kind: "project", id } });
      const q = ref.current.result?.queue.find((x) => x.request_id === id);
      const map = mapApi.current;
      if (!map) return;
      if (zoom) {
        const el = q?.reason?.element;
        const target: Sel = el
          ? el.line_id != null
            ? { kind: "line", id: el.line_id }
            : { kind: "bus", id: el.bus_id! }
          : { kind: "project", id };
        map.focusOn(elementPt(target), 2.6);
      } else if (map.zoomedIn()) map.focusOn(elementPt({ kind: "project", id }));
    },
    [elementPt, mapApi, patch, ref],
  );

  const setForm = useCallback(
    (p: Partial<FormState>) =>
      patch((st) => {
        const f = { ...st.form, ...p };
        if ("land" in p || "planning" in p || "finance" in p) f.readiness = readyFromForm(f);
        return { form: f };
      }),
    [patch],
  );

  /** A map hit was clicked: pick a bus (in pick mode), select a project, or select an element. */
  const pick = useCallback(
    (hit: Hit | null) => {
      const st = ref.current;
      if (!hit) {
        if (!st.pickMode) patch({ sel: null });
        return;
      }
      if (st.pickMode) {
        if (hit.kind === "bus") {
          setForm({ bus: String(hit.id) });
          patch({ pickMode: false });
        }
        return;
      }
      if (hit.kind === "load" || hit.kind === "existing") return;
      if (hit.kind === "project") return selectProject(String(hit.id));
      patch({ sel: { kind: hit.kind, id: Number(hit.id) } as Sel });
    },
    [patch, ref, selectProject, setForm],
  );

  const focusSel = useCallback(
    (target: Sel, kMin = 2.8) => {
      patch({ sel: target });
      mapApi.current?.focusOn(elementPt(target), kMin);
    },
    [elementPt, mapApi, patch],
  );

  return { selectProject, setForm, pick, focusSel };
}
