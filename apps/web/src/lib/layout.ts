// Where the floating panels sit for a viewport (desktop and laptop; mobile is out of scope). Pure,
// so the breakpoints are unit-tested; components read the flags and offsets from here.

export interface Layout {
  /** vw >= 1180: full header labels (Low / Standard / High, Diff, Merge, branch sub-line). */
  wide: boolean;
  /** vw < 1100: the left cards collapse into one pill. */
  narrow: boolean;
  /** vh < 820: the Copilot draft grid collapses into a row of pills. */
  compactH: boolean;
  /** vh >= 760: the readings card shows. */
  showReadings: boolean;
  /** vh >= 560: the roadmap dock shows. */
  showDock: boolean;
  dockPx: number;
  /** The side panel's width in px (clamp(320px, 30vw, 420px)), 0 when it is hidden. */
  sideW: number;
  /** Map padding so a fit frames the network between the floating panels. */
  pad: { top: number; bottom: number; left: number; right: number };
}

export function layoutFor(vw: number, vh: number, sideOpen: boolean): Layout {
  const wide = vw >= 1180;
  const narrow = vw < 1100;
  const showDock = vh >= 560;
  const dockPx = vh < 720 ? 132 : 164;
  const sideW = sideOpen ? Math.min(420, Math.max(320, vw * 0.3)) : 0;
  return {
    wide,
    narrow,
    compactH: vh < 820,
    showReadings: vh >= 760,
    showDock,
    dockPx,
    sideW,
    pad: {
      top: narrow ? 110 : 80,
      left: narrow ? 30 : 280,
      right: sideW + 70,
      bottom: showDock ? dockPx + 36 : 50,
    },
  };
}
