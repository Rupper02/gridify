// A planned window's verdict: the chip (Feasible / Curtailment / Demand at risk / Not feasible) and
// its plain-English detail, both from lib/maintenance.windowView. Shared by the Outages tab and the
// element card.

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
