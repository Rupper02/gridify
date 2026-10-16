// Where the floating panels sit for a viewport (desktop and laptop; mobile is out of scope). Pure: components read the
// flags and offsets from here.

/** The header sits 10px from the top and is 48px tall (styles.css `.header`). */
const HEADER_BOTTOM = 58;

export interface Layout {
  /** vw >= 1180: the header names the profile and the map layers, not only their icons. */
  wide: boolean;
  /** vw < 1100: a narrow window. */
  narrow: boolean;
  /** vh < 760: the readings in a tighter grid (a laptop screen). */
  compactReadings: boolean;
  /** vh >= 560: the timeline dock shows. */
  showDock: boolean;
  dockPx: number;
  /** The header's bottom edge in px from the top of the map: labels under it are not drawn. */
  headerBottom: number;
  /** The side panel's width in px (clamp(320px, 30vw, 420px)), 0 when it is hidden. */
  sideW: number;
  /** Map padding so a fit frames the network between the floating panels. */
  pad: { top: number; bottom: number; left: number; right: number };
}

export function layoutFor(vw: number, vh: number, sideOpen: boolean): Layout {
  const narrow = vw < 1100;
  const showDock = vh >= 560;
  const dockPx = vh < 720 ? 132 : 164;
  const sideW = sideOpen ? Math.min(420, Math.max(320, vw * 0.3)) : 0;
  return {
    wide: vw >= 1180,
    narrow,
    compactReadings: vh < 760,
    showDock,
    dockPx,
    headerBottom: HEADER_BOTTOM,
    sideW,
    pad: {
      top: narrow ? 110 : 80,
      left: narrow ? 30 : 280,
      right: sideW + 70,
      bottom: showDock ? dockPx + 36 : 50,
    },
  };
}
