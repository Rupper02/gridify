// The side panel: the branch's connections (and the registry to pull from), what limits the plan (this year's
// breaches, and every element that breaches with the year it starts), and the comparison with the parent branch.

import { ArrowRight, CalendarBlank, CaretRight, GitMerge, ListBullets, MagnifyingGlass, Plus, Scales, Trash, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import type { Planner } from "../hooks/usePlanner";
import { KIND_LABEL, busName, lineName, reasonSel, reasonText, trafoName } from "../lib/model";
import { C, signed, techLabel } from "../theme";
import type { Reason, Tab } from "../types";
import { RunsTab } from "./RunsTab";
import { DiffTile, TechTile } from "./ui";

const TABS: { id: Tab; label: string; Icon: typeof ListBullets }[] = [
  { id: "connections", label: "Connections", Icon: ListBullets },
  { id: "limits", label: "Limits", Icon: WarningCircle },
  { id: "compare", label: "Compare", Icon: Scales },
  { id: "runs", label: "Year runs", Icon: CalendarBlank },
];

export function SidePanel({ planner }: { planner: Planner }) {
  const { s, actions, derived } = planner;
  const badge: Record<Tab, string | null> = {
    connections: s.connections.length ? String(s.connections.length) : null,
    limits: derived.yr?.violations.length ? String(derived.yr.violations.length) : null,
    compare: null,
    runs: null,
  };
  return (
    <aside className={`side${s.sideOpen ? "" : " closed"}`}>
      <div className="tabs">
        {TABS.filter((t) => t.id !== "compare" || !derived.onMain).map(({ id, label, Icon }) => (
          <button key={id} className={s.tab === id ? "on" : ""} onClick={() => actions.setTab(id)}>
            <Icon size={14} /> {label}
            {badge[id] && <span className="badge">{badge[id]}</span>}
          </button>
        ))}
        <button className="hide" onClick={actions.toggleSide} title="Hide the panel (])">
          <CaretRight size={14} />
        </button>
      </div>
      <div className="tab-body">
        <div className="scroll" style={{ padding: "0 14px 14px", gap: 12 }}>
          {s.tab === "connections" && <ConnectionsTab planner={planner} />}
          {s.tab === "limits" && <LimitsTab planner={planner} />}
          {s.tab === "compare" && !derived.onMain && <CompareTab planner={planner} />}
          {s.tab === "runs" && <RunsTab planner={planner} />}
        </div>
      </div>
    </aside>
  );
}

// ---- connections ------------------------------------------------------------------------------------------
function ConnectionsTab({ planner }: { planner: Planner }) {
  const { s, actions, derived } = planner;
  const { ix } = derived;
  const [q, setQ] = useState("");
  const [showReg, setShowReg] = useState(false);
  useEffect(() => {
    if (showReg) void actions.loadRegistry();
  }, [showReg, actions]);
  const onBranch = new Set(s.connections.map((c) => c.request_id));
  const reg = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (s.registry ?? [])
      .filter((r) => !onBranch.has(r.request_id))
      .filter((r) => !needle || `${r.request_id} ${r.name} ${r.technology}`.toLowerCase().includes(needle))
      .slice(0, 60);
  }, [s.registry, q, onBranch]);
  const byYear = new Map<number, typeof s.connections>();
  s.connections.forEach((c) => byYear.set(c.year, [...(byYear.get(c.year) ?? []), c]));
  return (
    <>
      {s.connections.length === 0 ? (
        <div className="empty">
          <b>{derived.onMain ? "Main is the network as it exists today" : "No connections on this branch yet"}</b>
          <span>
            Click a busbar on the map to connect generation, storage or demand there and pick the year it energises, or pull a
            project from the registry below. {derived.onMain && "Main is read-only: the first change opens a branch."}
          </span>
        </div>
      ) : (
        [...byYear.entries()]
          .sort((a, b) => a[0] - b[0])
          .map(([year, cs]) => (
            <div key={year} className="qgroup">
              <div className="qhead">
                <b className="mono">{year}</b>
                <span className="mute" style={{ fontSize: 11 }}>{cs.reduce((a, c) => a + (c.rating_mw || c.import_mw || 0), 0).toFixed(0)} MW energise</span>
              </div>
              {cs.map((c) => (
                <div key={c.request_id} className="qrow" style={{ cursor: "pointer" }} onClick={() => actions.select({ kind: "connection", id: c.request_id })}>
                  <TechTile tech={c.technology} c={derived.hue} />
                  <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                    <b className="ellipsis" style={{ fontSize: 12.5 }}>{c.name || c.request_id}</b>
                    <span className="mute ellipsis" style={{ fontSize: 11 }}>
                      {c.request_id} · {techLabel(c.technology)} · {ix ? busName(ix, c.bus_id) : c.bus_id}
                    </span>
                  </span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span className="mono" style={{ fontSize: 12 }}>{c.rating_mw || c.import_mw} MW</span>
                    {!derived.onMain && (
                      <button className="icon-btn sm" title="Remove" onClick={(e) => (e.stopPropagation(), void actions.removeConnection(c.request_id))}>
                        <Trash size={12} />
                      </button>
                    )}
                  </span>
                </div>
              ))}
            </div>
          ))
      )}

      <button className="btn" onClick={() => setShowReg((x) => !x)}>
        <Plus size={13} /> {showReg ? "Hide the registry" : "Add from the registry"}
      </button>
      {showReg && (
        <>
          <span className="mute" style={{ fontSize: 11.5, lineHeight: 1.45 }}>
            Projects not built yet, as NGED publishes them (the Embedded Capacity Register and LTDS Table 5). Each comes in at its
            requested year; change it once it is on the branch.
          </span>
          <label className="search" style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <MagnifyingGlass size={13} />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name, id or technology" style={{ all: "unset", flex: 1 }} />
          </label>
          {!s.registry && <span className="mute">Loading the registry…</span>}
          {reg.map((r) => (
            <div key={r.request_id} className="reg-row">
              <TechTile tech={r.technology} c={C.mute} />
              <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                <b className="ellipsis" style={{ fontSize: 12 }}>{r.name}</b>
                <span className="mute ellipsis" style={{ fontSize: 11 }} title={r.note}>
                  {r.request_id} · {r.rating_mw ?? r.import_mw ?? "?"} MW · {r.year ?? "no year"}
                  {!r.complete && ` · ${r.review_reasons}`}
                </span>
              </span>
              <button
                className="btn"
                disabled={r.bus_id == null || r.year == null || !(r.rating_mw || r.import_mw)}
                title={r.bus_id == null ? "No bus in the model" : "Add to this branch"}
                onClick={() => void actions.addConnection({ from_registry: r.request_id })}
              >
                <Plus size={12} />
              </button>
            </div>
          ))}
        </>
      )}
    </>
  );
}

