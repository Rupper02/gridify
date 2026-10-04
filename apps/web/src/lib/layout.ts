// Where the floating panels sit for a viewport (desktop and laptop; mobile is out of scope). Pure,
// so the breakpoints are unit-tested; components read the flags and offsets from here.

/** The layer menu's fixed width (Flow / Loading / Voltage / Demand + the Deferred switch). */
export const LAYERS_W = 196;
const GAP = 10;

export interface Layout {
  /** vw >= 1180: full header labels (Low / Standard / High, Diff, Merge, branch sub-line). */
  wide: boolean;
  /** vw < 1100: the left cards collapse into one pill. */
  narrow: boolean;
  /** vh < 820: the maintenance draft grid collapses into a row of pills. */
  compactH: boolean;
  /** vh >= 760: the readings card shows. */
  showReadings: boolean;
  /** vh >= 560: the roadmap dock shows. */
  showDock: boolean;
  dockPx: number;
  /** The side panel's width in px (clamp(320px, 30vw, 420px)), 0 when it is hidden. */
  sideW: number;
  /** The layer menu, top right of the map (below the reopen button when the side panel is hidden). */
  layers: { top: number; right: number };
  /** Where the detail cards (project, element, region) and the diff banner stop: left of the layer menu. */
  cardRight: number;
  /** Map padding so a fit frames the network between the floating panels. */
  pad: { top: number; bottom: number; left: number; right: number };
}

export function layoutFor(vw: number, vh: number, sideOpen: boolean): Layout {
  const wide = vw >= 1180;
  const narrow = vw < 1100;
  const showDock = vh >= 560;
  const dockPx = vh < 720 ? 132 : 164;
  const sideW = sideOpen ? Math.min(420, Math.max(320, vw * 0.3)) : 0;
  const layers = { top: sideOpen ? 68 : 114, right: sideOpen ? sideW + 2 * GAP : GAP };
  return {
    wide,
    narrow,
    compactH: vh < 820,
    showReadings: vh >= 760,
    showDock,
    dockPx,
    sideW,
    layers,
    cardRight: layers.right + LAYERS_W + GAP,
    pad: {
      top: narrow ? 110 : 80,
      left: narrow ? 30 : 280,
      right: sideW + 70,
      bottom: showDock ? dockPx + 36 : 50,
    },
  };
}

/** The detail-card slot: top right of the map, left of the layer menu, clear of the roadmap dock
 * (one place for the project, element and region cards). */
export function cardSlot(layout: Layout, sideOpen: boolean, diffMode: boolean) {
  const top = diffMode ? (layout.narrow ? 160 : 118) : layout.narrow ? 110 : sideOpen ? 68 : 114;
  const reserve = layout.showDock ? layout.dockPx + 20 : 14;
  return { top, right: layout.cardRight, maxHeight: `calc(100% - ${top + reserve}px)` };
}
