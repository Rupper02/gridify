import type { Change, Status, Tech } from "./types";

export interface StatusStyle {
  label: string;
  short: string;
  c: string;
  bg: string;
  fg: string;
  soft: string;
  bd: string;
}

export const ST: Record<Status, StatusStyle> = {
  Phase1: { label: "Phase 1 · 2030", short: "Phase 1", c: "#16a34a", bg: "#dcfce7", fg: "#166534", soft: "#f0fdf4", bd: "#bbf7d0" },
  Phase2: { label: "Phase 2 · 2035", short: "Phase 2", c: "#2563eb", bg: "#dbeafe", fg: "#1e40af", soft: "#eff6ff", bd: "#bfdbfe" },
  Deferred: { label: "Deferred", short: "Deferred", c: "#d97706", bg: "#fef3c7", fg: "#92400e", soft: "#fffbeb", bd: "#fde68a" },
  Rejected: { label: "Rejected", short: "Rejected", c: "#9ca3af", bg: "#e5e7eb", fg: "#4b5563", soft: "#f9fafb", bd: "#e5e7eb" },
};

export const ORDER: Record<Status, number> = { Phase1: 0, Phase2: 1, Deferred: 2, Rejected: 3 };

export const CHG: Record<Change, { label: string; bg: string; fg: string }> = {
  accelerated: { label: "Accelerated", bg: "#dcfce7", fg: "#166534" },
  slipped: { label: "Slipped", bg: "#fef3c7", fg: "#92400e" },
  moved_up: { label: "Moved up", bg: "#dbeafe", fg: "#1e40af" },
  moved_down: { label: "Moved down", bg: "#e5e7eb", fg: "#4b5563" },
  added: { label: "Added", bg: "#dbeafe", fg: "#1e40af" },
  dropped: { label: "Dropped", bg: "#e5e7eb", fg: "#4b5563" },
  unchanged: { label: "No change", bg: "#f3f4f6", fg: "#6b7280" },
};

export const TECH: Record<Tech, string> = { solar: "Solar PV", wind: "Wind", battery: "Battery" };
export const techLabel = (t: string | null | undefined): string | undefined =>
  t ? TECH[t as Tech] : undefined;

/** Readiness evidence a manual applicant can tick; weights sum with the 0.1 floor to 1.0. */
export const EVID = [
  { k: "land", label: "Land rights secured", w: 0.3 },
  { k: "planning", label: "Planning consent granted", w: 0.35 },
  { k: "finance", label: "Financing committed", w: 0.25 },
] as const;

export const BSTAT = {
  open: { label: "open", bg: "#e5e7eb", fg: "#4b5563" },
  merged: { label: "merged", bg: "#dcfce7", fg: "#166534" },
  discarded: { label: "discarded", bg: "#f3f4f6", fg: "#9ca3af" },
} as const;

export const fmtMw = (x: number | null | undefined): string =>
  x == null ? "—" : (Math.round(x * 10) / 10).toString();

/** Linear mix of two hex colours (t in 0..1). */
export const mix = (a: string, b: string, t: number): string => {
  const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const A = p(a);
  const B = p(b);
  return "#" + A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, "0")).join("");
};

export const signed = (x: number): string => `${x > 0 ? "+" : ""}${Math.round(x * 10) / 10}`;
export const signedV = (x: number): string => `${x > 0 ? "+" : ""}${x.toFixed(3)}`;
export const deltaColor = (x: number, moreIsGood: boolean): string =>
  x === 0 ? "#6b7280" : x > 0 === moreIsGood ? "#166534" : "#b91c1c";

export const STEP_MS = 280; // pacing of the run-overlay progress steps
export const ADDED_ID_BASE = 2056; // manual projects are numbered CR-2056, CR-2057, … (mirrors the API)
