// The projects screen (a glass sheet over the map): the grids the planner can plan on, with Open and
// Delete, and the import form: a file (a CIM/CGMES zip, a pandapower JSON or a MATPOWER case), a name
// and the limits the operator knows, which are recorded as entered. Once a file is chosen its voltage levels
// are read (nothing stored) and the study basis is asked for: the demand forecast by year (Standard, and
// optionally Low and High), the lowest level the N-1 screen covers, and the voltage limits by level. The API
// validates it all and answers with a report; what it did not carry is listed before the project is opened.

import { CheckCircle, FileArrowUp, Globe, Trash, Warning, X } from "@phosphor-icons/react";
import { type CSSProperties, type FormEvent, type ReactNode, useState } from "react";

import { ApiError, api } from "../api";
import type { PlannerSlice } from "../hooks/planner/slice";
import {
  EMPTY_BASIS, LIMIT_FIELDS, PATHWAYS, type StudyBasisForm, assumptionText, capabilityChips, cumulativeOf, kindLabel, limitsFromForm, n1Covers, presetBands,
  reportLines,
  studyBasisFields,
} from "../lib/projects";
import { C } from "../theme";
import type { FileInspection, ImportReport, Project } from "../types";

export type ProjectsScreenPlanner = PlannerSlice<"projectId" | "projects" | "plan", "closeProjects" | "deleteProject" | "importProject" | "openProject">;

const TONE_INK = { good: C.greenInk, warn: C.amberInk, bad: C.redInk } as const;
const MAX_ASSUMPTIONS = 8;

export function ProjectsScreen({ planner }: { planner: ProjectsScreenPlanner }) {
  const { s, actions } = planner;
  return (
    <div className="modal-backdrop" onClick={actions.closeProjects}>
      <div className="modal glass" role="dialog" aria-label="Projects" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Globe size={18} color={C.accent} weight="bold" />
          <span style={{ fontSize: 16, fontWeight: 600, flex: 1 }}>Projects</span>
          <button className="icon-btn" onClick={actions.closeProjects} aria-label="Close projects">
            <X size={14} />
          </button>
        </div>
        <span style={{ fontSize: 12, color: C.mute, lineHeight: 1.45, textWrap: "pretty" }}>
          A project is a grid with its own plan of record. The built-in one is NGED's Bicker Fen GSP from open data; import any other as a
          CIM/CGMES zip, a pandapower JSON or a MATPOWER case. The same engine, branches, gate and agents work on every project.
        </span>
        <div className="modal-cols">
          <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
            <span style={{ fontSize: 12.5, fontWeight: 600 }}>Your projects</span>
            {s.projects.map((p) => (
              <ProjectRow key={p.project_id} p={p} current={p.project_id === s.projectId} onOpen={() => void actions.openProject(p.project_id)} onDelete={() => void actions.deleteProject(p.project_id)} />
            ))}
            {!s.projects.length && <span className="mute" style={{ fontSize: 12 }}>Loading the projects…</span>}
          </div>
          <ImportForm years={s.plan?.years.slice(1) ?? []} onImport={actions.importProject} onOpen={(pid) => void actions.openProject(pid)} />
        </div>
      </div>
    </div>
  );
}

