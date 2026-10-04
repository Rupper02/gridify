// Queue: Preliminary, Phase 1, Phase 2, Deferred (and Rejected) groups. Each row: tech tile, id,
// "this branch", applicant, tech · bus, MW and when it energises; deferred rows show the binding
// reason. Below, the registry of not-yet-built projects to pull onto the branch.

import { Plus, WarningDiamond } from "@phosphor-icons/react";
import { useState } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { effYearOf, headlineMw, nameElements, projectLabel, queueGroups } from "../lib/derive";
import { C, ST, fmtMw, techLabel, tint } from "../theme";
import type { QueueItem, RegistryItem } from "../types";
import { TechTile } from "./ui";

export type QueueTabPlanner = PlannerSlice<
  "registry" | "registryLoaded" | "sel",
  "addRegistryProject" | "loadRegistry" | "selectProject",
  "branchOnly" | "caps" | "hue" | "ix" | "onMain" | "prelim" | "q"
>;

const isQ = (x: QueueItem | RegistryItem): x is QueueItem => "rank" in x;

export function QueueTab({ planner }: { planner: QueueTabPlanner }) {
  const { s, actions, derived } = planner;
  const groups = queueGroups(derived.q, derived.prelim);
  const [showReg, setShowReg] = useState(false);
  const [query, setQuery] = useState("");
  const inPlan = new Set([...derived.q.map((x) => x.request_id), ...derived.prelim.map((x) => x.request_id)]);
  const needle = query.toLowerCase();
  const reg = s.registry.filter(
    (r) => !inPlan.has(r.request_id) && (!needle || `${r.request_id} ${r.applicant} ${r.technology}`.toLowerCase().includes(needle)),
  );

  return (
    <div className="scroll" style={{ padding: "0 10px 14px", gap: 14 }}>
      {!groups.length && (
        <div className="empty" style={{ margin: "4px 4px 0" }}>
          <b>{derived.onMain ? "main has no queued projects" : "Nothing queued on this branch yet"}</b>
          <span>
            main is the network as it exists today. {derived.caps.registry ? "Pull projects from the registry below, or start" : "Start"} a New project in the Ask tab.
            {derived.caps.registry ? " Both land" : " It lands"} in Preliminary until the next run.
          </span>
        </div>
      )}
      {groups.map(({ g, rows }) => (
        <div key={g.key} className="qgroup">
          <div className="qhead">
            <span className="sw" style={{ background: g.dashed ? "transparent" : g.c, border: g.dashed ? `1.5px dashed ${g.c}` : "none" }} />
            <span style={{ fontSize: 12.5, fontWeight: 600, color: ST[g.key === "prelim" ? "Prelim" : g.key].ink }}>{g.title}</span>
            <span className="mono" style={{ fontSize: 11, color: C.mute }}>{g.meta}</span>
          </div>
          {rows.map((x) => {
            const st = ST[isQ(x) ? x.status : "Prelim"];
            const onBranch = derived.branchOnly.has(x.request_id);
            const isSel = s.sel?.kind === "project" && s.sel.id === x.request_id;
            const eff = isQ(x) ? effYearOf(x) : null;
            const when = !isQ(x) ? "unranked" : eff ? `energises ${eff}` : x.status === "Rejected" ? "rejected" : "no year";
            const mw = headlineMw(x);
            return (
              <button
                key={x.request_id}
                className="qrow"
                onClick={() => actions.selectProject(x.request_id)}
                style={{
                  background: onBranch ? tint(derived.hue, "0d") : undefined,
                  borderColor: isSel ? C.accent : onBranch ? tint(derived.hue, "40") : undefined,
                }}
              >
                <TechTile tech={x.technology} c={st.c} />
                <div style={{ minWidth: 0, display: "flex", flexDirection: "column", lineHeight: 1.3 }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span className="mono" style={{ fontSize: 12.5, fontWeight: 600 }}>{x.request_id}</span>
                    {onBranch && !derived.onMain && <span className="tag-branch">this branch</span>}
                  </span>
                  <span className="ellipsis" style={{ fontSize: 12, color: C.ink2 }}>{projectLabel(x)}</span>
                  <span style={{ fontSize: 11, color: C.mute }}>{techLabel(x.technology)} · bus {x.bus_id ?? "–"}</span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", lineHeight: 1.3 }}>
                  <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>{fmtMw(mw)} MW</span>
                  <span style={{ fontSize: 10.5, color: st.c }}>{when}</span>
                </div>
                {isQ(x) && (x.status === "Deferred" || x.status === "Rejected") && x.reason && (
                  <div className="why">
                    <WarningDiamond size={12} style={{ flex: "none" }} />
                    {nameElements(x.reason.short, derived.ix)}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      ))}

      {derived.caps.registry && (
      <div className="qgroup">
        <button
          className="btn"
          style={{ alignSelf: "flex-start" }}
          onClick={() => {
            setShowReg((v) => !v);
            void actions.loadRegistry();
          }}
          aria-expanded={showReg}
        >
          <Plus size={13} />
          {showReg ? "Hide the registry" : "Add from the registry"}
        </button>
        {showReg && (
          <>
            <span style={{ fontSize: 11.5, color: C.mute, lineHeight: 1.45, padding: "2px 2px 0" }}>
              Not-yet-built projects from NGED's Embedded Capacity Register and the TEC register. Optional: they count only once added to a
              branch{derived.onMain ? " (adding opens one off main)" : ""}.
            </span>
            <input className="search" placeholder="Search id, applicant or technology" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search the registry" />
            {!s.registryLoaded && <span className="mute" style={{ fontSize: 12 }}>Loading the registry…</span>}
            {s.registryLoaded && !reg.length && <span className="mute" style={{ fontSize: 12 }}>Every registry project is already on this branch.</span>}
            {reg.map((r) => (
              <div key={r.request_id} className="reg-row">
                <TechTile tech={r.technology} c={C.mute} />
                <div style={{ minWidth: 0, display: "flex", flexDirection: "column", lineHeight: 1.3 }}>
                  <span className="mono" style={{ fontSize: 12, fontWeight: 600 }}>{r.request_id}</span>
                  <span className="ellipsis" style={{ fontSize: 11.5, color: C.ink2 }}>{projectLabel(r)}</span>
                  <span style={{ fontSize: 10.5, color: C.mute }}>
                    {techLabel(r.technology)} · {fmtMw(headlineMw(r))} MW{r.commissioning_year ? ` · asks ${r.commissioning_year}` : ""}
                  </span>
                </div>
                <button className="btn" onClick={() => void actions.addRegistryProject(r.request_id)} disabled={r.status !== "valid"} title={r.status !== "valid" ? r.review_reasons : "Add to Preliminary"}>
                  <Plus size={12} />
                  Add
                </button>
              </div>
            ))}
          </>
        )}
      </div>
      )}
    </div>
  );
}
