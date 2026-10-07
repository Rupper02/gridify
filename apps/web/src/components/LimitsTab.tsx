// Limits: what limits the branch, from the engine's own reduction of its last run (GET /branches/{id}/limits). Top to
// bottom: the elements that bind or come near a limit, each with its trajectory over the plan years, the worst figure
// and case, the projects it holds back and the N-1 outages that breach it; the deferred projects with the chain of what
// stops each (and what the engine's probe found, or a question to the agents); the N-1 causes (one weak link many
// outages overload, an island, a collapse); the planned works' verdicts; and, folded at the bottom, the findings ledger
// with the operator's call on each finding. Every figure is the engine's; a row sets the year and shows it on the map.

import { Sparkle, Wrench } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { connectQuestion } from "../lib/ask";
import { type ModelIndex, ZOOM_ELEMENT, ZOOM_REGION, nameElements, outageSel, plural } from "../lib/derive";
import { MAX_BINDING, MAX_CLUSTERS, bindingSel, chainSel, chainStudy, clusterLine, clusterSel, fromText, summaryLine, trajectoryPoints, worstText } from "../lib/limits";
import { VERDICTS } from "../lib/maintenance";
import { C, caseLabel, fmtMw, loadColor, techLabel, tint, voltColor } from "../theme";
import type { Chain, Cluster, ElementBinding, Limits, Model, Outage, Sel, Verdict, WorkVerdict } from "../types";
import { FindingsLedger, type FindingsLedgerPlanner } from "./FindingsLedger";
import { Sparkline, TechIcon } from "./ui";

export type LimitsTabPlanner = PlannerSlice<"activeBranch" | "limits" | "limitsError" | "year", "askAbout" | "loadLimits" | "run", "branch" | "onMain" | "run" | "stale"> &
  FindingsLedgerPlanner;

/** Where something shows on the map, in a year (the year first, so the map's figures are that year's). */
type Open = (sel: Sel | null, year: number | null) => void;

