import type { Planner } from "../hooks/usePlanner";
import { ADDED_ID_BASE, EVID, TECH } from "../theme";
import type { Tech } from "../types";

export function AddProjectDrawer({ planner }: { planner: Planner }) {
  const { s, patch, actions, derived, formInvalid } = planner;
  const { onMainView, reviewB } = derived;
  const f = s.form;
  const mwN = +f.mw;
  const mwWarn = mwN > s.maxMw;
  const nextId = `CR-${ADDED_ID_BASE + s.cands.filter((c) => c.manual).length}`;
  const busOpts = s.model ? [...s.model.buses].sort((a, b) => a.vn_kv - b.vn_kv || a.bus_id - b.bus_id) : [];
  const readyFg = f.readiness >= 0.6 ? "#166534" : f.readiness >= 0.35 ? "#1e40af" : "#92400e";
  const close = () => patch({ drawer: false, pickMode: false });
  return (
    <div className="drawer">
      <div className="drawer-head">
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>New connection application</div>
          <div style={{ fontSize: 11.5, color: "var(--mute)", marginTop: 2 }}>
            {onMainView ? "Opens a new branch off main and joins its queue, ranked on the next run." : `Joins branch ${reviewB?.name ?? "this branch"} as ${nextId}, ranked on the next run.`}
          </div>
        </div>
        <button className="btn icon" style={{ width: 26, height: 26, fontSize: 16 }} onClick={close}>×</button>
      </div>
      <div className="drawer-body">
        <label className="col" style={{ gap: 5 }}>
          <span className="flabel">Project / applicant</span>
          <input className="field" style={{ fontSize: 13 }} value={f.name} onChange={(e) => actions.setForm({ name: e.target.value })} placeholder="e.g. Sleaford Fen Solar" />
        </label>
        <div className="col" style={{ gap: 5 }}>
          <span className="flabel">Technology</span>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 6 }}>
            {(Object.keys(TECH) as Tech[]).map((t) => (
              <button key={t} className={`seg${f.tech === t ? " on" : ""}`} onClick={() => actions.setForm({ tech: t })}>{TECH[t]}</button>
            ))}
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <label className="col" style={{ gap: 5 }}>
            <span className="flabel">Capacity (MW)</span>
            <input className="field mono" type="number" min={0.1} step={0.5} value={f.mw} onChange={(e) => actions.setForm({ mw: e.target.value })} style={{ fontSize: 13, borderColor: mwWarn ? "#f87171" : undefined }} />
          </label>
          <div className="col" style={{ gap: 5 }}>
            <span className="flabel">Point of connection</span>
            <div className="row" style={{ gap: 6 }}>
              <select className="field mono" style={{ flex: 1, minWidth: 0, padding: "0 6px" }} value={f.bus} onChange={(e) => actions.setForm({ bus: e.target.value })}>
                <option value="">Bus…</option>
                {busOpts.map((b) => (
                  <option key={b.bus_id} value={String(b.bus_id)}>Bus {b.bus_id}{b.vn_kv != null ? ` · ${b.vn_kv} kV` : ""}</option>
                ))}
              </select>
              <button className="btn" title="Pick a bus on the network" style={{ padding: "0 9px", fontSize: 11.5, background: s.pickMode ? "#1d4ed8" : undefined, color: s.pickMode ? "#fff" : undefined, borderColor: s.pickMode ? "#1d4ed8" : undefined }} onClick={() => patch({ pickMode: !s.pickMode, sel: null })}>
                Map
              </button>
            </div>
          </div>
        </div>
        {mwWarn && <div style={{ marginTop: -8, fontSize: 11.5, color: "#b91c1c" }}>Above the {s.maxMw} MW connection cap for this network — will be rejected at intake.</div>}
        <div className="col" style={{ gap: 6 }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
            <span className="flabel">Readiness evidence</span>
            <span className="mono" style={{ fontSize: 13, fontWeight: 600, color: readyFg }}>{Math.round(f.readiness * 100)}%</span>
          </div>
          {EVID.map((e) => {
            const on = f[e.k];
            return (
              <button key={e.k} className="evidence" style={{ borderColor: on ? "var(--mute2)" : "var(--bd)", background: on ? "#f9fafb" : "#fff" }} onClick={() => actions.setForm({ [e.k]: !on })}>
                <span className="box" style={{ borderColor: on ? "var(--ink)" : "var(--bd2)", background: on ? "var(--ink)" : "#fff" }}>{on ? "✓" : ""}</span>
                <span style={{ flex: 1, fontSize: 12.5, color: "var(--ink)" }}>{e.label}</span>
                <span className="mono" style={{ fontSize: 11, color: "var(--mute2)" }}>+{Math.round(e.w * 100)}%</span>
              </button>
            );
          })}
          <input type="range" min={0} max={1} step={0.01} value={f.readiness} onChange={(e) => actions.setForm({ readiness: +e.target.value })} style={{ width: "100%", marginTop: 4 }} />
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10.5, color: "var(--mute2)" }}>
            <span>Speculative</span><span>Phase 2 ≥ 35%</span><span>Phase 1 ≥ 60%</span><span>Shovel-ready</span>
          </div>
        </div>
      </div>
      <div className="drawer-foot">
        <button className="btn lg" onClick={close}>Cancel</button>
        <div className="grow" />
        <button className="btn lg" disabled={formInvalid} style={{ color: formInvalid ? "#9ca3af" : undefined }} onClick={() => void actions.submit(false)}>Add to queue</button>
        <button className="btn primary lg" disabled={formInvalid} style={{ background: formInvalid ? "#9ca3af" : undefined, padding: "0 16px" }} onClick={() => void actions.submit(true)}>Add &amp; re-run</button>
      </div>
    </div>
  );
}
