// What the map shows, one kind of element at a time. A registry: each feature is a label, a group
// and an icon name; geo.ts and the HTML marker layers ask `shows(visible, key)` before drawing
// anything, so hiding a kind removes it from the map (and from clicks) everywhere at once.

export type FeatureKey =
  | "linesHigh"
  | "linesMid"
  | "linesLow"
  | "transformers"
  | "substations"
  | "buses"
  | "generation"
  | "projects"
  | "works"
  | "loads"
  | "demand";

export type FeatureGroup = "Network" | "Generation and plan" | "Customers";

// ---- the grid's own line voltages, in three tiers ----------------------------------------------------
/** The grid's line voltages ranked: its highest level, the next one, and whether any line runs lower still. */
export interface LineTiers {
  high: number | null;
  mid: number | null;
  low: boolean;
}
export type LineTier = "high" | "mid" | "low";

export const lineTiers = (kvs: number[]): LineTiers => {
  const levels = [...new Set(kvs)].sort((a, b) => b - a);
  return { high: levels[0] ?? null, mid: levels[1] ?? null, low: levels.length > 2 };
};
export const tierOf = (kv: number, t: LineTiers): LineTier =>
  t.high != null && kv >= t.high ? "high" : t.mid != null && kv >= t.mid ? "mid" : "low";

const kvText = (kv: number): string => `${+kv} kV`;

export interface FeatureSpec {
  label: string;
  group: FeatureGroup;
  /** Off until the operator turns it on (or a layer that needs it does). */
  offByDefault?: boolean;
  /** The label on this grid; null when the grid has none of it (the Show menu leaves it out). */
  forGrid?: (t: LineTiers) => string | null;
}

export const MAP_FEATURES: Record<FeatureKey, FeatureSpec> = {
  linesHigh: { label: "Highest-voltage lines", group: "Network", forGrid: (t) => (t.high == null ? null : `${kvText(t.high)} lines`) },
  linesMid: { label: "Next-voltage lines", group: "Network", forGrid: (t) => (t.mid == null ? null : `${kvText(t.mid)} lines`) },
  linesLow: { label: "Lower-voltage lines", group: "Network", forGrid: (t) => (t.low && t.mid != null ? `Below ${kvText(t.mid)}` : null) },
  transformers: { label: "Transformers", group: "Network" },
  substations: { label: "Substation names", group: "Network" },
  buses: { label: "Busbars", group: "Network" },
  generation: { label: "Generation today", group: "Generation and plan" },
  projects: { label: "Projects", group: "Generation and plan" },
  works: { label: "Planned works", group: "Generation and plan" },
  loads: { label: "Loads", group: "Customers" },
  demand: { label: "Demand groups", group: "Customers", offByDefault: true },
};

export const FEATURE_KEYS = Object.keys(MAP_FEATURES) as FeatureKey[];
export const FEATURE_GROUPS: FeatureGroup[] = ["Network", "Generation and plan", "Customers"];
export const DEFAULT_VISIBLE: FeatureKey[] = FEATURE_KEYS.filter((k) => !MAP_FEATURES[k].offByDefault);

export const shows = (visible: readonly FeatureKey[], key: FeatureKey): boolean => visible.includes(key);

const TIER_FEATURE: Record<LineTier, FeatureKey> = { high: "linesHigh", mid: "linesMid", low: "linesLow" };
/** Which line feature a circuit belongs to, by its voltage's tier on this grid. */
export const lineFeature = (kv: number, t: LineTiers): FeatureKey => TIER_FEATURE[tierOf(kv, t)];

/** A feature's label on this grid ("345 kV lines", "Below 33 kV"), or null when the grid has none of it. */
export const featureLabel = (k: FeatureKey, t: LineTiers): string | null => {
  const spec = MAP_FEATURES[k];
  return spec.forGrid ? spec.forGrid(t) : spec.label;
};

export const toggleFeature = (visible: readonly FeatureKey[], key: FeatureKey): FeatureKey[] =>
  visible.includes(key) ? visible.filter((k) => k !== key) : FEATURE_KEYS.filter((k) => k === key || visible.includes(k));

/** Focus on one kind: only it shows. Asking again for the one already alone brings the defaults back. */
export const onlyFeature = (visible: readonly FeatureKey[], key: FeatureKey): FeatureKey[] =>
  visible.length === 1 && visible[0] === key ? [...DEFAULT_VISIBLE] : [key];

/** Make sure a feature shows (a layer that needs it, e.g. the Demand layer and its groups). */
export const withFeature = (visible: readonly FeatureKey[], key: FeatureKey): FeatureKey[] =>
  visible.includes(key) ? [...visible] : toggleFeature(visible, key);

// ---- remembered per viewer (a convenience: losing it only resets to the defaults) ----------------
const STORE_KEY = "gridforge.mapFeatures";
/** Keys saved before the line features were tiers. */
const RENAMED: Record<string, FeatureKey> = { lines132: "linesHigh", lines33: "linesMid" };

export function loadVisible(): FeatureKey[] {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE_KEY) ?? "null");
    const keys = Array.isArray(raw) ? raw.map((k) => RENAMED[k] ?? k) : [];
    const saved = FEATURE_KEYS.filter((k) => keys.includes(k));
    // an empty map on opening looks broken, so a saved "nothing" starts from the defaults
    if (saved.length) return saved;
  } catch {
    /* private mode, blocked storage, bad JSON: the defaults */
  }
  return [...DEFAULT_VISIBLE];
}

export function saveVisible(visible: readonly FeatureKey[]): void {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(visible));
  } catch {
    /* not remembered: fine */
  }
}
