// The projects screen (a glass sheet over the map): the grids the planner can plan on, with Open and
// Delete, and the import form: a file (a CIM/CGMES zip, a pandapower JSON or a MATPOWER case), a name
// and the limits the operator knows, which are recorded as entered. The API validates the file and
// answers with a report; what it did not carry is listed before the project is opened.

import { CheckCircle, FileArrowUp, Globe, Trash, Warning, X } from "@phosphor-icons/react";
import { type CSSProperties, type FormEvent, useState } from "react";

import { ApiError } from "../api";
import type { PlannerSlice } from "../hooks/planner/slice";
import { LIMIT_FIELDS, assumptionText, capabilityChips, kindLabel, limitsFromForm, reportLines } from "../lib/projects";
import { C } from "../theme";
import type { ImportReport, Project } from "../types";

export type ProjectsScreenPlanner = PlannerSlice<"projectId" | "projects", "closeProjects" | "deleteProject" | "importProject" | "openProject">;

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
          <ImportForm onImport={actions.importProject} onOpen={(pid) => void actions.openProject(pid)} />
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

function ImportForm({ onImport, onOpen }: { onImport: (file: File, name: string, limits: Record<string, string>) => Promise<Project>; onOpen: (pid: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [showLimits, setShowLimits] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    const { limits, error } = limitsFromForm(values);
    if (error) {
      setFormError(error);
      return;
    }
    setFormError(null);
    setBusy(true);
    setOutcome(null);
    try {
      const project = await onImport(file, name.trim() || file.name.replace(/\.[^.]+$/, ""), limits);
      setOutcome({ kind: "done", project });
    } catch (err) {
      const detail = err instanceof ApiError ? (err.detail as { message?: string; report?: ImportReport } | string | null) : null;
      const report = detail && typeof detail === "object" && detail.report ? detail.report : null;
      setOutcome({ kind: "refused", message: err instanceof Error ? err.message : "the import failed", report });
    } finally {
      setBusy(false);
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
        <input type="file" accept=".zip,.json,.mat" aria-label="Grid file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} style={{ display: "none" }} />
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
      {formError && <span style={{ fontSize: 11.5, color: C.redInk }}>{formError}</span>}
      <button type="submit" className="btn primary sm" style={{ alignSelf: "flex-start" }} disabled={!file || busy}>
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
