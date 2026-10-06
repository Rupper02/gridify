// Findings: everything the branch's last run found, and what the agents found (with the evidence behind it), by
// criticality (breaches, warnings, notes) and then by kind, every finding once across the plan years it holds in
// (lib/findings.ts folds the ledger's one-row-per-year): a row shows the span and the worst year's figure and opens to
// its per-year rows, each still its own finding to acknowledge or trace. A row jumps to the element, project or
// demand group on the map in that year. Every group is collapsed until clicked: the headings are the overview.

import { ArrowCounterClockwise, CaretDown, CaretRight, Check, Receipt, Warning } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { ZOOM_ELEMENT, ZOOM_REGION, nameElements } from "../lib/derive";
import { type FindingGroup, type FindingSection, figureText, sectionCounts, yearSpan } from "../lib/findings";
import { SEVERITY, findingSel } from "../lib/gate";
import { C } from "../theme";
import type { Finding, FindingSeverity, FindingStatus } from "../types";

export type FindingsTabPlanner = PlannerSlice<
  "findings" | "findingsFocus" | "model" | "outages" | "running",
  "clearFindingsFocus" | "focusSel" | "openEvidence" | "setFindingStatus" | "setLayer" | "setYear",
  "branch" | "findingSections" | "ix" | "onMain" | "stale"
>;

const FILTERS: { key: FindingStatus; label: string }[] = [
  { key: "open", label: "Open" },
  { key: "acknowledged", label: "Acknowledged" },
  { key: "resolved", label: "Resolved" },
];

const SEVERITY_TITLE: Record<FindingSeverity, string> = { breach: "Breaches", warn: "Warnings", info: "Notes" };

/** The operator's next call on a finding in a status (none once resolved). */
const NEXT: Record<FindingStatus, { st: FindingStatus; label: string; icon: typeof Check } | null> = {
  open: { st: "acknowledged", label: "Acknowledge", icon: Check },
  acknowledged: { st: "open", label: "Reopen", icon: ArrowCounterClockwise },
  resolved: null,
};

// the keys of the collapsible levels (a group's key is its own)
const sevKey = (sev: FindingSeverity) => `sev:${sev}`;
const kindKey = (sev: FindingSeverity, title: string) => `kind:${sev}:${title}`;

