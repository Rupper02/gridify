// A planned window's verdict: the chip (Feasible / Curtailment / Demand at risk / Not feasible) and
// its plain-English detail, both from lib/maintenance.windowView, and its row's Remove button (none on main).
// Shared by the Outages tab and the element card.

import { Trash } from "@phosphor-icons/react";

import type { WindowView } from "../lib/maintenance";
import { tint } from "../theme";

export const VerdictChip = ({ view }: { view: WindowView }) =>
  view.chip ? (
    <span className="chip" style={{ background: tint(view.chip.c, "22"), color: view.chip.c }}>
      {view.chip.label}
    </span>
  ) : null;

export const WindowDetail = ({ view }: { view: WindowView }) => (
  <span className="wlines" style={{ color: view.c }}>
    {view.lines.map((t, i) => (
      <span key={i} className={i ? "sub" : undefined}>{t}</span>
    ))}
  </span>
);

/** The window's Remove button; on main (read-only) an empty cell keeps the row's grid. */
export const RemoveWindow = ({ onMain, onRemove, size }: { onMain: boolean; onRemove: () => void; size?: number }) =>
  onMain ? (
    <span />
  ) : (
    <button className="icon-btn sm" style={size ? { width: size, height: size } : undefined} onClick={onRemove} title="Remove" aria-label="Remove window">
      <Trash size={12} />
    </button>
  );
