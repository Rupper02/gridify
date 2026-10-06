// The floating header: logo, the project capsule (opens the projects screen), branch capsule + menu (a branch its parent
// moved past says "behind main"), Diff / Merge
// on a branch, the agents pill, the demand profile control and the Run button ("Re-run" when the shown result is out of date).

import { CaretDown, GitBranch, GitDiff, GitMerge, Globe, Lightning, LockSimple, Play, Sparkle, Warning } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { behindLabel, branchHue, parentName } from "../lib/derive";
import { agentsPill } from "../lib/trace";
import type { Layout } from "../lib/layout";
import { PROFILES, profileOf, tint } from "../theme";
import { ProfileGlyph } from "./ui";

export type HeaderPlanner = PlannerSlice<
  "activeBranch" | "agents" | "branches" | "diffMode" | "forecasts" | "menuOpen" | "model" | "projects" | "running",
  "createBranch" | "goReview" | "openProjects" | "run" | "selectBranch" | "setProfile" | "setTab" | "toggleDiff" | "toggleMenu",
  "branch" | "gate" | "hue" | "mainId" | "onMain" | "parent" | "prelim" | "profile" | "project" | "stale"
>;

export function Header({ planner, layout }: { planner: HeaderPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const { onMain, branch, hue, profile, stale, prelim, gate, project } = derived;
  const wide = layout.wide;
  const nAdded = branch?.n_added ?? 0;
  const parent = parentName(s.branches, branch, derived.mainId);
  const sub = onMain ? "plan of record" : `from ${parent} · ${nAdded} added${prelim.length ? ` · ${prelim.length} preliminary` : ""}`;
  const runLabel = wide ? `${stale.stale ? "Re-run" : "Run"} on ${profile.label}` : stale.stale ? "Re-run" : "Run";
  const pill = agentsPill(s.agents);

  return (
    <header className="header glass">
      <div className="logo" title="GridForge">
        <Lightning size={17} weight="bold" />
      </div>

      <button className="capsule project" onClick={actions.openProjects} title="Projects: switch or import a grid" aria-haspopup="dialog">
        <span className="chip-ic"><Globe size={15} weight="bold" /></span>
        <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", lineHeight: 1.2 }}>
          <span className="nm ellipsis" style={{ maxWidth: wide ? 220 : 120 }}>{project?.name ?? "Loading…"}</span>
          {wide && <span className="sub">{project?.builtin ? "built-in · open data" : project ? "imported" : ""}{s.projects.length > 1 ? ` · ${s.projects.length} projects` : ""}</span>}
        </span>
        <CaretDown size={13} color="var(--mute)" style={{ marginLeft: 6 }} />
      </button>

      <div style={{ position: "relative" }}>
        <button className="capsule" onClick={actions.toggleMenu} aria-haspopup="menu" aria-expanded={s.menuOpen}>
          <span className="chip-ic">{onMain ? <LockSimple size={15} weight="bold" /> : <GitBranch size={15} weight="bold" />}</span>
          <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", lineHeight: 1.2 }}>
            <span className="nm">{onMain ? "main" : (branch?.name ?? s.activeBranch)}</span>
            {wide && (
              <span className="sub">
                {sub}
                {behindLabel(branch, parent) && <span className="behind"> · {behindLabel(branch, parent)}</span>}
              </span>
            )}
          </span>
          <CaretDown size={13} color="var(--mute)" style={{ marginLeft: 6 }} />
        </button>
        {s.menuOpen && <BranchMenu planner={planner} />}
      </div>

      {!onMain && (
        <div style={{ display: "flex", gap: 4 }}>
          <button
            className="btn"
            onClick={actions.toggleDiff}
            title={`Diff vs ${derived.parent}`}
            style={s.diffMode ? { borderColor: hue, background: tint(hue, "24"), color: hue } : undefined}
          >
            <GitDiff size={14} />
            {wide && "Diff"}
          </button>
          <button className="btn hue" onClick={actions.goReview} title={gate.headline} data-gate={gate.state}>
            {gate.state === "blocked" || gate.state === "stale" ? <Warning size={14} weight="bold" /> : <GitMerge size={14} weight="bold" />}
            {wide && "Merge"}
          </button>
        </div>
      )}

      <button className="agents-pill" data-tone={pill.tone} data-live={s.agents?.status === "running" || undefined} title={pill.title} aria-label={pill.title} onClick={() => actions.setTab("ask")}>
        <Sparkle size={12} weight="fill" />
        {wide && pill.label}
      </button>

      <div className="grow" />

      <div style={{ display: "flex", alignItems: "center", gap: 10, flex: "none" }}>
        {wide && <span style={{ fontSize: 11, color: "var(--mute)" }}>Demand</span>}
        <div className="seg" role="radiogroup" aria-label="Demand profile" title={onMain ? "The demand profile main is planned on" : "Demand profile for this branch"}>
          {/* the project's own pathways: an import offers only those entered with it */}
          {PROFILES.filter((p) => !s.forecasts.length || s.forecasts.some((f) => f.id === p.id)).map((p) => {
            const on = p.id === branch?.scenario;
            return (
              <button
                key={p.id}
                role="radio"
                aria-checked={on}
                className={on ? "on" : ""}
                onClick={() => void actions.setProfile(p.id)}
                disabled={branch?.status !== undefined && branch.status !== "open"}
                style={{ padding: wide ? "0 12px" : "0 9px" }}
              >
                <ProfileGlyph bars={p.bars} on={on} />
                {wide ? p.label : p.short}
              </button>
            );
          })}
        </div>
      </div>

      <button className="btn primary" onClick={() => void actions.run()} disabled={s.running || !s.model}>
        <Play size={13} weight="bold" />
        {runLabel}
      </button>
    </header>
  );
}

function BranchMenu({ planner }: { planner: HeaderPlanner }) {
  const { s, actions, derived } = planner;
  const { mainId } = derived;
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const open = s.branches.filter((b) => b.branch_id === mainId || b.status === "open");
  const box = useRef<HTMLDivElement>(null);
  // a click anywhere else closes the menu
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (box.current && !box.current.contains(t) && !(t as HTMLElement).closest?.(".capsule")) actions.toggleMenu();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [actions]);
  return (
    <div className="menu" role="menu" ref={box}>
      {open.map((b) => {
        const hue = branchHue(s.branches, b.branch_id, mainId);
        const on = b.branch_id === (s.activeBranch || mainId);
        return (
          <button
            key={b.branch_id}
            role="menuitem"
            className="menu-row"
            onClick={() => actions.selectBranch(b.branch_id)}
            style={on ? { borderColor: tint(hue, "88"), background: tint(hue, "18") } : undefined}
          >
            <span className="dot" style={{ background: hue, boxShadow: `0 0 0 3px ${tint(hue, "33")}` }} />
            <span style={{ display: "flex", flexDirection: "column", flex: 1, minWidth: 0, lineHeight: 1.3 }}>
              <span className="mono ellipsis" style={{ fontSize: 12.5, fontWeight: 600 }}>{b.branch_id === mainId ? "main" : b.name}</span>
              <span style={{ fontSize: 11, color: "var(--mute)" }}>
                {b.branch_id === mainId ? "plan of record" : `from ${parentName(s.branches, b, mainId)} · ${b.n_added} added · open`}
                {behindLabel(b, parentName(s.branches, b, mainId)) && (
                  <span className="behind" title="its parent received changes after this branch was opened: rebase it from its Review tab before merging">
                    {" "}· {behindLabel(b, parentName(s.branches, b, mainId))}
                  </span>
                )}
              </span>
            </span>
            <span style={{ fontSize: 11, color: "var(--mute)" }}>{profileOf(b.scenario).label}</span>
          </button>
        );
      })}
      <div className="menu-sep" />
      {naming ? (
        <form
          className="menu-input"
          onSubmit={(e) => {
            e.preventDefault();
            void actions.createBranch(name);
          }}
        >
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="branch name, e.g. boston-batteries" aria-label="New branch name" />
          <button className="btn hue" type="submit" style={{ "--hue": "#7ce3ff", "--hue-bd": "#7ce3ff80", "--hue-bg": "#7ce3ff1f" } as CSSProperties}>
            Create
          </button>
        </form>
      ) : (
        <button className="menu-new" onClick={() => setNaming(true)}>
          <GitBranch size={15} />
          New branch from main
        </button>
      )}
    </div>
  );
}
