// GridForge API client: a thin wrapper over the FastAPI backend (apps/api), exposed as
// window.GridForgeAPI. Every call goes to config.base; deferral reasons are normalised for the UI.
(function () {
  const config = { base: "http://localhost:8000" };
  const MAX_MW = 300;  // intake cap — mirrors gridforge_optimizer.config.MAX_CONNECTION_MW; the API sends the real value

  const getJson = async (path) => (await fetch(`${config.base}${path}`)).json();
  const postJson = async (path, body) => (await fetch(`${config.base}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  })).json();

  // Normalize a deferral/rejection reason from the API ({type, element_id, value, message, case})
  // into a single shape the UI renders everywhere:
  // { kind, element:{line_id|bus_id}, short, why (plain English), action (what to do next) }.
  // Which planning study case a grid limit bites in — so the operator knows WHEN it's a problem.
  const _CASE_WHY = {
    summer_min: " This bites at summer minimum demand — a sunny, low-demand day when little local load is there to soak up the export and the wires are on their lower summer rating.",
    winter_peak: " This bites at winter peak demand.",
  };
  function _normReason(reason, item) {
    const out = _normReasonCore(reason, item);
    // (a GSP reason already names its case in the message, and explains it itself)
    if (out && out.kind === "grid" && reason && reason.type !== "gsp" && reason.case && _CASE_WHY[reason.case]) {
      out.why = `${out.why}${_CASE_WHY[reason.case]}`;
      out.caseLabel = reason.case === "summer_min" ? "summer minimum" : "winter peak";
    }
    return out;
  }
  function _normReasonCore(reason, item) {
    if (!reason) return reason;
    const it = item || {};
    const t = reason.type;
    const val = typeof reason.value === "number" ? reason.value : null;
    const msg = reason.message || "";
    const eid = reason.element_id != null
      ? reason.element_id
      : (reason.element ? (reason.element.line_id != null ? reason.element.line_id : reason.element.bus_id) : null);
    const pct = val != null ? Math.round(val) : null;
    const base = { ...reason, message: msg, value: val };

    if (t === "gsp") {
      // the transmission boundary: no distribution-side reinforcement can fix this
      const mw = val != null ? Math.round(val) : null;
      return { ...base, kind: "grid", element: null,
        short: `GSP export limit — the region would push ${mw != null ? `${mw} MW` : "too much"} up to transmission`,
        why: `${msg ? msg.charAt(0).toUpperCase() + msg.slice(1) + "." : "The GSP would export more than the transmission boundary allows."}${reason.case === "summer_min" ? " That's a sunny, low-demand day — the most generation and the least local load at the same time." : ""} The bottleneck isn't in the local network — it's the supergrid transformers and transmission network above the GSP, which already carry this region's surplus generation out.`,
        action: "No local reinforcement fixes this. Options: wait for transmission (NESO) reinforcement, take a flexible / non-firm connection that's curtailed at export peaks, pair it with storage to shift export, or site it under a GSP with headroom." };
    }
    if (t === "line" || t === "line_overload") {
      return { ...base, kind: "grid", element: { line_id: eid },
        short: `Overloads line ${eid}${pct != null ? ` to ${pct}%` : ""} — a grid limit, not the project`,
        why: `Connecting this would overload line ${eid}${pct != null ? ` to ${pct}% (limit 100%)` : ""}. The wires between here and the rest of the grid are the bottleneck — the project itself is fine.`,
        action: `Reinforce line ${eid} (add a parallel circuit) — open Review ▸ Suggestions for the exact plan and the MW it frees — or hold this project to 2035.` };
    }
    if (t === "trafo" || t === "trafo_overload") {
      return { ...base, kind: "grid", element: null,
        short: `Overloads transformer ${eid}${pct != null ? ` to ${pct}%` : ""}`,
        why: `Connecting this would overload transformer ${eid}${pct != null ? ` to ${pct}% (limit 100%)` : ""} — the primary substation can't pass this much power.`,
        action: `Uprate or reinforce transformer ${eid} — see Review ▸ Suggestions — or hold this project to 2035.` };
    }
    if (t === "voltage" || t === "voltage_high" || t === "voltage_low") {
      const high = t === "voltage_high" || (t === "voltage" && val != null && val > 1.0);
      if (high) {
        return { ...base, kind: "grid", element: { bus_id: eid },
          short: `Too much export — bus ${eid} rises to ${val != null ? val.toFixed(3) : "?"} pu (limit 1.10)`,
          why: `This much generation can't be absorbed here: it would push the voltage at bus ${eid}${val != null ? ` to ${val.toFixed(3)} pu` : ""}, above the 1.10 limit. The local network is too weak for this much export.`,
          action: `Reinforce the feeder or add reactive support at bus ${eid} — see Review ▸ Suggestions — or site a smaller project at this bus.` };
      }
      return { ...base, kind: "grid", element: { bus_id: eid },
        short: `Bus ${eid} sags to ${val != null ? val.toFixed(3) : "?"} pu (limit 0.90)`,
        why: `Voltage at bus ${eid}${val != null ? ` drops to ${val.toFixed(3)} pu` : ""}, below the 0.90 limit — the network is too weak here under this demand.`,
        action: `Reinforce the feeder to bus ${eid} — see Review ▸ Suggestions — or hold this project to 2035.` };
    }
    if (t === "readiness") {
      return { ...base, kind: "readiness", element: null, short: "Not developed enough yet",
        why: msg || "The project isn't developed enough yet (land rights, planning consent, grid-connection agreement or financing).",
        action: "Resubmit once land, planning and financing progress — the grid can take it; the project isn't ready." };
    }
    if (t === "phased") {
      return { ...base, kind: "phased", element: reason.element || null, short: msg,
        why: msg, action: "No action needed — it connects in 2035 as demand grows and headroom opens." };
    }
    // rejected / intake / non_convergent
    const m = msg.toLowerCase();
    let short, why, action;
    if (m.includes("not in") || m.includes("does not exist") || (m.includes("bus") && !m.includes("busbar"))) {
      short = "Connection point not in the network model";
      why = `The point of connection${it.bus_id != null ? ` (bus ${it.bus_id})` : ""} isn't in this network model, so it can't be assessed.`;
      action = "Pick a real connection point: in + Add project, choose a bus from the dropdown or click “Map” to pick one on the network.";
    } else if (m.includes("rating") && (m.includes("exceed") || m.includes("range") || m.includes("cap"))) {
      short = `Capacity over the ${MAX_MW} MW connection cap`;
      why = `The requested capacity${it.rating_mw != null ? ` (${it.rating_mw} MW)` : ""} is above the ${MAX_MW} MW connection cap for this network.`;
      action = `Reduce the capacity to ≤ ${MAX_MW} MW, split it across sites, or connect at a higher-voltage point.`;
    } else if (m.includes("missing") || m.includes("capacity")) {
      short = "Incomplete application";
      why = msg || "The application is missing required details.";
      action = "Complete the missing fields (capacity, point of connection, technology) in + Add project and resubmit.";
    } else {
      short = "Can't be assessed yet";
      why = msg || "This application can't be assessed yet.";
      action = "Complete the application details and resubmit.";
    }
    return { ...base, kind: "intake", element: null, short, why, action };
  }

  function _applyReasons(res) {
    if (res && Array.isArray(res.queue)) res.queue.forEach((q) => { q.reason = _normReason(q.reason, q); });
    return res;
  }
  function _applyDiffReasons(out) {
    if (out && Array.isArray(out.projects)) out.projects.forEach((p) => { p.head_reason = _normReason(p.head_reason, p); });
    return out;
  }

  const getModel = () => getJson("/model");
  const getCandidates = () => getJson("/optimize/candidates");
  const addCandidate = (c) => postJson("/optimize/candidates", c);
  const getRegistry = () => getJson("/registry");
  // persist the operator's energisation year for a project on a branch (null = follow the recommendation)
  async function setSchedule(branchId, requestId, year) {
    const res = await fetch(`${config.base}/branches/${branchId}/schedule`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request_id: requestId, year }) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `schedule failed (${res.status})`);
    return res.json();
  }
  const addFromRegistry = (branchId, requestId) => postJson(`/branches/${branchId}/registry`, { request_id: requestId });
  const optimize = async (body) => _applyReasons(await postJson("/optimize", body));
  // NESO FES 2025 demand pathways (fixed growth multipliers per pathway), served by GET /forecasts
  async function getForecasts() {
    const r = await getJson("/forecasts");
    return r && Array.isArray(r.forecasts) ? r.forecasts : [];
  }
  // the GSP boundary: export/import limits to transmission + the transmission projects behind it
  async function getBoundary() {
    try { return await getJson("/boundary"); } catch (e) { return null; }
  }
  async function getMaxConnectionMw() {
    try {
      const r = await getJson("/forecasts");
      if (r && r.max_connection_mw) return r.max_connection_mw;
    } catch (e) { /* fall back to the default cap */ }
    return MAX_MW;
  }

  // --- branches ("git for grids") + unblock suggestions ---------------------
  // A branch = a scenario (demand pathway) + the projects added on it.
  const createBranch = (body) => postJson("/branches", body);
  const listBranches = async () => (await getJson("/branches")).branches || [];
  const optimizeBranch = async (id, opts) => _applyReasons(await postJson(`/branches/${id}/optimize`, opts || {}));
  async function diffBranch(id, opts) {
    const qs = opts && opts.with_narration ? "?with_narration=1" : "";
    return _applyDiffReasons(await getJson(`/branches/${id}/diff${qs}`));
  }
  const mergeBranch = (id, opts) => postJson(`/branches/${id}/merge`, opts || { into: "main" });
  const discardBranch = async (id) => (await fetch(`${config.base}/branches/${id}/discard`, { method: "POST" })).json();
  async function getSuggestions(id, opts) {
    const p = new URLSearchParams();
    if (opts && opts.limit) p.set("limit", opts.limit);
    if (opts && opts.with_narration) p.set("with_narration", "1");
    const qs = p.toString() ? `?${p}` : "";
    return (await getJson(`/branches/${id}/suggestions${qs}`)).suggestions || [];
  }

  window.GridForgeAPI = { config, getModel, getCandidates, addCandidate, getRegistry, addFromRegistry, setSchedule, optimize,
    getForecasts, getMaxConnectionMw, getBoundary,
    createBranch, listBranches, optimizeBranch, diffBranch, mergeBranch, discardBranch, getSuggestions };
})();
