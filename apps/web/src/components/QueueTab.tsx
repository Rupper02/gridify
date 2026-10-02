import type { PlannerSlice, WithPatch } from "../hooks/planner/slice";

import { filterSortQueue, sumMw } from "../lib/derive";
import { ST, fmtMw, techLabel } from "../theme";
import type { QueueItem, SortKey, Status } from "../types";
import { TechIcon } from "./TechIcon";

export type QueueTabPlanner = PlannerSlice<
  "filter" | "grouped" | "prevStatus" | "query" | "result" | "sel" | "sortDir" | "sortKey",
  "selectProject",
  "q" | "manualIds"
> &
  WithPatch;

const COLS: [SortKey, string, "flex-start" | "flex-end"][] = [
  ["rank", "#", "flex-start"],
  ["id", "Project", "flex-start"],
  ["mw", "MW", "flex-end"],
  ["ready", "Ready", "flex-start"],
  ["status", "Status", "flex-end"],
];
const GROUP_ORDER: Status[] = ["Phase1", "Phase2", "Deferred", "Rejected"];

export function QueueTab({ planner }: { planner: QueueTabPlanner }) {
  const { s, patch, actions, derived } = planner;
  const { q, manualIds } = derived;
  const sorted = filterSortQueue(q, s.filter, s.query, s.sortKey, s.sortDir);
  const groups = s.grouped
    ? GROUP_ORDER.map((st) => ({ key: st as string, st: st as Status | null, rows: sorted.filter((x) => x.status === st) })).filter((g) => g.rows.length)
    : [{ key: "all", st: null, rows: sorted }];
  const sortBy = (key: SortKey) =>
    patch((st) => ({ sortKey: key, sortDir: st.sortKey === key ? ((-st.sortDir) as 1 | -1) : key === "mw" || key === "ready" ? -1 : 1 }));

  return (
    <>
      <div className="queue-tools">
        <input className="field sm" value={s.query} onChange={(e) => patch({ query: e.target.value })} placeholder="Search ID, applicant, bus…" />
        <button className="btn sm" style={{ height: 30, fontSize: 12, fontWeight: 500, borderColor: s.grouped ? "var(--mute2)" : "var(--bd)", background: s.grouped ? "#f3f4f6" : "#fff" }} onClick={() => patch({ grouped: !s.grouped })}>
          Group by status
        </button>
      </div>
      <div className="queue-cols">
        {COLS.map(([key, label, justify]) => (
          <button key={key} style={{ justifyContent: justify, color: s.sortKey === key ? "var(--ink)" : "var(--mute)" }} onClick={() => sortBy(key)}>
            {label}
            <span style={{ color: "var(--ink)" }}>{s.sortKey === key ? (s.sortDir > 0 ? "↑" : "↓") : ""}</span>
          </button>
        ))}
      </div>
      {groups.map((g) => (
        <div key={g.key}>
          {g.st && (
            <div className="group-head" style={{ color: ST[g.st].fg }}>
              <span className="dot" style={{ background: ST[g.st].c }} />
              {ST[g.st].label}
              <span style={{ color: "var(--mute2)", fontWeight: 500, letterSpacing: 0 }}>{g.rows.length} · {fmtMw(sumMw(g.rows))} MW</span>
            </div>
          )}
          {g.rows.map((x) => (
            <Row key={x.request_id} x={x} selected={s.sel?.kind === "project" && s.sel.id === x.request_id} was={s.prevStatus[x.request_id]} manual={manualIds.has(x.request_id)} onClick={() => actions.selectProject(x.request_id)} />
          ))}
        </div>
      ))}
      {s.result && sorted.length === 0 && <div className="empty">No projects match this filter.</div>}
    </>
  );
}

function Row({ x, selected, was, manual, onClick }: { x: QueueItem; selected: boolean; was: Status | undefined; manual: boolean; onClick: () => void }) {
  const st = ST[x.status];
  const rk = x.reason?.kind ?? null;
  const reason = x.reason ? x.reason.why || x.reason.message : "";
  const action = x.reason?.action ?? "";
  const hasAction = !!(action && rk !== "phased");
  const ready = Math.round(x.readiness_score * 100);
  return (
    <div className="qrow" onClick={onClick} style={{ background: selected ? "#f3f4f6" : "#fff", boxShadow: selected ? "inset 3px 0 0 #111827" : "none" }}>
      <span className="rank">{x.rank ?? "—"}</span>
      <div style={{ minWidth: 0 }}>
        <div className="row" style={{ gap: 6 }}>
          <span className="id">{x.request_id}</span>
          {manual && <span className="new">NEW</span>}
          {was && was !== x.status && <span style={{ fontSize: 10.5, color: "var(--mute)" }}>was {ST[was].short}</span>}
        </div>
        <div className="ellipsis" style={{ fontSize: 12, color: "var(--ink2)" }}>{x.applicant || "—"}</div>
        <div className="meta"><TechIcon tech={x.technology} /><span>{techLabel(x.technology) ?? "Unknown tech"} · bus {x.bus_id ?? "—"}</span></div>
      </div>
      <span className="mw">{fmtMw(x.rating_mw)}</span>
      <div className="col" style={{ gap: 4, paddingTop: 2 }}>
        <span className="ready">{ready}%</span>
        <div className="bar"><div style={{ width: `${ready}%`, background: x.readiness_score >= 0.6 ? "#374151" : x.readiness_score >= 0.35 ? "#9ca3af" : "#d1d5db" }} /></div>
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <span className="chip" style={{ background: st.bg, color: st.fg }}>{st.short}</span>
      </div>
      {rk === "grid" && (
        <div className="strip grid">
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}><span className="tag" style={{ color: "#b45309" }}>BINDING</span><span style={{ color: "#92400e", fontWeight: 500 }}>{reason}</span></div>
          {hasAction && <div style={{ fontSize: 11.5, color: "#b45309" }}><b>→</b> {action}</div>}
        </div>
      )}
      {rk === "readiness" && (
        <div className="strip" style={{ flexDirection: "row", alignItems: "baseline", gap: 8, color: "#92400e" }}><span className="tag" style={{ color: "#b45309" }}>NOT READY</span>{reason}</div>
      )}
      {rk === "phased" && (
        <div className="strip" style={{ flexDirection: "row", alignItems: "baseline", gap: 8, color: "#1e40af" }}><span className="tag" style={{ color: "#2563eb" }}>HELD TO 2035</span>{reason}</div>
      )}
      {rk === "intake" && (
        <div className="strip" style={{ color: "var(--mute)" }}>
          <div><span className="tag" style={{ color: "var(--mute2)" }}>INTAKE</span>{reason}</div>
          {hasAction && <div style={{ fontSize: 11.5 }}><b>→</b> {action}</div>}
        </div>
      )}
    </div>
  );
}
