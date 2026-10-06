// Findings: everything the branch's last run found, and what the agents found (with the evidence behind it),
// grouped by criticality (breaches, warnings, notes), each by plan year, every group collapsible. A row jumps to the element, project or demand group
// on the map; the operator can acknowledge a finding so it leaves the open list.

import { ArrowCounterClockwise, Check, Receipt, Warning } from "@phosphor-icons/react";
import { useState } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { ZOOM_ELEMENT, ZOOM_REGION, nameElements } from "../lib/derive";
import { SEVERITY, findingSel, findingTitle, findingsBySeverity } from "../lib/gate";
import { C } from "../theme";
import type { Finding, FindingSeverity, FindingStatus } from "../types";

export type FindingsTabPlanner = PlannerSlice<
  "findings" | "model" | "outages" | "running",
  "focusSel" | "openEvidence" | "setFindingStatus" | "setLayer" | "setYear",
  "branch" | "ix" | "onMain" | "openFindings" | "stale"
>;

const FILTERS: { key: FindingStatus; label: string }[] = [
  { key: "open", label: "Open" },
  { key: "acknowledged", label: "Acknowledged" },
  { key: "resolved", label: "Resolved" },
];

export function FindingsTab({ planner }: { planner: FindingsTabPlanner }) {
  const { s, actions, derived } = planner;
  const [filter, setFilter] = useState<FindingStatus>("open");
  const counts = derived.openFindings;
  const shown = s.findings.filter((f) => f.status === filter);
  const groups = findingsBySeverity(shown);
  const where = derived.onMain ? "main" : derived.branch?.name;

  const open = (f: Finding) => {
    if (f.year != null) actions.setYear(f.year);
    const sel = findingSel(f, s.model, s.outages);
    if (!sel) return;
    if (sel.kind === "region") actions.setLayer("demand");
    actions.focusSel(sel, sel.kind === "region" ? ZOOM_REGION : ZOOM_ELEMENT);
  };

  return (
    <div className="scroll" style={{ padding: "4px 14px 16px", gap: 10 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Findings on {where}</span>
        <span style={{ fontSize: 12, color: C.mute, lineHeight: 1.45 }}>
          What the last run found, year by year: overloads, voltages outside the band, the GSP against its limit, N-1, customer
          alerts, planned works and the projects it holds back. Every figure is the engine's; click a row to see it on the map.
        </span>
        <span className="mono" style={{ fontSize: 11.5, color: C.mute }}>
          {counts.open === 0 ? "nothing open" : (
            <>
              {counts.breach > 0 && <span style={{ color: C.red }}>{counts.breach} breach{counts.breach !== 1 ? "es" : ""}</span>}
              {counts.breach > 0 && counts.warn > 0 && " · "}
              {counts.warn > 0 && <span style={{ color: C.amber }}>{counts.warn} warning{counts.warn !== 1 ? "s" : ""}</span>}
              {counts.open - counts.breach - counts.warn > 0 && ` · ${counts.open - counts.breach - counts.warn} notes`}
            </>
          )}
        </span>
      </div>
      {derived.stale.stale && !s.running && <div className="notice amber">The result is out of date; these findings are from its last run.</div>}
      <div className="filter-chips" role="tablist" aria-label="Finding status">
        {FILTERS.map((f) => (
          <button key={f.key} role="tab" aria-selected={filter === f.key} className={filter === f.key ? "on" : ""} onClick={() => setFilter(f.key)}>
            {f.label}
          </button>
        ))}
      </div>
      {!groups.length && (
        <div className="empty">
          <Warning size={20} color={C.mute} />
          <b>{filter === "open" ? "No open findings" : `Nothing ${filter}`}</b>
          <span>{s.findings.length ? "Switch the filter to see the rest." : "Run the plan to fill the ledger."}</span>
        </div>
      )}
      {groups.map((g) => {
        const sev = SEVERITY[g.severity];
        return (
          // keyed by the filter too, so each filter opens with its own defaults
          <details key={`${filter}:${g.severity}`} className="fsev" open={g.severity !== "info"}>
            <summary>
              <span className="sev-dot" style={{ background: sev.c }} />
              <b>{SEVERITY_TITLE[g.severity]}</b>
              <span className="mono fcount">{g.count}</span>
              <span className="mono fyears">{yearSpan(g.years.map((y) => y.year))}</span>
            </summary>
            {g.years.map((y) => (
              <details key={y.year ?? "plan"} className="ygroup" open>
                <summary className="ygroup-head mono">
                  {y.year ?? "Plan-wide"} <span className="fcount">{y.rows.length}</span>
                </summary>
                {y.rows.map((f) => (
                  <FindingRow
                    key={f.finding_id}
                    f={f}
                    ix={derived.ix}
                    onOpen={() => open(f)}
                    onStatus={(st) => void actions.setFindingStatus(f.finding_id, st)}
                    onEvidence={f.evidence_kind === "tool_call" ? () => void actions.openEvidence(f.evidence_ref) : undefined}
                  />
                ))}
              </details>
            ))}
          </details>
        );
      })}
    </div>
  );
}

const SEVERITY_TITLE: Record<FindingSeverity, string> = { breach: "Breaches", warn: "Warnings", info: "Notes" };

/** The years a criticality spans, for its header: "2026–2035", "2030", or "plan-wide". */
function yearSpan(years: (number | null)[]): string {
  const ys = years.filter((y): y is number => y != null);
  if (!ys.length) return "plan-wide";
  const lo = Math.min(...ys);
  const hi = Math.max(...ys);
  return lo === hi ? String(lo) : `${lo}–${hi}`;
}

function FindingRow({ f, ix, onOpen, onStatus, onEvidence }: { f: Finding; ix: FindingsTabPlanner["derived"]["ix"]; onOpen: () => void; onStatus: (st: FindingStatus) => void; onEvidence?: () => void }) {
  const sev = SEVERITY[f.severity] ?? SEVERITY.info;
  const next: { st: FindingStatus; label: string; icon: typeof Check } | null =
    f.status === "open" ? { st: "acknowledged", label: "Acknowledge", icon: Check } : f.status === "acknowledged" ? { st: "open", label: "Reopen", icon: ArrowCounterClockwise } : null;
  return (
    <div className="frow">
      <span className="sev-dot" style={{ background: sev.c }} title={sev.label} />
      <button className="frow-main" onClick={onOpen} title="Show on the map">
        <span className="ellipsis" style={{ fontSize: 12.5, fontWeight: 600 }}>{findingTitle(f)}</span>
        {f.source !== "engine" && <span className="chip" style={{ background: "rgba(255,255,255,0.08)", color: C.mute }}>{f.source}</span>}
      </button>
      {next ? (
        <button className="icon-btn sm" style={{ width: 24, height: 24 }} onClick={() => onStatus(next.st)} title={next.label} aria-label={next.label}>
          <next.icon size={12} />
        </button>
      ) : (
        <span />
      )}
      <span className="fmsg">
        {nameElements(f.message, ix)}
        {onEvidence && (
          <button className="tchip link" data-status="done" style={{ marginLeft: 6, verticalAlign: 1 }} onClick={onEvidence} title="The study behind this finding">
            <Receipt size={10} />
            evidence
          </button>
        )}
      </span>
    </div>
  );
}
