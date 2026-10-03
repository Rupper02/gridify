// The evidence behind a step an agent cited: the study it ran, re-read from the durable cache, its
// items with the engine's figures, what it did not study, and whether the engine has changed since.

import { Receipt, Warning, X } from "@phosphor-icons/react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { nameElements } from "../lib/derive";
import { SEVERITY } from "../lib/gate";
import { argsLine, toolLabel } from "../lib/trace";
import { C } from "../theme";
import type { StudyItem } from "../types";

export type StudyDrawerPlanner = PlannerSlice<"study", "closeEvidence", "ix">;

const MAX_ITEMS = 40;
const SEV_ORDER: Record<string, number> = { breach: 0, warn: 1, info: 2 };
const fmt = (v: number): string => (Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) < 10 ? 2 : 1));
const worstFirst = (a: StudyItem, b: StudyItem) => (SEV_ORDER[a.severity] ?? 3) - (SEV_ORDER[b.severity] ?? 3) || a.index - b.index;

export function StudyDrawer({ planner }: { planner: StudyDrawerPlanner }) {
  const { s, actions, derived } = planner;
  const ev = s.study;
  if (!ev) return null;
  const st = ev.study;
  const items = st ? [...st.items].sort(worstFirst).slice(0, MAX_ITEMS) : [];
  return (
    <div className="study-drawer glass" role="dialog" aria-label="Study evidence">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Receipt size={15} color={C.accent} />
        <span className="ellipsis" style={{ fontSize: 13, fontWeight: 600, flex: 1, minWidth: 0 }}>{toolLabel(ev.step.tool)}</span>
        <button className="icon-btn" onClick={actions.closeEvidence} aria-label="Close the evidence">
          <X size={13} />
        </button>
      </div>
      <span className="mono" style={{ fontSize: 10.5, color: C.mute }}>{argsLine(ev.step.args) || "default parameters"}</span>
      {ev.stale && (
        <div className="notice amber">
          <Warning size={12} weight="fill" style={{ marginRight: 4, verticalAlign: -1 }} />
          The engine has changed since this study ran; the figures are as recorded then.
        </div>
      )}
      {!st && (
        <span className="mute" style={{ fontSize: 12, lineHeight: 1.45 }}>
          This step was a lookup, not a study: {ev.result != null ? JSON.stringify(ev.result).slice(0, 500) : "no stored result"}
        </span>
      )}
      {st && (
        <>
          <span style={{ fontSize: 12, color: C.ink3, lineHeight: 1.45, textWrap: "pretty" }}>{nameElements(st.summary, derived.ix)}</span>
          <div className="items">
            {items.map((it) => (
              <div key={it.index} className="study-item">
                <span className="sev-dot" style={{ background: SEVERITY[it.severity]?.c ?? C.mute }} title={SEVERITY[it.severity]?.label ?? it.severity} />
                <span className="ellipsis" style={{ fontWeight: 600 }}>
                  {it.element_name || `${it.element_kind} ${it.element_id}`}
                  {it.year ? ` · ${it.year}` : ""}
                  {it.case ? ` · ${it.case.replace(/_/g, " ")}` : ""}
                </span>
                <span className="mono" style={{ color: C.mute, whiteSpace: "nowrap" }}>
                  {it.value != null ? `${fmt(it.value)}${it.limit != null ? ` / ${fmt(it.limit)}` : ""} ${it.unit}` : ""}
                </span>
                <span className="msg">{nameElements(it.message, derived.ix)}</span>
              </div>
            ))}
            {!items.length && <span className="mute" style={{ fontSize: 12 }}>The study found nothing to list.</span>}
          </div>
          {st.items.length > MAX_ITEMS && <span className="mute" style={{ fontSize: 11 }}>{st.items.length - MAX_ITEMS} more items in the full study.</span>}
          {st.not_studied.length > 0 && <span style={{ fontSize: 11, color: C.mute, lineHeight: 1.4 }}>Not studied: {st.not_studied.join("; ")}</span>}
        </>
      )}
      <span className="evidence-line">
        step {ev.step.step_id} · engine {ev.current_engine.slice(0, 10)}
        {st ? ` · ${st.solves} ${st.solves === 1 ? "solve" : "solves"}` : ""}
      </span>
    </div>
  );
}
