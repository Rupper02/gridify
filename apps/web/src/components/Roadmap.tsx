// The roadmap dock: ten year columns (project and maintenance chips, the phase band, cumulative MW),
// a year slider under them, and the Unscheduled column of deferred projects. Moving the slider only
// switches between the stored years of the last run; it never starts a run.

import type { PlannerSlice } from "../hooks/planner/slice";
import { byStatus, elementInfo, lensFor, outageSel, roadmapYears, sumMw } from "../lib/derive";
import type { Layout } from "../lib/layout";
import { VERDICTS, WORK_UI, outageChipTag, verdictColor } from "../lib/maintenance";
import { C, PLAN_YEARS, ST, tint } from "../theme";
import { TechIcon } from "./ui";

export type RoadmapPlanner = PlannerSlice<
  "outages" | "result" | "sel" | "solving" | "year",
  "selectProject" | "setYear",
  "branchOnly" | "hue" | "ix" | "prelim" | "q" | "yr"
>;

export function Roadmap({ planner, layout }: { planner: RoadmapPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const { q, prelim, branchOnly, hue, ix, yr } = derived;
  const shortName = (o: (typeof s.outages)[number]) =>
    `${outageChipTag(o)} ${ix ? (elementInfo(outageSel(o), ix, null, o.year)?.short ?? o.element_id) : o.element_id}`;
  const years = roadmapYears(s.result, prelim, s.outages, branchOnly, shortName);
  const p1 = byStatus(q, "Phase1");
  const p2 = byStatus(q, "Phase2");
  const df = byStatus(q, "Deferred");
  const lens = lensFor(s.year);
  const pos = (s.year - PLAN_YEARS[0]) / (PLAN_YEARS.length - 1);

  return (
    <div className="dock glass" style={{ right: layout.sideW + 20, height: layout.dockPx }}>
      <div className="dock-main">
        <div className="dock-head">
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>Connection roadmap</span>
          <span className="ellipsis" style={{ fontSize: 11.5, color: C.mute, minWidth: 0 }}>
            {s.result ? `${sumMw(p1)} MW by 2030 · ${Math.round((sumMw(p1) + sumMw(p2)) * 10) / 10} MW by 2035 · ${df.length} deferred` : "no run yet"}
          </span>
          <span style={{ marginLeft: "auto", display: "flex", alignItems: "baseline", gap: 7, flex: "none" }}>
            {layout.wide && <span style={{ fontSize: 10.5, color: C.mute2 }}>{s.solving ? "solving years…" : s.result ? "all years solved" : ""}</span>}
            <b className="mono" style={{ fontSize: 15, fontWeight: 700 }}>{s.year}</b>
            <span style={{ fontSize: 11, fontWeight: 600, color: lens.c }}>{lens.label}</span>
          </span>
        </div>
        <div className="years">
          {years.map((y) => {
            const on = y.y === s.year;
            return (
              <button
                key={y.y}
                className={`ycol${on ? " on" : ""}${s.result && !y.solved ? " unsolved" : ""}`}
                onClick={() => actions.setYear(y.y)}
                aria-label={`Show ${y.y}`}
                aria-pressed={on}
              >
                {s.result && !y.solved && s.solving && <span className="solving">solving</span>}
                <div className="chips">
                  {y.chips.map((c, i) => {
                    if (c.kind === "outage") {
                      const vc = verdictColor(c.verdict);
                      const tag = WORK_UI[c.work ?? "maintenance"].label;
                      return (
                        <span
                          key={`o${i}-${c.id}`}
                          className="ychip works"
                          title={`${tag}${c.verdict ? ` · ${VERDICTS[c.verdict].label}` : " · not studied yet"}`}
                          style={{ color: vc ?? C.ink2, background: vc ? tint(vc, "14") : "rgba(201,214,232,0.08)", borderColor: vc ?? "rgba(201,214,232,0.45)", borderStyle: vc ? "solid" : "dashed" }}
                        >
                          {c.id}
                        </span>
                      );
                    }
                    const st = ST[c.status ?? "Phase1"];
                    const pre = c.kind === "prelim";
                    return (
                      <span
                        key={c.id}
                        className="ychip"
                        role="link"
                        onClick={(e) => {
                          e.stopPropagation();
                          actions.selectProject(c.id);
                        }}
                        style={{
                          color: st.c,
                          background: pre ? "transparent" : tint(st.c, "1f"),
                          borderColor: c.branchOnly ? hue : pre ? st.c : tint(st.c, "55"),
                          borderStyle: pre ? "dashed" : "solid",
                          boxShadow: s.sel?.kind === "project" && s.sel.id === c.id ? `0 0 0 2px ${tint(C.accent, "66")}` : undefined,
                        }}
                      >
                        {layout.wide ? c.id : c.id.replace(/^[A-Z]+-/, "")}
                      </span>
                    );
                  })}
                </div>
                <span className="band" style={{ background: y.band }} />
                <span className="foot">
                  <b style={{ color: on ? C.ink : C.mute }}>{y.y}</b>
                  {layout.wide && <span>{y.mw ? `${y.mw} MW` : ""}</span>}
                </span>
              </button>
            );
          })}
        </div>
        <div className="slider">
          <div className="track" />
          <div className="fill" style={{ width: `calc((100% - (100% - 27px) / 10) * ${pos})` }} />
          <input
            className="gf-range"
            type="range"
            min={PLAN_YEARS[0]}
            max={PLAN_YEARS[PLAN_YEARS.length - 1]}
            step={1}
            value={s.year}
            onChange={(e) => actions.setYear(+e.target.value)}
            aria-label="Study year"
            aria-valuetext={`${s.year}${yr && yr.year !== s.year ? `, showing ${yr.year} until solved` : ""}`}
          />
        </div>
      </div>
      <div className="unsched">
        <span style={{ fontSize: 12, fontWeight: 600, color: C.amberInk }}>Unscheduled</span>
        <span style={{ fontSize: 11, color: C.mute }}>{df.length ? "Deferred by a named constraint" : "Nothing deferred"}</span>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 2, overflow: "auto" }}>
          {df.map((x) => (
            <button key={x.request_id} className="dchip" onClick={() => actions.selectProject(x.request_id)} title={x.reason?.short ?? "Deferred"}>
              <TechIcon tech={x.technology} size={10} />
              {x.request_id}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