function ProjectRow({ p, current, onOpen, onDelete }: { p: Project; current: boolean; onOpen: () => void; onDelete: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const counts = p.report?.counts;
  return (
    <div className={`proj-row${current ? " current" : ""}`}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        <span className="ellipsis" style={{ fontSize: 13, fontWeight: 600, flex: 1, minWidth: 0 }}>{p.name}</span>
        {current && <span className="chip" style={{ background: "rgba(124,227,255,0.14)", color: C.accent }}>open</span>}
        {p.builtin && <span className="chip" style={{ background: "rgba(255,255,255,0.08)", color: C.mute }}>built-in</span>}
      </div>
      <span style={{ fontSize: 11.5, color: C.mute, lineHeight: 1.4 }}>
        {kindLabel(p.source_kind)}
        {counts ? ` · ${counts.buses} buses · ${counts.lines} lines · ${counts.transformers} transformers` : ""}
        {p.file_name ? ` · ${p.file_name}` : ""} · {p.created_at.slice(0, 10)}
      </span>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {capabilityChips(p.capabilities).map((c) => (
          <span key={c} className="cap-chip">{c}</span>
        ))}
      </div>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <button className="btn hue" style={{ height: 28, fontSize: 11.5, "--hue": "#7ce3ff", "--hue-bd": "#7ce3ff80", "--hue-bg": "#7ce3ff1f" } as CSSProperties} onClick={onOpen} disabled={current}>
          {current ? "Open now" : "Open"}
        </button>
        {!p.builtin && !confirm && (
          <button className="btn ghost" style={{ height: 28, fontSize: 11.5 }} onClick={() => setConfirm(true)} title="Remove this project and its branches">
            <Trash size={12} />
            Delete
          </button>
        )}
        {confirm && (
          <>
            <span style={{ fontSize: 11.5, color: C.amberInk }}>Remove it with its branches?</span>
            <button className="btn danger" style={{ height: 28, fontSize: 11.5 }} onClick={onDelete}>Remove</button>
            <button className="btn" style={{ height: 28, fontSize: 11.5 }} onClick={() => setConfirm(false)}>Keep</button>
          </>
        )}
      </div>
    </div>
  );
}

type Outcome = { kind: "done"; project: Project } | { kind: "refused"; message: string; report: ImportReport | null } | null;

function ImportForm({ years, onImport, onOpen }: { years: number[]; onImport: (file: File, name: string, limits: Record<string, string>) => Promise<Project>; onOpen: (pid: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [inspection, setInspection] = useState<FileInspection | null>(null);
  const [inspectError, setInspectError] = useState<string | null>(null);
  const [basis, setBasis] = useState<StudyBasisForm>(EMPTY_BASIS);
  const [name, setName] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [showLimits, setShowLimits] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file || !inspection) return;
    const { limits, error } = limitsFromForm(values);
    const study = studyBasisFields(basis, years, inspection.levels);
    if (error || study.error) {
      setFormError(error ?? study.error);
      return;
    }
    setFormError(null);
    setBusy(true);
    setOutcome(null);
    try {
      const project = await onImport(file, name.trim() || file.name.replace(/\.[^.]+$/, ""), { ...limits, ...study.fields });
      setOutcome({ kind: "done", project });
    } catch (err) {
      const detail = err instanceof ApiError ? (err.detail as { message?: string; report?: ImportReport } | string | null) : null;
      const report = detail && typeof detail === "object" && detail.report ? detail.report : null;
      setOutcome({ kind: "refused", message: err instanceof Error ? err.message : "the import failed", report });
    } finally {
      setBusy(false);
    }
  };

  /** A new file: read its voltage levels for the study basis (the limits by level and the N-1 choices). */
  const choose = async (f: File | null) => {
    setFile(f);
    setInspection(null);
    setInspectError(null);
    setBasis(EMPTY_BASIS);
    setOutcome(null);
    if (!f) return;
    try {
      setInspection(await api.inspectFile(f));
    } catch (err) {
      setInspectError(err instanceof Error ? err.message : "could not read the file");
    }
  };

  return (
    <form className="import-form" onSubmit={(e) => void submit(e)}>
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>Import a grid</span>
      <label className="file-drop">
        <FileArrowUp size={18} color={C.accent} />
        <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
          <span className="ellipsis" style={{ fontSize: 12.5 }}>{file ? file.name : "Choose a file"}</span>
          <span style={{ fontSize: 11, color: C.mute }}>.zip (CGMES), .json (pandapower), .mat (MATPOWER) · up to 50 MB</span>
        </span>
        <input type="file" accept=".zip,.json,.mat" aria-label="Grid file" onChange={(e) => void choose(e.target.files?.[0] ?? null)} style={{ display: "none" }} />
      </label>
      <input className="search" value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name (defaults to the file name)" aria-label="Project name" />
      <button type="button" className="btn ghost" style={{ alignSelf: "flex-start", height: 26, fontSize: 11.5 }} onClick={() => setShowLimits((v) => !v)} aria-expanded={showLimits}>
        {showLimits ? "Hide the known limits" : "Known limits (optional)"}
      </button>
      {showLimits && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 11, color: C.mute, lineHeight: 1.4 }}>
            What you know and the file does not carry. Each is applied to the whole grid and recorded as entered by you; leave blank what you do not know.
          </span>
          {LIMIT_FIELDS.map((f) => (
            <label key={f.key} style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 11.5 }}>
              <span>{f.label} <span style={{ color: C.mute2 }}>· {f.hint}</span></span>
              <input className="search" value={values[f.key] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))} aria-label={f.label} />
            </label>
          ))}
        </div>
      )}
      {file && !inspection && !inspectError && <span className="mute" style={{ fontSize: 11.5 }}>Reading the file's voltage levels…</span>}
      {inspectError && <span style={{ fontSize: 11.5, color: C.redInk }}>Could not read the file: {inspectError}</span>}
      {inspection && <StudyBasis years={years} inspection={inspection} basis={basis} onChange={setBasis} />}
      {formError && <span style={{ fontSize: 11.5, color: C.redInk }}>{formError}</span>}
      <button type="submit" className="btn primary sm" style={{ alignSelf: "flex-start" }} disabled={!file || !inspection || busy}>
        {busy ? "Validating…" : "Import"}
      </button>
      {outcome?.kind === "done" && <Report report={outcome.project.report} ok onOpen={() => onOpen(outcome.project.project_id)} />}
      {outcome?.kind === "refused" && (
        <div className="notice amber" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
            <Warning size={13} weight="fill" style={{ flex: "none", marginTop: 2 }} />
            <span>Not imported: {outcome.message}</span>
          </span>
          {outcome.report && <Report report={outcome.report} ok={false} />}
        </div>
      )}
    </form>
  );
}