// ---- limits ---------------------------------------------------------------------------------------------------
function ReasonRow({ planner, r, extra }: { planner: Planner; r: Reason; extra?: string }) {
  const { actions, derived } = planner;
  const t = reasonText(r, derived.ix);
  const sel = reasonSel(r);
  return (
    <button className="qrow" onClick={() => sel && actions.select(sel)} disabled={!sel} style={{ gridTemplateColumns: "minmax(0, 1fr) auto" }}>
      <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
        <b className="ellipsis" style={{ fontSize: 12 }}>{t.title}</b>
        <span className="mute" style={{ fontSize: 11 }}>{t.figure}{t.when && ` · ${t.when}`}</span>
      </span>
      {extra && <span className="mono" style={{ fontSize: 11, color: C.redInk }}>{extra}</span>}
    </button>
  );
}

function LimitsTab({ planner }: { planner: Planner }) {
  const { s, actions, derived } = planner;
  const { yr, limits } = derived;
  if (!yr) return <div className="empty"><b>No result yet</b><span>Run the branch to see what limits it.</span></div>;
  const groups = new Map<string, Reason[]>();
  yr.violations.forEach((r) => groups.set(r.type, [...(groups.get(r.type) ?? []), r]));
  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <b style={{ fontSize: 13 }}>In {s.year}</b>
        <span className="mute" style={{ fontSize: 11.5, lineHeight: 1.45 }}>
          Every limit breached at winter peak (grown demand, winter ratings, solar and wind at nil, batteries charging) or at
          summer minimum (minimum demand, summer ratings, everything exporting).
        </span>
      </div>
      {!yr.converged && <div className="notice red">{yr.violations[0]?.type === "voltage_collapse"
        ? "No valid operating point this year: the solver's only solution is a voltage collapse, so no loading is shown. The network cannot carry the plan as it stands."
        : "The power flow has no solution this year: the network cannot carry the plan as it stands."}</div>}
      {yr.converged && yr.violations.length === 0 && <div className="notice" style={{ background: "rgba(94,230,168,0.08)", border: "1px solid rgba(94,230,168,0.35)", color: C.greenInk }}>Every limit holds in {s.year}.</div>}
      {[...groups.entries()].map(([type, rs]) => (
        <div key={type} className="qgroup">
          <div className="qhead">
            <span className="sw" style={{ background: C.red }} />
            <b style={{ fontSize: 12 }}>{KIND_LABEL[type] ?? type}</b>
            <span className="fcount">{rs.length}</span>
          </div>
          {rs.map((r, i) => <ReasonRow key={i} planner={planner} r={r} />)}
        </div>
      ))}

      <div className="menu-sep" />
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <b style={{ fontSize: 13 }}>Across the plan</b>
        <span className="mute" style={{ fontSize: 11.5, lineHeight: 1.45 }}>Every element that breaches in some year, from the first year it does. Pick one to see its figure year by year.</span>
      </div>
      {limits.length === 0 && <span className="mute">Nothing breaches in any solved year.</span>}
      {limits.map((l) => (
        <div key={l.key} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <ReasonRow planner={planner} r={l.reason} extra={`from ${l.first}`} />
          <span className="mute-2" style={{ fontSize: 10.5, paddingLeft: 10 }}>
            worst shown · breaches in {l.years.length} year{l.years.length === 1 ? "" : "s"}
            {" · "}
            <button className="btn ghost" style={{ height: "auto", padding: 0, fontSize: 10.5 }} onClick={() => actions.setYear(l.first)}>view {l.first}</button>
          </span>
        </div>
      ))}
    </>
  );
}

