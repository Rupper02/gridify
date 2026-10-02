// Review: branches (create / select / diff / suggestions / merge / discard), the registry of
// projected projects to pull onto a branch, the consequence diff and the copilot suggestions.

import type { Planner } from "../hooks/usePlanner";
import { BSTAT, CHG, ST, deltaColor, fmtMw, signed, signedV, techLabel } from "../theme";
import { TechIcon } from "./TechIcon";

export function ReviewTab({ planner }: { planner: Planner }) {
  const { s, patch, actions, derived } = planner;
  const { q, reviewB, hasReviewBranch, onMainView } = derived;
  const branchActionsDisabled = !reviewB || reviewB.status !== "open";
  const scenLabel = (id: string) => s.forecasts.find((y) => y.id === id)?.label ?? (id || "custom");
  const visibleBranches = s.branches.filter((b) => b.status !== "discarded" || b.branch_id === s.activeBranch);

  // registry: pull projected projects onto the active branch; hide the ones already on it
  const onBranchIds = new Set(hasReviewBranch ? [...q.map((x) => x.request_id), ...Object.keys(s.pendingAdds)] : []);
  const needle = s.registryQuery.toLowerCase();
  const regList = s.registry.filter(
    (c) => !onBranchIds.has(c.request_id) && (!needle || `${c.request_id} ${c.applicant || ""} ${c.technology || ""} bus ${c.bus_id}`.toLowerCase().includes(needle)),
  );

  const d = s.diff;
  const hl = d?.headline;
  const movers = d ? d.projects.filter((p) => p.change !== "unchanged") : [];

  return (
    <div className="review">
      <div className="box">
        <div className="box-head">
          <div className="col" style={{ lineHeight: 1.3 }}>
            <span className="t">Branches</span>
            <span className="d">Branch off <b>main</b>, propose a change, review the consequence, then merge.</span>
          </div>
          <button className="btn sm" onClick={() => patch({ showNewBranch: !s.showNewBranch })}>{s.showNewBranch ? "Cancel" : "＋ New branch"}</button>
        </div>
        {s.showNewBranch && (
          <div className="subbox">
            <input className="field" style={{ height: 32 }} value={s.newBranchName} onChange={(e) => patch({ newBranchName: e.target.value })} placeholder="Branch name, e.g. ‘Connect the Bicker Fen batteries’" />
            <span className="caps">Demand profile — the scenario this branch is tested against</span>
            <div className="row" style={{ gap: 6 }}>
              <select className="field" style={{ flex: 1, minWidth: 0, height: 32, padding: "0 8px" }} value={s.newBranchForecast} onChange={(e) => patch({ newBranchForecast: e.target.value })}>
                {s.forecasts.map((x) => (
                  <option key={x.id} value={x.id}>FES 2025 · {x.label}</option>
                ))}
              </select>
              <button className="btn dark md" disabled={s.creatingBranch} style={{ background: s.creatingBranch ? "#9ca3af" : undefined }} onClick={() => void actions.createBranchFlow()}>
                {s.creatingBranch ? "Creating…" : "Create"}
              </button>
            </div>
            <span style={{ fontSize: 11, color: "var(--mute)" }}>A branch is a safe copy of <b>main</b>. Add projects or change the demand profile, review the consequence, then merge.</span>
          </div>
        )}
        <div className="col" style={{ gap: 4 }}>
          {visibleBranches.map((b) => {
            const isMain = b.branch_id === "main";
            const isSel = b.branch_id === s.activeBranch;
            const st = BSTAT[b.status] ?? BSTAT.open;
            return (
              <button key={b.branch_id} className="branch-row" style={{ borderColor: isSel ? "var(--ink)" : "var(--bd)", background: isSel ? "#f3f4f6" : "#fff", opacity: b.status === "discarded" ? 0.5 : 1 }} onClick={() => actions.selectBranch(b.branch_id)}>
                <span className="name">{isMain ? "main · plan of record" : b.name}</span>
                {!isMain && <span className="chip sm" style={{ background: st.bg, color: st.fg, fontSize: 10 }}>{st.label}</span>}
                <span className="meta">{b.n_added ? `${b.n_added}＋ · ` : ""}FES {scenLabel(b.scenario)}</span>
              </button>
            );
          })}
        </div>
        {hasReviewBranch && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, paddingTop: 8, borderTop: "1px solid var(--bd)" }}>
            <button className="btn dark md" disabled={s.comparing} onClick={() => void actions.runBranchDiff()}>{s.comparing ? "Diffing…" : "Diff vs main"}</button>
            <button className="btn md" disabled={s.loadingSuggestions} onClick={() => void actions.runSuggestions()}>{s.loadingSuggestions ? "Thinking…" : "Suggestions"}</button>
            <div className="grow" />
            <button className="btn green md" disabled={branchActionsDisabled} style={{ background: branchActionsDisabled ? "#9ca3af" : undefined }} onClick={() => void actions.mergeBranchFlow()}>Merge to main</button>
            <button className="btn md" disabled={branchActionsDisabled} style={{ color: branchActionsDisabled ? "#9ca3af" : "#b91c1c" }} onClick={() => void actions.discardBranchFlow()}>Discard</button>
          </div>
        )}
      </div>

      <div className="box">
        <div className="box-head">
          <div className="col" style={{ lineHeight: 1.3 }}>
            <span className="t">Registry · projected projects</span>
            <span className="d">{onMainView ? "Adding a project opens a new branch off main (main stays the plan of record)." : `Projects are added to ${reviewB?.name ?? "this branch"}.`}</span>
          </div>
          <button className="btn sm" onClick={actions.toggleRegistry}>{s.showRegistry ? "Hide registry" : "Browse registry"}</button>
        </div>
        {s.showRegistry && (
          <div className="col" style={{ gap: 8 }}>
            <input className="field sm" value={s.registryQuery} onChange={(e) => patch({ registryQuery: e.target.value })} placeholder="Search registry — ID, applicant, tech, bus…" />
            <div className="col" style={{ gap: 4, maxHeight: 280, overflow: "auto" }}>
              {regList.map((c) => (
                <div key={c.request_id} className="reg-row">
                  <div style={{ minWidth: 0 }}>
                    <div className="row" style={{ gap: 6 }}>
                      <span className="mono" style={{ fontSize: 12.5, fontWeight: 600 }}>{c.request_id}</span>
                      <span className="ellipsis" style={{ fontSize: 12, color: "var(--ink2)" }}>{c.applicant || "—"}</span>
                    </div>
                    <div className="row" style={{ gap: 5, fontSize: 11, color: "var(--mute2)" }}>
                      <TechIcon tech={c.technology} />
                      <span>{techLabel(c.technology) ?? "Unknown tech"} · {fmtMw(c.rating_mw)} MW · bus {c.bus_id ?? "—"} · ready {Math.round((c.readiness_score || 0) * 100)}%</span>
                    </div>
                  </div>
                  <button className="btn dark sm" style={{ padding: "0 13px" }} onClick={() => void actions.addRegistryProject(c.request_id)}>Add</button>
                </div>
              ))}
            </div>
            {s.registryLoaded && regList.length === 0 && <div className="empty" style={{ padding: 14, fontSize: 12 }}>No registry projects match — or they're all on this branch already.</div>}
          </div>
        )}
      </div>

      {hasReviewBranch && (
        <div className="banner">
          <span style={{ fontSize: 15, lineHeight: 1 }}>⎇</span>
          <span>You're on branch <b>{reviewB?.name}</b> — the map, Queue and roadmap show this <b>proposal</b>. <b>main</b> (the plan of record) stays unchanged until you <b>Merge</b>.</span>
        </div>
      )}
      {!d && (
        <div className="empty" style={{ padding: "24px 14px" }}>
          {hasReviewBranch ? "Press Diff vs main to see this branch’s consequence." : "Create or select a branch, then Diff vs main to see the consequence."}
        </div>
      )}

      {d && hl && (
        <div className="col" style={{ gap: 14 }}>
          <div className="mono" style={{ fontSize: 11, color: "var(--mute)" }}>{reviewB ? `main  →  ${reviewB.name}` : ""}</div>
          {d.narration && <p className="narration pretty">{d.narration}</p>}
          <div className="cmp-tiles">
            {[
              { key: "mw30", label: "MW by 2030", base: fmtMw(hl.mw_2030_base), head: fmtMw(hl.mw_2030_head), delta: `${signed(hl.mw_2030_delta)} MW`, color: deltaColor(hl.mw_2030_delta, true) },
              { key: "mw35", label: "MW by 2035", base: fmtMw(hl.mw_2035_base), head: fmtMw(hl.mw_2035_head), delta: `${signed(hl.mw_2035_delta)} MW`, color: deltaColor(hl.mw_2035_delta, true) },
              { key: "conn", label: "Connected", base: String(hl.n_connected_base), head: String(hl.n_connected_head), delta: signed(hl.n_connected_head - hl.n_connected_base), color: deltaColor(hl.n_connected_head - hl.n_connected_base, true) },
              { key: "def", label: "Deferred", base: String(hl.n_deferred_base), head: String(hl.n_deferred_head), delta: signed(hl.n_deferred_head - hl.n_deferred_base), color: deltaColor(hl.n_deferred_head - hl.n_deferred_base, false) },
            ].map((t) => (
              <div key={t.key} className="cmp-tile">
                <div className="caps-sm" style={{ letterSpacing: "0.04em", color: "var(--mute)" }}>{t.label}</div>
                <div className="vals">
                  <span className="mono" style={{ fontSize: 15, color: "var(--mute2)" }}>{t.base}</span>
                  <span style={{ color: "var(--mute2)" }}>→</span>
                  <span className="mono" style={{ fontSize: 18, fontWeight: 600 }}>{t.head}</span>
                  <span className="mono" style={{ fontSize: 12, fontWeight: 600, color: t.color, marginLeft: "auto" }}>{t.delta}</span>
                </div>
              </div>
            ))}
          </div>

          <div>
            <div className="caps-sm" style={{ marginBottom: 6 }}>Network effect — what needs attention</div>
            {d.phases.map((pp) => (
              <div key={pp.phase} className="phase-box">
                <div className="row" style={{ marginBottom: 6 }}>
                  <span className="mono" style={{ fontSize: 12.5, fontWeight: 600 }}>{pp.phase}</span>
                  <span style={{ fontSize: 11.5, color: "var(--mute)" }}>connected {fmtMw(pp.mw_connected_base)} → {fmtMw(pp.mw_connected_head)} MW</span>
                  <span className="mono" style={{ fontSize: 11.5, fontWeight: 600, color: deltaColor(pp.mw_connected_delta, true), marginLeft: "auto" }}>{signed(pp.mw_connected_delta)} MW</span>
                </div>
                <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 11.5, color: "var(--ink3)" }}>
                  <span>Worst line <b className="mono" style={{ color: deltaColor(pp.worst_line_delta, false) }}>{signed(pp.worst_line_delta)}%</b></span>
                  <span>Voltage <b className="mono" style={{ color: "var(--ink)" }}>min {signedV(pp.min_vm_delta)} · max {signedV(pp.max_vm_delta)} pu</b></span>
                </div>
                {pp.newly_overloaded_line_ids.length > 0 && <div style={{ marginTop: 6, fontSize: 11.5, color: "#991b1b" }}>⚠ Newly overloaded lines: {pp.newly_overloaded_line_ids.join(", ")}</div>}
                {pp.cleared_line_ids.length > 0 && <div style={{ marginTop: 4, fontSize: 11.5, color: "#166534" }}>✓ Cleared lines: {pp.cleared_line_ids.join(", ")}</div>}
              </div>
            ))}
          </div>

          <div>
            <div className="caps-sm" style={{ marginBottom: 4 }}>Who moved</div>
            {movers.map((p) => {
              const cg = CHG[p.change] ?? CHG.unchanged;
              const bs = p.base_status ? ST[p.base_status] : null;
              const hs = p.head_status ? ST[p.head_status] : null;
              const reason = p.head_reason ? p.head_reason.short || p.head_reason.why || p.head_reason.message : "";
              return (
                <div key={p.request_id} className="mover" onClick={() => actions.selectProject(p.request_id)}>
                  <div className="row">
                    <span className="mono" style={{ fontSize: 12.5, fontWeight: 600 }}>{p.request_id}</span>
                    <span className="chip sm" style={{ background: cg.bg, color: cg.fg, fontSize: 10.5, padding: "2px 7px", borderRadius: 5 }}>{cg.label}</span>
                    <span className="mono" style={{ fontSize: 11, color: "var(--mute)", marginLeft: "auto" }}>
                      {p.rank_delta != null && p.rank_delta !== 0 ? (p.rank_delta < 0 ? `▲ ${-p.rank_delta}` : `▼ ${p.rank_delta}`) : ""}
                    </span>
                  </div>
                  <div className="row" style={{ gap: 6, fontSize: 11.5, flexWrap: "wrap" }}>
                    <span className="chip sm" style={{ background: bs?.bg ?? "#f3f4f6", color: bs?.fg ?? "#9ca3af" }}>{bs?.short ?? "—"}</span>
                    <span style={{ color: "var(--mute2)" }}>→</span>
                    <span className="chip sm" style={{ background: hs?.bg ?? "#f3f4f6", color: hs?.fg ?? "#9ca3af" }}>{hs?.short ?? "—"}</span>
                    <span style={{ color: "var(--mute)" }}>{techLabel(p.technology) ?? "—"} · {fmtMw(p.rating_mw)} MW · bus {p.bus_id ?? "—"}</span>
                  </div>
                  {reason && <div style={{ fontSize: 11.5, color: "#92400e" }}>{reason}</div>}
                </div>
              );
            })}
            {movers.length === 0 && <div className="empty" style={{ padding: 16 }}>No projects changed on this branch versus main.</div>}
          </div>
        </div>
      )}

      {s.suggestions != null && (
        <div className="col" style={{ gap: 8 }}>
          <div className="row" style={{ gap: 7 }}>
            <span className="caps-sm">Copilot · what would it take</span>
            <span style={{ fontSize: 11, color: "var(--mute2)" }}>{reviewB ? `on ${reviewB.name}` : ""}</span>
          </div>
          {s.suggestions.length === 0 && <div className="empty" style={{ padding: 16 }}>No grid-constrained deferrals on this branch — nothing to unblock.</div>}
          {s.suggestions.map((x, i) => (
            <div key={i} className="sugg">
              <div className="row">
                <span style={{ fontSize: 12.5, fontWeight: 600 }}>{x.action}</span>
                <span className="chip sm" style={{ marginLeft: "auto", background: x.connects_target ? "#dcfce7" : "#fef3c7", color: x.connects_target ? "#166534" : "#92400e", fontSize: 10.5, padding: "2px 7px", borderRadius: 5 }}>{x.connects_target ? "connects" : "partial"}</span>
              </div>
              <div className="mono" style={{ fontSize: 12, color: "#166534", fontWeight: 600 }}>
                Frees ≈{fmtMw(x.freed_mw_2035)} MW by 2035{x.freed_mw_2030 !== x.freed_mw_2035 ? ` (≈${fmtMw(x.freed_mw_2030)} by 2030)` : ""}
              </div>
              {x.newly_connected_project_ids.length > 0 && (
                <div className="row" style={{ gap: 5, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 11, color: "var(--mute)" }}>Connects</span>
                  {x.newly_connected_project_ids.map((id) => <span key={id} className="idchip" style={{ fontWeight: 600, background: "#dcfce7", color: "#166534" }}>{id}</span>)}
                </div>
              )}
              {x.blocked_project_ids.length > 0 && (
                <div className="row" style={{ gap: 5, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 11, color: "var(--mute2)" }}>For deferred</span>
                  {x.blocked_project_ids.map((id) => <span key={id} className="idchip" style={{ background: "#f3f4f6", color: "var(--mute)" }}>{id}</span>)}
                </div>
              )}
              {x.narration && <p className="narration pretty">{x.narration}</p>}
              <div className="pretty" style={{ fontSize: 10.5, color: "var(--mute2)" }}>{x.caveat}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