export function LimitsTab({ planner }: { planner: LimitsTabPlanner }) {
  const { s, actions, derived } = planner;
  const { ix, run } = derived;
  const where = derived.onMain ? "main" : derived.branch?.name;
  const l = s.limits;
  const [ledgerOpen, setLedgerOpen] = useState(false);
  // another card sent the operator to a findings group (the readings' N-1 stat): the ledger unfolds and expands it
  useEffect(() => {
    if (s.findingsFocus) setLedgerOpen(true);
  }, [s.findingsFocus]);
  const open: Open = (sel, year) => {
    if (year != null) actions.setYear(year);
    if (!sel) return;
    if (sel.kind === "region") actions.setLayer("demand");
    actions.focusSel(sel, sel.kind === "region" ? ZOOM_REGION : ZOOM_ELEMENT);
  };
  return (
    <div className="scroll" style={{ padding: "4px 14px 16px", gap: 12 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>What limits {where}</span>
        {l ? (
          <>
            <span style={{ fontSize: 12, color: C.ink2, lineHeight: 1.45 }}>{l.character.text}</span>
            <span className="mono" style={{ fontSize: 11.5, color: C.mute, lineHeight: 1.45 }}>{summaryLine(l)}</span>
          </>
        ) : (
          <span style={{ fontSize: 12, color: C.mute, lineHeight: 1.45 }}>
            The engine's own reading of the last run: what binds, where, in which case and year, what it holds back, and what it would take.
          </span>
        )}
      </div>
      {derived.stale.stale && !run.inProgress && <div className="notice amber">The result is out of date; this is what limited its last run.</div>}
      {!l && (
        <Waiting
          problem={run.problem}
          error={run.inProgress ? null : s.limitsError}
          inProgress={run.inProgress}
          where={where ?? ""}
          onRetryRun={() => void actions.run()}
          onRetryRead={() => void actions.loadLimits(s.activeBranch)}
        />
      )}
      {l && (
        <>
          <BindingSet l={l} year={s.year} model={s.model} onOpen={open} />
          <DeferredProjects chains={l.chains} ix={ix} model={s.model} onOpen={open} onAsk={(id) => void actions.askAbout(connectQuestion(id))} />
          <Causes clusters={l.clusters} model={s.model} onOpen={open} />
          <PlannedWorks works={l.works} ix={ix} outages={s.outages} onOpen={open} />
        </>
      )}
      <details className="ledger-fold" open={ledgerOpen} onToggle={(e) => setLedgerOpen(e.currentTarget.open)}>
        <summary>All findings · {plural(s.findings.length, "row")}</summary>
        <FindingsLedger planner={planner} />
      </details>
    </div>
  );
}

/** Nothing to show yet: the run did not finish (its own Retry), the read failed (Retry), or it is on its way. */
function Waiting({ problem, error, inProgress, where, onRetryRun, onRetryRead }: { problem: string | null; error: string | null; inProgress: boolean; where: string; onRetryRun: () => void; onRetryRead: () => void }) {
  if (problem)
    return (
      <span className="notice amber" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="grow">{problem}</span>
        <button className="btn" onClick={onRetryRun}>Retry</button>
      </span>
    );
  if (error)
    return (
      <span className="notice amber" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="grow">Could not read what limits {where}: {error}</span>
        <button className="btn" onClick={onRetryRead}>Retry</button>
      </span>
    );
  return <span className="mute" style={{ fontSize: 12 }}>{inProgress ? "Solving the plan; what limits it appears once every year is in." : `Reading what limits ${where}…`}</span>;
}

/** Show the first rows, and the rest on request. */
function ShowAll({ total, shown, all, onToggle }: { total: number; shown: number; all: boolean; onToggle: () => void }) {
  if (total <= shown) return null;
  return (
    <button className="show-more" onClick={onToggle}>
      {all ? `Show the first ${shown}` : `Show all ${total}`}
    </button>
  );
}

// ---- the binding set ------------------------------------------------------------------------------
const SEV_COLOR: Record<ElementBinding["severity"], string> = { breach: C.red, near: C.amber, ok: C.mute2 };
const SEV_TITLE: Record<ElementBinding["severity"], string> = { breach: "Over its limit", near: "Near its limit", ok: "Within its limit" };
const KIND_LABEL: Record<ElementBinding["kind"], string> = { line: "circuit", trafo: "transformer", bus: "busbar" };

function BindingSet({ l, year, model, onOpen }: { l: Limits; year: number; model: Model | null; onOpen: Open }) {
  const [all, setAll] = useState(false);
  const rows = all ? l.binding : l.binding.slice(0, MAX_BINDING);
  return (
    <section className="lsec">
      <span className="lsec-title">Binding set</span>
      {!l.binding.length && <span className="mute" style={{ fontSize: 12 }}>No element binds or comes near a limit in any plan year.</span>}
      {rows.map((b) => (
        <BindingRow key={`${b.kind}:${b.element_id}`} b={b} years={l.years} year={year} model={model} onOpen={onOpen} />
      ))}
      <ShowAll total={l.binding.length} shown={MAX_BINDING} all={all} onToggle={() => setAll(!all)} />
    </section>
  );
}

/** One element: its name and kind, its trajectory (the dashed line its limit), the worst figure with its case and year,
 * from when it nears or breaches, its room in MW, the projects it holds back, the outages that breach it. */
function BindingRow({ b, years, year, model, onOpen }: { b: ElementBinding; years: number[]; year: number; model: Model | null; onOpen: Open }) {
  // a loading reads against its rating (100%); a voltage against the bus's own band, in pu
  const bus = b.kind === "bus" ? model?.buses.find((x) => x.bus_id === b.element_id) : undefined;
  const color = b.unit === "pu" ? (bus ? (v: number | null) => voltColor(v, bus.vmin_pu, bus.vmax_pu) : () => SEV_COLOR[b.severity]) : loadColor;
  const fmt = b.unit === "pu" ? (v: number) => `${v} pu` : undefined;
  const from = fromText(b);
  return (
    <div className="lrow">
      <span className="sev-dot" style={{ background: SEV_COLOR[b.severity] }} title={SEV_TITLE[b.severity]} />
      <button className="frow-main" onClick={() => onOpen(bindingSel(b, model), b.worst.year)} title={`Show it on the map in ${b.worst.year}`}>
        <span className="ellipsis" style={{ fontSize: 12.5, fontWeight: 600 }}>{b.name}</span>
        <span className="chip kind">{KIND_LABEL[b.kind]}</span>
      </button>
      <Sparkline points={trajectoryPoints(b, years)} year={year} color={color} limit={b.limit} fmt={fmt} />
      <span className="lfacts">
        <b className="mono" style={{ color: SEV_COLOR[b.severity] }}>{worstText(b)}</b>
        {from && <span>{from}</span>}
        {b.headroom_mw != null && <span>{fmtMw(b.headroom_mw)} MW room</span>}
        {b.n1_outages > 0 && <span>{plural(b.n1_outages, "outage")} breach{b.n1_outages === 1 ? "es" : ""} it</span>}
      </span>
      {b.holds_back.length > 0 && (
        <span className="chips">
          {b.holds_back.map((id) => (
            <span key={id} className="chip hold">holds back {id}</span>
          ))}
        </span>
      )}
    </div>
  );
}

// ---- the deferred projects ------------------------------------------------------------------------
function DeferredProjects({ chains, ix, model, onOpen, onAsk }: { chains: Chain[]; ix: ModelIndex | null; model: Model | null; onOpen: Open; onAsk: (requestId: string) => void }) {
  if (!chains.length) return null;
  return (
    <section className="lsec">
      <span className="lsec-title">Deferred projects</span>
      {chains.map((c) => (
        <ChainCard key={c.request_id} c={c} ix={ix} model={model} onOpen={onOpen} onAsk={onAsk} />
      ))}
    </section>
  );
}

/** One deferred project: why (the engine's message, elements named), the element that stops it as a link, the case
 * and phase, from when that element binds; what the probe found, or a way to ask the agents what it would take. */
function ChainCard({ c, ix, model, onOpen, onAsk }: { c: Chain; ix: ModelIndex | null; model: Model | null; onOpen: Open; onAsk: (requestId: string) => void }) {
  const sel = chainSel(c, model);
  const study = chainStudy(c);
  const what = [c.technology ? techLabel(c.technology) : "", c.rating_mw != null ? `${fmtMw(c.rating_mw)} MW` : ""].filter(Boolean).join(" · ");
  return (
    <div className="chain-card">
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        <TechIcon tech={c.technology} size={14} color={C.amber} />
        <span className="mono" style={{ fontSize: 12.5, fontWeight: 600 }}>{c.request_id}</span>
        {what && <span className="mute ellipsis" style={{ fontSize: 11 }}>{what}</span>}
      </div>
      <span style={{ fontSize: 12, lineHeight: 1.45, color: C.ink2, textWrap: "pretty" }}>Deferred: {nameElements(c.message, ix)}</span>
      <span style={{ fontSize: 11.5, color: C.mute, lineHeight: 1.4 }}>
        {sel ? (
          <button className="link-btn" onClick={() => onOpen(sel, c.first_near_year)} title="Show the element on the map">{c.element_name}</button>
        ) : (
          c.element_name
        )}
        {c.case ? ` · ${caseLabel(c.case)}, phase ${c.phase}` : ` · phase ${c.phase}`}
        {c.first_near_year != null && ` · that element binds from ${c.first_near_year}`}
      </span>
      {study.length > 0 ? (
        <ul className="lstudy">
          {study.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      ) : (
        <button className="btn" style={{ alignSelf: "flex-start", height: 28, fontSize: 11.5 }} onClick={() => onAsk(c.request_id)}>
          <Sparkle size={12} weight="fill" />
          Ask what it would take
        </button>
      )}
    </div>
  );
}

// ---- the N-1 causes -------------------------------------------------------------------------------
const CLUSTER_KIND: Record<Cluster["kind"], string> = { weak_link: "weak link", island: "island", collapse: "collapse" };

function Causes({ clusters, model, onOpen }: { clusters: Cluster[]; model: Model | null; onOpen: Open }) {
  const [all, setAll] = useState(false);
  if (!clusters.length) return null;
  const rows = all ? clusters : clusters.slice(0, MAX_CLUSTERS);
  return (
    <section className="lsec">
      <span className="lsec-title">Causes · N-1</span>
      {rows.map((c) => {
        const sel = clusterSel(c, model);
        const body = (
          <>
            <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
              <span className="ellipsis" style={{ fontSize: 12.5, fontWeight: 600 }}>{c.label}</span>
              <span className="chip kind">{CLUSTER_KIND[c.kind]}</span>
            </span>
            <span className="mono" style={{ fontSize: 11, color: C.mute }}>
              {clusterLine(c)}
              {c.cases.length ? ` · ${c.cases.map(caseLabel).join(", ")}` : ""}
            </span>
          </>
        );
        // a weak link is an element on the map; an island or a collapse is an outage's doing, with nothing to point at
        return sel ? (
          <button key={c.key} className="cause-row link" onClick={() => onOpen(sel, null)} title="Show the element on the map">{body}</button>
        ) : (
          <div key={c.key} className="cause-row">{body}</div>
        );
      })}
      <ShowAll total={clusters.length} shown={MAX_CLUSTERS} all={all} onToggle={() => setAll(!all)} />
    </section>
  );
}

// ---- the planned works ----------------------------------------------------------------------------
function PlannedWorks({ works, ix, outages, onOpen }: { works: WorkVerdict[]; ix: ModelIndex | null; outages: Outage[]; onOpen: Open }) {
  if (!works.length) return null;
  return (
    <section className="lsec">
      <span className="lsec-title">Planned works</span>
      {works.map((w) => {
        const v = w.verdict in VERDICTS ? VERDICTS[w.verdict as Verdict] : null;
        const o = outages.find((x) => x.outage_id === w.outage_id);
        const facts = [
          w.curtailed_mw > 0 ? `${fmtMw(w.curtailed_mw)} MW curtailed` : "",
          w.demand_at_risk_mw > 0 ? `${fmtMw(w.demand_at_risk_mw)} MW demand at risk` : "",
          w.n1_findings ? `${plural(w.n1_findings, "N-1 finding")} during it` : "",
        ].filter(Boolean);
        return (
          <button key={w.outage_id} className="cause-row link" onClick={() => onOpen(o ? outageSel(o) : null, w.year)} title={`Show it on the map in ${w.year}`}>
            <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
              <Wrench size={12} color={C.mute} style={{ flex: "none" }} />
              <span className="ellipsis" style={{ fontSize: 12.5, fontWeight: 600 }}>{nameElements(w.element, ix)}</span>
              <span className="mono" style={{ marginLeft: "auto", fontSize: 11, color: C.mute }}>{w.year}</span>
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", fontSize: 11, color: C.mute }}>
              <span className="chip" style={v ? { background: tint(v.c, "22"), color: v.c } : { background: "rgba(255,255,255,0.08)" }}>{v?.label ?? w.verdict}</span>
              {facts.join(" · ")}
            </span>
          </button>
        );
      })}
    </section>
  );
}
