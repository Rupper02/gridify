// What the map shows, one kind of element at a time. A registry: each feature is a label, a group
// and an icon name; geo.ts and the HTML marker layers ask `shows(visible, key)` before drawing
// anything, so hiding a kind removes it from the map (and from clicks) everywhere at once.

export type FeatureKey =
  | "lines132"
  | "lines33"
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

export interface FeatureSpec {
  label: string;
  group: FeatureGroup;
  /** Off until the operator turns it on (or a layer that needs it does). */
  offByDefault?: boolean;
}

export const MAP_FEATURES: Record<FeatureKey, FeatureSpec> = {
  lines132: { label: "132 kV lines", group: "Network" },
  lines33: { label: "33 kV lines", group: "Network" },
  linesLow: { label: "Below 33 kV", group: "Network" },
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

/** Which line feature a circuit belongs to, by its voltage. */
export const lineFeature = (kv: number): FeatureKey => (kv >= 132 ? "lines132" : kv >= 33 ? "lines33" : "linesLow");

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

export function loadVisible(): FeatureKey[] {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE_KEY) ?? "null");
    const saved = Array.isArray(raw) ? FEATURE_KEYS.filter((k) => raw.includes(k)) : [];
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
