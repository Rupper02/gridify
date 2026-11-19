// The card of what is selected: a line, transformer or busbar with its figure this year and across the plan, an
// existing generator, or a connection on the branch (its year, its size, remove). A busbar's card places a new
// connection there.

import { Broadcast, Circuitry, Lightning, Trash, X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import type { Planner } from "../hooks/usePlanner";
import type { Layout } from "../lib/layout";
import { busName, caseOf, lineMva, lineName, reasonText, trafoName, trafoRatio } from "../lib/model";
import { C, TECH, caseLabel, isTech, loadColor, techLabel, voltColor } from "../theme";
import type { Reason, Sel, Tech, YearResult } from "../types";
import { RunDetail } from "./RunsTab";
import { Sparkline, Stepper, TechIcon, TechTile } from "./ui";

const TECHS = Object.keys(TECH) as Tech[];

function series(years: Record<string, YearResult>, planYears: number[], f: (y: YearResult) => number | undefined) {
  return planYears.map((year) => {
    const y = years[String(year)];
    const v = y ? f(y) : undefined;
    return { year, pct: v == null ? null : v };
  });
}

/** The breaches this year that name the selected element. */
function ownBreaches(yr: YearResult | null, sel: Sel): Reason[] {
  if (!yr) return [];
  const type = sel.kind === "line" ? "line" : sel.kind === "trafo" ? "trafo" : sel.kind === "bus" ? "voltage" : null;
  return type ? yr.violations.filter((r) => r.type === type && r.element_id === sel.id) : [];
}

export function DetailCard({ planner, layout }: { planner: Planner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const { ix, yr } = derived;
  const sel = s.sel;
  if (!sel || !ix) return null;
  const years = s.result?.years ?? {};
  const style = { top: 68, left: 10, width: 300, maxHeight: `calc(100% - ${68 + (layout.showDock ? layout.dockPx + 20 : 14)}px)` };
  const close = () => actions.select(null);
  const head = (icon: React.ReactNode, title: string, sub: string) => (
    <div className="head">
      <span className="ic" style={{ background: "rgba(124,227,255,0.12)", color: C.accent }}>{icon}</span>
      <span className="grow" style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <b style={{ fontSize: 13 }}>{title}</b>
        <span className="mute" style={{ fontSize: 11 }}>{sub}</span>
      </span>
      <button className="icon-btn sm" onClick={close} aria-label="Close">
        <X size={13} />
      </button>
    </div>
  );
  const breachList = ownBreaches(yr, sel).map((r, i) => {
    const t = reasonText(r, ix);
    return (
      <div key={i} className="notice red" style={{ padding: "7px 10px" }}>
        {t.figure} at {t.when}
      </div>
    );
  });

  let body: React.ReactNode = null;
  if (sel.kind === "line") {
    const l = ix.line.get(sel.id);
    if (!l) return null;
    const pct = yr?.line_loading[String(sel.id)];
    body = (
      <>
        {head(<Circuitry size={17} />, lineName(ix, sel.id), `${+l.voltage_kv} kV line${l.in_service ? "" : " · open point"}`)}
        <div className="kv">
          <span>Rating</span><span className="mono">{Math.round(l.rating_a)} A · {Math.round(lineMva(l))} MVA</span>
          {l.length_km != null && <><span>Length</span><span className="mono">{l.length_km.toFixed(1)} km</span></>}
          <span>{s.year}</span>
          <span className="mono" style={{ color: loadColor(pct) }}>{pct != null ? `${Math.round(pct)}% at ${caseLabel(caseOf(yr, "lines", sel.id))}` : "–"}</span>
        </div>
        <Sparkline points={series(years, derived.years, (y) => y.line_loading[String(sel.id)])} year={s.year} color={loadColor} />
        {breachList}
      </>
    );
  } else if (sel.kind === "trafo") {
    const t = ix.trafo.get(sel.id);
    if (!t) return null;
    const pct = yr?.trafo_loading[String(sel.id)];
    body = (
      <>
        {head(<Lightning size={17} />, trafoName(ix, sel.id), `${trafoRatio(t)} transformer`)}
        <div className="kv">
          <span>Rating</span><span className="mono">{Math.round(t.sn_mva)} MVA</span>
          <span>{s.year}</span>
          <span className="mono" style={{ color: loadColor(pct) }}>{pct != null ? `${Math.round(pct)}% at ${caseLabel(caseOf(yr, "trafos", sel.id))}` : "–"}</span>
        </div>
        <Sparkline points={series(years, derived.years, (y) => y.trafo_loading[String(sel.id)])} year={s.year} color={loadColor} />
        {breachList}
      </>
    );
  } else if (sel.kind === "bus") {
    const b = ix.bus.get(sel.id);
    if (!b) return null;
    const v = yr?.bus_vm[String(sel.id)];
    const here = s.connections.filter((c) => c.bus_id === sel.id);
    body = (
      <>
        {head(<Broadcast size={17} />, busName(ix, sel.id), `${+b.vn_kv} kV busbar · ${b.name}`)}
        <div className="kv">
          <span>Band</span><span className="mono">{b.vmin_pu.toFixed(2)}–{b.vmax_pu.toFixed(2)} pu</span>
          <span>{s.year}</span>
          <span className="mono" style={{ color: voltColor(v, b.vmin_pu, b.vmax_pu) }}>{v != null ? `${v.toFixed(3)} pu at ${caseLabel(caseOf(yr, "buses", sel.id))}` : "–"}</span>
        </div>
        <Sparkline
          points={series(years, derived.years, (y) => {
            const x = y.bus_vm[String(sel.id)];
            return x == null ? undefined : Math.abs(x - 1) * 100;
          })}
          year={s.year}
          limit={Math.max(1 - b.vmin_pu, b.vmax_pu - 1) * 100}
          color={(d) => (d == null ? C.mute2 : d > Math.max(1 - b.vmin_pu, b.vmax_pu - 1) * 100 ? C.red : C.ink2)}
          fmt={(d) => `${d.toFixed(1)}% from nominal`}
        />
        {breachList}
        {here.length > 0 && <span className="mute" style={{ fontSize: 11.5 }}>On this branch here: {here.map((c) => c.request_id).join(", ")}</span>}
        <NewConnection planner={planner} busId={sel.id} />
      </>
    );
  } else if (sel.kind === "gen") {
    const g = ix.gen.get(sel.id);
    if (!g) return null;
    body = (
      <>
        {head(<TechIcon tech={g.technology} size={17} />, g.applicant, `Existing ${techLabel(g.technology).toLowerCase()} · connected today`)}
        <div className="kv">
          <span>Rating</span><span className="mono">{g.rating_mw.toFixed(1)} MW</span>
          <span>At</span><span>{busName(ix, g.bus_id)}</span>
          {isTech(g.technology) && <><span>Dispatch</span><span>{TECH[g.technology].treatment}</span></>}
        </div>
      </>
    );
  } else {
    const c = s.connections.find((x) => x.request_id === sel.id);
    if (!c) return null;
    const editable = !derived.onMain;
    const imports = isTech(c.technology) && TECH[c.technology].imports;
    const importOnly = isTech(c.technology) && TECH[c.technology].importOnly;
    const first = derived.years[0];
    const last = derived.years[derived.years.length - 1];
    body = (
      <>
        <div className="head">
          <TechTile tech={c.technology} c={derived.hue} size={34} />
          <span className="grow" style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <b style={{ fontSize: 13 }}>{c.name || c.request_id}</b>
            <span className="mute" style={{ fontSize: 11 }}>{c.request_id} · {techLabel(c.technology)}</span>
          </span>
          <button className="icon-btn sm" onClick={close} aria-label="Close">
            <X size={13} />
          </button>
        </div>
        <div className="kv">
          <span>At</span><span>{busName(ix, c.bus_id)}</span>
          {!importOnly && <><span>Export</span><span className="mono">{c.rating_mw} MW</span></>}
          {imports && <><span>Import</span><span className="mono">{c.import_mw ?? c.rating_mw} MW</span></>}
          <span>Dispatch</span><span>{isTech(c.technology) ? TECH[c.technology].treatment : "Firm in both cases"}</span>
          <span>In service</span><span className="mono">{c.year <= s.year ? `since ${c.year}` : `from ${c.year}`}</span>
        </div>
        {editable && (
          <>
            <div className="form-row">
              <span className="lbl">Energises in</span>
              <Stepper
                value={c.year}
                label="year"
                onDec={() => c.year > first && void actions.changeConnection(c.request_id, { year: c.year - 1 })}
                onInc={() => c.year < last && void actions.changeConnection(c.request_id, { year: c.year + 1 })}
              />
            </div>
            <button className="btn danger" onClick={() => void actions.removeConnection(c.request_id)}>
              <Trash size={14} /> Remove from this branch
            </button>
          </>
        )}
        {!editable && <span className="mute" style={{ fontSize: 11.5 }}>Merged into main. Open a branch to change it.</span>}
      </>
    );
  }
  return (
    <div className="detail glass" style={style}>
      {body}
      {s.layer === "hours" && <RunDetail planner={planner} />}
    </div>
  );
}

/** Place a new connection at a busbar: what it is, how big, from which year. */
function NewConnection({ planner, busId }: { planner: Planner; busId: number }) {
  const { s, actions, derived } = planner;
  const [tech, setTech] = useState<Tech>("solar");
  const [mw, setMw] = useState("20");
  const [imp, setImp] = useState("");
  const [year, setYear] = useState(s.year || derived.years[0]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setYear(s.year || derived.years[0]), [busId, s.year, derived.years]);
  const meta = TECH[tech];
  const max = s.forecasts?.max_connection_mw ?? 300;
  const submit = async () => {
    setBusy(true);
    const ok = await actions.addConnection({
      bus_id: busId,
      technology: tech,
      name: name.trim() || null,
      rating_mw: meta.importOnly ? 0 : Number(mw),
      import_mw: meta.imports && imp !== "" ? Number(imp) : meta.importOnly ? Number(mw) : null,
      year,
    });
    setBusy(false);
    if (ok) setName("");
  };
  const valid = Number(mw) > 0 && Number(mw) <= max && (imp === "" || (Number(imp) >= 0 && Number(imp) <= max));
  return (
    <div className="box dark">
      <b style={{ fontSize: 12 }}>Connect here{derived.onMain ? " (opens a branch)" : ""}</b>
      <div className="form-row">
        <span className="lbl">Technology</span>
        <select className="search" value={tech} onChange={(e) => setTech(e.target.value as Tech)}>
          {TECHS.map((t) => (
            <option key={t} value={t}>{TECH[t].label}</option>
          ))}
        </select>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <label className="form-row grow">
          <span className="lbl">{meta.importOnly ? "Import (MW)" : "Export (MW)"}</span>
          <input className="search" type="number" min={0} max={max} value={mw} onChange={(e) => setMw(e.target.value)} />
        </label>
        {meta.imports && !meta.importOnly && (
          <label className="form-row grow">
            <span className="lbl">Import (MW)</span>
            <input className="search" type="number" min={0} max={max} placeholder={mw} value={imp} onChange={(e) => setImp(e.target.value)} />
          </label>
        )}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <label className="form-row grow">
          <span className="lbl">Energises in</span>
          <select className="search" value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {derived.years.map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </label>
        <label className="form-row grow">
          <span className="lbl">Name (optional)</span>
          <input className="search" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
      </div>
      <span className="mute" style={{ fontSize: 11 }}>{meta.treatment}</span>
      <button className="btn primary sm" disabled={!valid || busy} onClick={() => void submit()}>
        {busy ? "Adding…" : "Add connection"}
      </button>
    </div>
  );
}
