// The plan's years along the bottom: per year, the connections that energise in it and how many limits it breaches;
// a column or the slider picks the year the map, the readings and the panels show. The slider never starts a run:
// every run solves all the years, and a year still solving says so.

import type { Planner } from "../hooks/usePlanner";
import type { Layout } from "../lib/layout";
import { C } from "../theme";
import { TechIcon } from "./ui";

export function Timeline({ planner, layout }: { planner: Planner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const years = derived.years;
  if (!years.length) return null;
  const i = Math.max(0, years.indexOf(s.year));
  const result = s.result;
  return (
    <div className="dock glass" style={{ right: layout.sideW ? layout.sideW + 20 : 10, height: layout.dockPx, ["--years" as string]: years.length }}>
      <div className="dock-main">
        <div className="dock-head">
          <b style={{ fontSize: 12.5 }}>Plan years</b>
          <span className="mute ellipsis" style={{ fontSize: 11 }}>
            demand grown to each year, the connections in service by then, both study cases
          </span>
        </div>
        <div className="years">
          {years.map((y) => {
            const yr = result?.years[String(y)];
            const n = yr?.violations.length ?? 0;
            const energising = s.connections.filter((c) => c.year === y);
            return (
              <button key={y} className={`ycol${y === s.year ? " on" : ""}${yr ? "" : " unsolved"}`} onClick={() => actions.setYear(y)}>
                {!yr && derived.running && <span className="solving">solving</span>}
                <span className="chips">
                  {energising.slice(0, 3).map((c) => (
                    <span key={c.request_id} className="ychip" style={{ borderColor: derived.hue, color: derived.hue, gap: 3 }} title={`${c.request_id} energises`}>
                      <TechIcon tech={c.technology} size={10} color={derived.hue} />
                      {c.rating_mw || c.import_mw}
                    </span>
                  ))}
                  {energising.length > 3 && <span className="ychip" style={{ borderColor: derived.hue, color: derived.hue }}>+{energising.length - 3}</span>}
                </span>
                <span className="band" style={{ background: !yr ? "transparent" : !yr.converged || n ? C.red : C.phase1, opacity: yr ? 0.8 : 0 }} />
                <span className="foot" style={{ flexDirection: "column", alignItems: "flex-start", gap: 1 }}>
                  <span style={{ color: yr && (n || !yr.converged) ? C.redInk : undefined }}>{yr ? (yr.converged ? (n ? `${n} breach${n === 1 ? "" : "es"}` : "holds") : "no solution") : "–"}</span>
                  <b>{y}</b>
                </span>
              </button>
            );
          })}
        </div>
        <div className="slider">
          <span className="track" style={{ background: C.mute }} />
          <span className="fill" style={{ width: `calc((100% - (100% - 27px) / ${years.length}) * ${i / Math.max(1, years.length - 1)})` }} />
          <input
            className="gf-range"
            type="range"
            min={0}
            max={years.length - 1}
            value={i}
            onChange={(e) => actions.setYear(years[Number(e.target.value)])}
            aria-label="Plan year"
          />
        </div>
      </div>
    </div>
  );
}
