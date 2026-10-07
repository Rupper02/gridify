// Where the floating panels sit for a viewport (desktop and laptop; mobile is out of scope). Pure,
// so the breakpoints are unit-tested; components read the flags and offsets from here.

/** The layer menu's fixed width (Flow / Loading / Voltage / Demand + the Deferred switch). */
const GAP = 10;
/** The header sits 10px from the top and is 48px tall (styles.css `.header`). */
const HEADER_BOTTOM = 58;

export interface Layout {
  /** Wide enough for the header to name the map layers, not only show their icons. */
  roomy: boolean;
  /** vw >= 1180: full header labels (Low / Standard / High, Diff, Merge, branch sub-line). */
  wide: boolean;
  /** vw < 1100: the left cards collapse into one pill. */
  narrow: boolean;
  /** vh >= 700: the readings card shows. */
  showReadings: boolean;
  /** vh < 760: the readings in a tighter two-row grid (a laptop screen). */
  compactReadings: boolean;
  /** vh >= 560: the roadmap dock shows. */
  showDock: boolean;
  dockPx: number;
  /** The header's bottom edge in px from the top of the map: labels under it are not drawn. */
  headerBottom: number;
  /** The left column's right edge in px (the result stamp and the readings), 0 when it is a pill: the run card centres right of it. */
  leftW: number;
  /** The side panel's width in px (clamp(320px, 30vw, 420px)), 0 when it is hidden. */
  sideW: number;
  /** Where the narrow detail card and the diff banner stop on the right: clear of the side panel. */
  cardRight: number;
  /** Map padding so a fit frames the network between the floating panels. */
  pad: { top: number; bottom: number; left: number; right: number };
}

/** The roadmap folded to its header line. */
export const FOLDED_DOCK_PX = 52;

export function layoutFor(vw: number, vh: number, sideOpen: boolean, dockFolded = false): Layout {
  const wide = vw >= 1180;
  const roomy = vw >= 1640; // the header has room to name the map layers
  const narrow = vw < 1100;
  const showDock = vh >= 560;
  const dockPx = dockFolded ? FOLDED_DOCK_PX : vh < 720 ? 132 : 164;
  const sideW = sideOpen ? Math.min(420, Math.max(320, vw * 0.3)) : 0;
  return {
    roomy,
    wide,
    narrow,
    showReadings: vh >= 700,
    compactReadings: vh < 760,
    showDock,
    dockPx,
    headerBottom: HEADER_BOTTOM,
    leftW: narrow ? 0 : 268,
    sideW,
    cardRight: sideOpen ? sideW + 2 * GAP : GAP,
    pad: {
      top: narrow ? 110 : 80,
      left: narrow ? 30 : 280,
      right: sideW + 70,
      bottom: showDock ? dockPx + 36 : 50,
    },
  };
}

/** The detail-card slot: a clicked element's card takes the left column's place (the readings step aside), top left
 * of the map and clear of the roadmap dock (one place for the project, element and region cards). A narrow window,
 * which has no left column, keeps it top right, left of the layer menu. */
export function cardSlot(layout: Layout, sideOpen: boolean, diffMode: boolean) {
  const reserve = layout.showDock ? layout.dockPx + 20 : 14;
  if (!layout.narrow) return { top: 68, left: 10, width: DOCKED_CARD_W, maxHeight: `calc(100% - ${68 + reserve}px)` };
  const top = diffMode ? 160 : 110;
  void sideOpen;
  return { top, right: layout.cardRight, width: 308, maxHeight: `calc(100% - ${top + reserve}px)` };
}

/** The docked card's width: the left column's, plus the room its forms need (the diff banner starts right of it). */
export const DOCKED_CARD_W = 258;
