// Design tokens the TypeScript side needs (colours on the map and in data-driven styles); the CSS
// side lives in styles.css under the same names. GridForge Glass: one interactive accent (arc
// cyan), planning-state colours, and a hue per branch.

import type { Change, Status, Tech } from "./types";

export const C = {
  night: "#0b111a",
  substation: "#152031",
  ambient: "#2b3d57",
  ink: "#eaf0f7",
  ink2: "#c9d6e8",
  ink3: "#dbe4ef",
  mute: "#9aa9bc",
  mute2: "#7d8da3",
  accent: "#7ce3ff",
  phase1: "#5ee6a8",
  phase2: "#8fb4ff",
  amber: "#ffc36b",
  amberInk: "#ffd99a",
  red: "#ff6b6b",
  redInk: "#ff9b9b",
  greenInk: "#8ef0c2",
  rejected: "#7d8da3",
  existing: "#2fbfa5",
  line132: "#dce6f2",
  line33: "#6f8ba8",
  lineLow: "#4f6680",
  dimmed: "#3d4f66",
} as const;

/** Append an alpha byte to a #rrggbb hue (tints: 1f backgrounds, 80 borders, 1c glow). */
export const tint = (hex: string, alpha: string): string => `${hex}${alpha}`;

export interface StatusStyle {
  label: string;
  long: string;
  c: string;
  ink: string;
}
/** Planning states. "Prelim" is a project added to the branch but not yet in a run. */
export const ST: Record<Status | "Prelim", StatusStyle> = {
  Phase1: { label: "Phase 1", long: "Phase 1 · by 2030", c: C.phase1, ink: C.greenInk },
  Phase2: { label: "Phase 2", long: "Phase 2 · 2031 to 2035", c: C.phase2, ink: "#b5ccff" },
  Deferred: { label: "Deferred", long: "Deferred", c: C.amber, ink: C.amberInk },
  Rejected: { label: "Rejected", long: "Rejected at intake", c: C.rejected, ink: C.mute },
  Prelim: { label: "Preliminary", long: "Preliminary · unranked", c: C.accent, ink: C.accent },
};

export const ORDER: Record<Status, number> = { Phase1: 0, Phase2: 1, Deferred: 2, Rejected: 3 };

export const CHG: Record<Change, { label: string; c: string }> = {
  accelerated: { label: "Accelerated", c: C.phase1 },
  slipped: { label: "Slipped", c: C.amber },
  moved_up: { label: "Moved up", c: C.phase2 },
  moved_down: { label: "Moved down", c: C.mute },
  added: { label: "Added", c: C.accent },
  dropped: { label: "Dropped", c: C.mute },
  unchanged: { label: "No change", c: C.mute2 },
};

// ---- technologies -------------------------------------------------------------------------------
export interface TechMeta {
  label: string;
  /** How the engine dispatches it in the two study cases (config.GENERATION_FACTORS). */
  treatment: string;
  /** It only draws power (demand, electrolyser): judged on its import, exports nothing. */
  importOnly: boolean;
  /** It draws power at winter peak (batteries charging), so the intake asks for its import. */
  imports: boolean;
}
export const TECH: Record<Tech, TechMeta> = {
  solar: { label: "Solar PV", treatment: "Nil at winter peak, full at summer min", importOnly: false, imports: false },
  wind: { label: "Onshore wind", treatment: "Nil at winter peak, full at summer min", importOnly: false, imports: false },
  battery: { label: "Battery", treatment: "Charging at winter peak, exporting at summer min", importOnly: false, imports: true },
  hybrid: { label: "Solar + battery", treatment: "PV nil and battery charging at winter peak", importOnly: false, imports: true },
  gas: { label: "Gas (CCGT / OCGT)", treatment: "Firm in both cases", importOnly: false, imports: false },
  gas_engine: { label: "Gas engines", treatment: "Firm in both cases", importOnly: false, imports: false },
  biomass: { label: "Biomass / EfW", treatment: "Firm in both cases", importOnly: false, imports: false },
  electrolyser: { label: "Hydrogen electrolyser", treatment: "Import at winter peak, half of it at summer min", importOnly: true, imports: true },
  demand: { label: "Demand connection", treatment: "Import at winter peak, half of it at summer min", importOnly: true, imports: true },
};
export const isTech = (t: string | null | undefined): t is Tech => !!t && t in TECH;
export const techLabel = (t: string | null | undefined): string => (isTech(t) ? TECH[t].label : t ? t : "Unknown");

/** Readiness evidence an applicant can show; the weights sum with the 0.1 floor to 1.0. */
export const EVID = [
  { k: "land", label: "Land rights", w: 0.3 },
  { k: "planning", label: "Planning consent", w: 0.35 },
  { k: "finance", label: "Financing", w: 0.25 },
] as const;
export const READINESS_FLOOR = 0.1;

// ---- demand profiles ----------------------------------------------------------------------------
/** The three demand profiles the engine offers (FES pathways), with their bar glyph. */
export const PROFILES: { id: string; label: string; short: string; bars: 1 | 2 | 3 }[] = [
  { id: "fb", label: "Low", short: "L", bars: 1 },
  { id: "ht", label: "Standard", short: "S", bars: 2 },
  { id: "ee", label: "High", short: "H", bars: 3 },
];
export const profileOf = (id: string | null | undefined) =>
  PROFILES.find((p) => p.id === id) ?? { id: id ?? "custom", label: "Custom", short: "C", bars: 2 as const };

// ---- branch hues --------------------------------------------------------------------------------
export const MAIN_HUE = "#c9d6e8";
/** Branch identity hues, in branch creation order (cyan and coral first, as specified). */
export const BRANCH_HUES = ["#7ce3ff", "#ff9f7a", "#c3a6ff", "#f2d06b"];

// ---- formatting ---------------------------------------------------------------------------------
export const fmtMw = (x: number | null | undefined): string =>
  x == null ? "–" : (Math.round(x * 10) / 10).toString();
export const signed = (x: number): string => `${x > 0 ? "+" : ""}${Math.round(x * 10) / 10}`;

/** Loading colour on the map and in readings. */
export const loadColor = (v: number | null | undefined): string =>
  v == null ? C.mute2 : v > 100 ? C.red : v > 90 ? C.amber : v > 70 ? "#e6d7a8" : v > 45 ? "#9fb3c9" : "#5d7591";
/** Bus voltage colour for the voltage layer (outside the band in red). */
export const voltColor = (v: number | null | undefined, lo: number, hi: number): string =>
  v == null ? C.mute2 : v < lo || v > hi ? C.red : v < lo + 0.02 ? C.phase2 : v > hi - 0.03 ? C.amber : C.ink2;

export const PLAN_YEARS = Array.from({ length: 10 }, (_, i) => 2026 + i);
export const ADDED_ID_BASE = 2056; // manual projects are numbered CR-2056, CR-2057, … (mirrors the API)