// ---- compare ------------------------------------------------------------------------------------------------
function CompareTab({ planner }: { planner: Planner }) {
  const { s, actions, derived } = planner;
  const { ix } = derived;
  const d = s.diff;
  const parent = derived.branch?.parent_id === "main" ? "main" : derived.branch?.parent_id ?? "main";
  const running = derived.running;
  const yd = d?.years[String(s.year)] ?? null;
  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <b style={{ fontSize: 13 }}>This branch against {parent}</b>
        <span className="mute" style={{ fontSize: 11.5, lineHeight: 1.45 }}>
          Both solved on this branch's demand profile, so every difference is the branch's connections. The map shows the change in
          loading for the year in view.
        </span>
      </div>
      {running && <span className="mute">Comparing once the run finishes…</span>}
      {s.diffError && (
        <div className="notice amber">
          Could not compare: {s.diffError}{" "}
          <button className="btn warn" onClick={() => void actions.loadDiff(s.activeBranch)}>Retry</button>
        </div>
      )}
      {!running && !d && !s.diffError && <span className="mute">Comparing…</span>}
      {d && (
        <>
          <div className="notice" style={{ border: "1px solid var(--hue-bd)", background: "var(--hue-bg)" }}>
            {d.headline.first_year_with_new_violations != null
              ? `New breaches in ${d.headline.years_with_new_violations} year${d.headline.years_with_new_violations === 1 ? "" : "s"}, from ${d.headline.first_year_with_new_violations}.`
              : "No new breaches in any year."}{" "}
            {d.headline.years_with_cleared_violations > 0 && `Clears breaches ${parent} has in ${d.headline.years_with_cleared_violations} year${d.headline.years_with_cleared_violations === 1 ? "" : "s"}.`}
          </div>
          <div className="year-pick">
            {derived.years.map((y) => {
              const x = d.years[String(y)];
              return (
                <button key={y} className={y === s.year ? "on" : ""} onClick={() => actions.setYear(y)} disabled={!x}>
                  {y}
                  {x?.new_violations.length ? <span className="flag" /> : null}
                </button>
              );
            })}
          </div>
          {yd && (
            <>
              <div className="tiles">
                <DiffTile label="Worst line" base={`${Math.round(yd.worst_line_base)}%`} head={`${Math.round(yd.worst_line_head)}%`} delta={signed(yd.worst_line_delta)} c={yd.worst_line_delta > 0 ? C.amber : C.phase1} />
                <DiffTile label="Worst transformer" base={`${Math.round(yd.worst_trafo_base)}%`} head={`${Math.round(yd.worst_trafo_head)}%`} delta={signed(yd.worst_trafo_delta)} c={yd.worst_trafo_delta > 0 ? C.amber : C.phase1} />
                <DiffTile label="GSP export (MW)" base={`${Math.round(yd.gsp_export_base)}`} head={`${Math.round(yd.gsp_export_head)}`} delta={signed(yd.gsp_export_delta)} c={C.ink2} />
                <DiffTile label="Breaches" base={`${yd.violations_base}`} head={`${yd.violations_head}`} delta={signed(yd.violations_head - yd.violations_base)} c={yd.violations_head > yd.violations_base ? C.red : C.phase1} />
              </div>
              {yd.energised_only_head.length > 0 && <span className="mute" style={{ fontSize: 11.5 }}>In service in {s.year} on this branch only: {yd.energised_only_head.join(", ")}</span>}
              {yd.new_violations.length > 0 && (
                <div className="qgroup">
                  <div className="qhead"><span className="sw" style={{ background: C.red }} /><b style={{ fontSize: 12 }}>New in {s.year}</b></div>
                  {yd.new_violations.map((r, i) => <ReasonRow key={i} planner={planner} r={r} />)}
                </div>
              )}
              {yd.cleared_violations.length > 0 && (
                <div className="qgroup">
                  <div className="qhead"><span className="sw" style={{ background: C.phase1 }} /><b style={{ fontSize: 12 }}>Cleared in {s.year}</b></div>
                  {yd.cleared_violations.map((r, i) => <ReasonRow key={i} planner={planner} r={r} />)}
                </div>
              )}
              {[...yd.top_line_deltas.map((x) => ({ ...x, kind: "line" as const })), ...yd.top_trafo_deltas.map((x) => ({ ...x, kind: "trafo" as const }))]
                .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
                .slice(0, 8)
                .map((m) => (
                  <button key={`${m.kind}${m.element_id}`} className="mover" onClick={() => actions.select({ kind: m.kind, id: m.element_id })} style={{ textAlign: "left", color: "inherit", font: "inherit" }}>
                    <span className="mono" style={{ fontSize: 11, color: m.delta > 0 ? C.amber : C.phase1 }}>{signed(m.delta)}%</span>
                    <span className="ellipsis" style={{ fontSize: 12 }}>{ix ? (m.kind === "line" ? lineName(ix, m.element_id) : trafoName(ix, m.element_id)) : m.element_id}</span>
                    <span className="mono mute" style={{ fontSize: 11 }}>
                      {Math.round(m.base_pct ?? 0)}% <ArrowRight size={9} /> {Math.round(m.head_pct ?? 0)}%
                    </span>
                  </button>
                ))}
            </>
          )}
        </>
      )}
      <div className="menu-sep" />
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn solid-hue grow" onClick={() => void actions.merge()} disabled={running}>
          <GitMerge size={14} /> Merge into {parent}
        </button>
        <button className="btn danger" onClick={() => void actions.discard()} disabled={running}>
          Discard
        </button>
      </div>
      <span className="mute-2" style={{ fontSize: 11 }}>Merging makes this branch's connections and demand profile {parent}'s.</span>
    </>
  );
}
