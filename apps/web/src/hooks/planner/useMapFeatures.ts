// What the map shows: the layer, and which kinds of element (lib/mapFeatures.ts). The choice of
// elements is remembered in this browser.

import { useCallback, useEffect } from "react";

import { DEFAULT_VISIBLE, type FeatureKey, onlyFeature, saveVisible, toggleFeature, withFeature } from "../../lib/mapFeatures";
import type { MapLayer } from "../../types";
import type { Core } from "./core";

export function useMapFeatures({ patch }: Core, visible: FeatureKey[]) {
  useEffect(() => saveVisible(visible), [visible]);

  /** Switch the colouring layer; the Demand layer brings its demand groups with it. */
  const setLayer = useCallback(
    (layer: MapLayer) => patch((st) => ({ layer, ...(layer === "demand" ? { visible: withFeature(st.visible, "demand") } : {}) })),
    [patch],
  );
  const toggleFeatureShown = useCallback((key: FeatureKey) => patch((st) => ({ visible: toggleFeature(st.visible, key) })), [patch]);
  const showOnly = useCallback((key: FeatureKey) => patch((st) => ({ visible: onlyFeature(st.visible, key) })), [patch]);
  const showAll = useCallback(() => patch({ visible: [...DEFAULT_VISIBLE] }), [patch]);
  const toggleShowMenu = useCallback(() => patch((st) => ({ showMenuOpen: !st.showMenuOpen })), [patch]);

  return { setLayer, toggleFeatureShown, showOnly, showAll, toggleShowMenu };
}
