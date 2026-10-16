// Design tokens the TypeScript side needs (colours on the map and in data-driven styles); the CSS
// side lives in styles.css under the same names. GridForge Glass: one interactive accent (arc
// cyan), the limit colours, and a hue per branch.

import type { Tech } from "./types";

export const C = {
  night: "#0b111a",
  substation: "#152031",
  ink: "#eaf0f7",
  ink2: "#c9d6e8",
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
  existing: "#2fbfa5",
  // the grid's line voltage tiers (lib/mapFeatures.lineTiers): its highest level, the next, and the rest
  lineHigh: "#dce6f2",
  lineMid: "#6f8ba8",
  lineLow: "#4f6680",
  dimmed: "#3d4f66",
} as const;

/** Append an alpha byte to a #rrggbb hue (tints: 1f backgrounds, 80 borders, 1c glow). */
export const tint = (hex: string, alpha: string): string => `${hex}${alpha}`;

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
// `treatment` restates the engine's dispatch per study case (config.GENERATION_FACTORS, GENERATION_FACTOR_DEFAULT for the
// firm kinds, DEMAND_PROJECT_MIN_FACTOR): a mirror for the legend; change both together.
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
  // a unit whose fuel the source does not name (the engine's "other"): dispatched as firm
  other: { label: "Other generation", treatment: "Firm in both cases", importOnly: false, imports: false },
};
export const isTech = (t: string | null | undefined): t is Tech => !!t && t in TECH;
export const techLabel = (t: string | null | undefined): string => (isTech(t) ? TECH[t].label : t ? t : "Unknown");

// ---- demand profiles ----------------------------------------------------------------------------
/** The three demand profiles the picker offers, with their bar glyph. The ids are the engine's FORECASTS pathways and the
 * labels mirror config.FORECASTS[*].short (served on /forecasts): change both together. */
export interface Profile {
  id: string;
  label: string;
  short: string;
  bars: 1 | 2 | 3;
}
export const PROFILES: Profile[] = [
  { id: "fb", label: "Low", short: "L", bars: 1 },
  { id: "ht", label: "Standard", short: "S", bars: 2 },
  { id: "ee", label: "High", short: "H", bars: 3 },
];
/** The profile an id names; null for an empty or unknown id (nothing is known yet, so nothing is claimed). */
export const profileOf = (id: string | null | undefined): Profile | null => PROFILES.find((p) => p.id === id) ?? null;
/** A profile's label, or the id itself when the picker has no name for it. */
export const profileLabel = (id: string | null | undefined): string => profileOf(id)?.label ?? (id || "unknown");

// ---- branch hues --------------------------------------------------------------------------------
export const MAIN_HUE = "#c9d6e8";
/** Branch identity hues, in branch creation order (cyan and coral first, as specified). */
export const BRANCH_HUES = ["#7ce3ff", "#ff9f7a", "#c3a6ff", "#f2d06b"];

// ---- formatting ---------------------------------------------------------------------------------
export const signed = (x: number): string => `${x > 0 ? "+" : ""}${Math.round(x * 10) / 10}`;

/** Loading colour on the map and in readings. */
export const loadColor = (v: number | null | undefined): string =>
  v == null ? C.mute2 : v > 100 ? C.red : v > 90 ? C.amber : v > 70 ? "#e6d7a8" : v > 45 ? "#9fb3c9" : "#5d7591";
/** Bus voltage colour for the voltage layer (outside the band in red). */
export const voltColor = (v: number | null | undefined, lo: number, hi: number): string =>
  v == null ? C.mute2 : v < lo || v > hi ? C.red : v < lo + 0.02 ? C.phase2 : v > hi - 0.03 ? C.amber : C.ink2;


/** A study case as the planner names it; a case it does not know passes through. */
export const CASE_LABEL: Record<string, string> = { summer_min: "summer min", winter_peak: "winter peak" };
export const caseLabel = (c: string | null | undefined): string => CASE_LABEL[c ?? ""] ?? (c || "studied");
