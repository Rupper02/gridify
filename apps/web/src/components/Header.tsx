// The header: the grid, the branch picker (switch, open a branch from the one in view), the demand profile, the map
// layer, what the map shows, and Run.

import { CaretDown, Clock, Eye, GitBranch, Lightning, Play, Plus, Pulse, Waveform } from "@phosphor-icons/react";
import { useState } from "react";

import { MAIN_ID, type Planner, branchHue } from "../hooks/usePlanner";
import { FEATURE_GROUPS, FEATURE_KEYS, MAP_FEATURES, featureLabel } from "../lib/mapFeatures";
import { PROFILES } from "../theme";
import type { MapLayer } from "../types";
import { ProfileGlyph, Switch } from "./ui";

const LAYERS: { id: MapLayer; label: string; Icon: typeof Pulse }[] = [
  { id: "flow", label: "Flow", Icon: Waveform },
  { id: "loading", label: "Loading", Icon: Pulse },
  { id: "voltage", label: "Voltage", Icon: Lightning },
  { id: "hours", label: "Over rating", Icon: Clock },
];

export function Header({ planner, wide }: { planner: Planner; wide: boolean }) {
  const { s, actions, derived } = planner;
  const [name, setName] = useState<string | null>(null);
  const [showOpen, setShowOpen] = useState(false);
  const branch = derived.branch;
  const open = s.branches.filter((b) => b.status === "open");
  const running = derived.running;
  const submit = () => {
    const n = (name ?? "").trim();
    if (!n) return;
    setName(null);
    void actions.createBranch(n);
  };
  return (
    <header className="header glass">
      <div className="capsule" style={{ borderColor: "rgba(255,255,255,0.14)", background: "rgba(255,255,255,0.05)" }}>
        <span className="chip-ic logo-ic">
          <Lightning size={15} weight="bold" />
        </span>
        <span style={{ display: "flex", flexDirection: "column", lineHeight: 1.15 }}>
          <span className="nm project-nm" style={{ maxWidth: 200 }}>Gridify</span>
          <span className="sub ellipsis" style={{ maxWidth: 200 }}>{s.model?.name ?? "Loading the grid…"}</span>
        </span>
      </div>

      <div style={{ position: "relative" }}>
        <button className="capsule" onClick={() => actions.toggleMenu()} aria-expanded={s.menuOpen}>
          <span className="chip-ic">
            <GitBranch size={15} weight="bold" />
          </span>
          <span style={{ display: "flex", flexDirection: "column", lineHeight: 1.15, alignItems: "flex-start" }}>
            <span className="nm">{branch?.name ?? "main"}</span>
            <span className="sub">{derived.onMain ? "the network as it is today" : `from ${branch?.parent_id === MAIN_ID ? "main" : branch?.parent_id} · ${s.connections.length} connection${s.connections.length === 1 ? "" : "s"}`}</span>
          </span>
          <CaretDown size={13} />
        </button>
        {s.menuOpen && (
          <div className="menu">
            {open.map((b) => (
              <button key={b.branch_id} className="menu-row" onClick={() => void actions.openBranch(b.branch_id)}>
                <span className="dot" style={{ background: branchHue(s.branches, b.branch_id) }} />
                <span className="grow" style={{ display: "flex", flexDirection: "column" }}>
                  <b className="mono" style={{ fontSize: 12.5 }}>{b.name}</b>
                  <span className="mute" style={{ fontSize: 11 }}>
                    {b.branch_id === MAIN_ID ? "plan of record" : `${b.n_connections} connection${b.n_connections === 1 ? "" : "s"}`}
                  </span>
                </span>
                {b.branch_id === s.activeBranch && <span className="mute" style={{ fontSize: 11 }}>viewing</span>}
              </button>
            ))}
            <div className="menu-sep" />
            {name == null ? (
              <button className="menu-new" onClick={() => setName("")}>
                <Plus size={14} weight="bold" /> New branch from {branch?.name ?? "main"}
              </button>
            ) : (
              <div className="menu-input">
                <input autoFocus value={name} placeholder="branch name" onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()} />
                <button className="btn primary sm" onClick={submit} disabled={!name.trim()}>Open</button>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="grow" />

      <div className="seg" role="group" aria-label="Demand profile">
        {PROFILES.map((p) => (
          <button key={p.id} className={branch?.scenario === p.id ? "on" : ""} onClick={() => void actions.setProfile(p.id)} disabled={running} title={`${p.label} demand growth`}>
            <ProfileGlyph bars={p.bars} on={branch?.scenario === p.id} />
            {wide && p.label}
          </button>
        ))}
      </div>

      <div className="seg" role="group" aria-label="Map layer">
        {LAYERS.map(({ id, label, Icon }) => (
          <button key={id} className={s.layer === id ? "on" : ""} onClick={() => actions.setLayer(id)} title={label}>
            <Icon size={14} />
            {wide && label}
          </button>
        ))}
      </div>

      <div style={{ position: "relative" }}>
        <button className="btn" onClick={() => setShowOpen((o) => !o)} aria-expanded={showOpen}>
          <Eye size={14} /> Show
        </button>
        {showOpen && (
          <div className="show-menu glass">
            {FEATURE_GROUPS.map((g) => (
              <div key={g} className="show-group">
                <span className="show-head">{g}</span>
                {FEATURE_KEYS.filter((k) => MAP_FEATURES[k].group === g).map((k) => {
                  const label = featureLabel(k, derived.tiers);
                  if (!label) return null;
                  const on = s.visible.includes(k);
                  return (
                    <div key={k} className="show-row">
                      <button className="show-label" onClick={() => actions.toggleFeature(k)}>
                        <span className="ellipsis">{label}</span>
                        <Switch on={on} />
                      </button>
                      <button className={`show-only${s.visible.length === 1 && on ? " on" : ""}`} onClick={() => actions.onlyFeature(k)} title={`Only ${label}`}>
                        <Eye size={12} />
                      </button>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        )}
      </div>

      <button className="btn primary" onClick={() => void actions.run()} disabled={running || !s.activeBranch}>
        <Play size={14} weight="fill" /> {running ? "Running…" : "Run"}
      </button>
    </header>
  );
}