/** What the import must state that the file does not: the forecast by year, the N-1 floor, the limits by level. */
function StudyBasis({ years, inspection, basis, onChange }: { years: number[]; inspection: FileInspection; basis: StudyBasisForm; onChange: (b: StudyBasisForm) => void }) {
  const { levels, presets } = inspection;
  const setCell = (pid: string, y: number, v: string) => onChange({ ...basis, forecast: { ...basis.forecast, [pid]: { ...(basis.forecast[pid] ?? {}), [y]: v } } });
  const setBand = (kv: number, side: "vmin" | "vmax", v: string) => {
    const cur = basis.bands[`${kv}`] ?? { vmin: "", vmax: "" };
    onChange({ ...basis, bands: { ...basis.bands, [`${kv}`]: { ...cur, [side]: v } } });
  };
  return (
    <div className="study-basis">
      <span style={{ fontSize: 12, fontWeight: 600 }}>Study basis (required)</span>
      <span style={{ fontSize: 11, color: C.mute, lineHeight: 1.4 }}>What the plan is judged on that a grid file does not carry. Each is recorded as entered by you.</span>

      <span style={{ fontSize: 11.5 }}>
        Demand forecast <span style={{ color: C.mute2 }}>· peak demand's growth on the year before (1.02 = +2 %); Standard is required, Low and High optional</span>
      </span>
      <div className="forecast-grid" style={{ gridTemplateColumns: `64px repeat(${years.length}, minmax(0, 1fr))` }}>
        <span />
        {years.map((y) => (
          <span key={y} className="fc-year">{y}</span>
        ))}
        {PATHWAYS.map((p) => (
          <GridRow key={p.id} label={`${p.label}${p.required ? " *" : ""}`}>
            {years.map((y) => (
              <input key={y} className="fc-cell" inputMode="decimal" value={basis.forecast[p.id]?.[y] ?? ""} onChange={(e) => setCell(p.id, y, e.target.value)} aria-label={`${p.label} forecast ${y}`} />
            ))}
          </GridRow>
        ))}
      </div>
      <ForecastTotals years={years} basis={basis} />
      <input className="search" value={basis.source} onChange={(e) => onChange({ ...basis, source: e.target.value })} placeholder="Where the forecast comes from (e.g. the DSO's own forecast and its edition)" aria-label="Forecast source" />

      <span style={{ fontSize: 11.5 }}>
        N-1 screen <span style={{ color: C.mute2 }}>· the lowest voltage whose lines and transformers are taken out one at a time</span>
      </span>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {levels.map((l) => (
          <label key={l.kv} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 11.5 }}>
            <input type="radio" name="n1-floor" checked={basis.n1MinKv === `${l.kv}`} onChange={() => onChange({ ...basis, n1MinKv: `${l.kv}` })} />
            <span>
              {l.kv} kV and above <span style={{ color: C.mute }}>· {n1Covers(l)}</span>
            </span>
          </label>
        ))}
      </div>

      <span style={{ fontSize: 11.5 }}>
        Voltage limits by level <span style={{ color: C.mute2 }}>· per unit, after the tap changers settle</span>
      </span>
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ fontSize: 11, color: C.mute }}>Fill from</span>
        {presets.map((p) => (
          <button key={p.id} type="button" className="btn ghost" style={{ height: 24, fontSize: 11 }} title={p.note} onClick={() => onChange({ ...basis, bands: presetBands(p, levels, basis.bands) })}>
            {p.label}
          </button>
        ))}
      </div>
      <div className="band-grid">
        <span />
        <span className="fc-year">min</span>
        <span className="fc-year">max</span>
        {levels.map((l) => (
          <GridRow key={l.kv} label={`${l.kv} kV`}>
            <input className="fc-cell" inputMode="decimal" value={basis.bands[`${l.kv}`]?.vmin ?? ""} onChange={(e) => setBand(l.kv, "vmin", e.target.value)} aria-label={`Minimum at ${l.kv} kV`} />
            <input className="fc-cell" inputMode="decimal" value={basis.bands[`${l.kv}`]?.vmax ?? ""} onChange={(e) => setBand(l.kv, "vmax", e.target.value)} aria-label={`Maximum at ${l.kv} kV`} />
          </GridRow>
        ))}
      </div>
    </div>
  );
}