export function FindingsTab({ planner }: { planner: FindingsTabPlanner }) {
  const { s, actions, derived } = planner;
  const [filter, setFilter] = useState<FindingStatus>("open");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const sections = derived.findingSections[filter];
  const counts = sectionCounts(derived.findingSections.open);
  const where = derived.onMain ? "main" : derived.branch?.name;
  // the engine names elements by index: name every message once per ledger, not per row per render
  const named = useMemo(() => new Map(s.findings.map((f) => [f.finding_id, nameElements(f.message, derived.ix)])), [s.findings, derived.ix]);
  const firstN1 = sections.flatMap((sec) => sec.kinds).find((k) => k.kind === "n1");
  const n1Ref = useRef<HTMLDetailsElement | null>(null);

  const toggle = (key: string, on: boolean) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });

  // another card sent the operator here (the readings' N-1 stat): expand that kind's groups among the open findings,
  // scroll to the first, then forget the focus so the tab is the operator's again
  useEffect(() => {
    const focus = s.findingsFocus;
    if (!focus) return;
    const keys: string[] = [];
    derived.findingSections.open.forEach((sec) =>
      sec.kinds.filter((k) => k.kind === focus).forEach((k) => keys.push(sevKey(sec.severity), kindKey(sec.severity, k.title))),
    );
    setFilter("open");
    setExpanded((prev) => new Set([...prev, ...keys]));
    actions.clearFindingsFocus();
    requestAnimationFrame(() => n1Ref.current?.scrollIntoView({ block: "start", behavior: "smooth" }));
  }, [actions, derived.findingSections, s.findingsFocus]);

  const open = (f: Finding) => {
    if (f.year != null) actions.setYear(f.year);
    const sel = findingSel(f, s.model, s.outages);
    if (!sel) return;
    if (sel.kind === "region") actions.setLayer("demand");
    actions.focusSel(sel, sel.kind === "region" ? ZOOM_REGION : ZOOM_ELEMENT);
  };
  const evidenceFor = (f: Finding) => (f.evidence_kind === "tool_call" ? () => void actions.openEvidence(f.evidence_ref) : undefined);

  return (
    <div className="scroll" style={{ padding: "4px 14px 16px", gap: 10 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Findings on {where}</span>
        <span style={{ fontSize: 12, color: C.mute, lineHeight: 1.45 }}>
          What the last run found: overloads, voltages outside the band, the GSP against its limit, N-1, customer alerts,
          planned works and the projects it holds back. Each finding is counted once across the plan years it holds in; open
          it for the years. Every figure is the engine's; click a row to see it on the map.
        </span>
        <span className="mono" style={{ fontSize: 11.5, color: C.mute }} title={counts.rows ? `${counts.rows} ledger rows, one per plan year` : undefined}>
          {counts.groups === 0 ? "nothing open" : (
            <>
              {counts.breach > 0 && <span style={{ color: C.red }}>{counts.breach} breach{counts.breach !== 1 ? "es" : ""}</span>}
              {counts.breach > 0 && counts.warn > 0 && " · "}
              {counts.warn > 0 && <span style={{ color: C.amber }}>{counts.warn} warning{counts.warn !== 1 ? "s" : ""}</span>}
              {counts.info > 0 && ` · ${counts.info} note${counts.info !== 1 ? "s" : ""}`}
            </>
          )}
        </span>
      </div>
      {derived.stale.stale && !s.running && <div className="notice amber">The result is out of date; these findings are from its last run.</div>}
      <div className="filter-chips" role="tablist" aria-label="Finding status">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            role="tab"
            aria-selected={filter === f.key}
            className={filter === f.key ? "on" : ""}
            onClick={() => {
              setFilter(f.key);
              setExpanded(new Set()); // a switch starts closed
            }}
          >
            {f.label}
          </button>
        ))}
      </div>
      {!sections.length && (
        <div className="empty">
          <Warning size={20} color={C.mute} />
          <b>{filter === "open" ? "No open findings" : `Nothing ${filter}`}</b>
          <span>{s.findings.length ? "Switch the filter to see the rest." : "Run the plan to fill the ledger."}</span>
        </div>
      )}
      {sections.map((sec) => (
        <Section key={sec.severity} sec={sec} expanded={expanded} toggle={toggle} firstN1={firstN1} n1Ref={n1Ref}>
          {(g) => (
            <GroupRow
              key={g.key}
              g={g}
              expanded={expanded.has(g.key)}
              onToggle={(on) => toggle(g.key, on)}
              named={named}
              onOpen={open}
              onStatus={(id, st) => void actions.setFindingStatus(id, st)}
              evidenceFor={evidenceFor}
            />
          )}
        </Section>
      ))}
    </div>
  );
}

/** A criticality: its heading (count of findings, the years they span), then a collapsible group per kind. */
function Section({
  sec, expanded, toggle, firstN1, n1Ref, children,
}: {
  sec: FindingSection;
  expanded: Set<string>;
  toggle: (key: string, on: boolean) => void;
  firstN1: FindingSection["kinds"][number] | undefined;
  n1Ref: React.RefObject<HTMLDetailsElement | null>;
  children: (g: FindingGroup) => React.ReactNode;
}) {
  const sev = SEVERITY[sec.severity];
  const key = sevKey(sec.severity);
  return (
    <details className="fsev" open={expanded.has(key)} onToggle={(e) => toggle(key, e.currentTarget.open)}>
      <summary>
        <span className="sev-dot" style={{ background: sev.c }} />
        <b>{SEVERITY_TITLE[sec.severity]}</b>
        <span className="mono fcount">{sec.groups.length}</span>
        <span className="mono fyears">{yearSpan(sec.years)}</span>
      </summary>
      {sec.kinds.map((k) => {
        const kk = kindKey(sec.severity, k.title);
        return (
          <details key={kk} className="fkind" open={expanded.has(kk)} onToggle={(e) => toggle(kk, e.currentTarget.open)} ref={k === firstN1 ? n1Ref : undefined}>
            <summary>
              <span className="grow ellipsis">{k.title}</span>
              <span className="mono fcount">{k.groups.length}</span>
            </summary>
            {k.groups.map(children)}
          </details>
        );
      })}
    </details>
  );
}

