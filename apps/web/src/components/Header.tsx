// The floating header: logo, branch capsule + menu, Diff / Merge on a branch, the demand profile
// control and the Run button ("Re-run" when the shown result is out of date).

import { CaretDown, GitBranch, GitDiff, GitMerge, Lightning, LockSimple, Play, Warning } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { branchHue } from "../lib/derive";
import type { Layout } from "../lib/layout";
import { PROFILES, profileOf, tint } from "../theme";
import { ProfileGlyph } from "./ui";

export type HeaderPlanner = PlannerSlice<
  "activeBranch" | "branches" | "diffMode" | "menuOpen" | "running",
  "createBranch" | "goReview" | "run" | "selectBranch" | "setProfile" | "toggleDiff" | "toggleMenu",
  "branch" | "gate" | "hue" | "onMain" | "prelim" | "profile" | "stale"
>;

export function Header({ planner, layout }: { planner: HeaderPlanner; layout: Layout }) {
  const { s, actions, derived } = planner;
  const { onMain, branch, hue, profile, stale, prelim, gate } = derived;
  const wide = layout.wide;
  const nAdded = branch?.n_added ?? 0;
  const sub = onMain ? "plan of record" : `from main · ${nAdded} added${prelim.length ? ` · ${prelim.length} preliminary` : ""}`;
  const runLabel = wide ? `${stale.stale ? "Re-run" : "Run"} on ${profile.label}` : stale.stale ? "Re-run" : "Run";

  return (
    <header className="header glass">
      <div className="logo" title="GridForge · NGED Bicker Fen 132 kV GSP">
        <Lightning size={17} weight="bold" />
      </div>

      <div style={{ position: "relative" }}>
        <button className="capsule" onClick={actions.toggleMenu} aria-haspopup="menu" aria-expanded={s.menuOpen}>
          <span className="chip-ic">{onMain ? <LockSimple size={15} weight="bold" /> : <GitBranch size={15} weight="bold" />}</span>
          <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", lineHeight: 1.2 }}>
            <span className="nm">{onMain ? "main" : (branch?.name ?? s.activeBranch)}</span>
            {wide && <span className="sub">{sub}</span>}
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
            title="Diff vs main"
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

      <div className="grow" />

      <div style={{ display: "flex", alignItems: "center", gap: 10, flex: "none" }}>
        {wide && <span style={{ fontSize: 11, color: "var(--mute)" }}>Demand</span>}
        <div className="seg" role="radiogroup" aria-label="Demand profile" title={onMain ? "The demand profile main is planned on" : "Demand profile for this branch"}>
          {PROFILES.map((p) => {
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

      <button className="btn primary" onClick={() => void actions.run()} disabled={s.running}>
        <Play size={13} weight="bold" />
        {runLabel}
      </button>
    </header>
  );
}

function BranchMenu({ planner }: { planner: HeaderPlanner }) {
  const { s, actions } = planner;
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const open = s.branches.filter((b) => b.branch_id === "main" || b.status === "open");
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
        const hue = branchHue(s.branches, b.branch_id);
        const on = b.branch_id === (s.activeBranch || "main");
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
              <span className="mono ellipsis" style={{ fontSize: 12.5, fontWeight: 600 }}>{b.branch_id === "main" ? "main" : b.name}</span>
              <span style={{ fontSize: 11, color: "var(--mute)" }}>{b.branch_id === "main" ? "plan of record" : `from main · ${b.n_added} added · open`}</span>
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
