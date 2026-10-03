// Review: the branch against main as a consequence diff (the four tiles, the network effect, what
// changed), the reinforcements proposed on it, then Merge into main or Discard. main has nothing to
// review.

import { ArrowRight, Check, GitMerge, LockSimple, Trash, Warning } from "@phosphor-icons/react";

import type { PlannerSlice } from "../hooks/planner/slice";
import { lineName, nameElements } from "../lib/derive";
import { C, ST, fmtMw, profileOf, signed, tint } from "../theme";
import type { Diff, Status } from "../types";
import { DiffTile } from "./ui";

export type ReviewTabPlanner = PlannerSlice<
  "branches" | "diff" | "reinforcements",
  "createBranch" | "discardBranch" | "mergeBranch" | "removeReinforcement",
  "branch" | "hue" | "ix" | "onMain"
>;

const statusLabel = (st: Status | null, year?: number | null): string =>
  st == null ? "not on main" : st === "Phase1" || st === "Phase2" ? `${ST[st].label}${year ? ` · ${year}` : ""}` : ST[st].label;

export function ReviewTab({ planner }: { planner: ReviewTabPlanner }) {
  const { s, actions, derived } = planner;
  const { branch, hue, ix } = derived;
  if (derived.onMain)
    return (
      <div className="scroll" style={{ padding: "4px 14px 16px", gap: 12 }}>
        <div className="empty" style={{ padding: 18, gap: 10 }}>
          <LockSimple size={20} color={C.mute} />
          <b style={{ fontSize: 13 }}>main has nothing to review</b>
          <span>It is the plan of record. Open a branch, add projects or change the demand profile, then compare it here.</span>
          <button className="btn" style={{ borderColor: "rgba(124,227,255,0.45)", background: "rgba(124,227,255,0.12)", color: C.accent }} onClick={() => void actions.createBranch()}>
            New branch
          </button>
        </div>
      </div>
    );

  const main = s.branches.find((b) => b.branch_id === "main");
  const mismatch = main && branch && main.scenario !== branch.scenario;
  const d = s.diff;
  const open = branch?.status === "open";
  return (
    <div className="scroll" style={{ padding: "4px 14px 16px", gap: 12 }}>
      <div className="mono" style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
        <span style={{ color: C.mute }}>main</span>
        <ArrowRight size={12} color={C.mute2} />
        <span style={{ color: hue, fontWeight: 600 }}>{branch?.name}</span>
      </div>
      {mismatch && (
        <div className="notice amber">
          main is tested on {profileOf(main!.scenario).label} and this branch on {profileOf(branch!.scenario).label}. Part of the difference below comes from demand, not from
          the projects you added.
        </div>
      )}
      {!d ? (
        <span className="mute" style={{ fontSize: 12 }}>Comparing with main…</span>
      ) : (
        <>
          {d.narration && <span style={{ fontSize: 12.5, lineHeight: 1.5, color: C.ink3 }}>{d.narration}</span>}
          <Tiles d={d} />
          <NetworkEffect d={d} name={(id) => (ix ? lineName(ix, id) : `Line ${id}`)} />
          <Changed d={d} name={(t) => nameElements(t, ix)} />
        </>
      )}
      {s.reinforcements.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>Proposed reinforcements</span>
          {s.reinforcements.map((r) => (
            <div key={r.reinforcement_id} className="mrow">
              <GitMerge size={13} color={hue} />
              <span className="ellipsis" style={{ fontSize: 12 }}>{r.label || `${r.action} ${r.kind} ${r.element_id}`}</span>
              <button className="icon-btn sm" onClick={() => void actions.removeReinforcement(r.reinforcement_id)} title="Remove" aria-label="Remove reinforcement" disabled={!open}>
                <Trash size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, paddingTop: 4 }}>
        <button className="btn solid-hue grow" onClick={() => void actions.mergeBranch()} disabled={!open}>
          <GitMerge size={14} weight="bold" />
          Merge into main
        </button>
        <button className="btn danger" onClick={() => void actions.discardBranch()} disabled={!open}>
          Discard
        </button>
      </div>
      {!open && <span className="mute" style={{ fontSize: 11.5 }}>This branch is {branch?.status}. Open a new one to propose more.</span>}
    </div>
  );
}

function Tiles({ d }: { d: Diff }) {
  const h = d.headline;
  const tile = (label: string, base: number, head: number, moreIsGood: boolean) => {
    const delta = head - base;
    const c = delta === 0 ? C.mute : delta > 0 === moreIsGood ? C.greenInk : C.redInk;
    return <DiffTile key={label} label={label} base={fmtMw(base)} head={fmtMw(head)} delta={delta === 0 ? "0" : signed(delta)} c={c} />;
  };
  return (
    <div className="tiles">
      {tile("MW by 2030", h.mw_2030_base ?? 0, h.mw_2030_head ?? 0, true)}
      {tile("MW by 2035", h.mw_2035_base ?? 0, h.mw_2035_head ?? 0, true)}
      {tile("Connected", h.n_connected_base ?? 0, h.n_connected_head ?? 0, true)}
      {tile("Deferred", h.n_deferred_base ?? 0, h.n_deferred_head ?? 0, false)}
    </div>
  );
}

function NetworkEffect({ d, name }: { d: Diff; name: (id: number) => string }) {
  const items: { bad: boolean; good?: boolean; text: string }[] = [];
  d.phases.forEach((p) => {
    p.newly_overloaded_line_ids.forEach((id) => {
      const td = p.top_line_deltas.find((x) => x.line_id === id);
      items.push({ bad: true, text: `${name(id)} newly over 100% by ${p.phase}${td ? ` (${Math.round(td.base_pct)}% to ${Math.round(td.head_pct)}%)` : ""}.` });
    });
    p.cleared_line_ids.forEach((id) => items.push({ bad: false, good: true, text: `${name(id)} back within its rating by ${p.phase}.` }));
    p.top_line_deltas
      .filter((t) => Math.abs(t.delta) >= 5 && !p.newly_overloaded_line_ids.includes(t.line_id))
      .slice(0, 3)
      .forEach((t) => items.push({ bad: t.delta > 0 && t.head_pct > 90, good: t.delta < 0, text: `${name(t.line_id)} ${t.delta > 0 ? "rises" : "falls"} from ${Math.round(t.base_pct)}% to ${Math.round(t.head_pct)}% by ${p.phase}.` }));
    if (Math.abs(p.worst_line_delta) >= 1)
      items.push({ bad: p.worst_line_delta > 0, good: p.worst_line_delta < 0, text: `Worst line loading ${p.worst_line_delta > 0 ? "rises" : "falls"} ${Math.abs(Math.round(p.worst_line_delta))} points by ${p.phase}.` });
    if (Math.abs(p.min_vm_delta) >= 0.002)
      items.push({ bad: p.min_vm_delta < 0, good: p.min_vm_delta > 0, text: `Lowest voltage ${p.min_vm_delta > 0 ? "lifts" : "drops"} ${Math.abs(p.min_vm_delta).toFixed(3)} pu by ${p.phase}.` });
  });
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>Network effect</span>
      <div className="well" style={{ display: "flex", flexDirection: "column", gap: 6, padding: "11px 12px", fontSize: 12, lineHeight: 1.45 }}>
        {items.length ? (
          items.slice(0, 8).map((x, i) => (
            <span key={i} style={{ color: x.bad ? C.redInk : x.good ? C.greenInk : C.ink2, display: "flex", gap: 6 }}>
              {x.bad ? <Warning size={12} style={{ flex: "none", marginTop: 3 }} /> : x.good ? <Check size={12} style={{ flex: "none", marginTop: 3 }} /> : <ArrowRight size={12} style={{ flex: "none", marginTop: 3 }} />}
              {x.text}
            </span>
          ))
        ) : (
          <span className="mute">No material change to loadings or voltages at 2030 or 2035.</span>
        )}
      </div>
    </div>
  );
}

function Changed({ d, name }: { d: Diff; name: (t: string) => string }) {
  const movers = d.projects.filter((p) => p.change !== "unchanged");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>What changed</span>
      {!movers.length && <span className="mute" style={{ fontSize: 12 }}>No project moved.</span>}
      {movers.map((p) => {
        const to = p.head_status;
        const c = to ? ST[to].c : C.mute;
        return (
          <div key={p.request_id} className="mover">
            <span className="mono" style={{ fontSize: 12.5, fontWeight: 600 }}>{p.request_id}</span>
            <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, whiteSpace: "nowrap", minWidth: 0 }}>
              <span style={{ padding: "1px 7px", borderRadius: 999, background: "rgba(255,255,255,0.06)", color: C.mute }}>{statusLabel(p.base_status)}</span>
              <ArrowRight size={11} color={C.mute2} />
              <span style={{ padding: "1px 7px", borderRadius: 999, background: tint(c, "22"), color: c }}>{to ? statusLabel(to) : "dropped"}</span>
            </span>
            <span className="mono" style={{ fontSize: 11.5, color: C.mute }}>{fmtMw(p.rating_mw)} MW</span>
            <span className="ellipsis" style={{ gridColumn: "2 / -1", fontSize: 11, color: C.mute }}>
              {p.head_reason ? name(p.head_reason.short) : p.rank_delta ? `rank ${p.rank_delta > 0 ? "down" : "up"} ${Math.abs(p.rank_delta)}` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}