/** One finding across its plan years: the span and the worst year's figure, the worst year's message, a call on every
 * year at once; opened, each year's own row (its message, its call, its evidence). */
function GroupRow({
  g, expanded, onToggle, named, onOpen, onStatus, evidenceFor,
}: {
  g: FindingGroup;
  expanded: boolean;
  onToggle: (on: boolean) => void;
  named: Map<string, string>;
  onOpen: (f: Finding) => void;
  onStatus: (id: string, st: FindingStatus) => void;
  evidenceFor: (f: Finding) => (() => void) | undefined;
}) {
  const f = g.worst;
  const multi = g.rows.length > 1;
  const sev = SEVERITY[g.severity];
  const next = NEXT[f.status];
  const figure = figureText(f);
  const Caret = expanded ? CaretDown : CaretRight;
  return (
    <div className="frow">
      <span className="sev-dot" style={{ background: sev.c }} title={sev.label} />
      <button className="frow-main" onClick={() => onOpen(f)} title={multi ? `Show the worst year (${f.year}) on the map` : "Show on the map"}>
        <span className="ellipsis" style={{ fontSize: 12.5, fontWeight: 600 }}>{g.title}</span>
        {f.source !== "engine" && <span className="chip" style={{ background: "rgba(255,255,255,0.08)", color: C.mute }}>{f.source}</span>}
        <span className="fspan">{yearSpan(g.years)}{multi && figure ? ` · worst ${figure}` : ""}</span>
      </button>
      <span className="facts">
        {next && (
          <button
            className="icon-btn sm"
            onClick={() => g.rows.forEach((r) => onStatus(r.finding_id, next.st))}
            title={multi ? `${next.label} all ${g.rows.length} years` : next.label}
            aria-label={multi ? `${next.label} all ${g.rows.length} years` : next.label}
          >
            <next.icon size={12} />
          </button>
        )}
        {multi && (
          <button className="icon-btn sm" onClick={() => onToggle(!expanded)} aria-expanded={expanded} title={expanded ? "Hide the years" : `Show the ${g.rows.length} years`}>
            <Caret size={12} />
          </button>
        )}
      </span>
      <span className="fmsg">
        {named.get(f.finding_id) ?? f.message}
        {!multi && <EvidenceChip onClick={evidenceFor(f)} />}
      </span>
      {multi && expanded && (
        <div className="fyrows">
          {g.rows.map((r) => {
            const rn = NEXT[r.status];
            return (
              <div key={r.finding_id} className="fyrow">
                <button className="frow-main" onClick={() => onOpen(r)} title="Show on the map in this year">
                  <span className="yr">{r.year ?? "plan"}</span>
                  <span className="fmsg">
                    {named.get(r.finding_id) ?? r.message}
                    <EvidenceChip onClick={evidenceFor(r)} />
                  </span>
                </button>
                {rn ? (
                  <button className="icon-btn sm" onClick={() => onStatus(r.finding_id, rn.st)} title={`${rn.label} ${r.year ?? ""}`.trim()} aria-label={`${rn.label} ${r.year ?? ""}`.trim()}>
                    <rn.icon size={12} />
                  </button>
                ) : (
                  <span />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** The study behind an agent's finding (nothing for the engine's own). */
function EvidenceChip({ onClick }: { onClick?: () => void }) {
  if (!onClick) return null;
  return (
    <button
      className="tchip link"
      data-status="done"
      style={{ marginLeft: 6, verticalAlign: 1 }}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      title="The study behind this finding"
    >
      <Receipt size={10} />
      evidence
    </button>
  );
}