/** What the typed growth adds up to, per pathway: the multiple of today's peak at each phase's end, as the plan studies it. */
function ForecastTotals({ years, basis }: { years: number[]; basis: StudyBasisForm }) {
  const ends = [2030, years[years.length - 1]].filter((y, i, a) => years.includes(y) && a.indexOf(y) === i);
  const lines = PATHWAYS.flatMap((p) => {
    const c = cumulativeOf(basis.forecast[p.id], years);
    return c ? [`${p.label} ${ends.map((y) => `×${c[y].toFixed(2)} by ${y}`).join(", ")}`] : [];
  });
  return lines.length ? <span style={{ fontSize: 11, color: C.mute, lineHeight: 1.4 }}>Of today's peak: {lines.join(" · ")}</span> : null;
}

/** A labelled row of a CSS grid: the label cell, then its cells (the grid's columns place them). */
function GridRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <span className="fc-label">{label}</span>
      {children}
    </>
  );
}

function Report({ report, ok, onOpen }: { report: ImportReport | null; ok: boolean; onOpen?: () => void }) {
  const lines = reportLines(report);
  const assumptions = report?.assumptions ?? [];
  return (
    <div className="report">
      {ok && (
        <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 600, color: C.greenInk }}>
          <CheckCircle size={14} weight="fill" />
          Imported and validated
        </span>
      )}
      {lines.map((l, i) => (
        <span key={i} style={{ fontSize: 11.5, color: TONE_INK[l.tone], lineHeight: 1.45 }}>{l.text}</span>
      ))}
      {assumptions.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span style={{ fontSize: 11.5, fontWeight: 600 }}>What the model assumes or lacks</span>
          {assumptions.slice(0, MAX_ASSUMPTIONS).map((a) => (
            <span key={a.key} style={{ fontSize: 11, color: C.ink2, lineHeight: 1.4 }}>· {assumptionText(a)}</span>
          ))}
          {assumptions.length > MAX_ASSUMPTIONS && <span style={{ fontSize: 11, color: C.mute }}>{assumptions.length - MAX_ASSUMPTIONS} more under the result stamp once the project is open.</span>}
        </div>
      )}
      {onOpen && (
        <button type="button" className="btn primary sm" style={{ alignSelf: "flex-start" }} onClick={onOpen}>
          Open project
        </button>
      )}
    </div>
  );
}
