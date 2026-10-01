// GridForge API client — mock implementation matching the FastAPI shapes.
// To go live: set GridForgeAPI.config.mock = false (base = http://localhost:8000).
(function () {
  const config = { mock: false, base: "http://localhost:8000", latencyMs: 900 };
  const V_MIN = 0.9, V_MAX = 1.1, LINE_MAX = 100, MAX_MW = 20;
  const W_READY = 0.5, W_NEED = 0.35, W_STRAT = 0.15;
  const READY_P1 = 0.6, READY_P2 = 0.35;
  const R_OHM_KM = 0.26, V_SET = 1.02;

  const CANDIDATES = [
    { request_id: "CR-2041", applicant: "Rheintal Solar GmbH", bus_id: 120, technology: "solar", rating_mw: 4.5, readiness_score: 0.46, strategic_fit: 0.7, status: "valid", review_reasons: "", readiness_rationale: "Initial enquiry; no consent or land agreement referenced." },
    { request_id: "CR-2042", applicant: "Unnamed BESS developer", bus_id: 250, technology: "battery", rating_mw: 2, readiness_score: 0.5, strategic_fit: 0.8, status: "rejected", review_reasons: "Point of connection bus 250 does not exist in the network model", readiness_rationale: "Commissioning date given, but no consent evidence." },
    { request_id: "CR-2043", applicant: "Ettenheim depot enquiry", bus_id: null, technology: "solar", rating_mw: null, readiness_score: 0.1, strategic_fit: 0.6, status: "rejected", review_reasons: "Missing capacity and point of connection", readiness_rationale: "Size and connection point unconfirmed." },
    { request_id: "CR-2044", applicant: "Oberrhein Wind Partners", bus_id: 42, technology: "wind", rating_mw: 850, readiness_score: 0.3, strategic_fit: 0.7, status: "rejected", review_reasons: "850 MW exceeds the 20 MW plausibility cap for a 20 kV feeder", readiness_rationale: "Feasibility stage only." },
    { request_id: "CR-2045", applicant: "Lahr Speicher AG", bus_id: 174, technology: "battery", rating_mw: 4.5, readiness_score: 0.64, strategic_fit: 0.82, status: "valid", review_reasons: "", readiness_rationale: "Site works scheduled next spring; consent implied." },
    { request_id: "CR-2046", applicant: "Kappel Solarfeld", bus_id: 200, technology: "solar", rating_mw: 3, readiness_score: 0.5, strategic_fit: 0.7, status: "valid", review_reasons: "", readiness_rationale: "Capacity check requested; no consent referenced." },
    { request_id: "CR-2047", applicant: "Schwarzwald Wind eG", bus_id: 155, technology: "wind", rating_mw: 18, readiness_score: 0.93, strategic_fit: 0.86, status: "valid", review_reasons: "", readiness_rationale: "Full planning consent, land secured, financing in place, 2029 COD." },
    { request_id: "CR-2048", applicant: "Mahlberg PV Projekt", bus_id: 159, technology: "solar", rating_mw: 16, readiness_score: 0.58, strategic_fit: 0.74, status: "valid", review_reasons: "", readiness_rationale: "Planning submitted, awaiting determination; land option agreed." },
    { request_id: "CR-2049", applicant: "Kinzig Wind (scoping)", bus_id: 157, technology: "wind", rating_mw: 15, readiness_score: 0.16, strategic_fit: 0.7, status: "valid", review_reasons: "", readiness_rationale: "Pre-application; no land, planning or financing." },
    { request_id: "CR-2050", applicant: "Rust Energiespeicher", bus_id: 305, technology: "battery", rating_mw: 6, readiness_score: 0.9, strategic_fit: 0.85, status: "valid", review_reasons: "", readiness_rationale: "Consent granted, land secured, financing committed; ready 2028." },
    { request_id: "CR-2051", applicant: "Schutterwald Solarpark", bus_id: 81, technology: "solar", rating_mw: 7.5, readiness_score: 0.81, strategic_fit: 0.72, status: "valid", review_reasons: "", readiness_rationale: "Consent granted; lease signed; EPC tender under way." },
    { request_id: "CR-2052", applicant: "Ortenau Windpark II", bus_id: 236, technology: "wind", rating_mw: 9, readiness_score: 0.72, strategic_fit: 0.8, status: "valid", review_reasons: "", readiness_rationale: "Consent granted; financing at term-sheet stage." },
    { request_id: "CR-2053", applicant: "Friesenheim BESS", bus_id: 132, technology: "battery", rating_mw: 3, readiness_score: 0.68, strategic_fit: 0.84, status: "valid", review_reasons: "", readiness_rationale: "Land secured; planning approved with conditions." },
    { request_id: "CR-2054", applicant: "Seelbach Agri-PV", bus_id: 286, technology: "solar", rating_mw: 5, readiness_score: 0.41, strategic_fit: 0.68, status: "valid", review_reasons: "", readiness_rationale: "Land option only; planning pre-app meeting held." },
    { request_id: "CR-2055", applicant: "Meißenheim Solar Süd", bus_id: 153, technology: "solar", rating_mw: 11, readiness_score: 0.84, strategic_fit: 0.73, status: "valid", review_reasons: "", readiness_rationale: "Consent granted, land owned, debt financing agreed." },
  ];

  let model = null, extra = [], net = null;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const hash = (n) => { const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x); };
  const fixRating = (r) => (typeof r === "number" && r > 0 ? r : 362);

  function buildNet(m) {
    const busById = {}; m.buses.forEach((b) => (busById[b.bus_id] = b));
    const adj = {}; m.buses.forEach((b) => (adj[b.bus_id] = []));
    m.lines.forEach((l) => {
      if (l.in_service === false) return;
      adj[l.from_bus].push({ to: l.to_bus, line: l });
      adj[l.to_bus].push({ to: l.from_bus, line: l });
    });
    const roots = m.transformers.map((t) => t.lv_bus);
    const parent = {}, parentLine = {}, order = [], depthKm = {}, feeder = {};
    roots.forEach((r, i) => { parent[r] = null; depthKm[r] = 0; feeder[r] = i; order.push(r); });
    for (let i = 0; i < order.length; i++) {
      const n = order[i];
      for (const e of adj[n] || []) if (!(e.to in parent)) {
        parent[e.to] = n; parentLine[e.to] = e.line; depthKm[e.to] = depthKm[n] + e.line.length_km;
        feeder[e.to] = feeder[n]; order.push(e.to);
      }
    }
    // base demand per 20 kV bus (MW) — deterministic, heavier toward the town centres
    const load = {};
    m.buses.forEach((b) => { load[b.bus_id] = b.vn_kv > 20 ? 0 : +(0.07 + hash(b.bus_id) * 0.2).toFixed(3); });
    // industrial demand pocket: one branch sized to reach ~104% loading at 1.25× growth
    const size = {}, sub = {};
    for (let i = order.length - 1; i >= 0; i--) { const b = order[i]; size[b] = (size[b] || 0) + 1; sub[b] = (sub[b] || []).concat([b]); if (parent[b] != null) { size[parent[b]] = (size[parent[b]] || 0) + size[b]; sub[parent[b]] = (sub[parent[b]] || []).concat(sub[b]); } }
    const head = order.filter((b) => size[b] >= 12 && size[b] <= 24 && parentLine[b] && parentLine[b].rating_a <= 421).sort((a, b) => depthKm[a] - depthKm[b])[0];
    if (head != null) {
      const S = sub[head].reduce((s, b) => s + load[b], 0);
      const M = (Math.sqrt(3) * 20 * parentLine[head].rating_a) / 1000;
      const f = (1.04 / 1.25) * M * 0.95 / S;
      sub[head].forEach((b) => (load[b] = +(load[b] * f).toFixed(3)));
    }
    return { busById, parent, parentLine, order, depthKm, load, roots, hotHead: head };
  }

  function powerFlow(gens, growth) {
    const { order, parent, parentLine, load, roots } = net;
    const inj = {};
    order.forEach((b) => (inj[b] = -load[b] * growth));
    for (const g of gens) if (g.bus_id in inj) inj[g.bus_id] += g.rating_mw;
    const flow = {}; // export (toward root) on each bus's parent line, MW
    for (let i = order.length - 1; i >= 0; i--) {
      const b = order[i]; flow[b] = (flow[b] || 0) + inj[b];
      if (parent[b] != null) flow[parent[b]] = (flow[parent[b]] || 0) + flow[b];
    }
    const vm = {}, loading = {};
    for (const b of order) {
      if (parent[b] == null) { vm[b] = V_SET; continue; }
      const l = parentLine[b];
      const subFlow = flow[b];
      vm[b] = vm[parent[b]] + (subFlow * (l.r_ohm_per_km || R_OHM_KM) * l.length_km) / 400;
      const mva = (Math.sqrt(3) * 20 * fixRating(l.rating_a)) / 1000;
      loading[l.line_id] = (Math.abs(subFlow) / 0.95 / mva) * 100;
    }
    let worst = 0, worstLine = null, vmin = 9, vmax = 0, vminBus = null, vmaxBus = null;
    for (const id in loading) if (loading[id] > worst) { worst = loading[id]; worstLine = +id; }
    for (const b in vm) { if (vm[b] < vmin) { vmin = vm[b]; vminBus = +b; } if (vm[b] > vmax) { vmax = vm[b]; vmaxBus = +b; } }
    return { vm, loading, worst, worstLine, vmin, vmax, vminBus, vmaxBus };
  }

  // violations introduced/worsened relative to a reference flow
  function violations(pf, ref) {
    const v = [];
    for (const id in pf.loading) if (pf.loading[id] > LINE_MAX && pf.loading[id] > ref.loading[id] + 0.5)
      v.push({ type: "line_overload", line_id: +id, value: pf.loading[id], message: `Line ${id} overloaded ${Math.round(pf.loading[id])}%` });
    for (const b in pf.vm) {
      if (pf.vm[b] > V_MAX && pf.vm[b] > ref.vm[b] + 0.0005) v.push({ type: "voltage_high", bus_id: +b, value: pf.vm[b], message: `Voltage ${pf.vm[b].toFixed(3)} pu at bus ${b}` });
      if (pf.vm[b] < V_MIN && pf.vm[b] < ref.vm[b] - 0.0005) v.push({ type: "voltage_low", bus_id: +b, value: pf.vm[b], message: `Voltage ${pf.vm[b].toFixed(3)} pu at bus ${b}` });
    }
    const sev = (x) => (x.type === "line_overload" ? (x.value - 100) / 10 : Math.abs(x.value - 1) * 100 - 10 + 1);
    return v.sort((a, b) => sev(b) - sev(a));
  }

  function gridNeed(bus_id, growth) {
    // how much local demand sits on this branch relative to its capacity under future growth
    const pf = powerFlow([], growth);
    let b = bus_id, peak = 0, hops = 0;
    while (b != null && hops < 6) { const l = net.parentLine[b]; if (l) peak = Math.max(peak, pf.loading[l.line_id] || 0); b = net.parent[b]; hops++; }
    const dist = Math.min(1, (net.depthKm[bus_id] || 0) / 12);
    return +Math.min(1, 0.25 + peak / 140 + dist * 0.25).toFixed(2);
  }

  function runOptimizer(cands, p) {
    const g30 = p.growth_2030, g35 = p.growth_2035;
    const base30 = powerFlow([], g30), base35 = powerFlow([], g35);
    const rows = cands.map((c) => {
      let status = c.status, reason = null;
      if (status === "valid") {
        if (c.bus_id == null || !(c.bus_id in net.busById)) { status = "rejected"; reason = `Bus ${c.bus_id} not in network model`; }
        else if (c.rating_mw == null || c.rating_mw <= 0) { status = "rejected"; reason = "Missing capacity"; }
        else if (c.rating_mw > MAX_MW) { status = "rejected"; reason = `${c.rating_mw} MW exceeds ${MAX_MW} MW cap`; }
      } else reason = c.review_reasons || "Rejected at intake";
      const need = status === "valid" ? gridNeed(c.bus_id, g35) : 0;
      const score = status === "valid" ? +(W_READY * c.readiness_score + W_NEED * need + W_STRAT * c.strategic_fit).toFixed(3) : null;
      return { c, status, reason, need, score };
    });
    const valid = rows.filter((r) => r.status === "valid").sort((a, b) => b.score - a.score);
    const A30 = [], A35 = [];
    const out = [];
    valid.forEach((r, i) => {
      const c = r.c, g = { request_id: c.request_id, bus_id: c.bus_id, rating_mw: c.rating_mw, technology: c.technology };
      let status, reason = null;
      const pf35 = powerFlow([...A35, g], g35), v35 = violations(pf35, base35);
      const pf30 = powerFlow([...A30, g], g30), v30 = violations(pf30, base30);
      if (c.readiness_score >= READY_P1 && !v30.length && !v35.length) { status = "Phase1"; A30.push(g); A35.push(g); }
      else if (c.readiness_score >= READY_P2 && !v35.length) {
        status = "Phase2"; A35.push(g);
        if (c.readiness_score >= READY_P1 && v30.length) reason = { type: "phased", message: `Held to 2035 — ${v30[0].message} under 2030 demand`, element: v30[0] };
      } else if (c.readiness_score < READY_P2) {
        status = "Deferred"; reason = { type: "readiness", message: `Readiness ${Math.round(c.readiness_score * 100)}% below ${READY_P2 * 100}% threshold` };
        if (v35.length) reason.grid = v35[0];
      } else {
        status = "Deferred"; const v = v35[0];
        reason = { type: v.type, message: v.message, element: v };
      }
      out.push({ rank: i + 1, request_id: c.request_id, applicant: c.applicant, bus_id: c.bus_id, technology: c.technology, rating_mw: c.rating_mw,
        readiness_score: c.readiness_score, grid_need: r.need, rank_score: r.score, status, reason });
    });
    rows.filter((r) => r.status !== "valid").forEach((r) => out.push({ rank: null, request_id: r.c.request_id, applicant: r.c.applicant, bus_id: r.c.bus_id,
      technology: r.c.technology, rating_mw: r.c.rating_mw, readiness_score: r.c.readiness_score, grid_need: 0, rank_score: null, status: "Rejected",
      reason: { type: "intake", message: r.reason } }));
    out.forEach((q) => { const b = net.busById[q.bus_id]; q.lon = b ? b.lon : null; q.lat = b ? b.lat : null; });
    const phase = (gens, growth) => {
      const pf = powerFlow(gens, growth);
      return {
        accepted: gens.map((x) => x.request_id),
        overloaded_line_ids: Object.keys(pf.loading).filter((k) => pf.loading[k] > LINE_MAX).map(Number),
        generators: gens.map((x) => ({ ...x, lon: net.busById[x.bus_id].lon, lat: net.busById[x.bus_id].lat })),
        worst_line_loading_pct: +pf.worst.toFixed(1), worst_line_id: pf.worstLine,
        min_vm_pu: +pf.vmin.toFixed(3), max_vm_pu: +pf.vmax.toFixed(3), min_vm_bus: pf.vminBus, max_vm_bus: pf.vmaxBus,
        voltage_violation_bus_ids: Object.keys(pf.vm).filter((b) => pf.vm[b] > V_MAX || pf.vm[b] < V_MIN).map(Number),
        line_loading: Object.fromEntries(Object.entries(pf.loading).map(([k, v]) => [k, +v.toFixed(1)])),
        bus_vm: Object.fromEntries(Object.entries(pf.vm).map(([k, v]) => [k, +v.toFixed(3)])),
      };
    };
    return { queue: out, phases: { "2030": phase(A30, g30), "2035": phase(A35, g35) } };
  }

  function justify(res, p) {
    const q = res.queue, by = (s) => q.filter((x) => x.status === s);
    const mw = (xs) => xs.reduce((s, x) => s + (x.rating_mw || 0), 0);
    const p1 = by("Phase1"), p2 = by("Phase2"), d = by("Deferred"), r = by("Rejected");
    const gridD = d.filter((x) => x.reason && x.reason.type !== "readiness");
    let t = `Under ${p.growth_2030.toFixed(2)}× (2030) and ${p.growth_2035.toFixed(2)}× (2035) demand growth, ${p1.length} projects (${mw(p1)} MW) connect in Phase 1 and ${p2.length} (${mw(p2)} MW) in Phase 2. `;
    t += `Ordering follows "first ready and needed, first connected": rank score weights readiness ${W_READY}, grid need ${W_NEED} and strategic fit ${W_STRAT}. `;
    if (gridD.length) t += `${gridD.length} ready project${gridD.length > 1 ? "s are" : " is"} held back purely by network limits — reinforcement, not developer progress, is the critical path there. `;
    if (r.length) t += `${r.length} application${r.length > 1 ? "s were" : " was"} rejected at intake for data or plausibility issues.`;
    const notes = q.map((x) => {
      const head = `${x.request_id} (${x.technology || "—"}, ${x.rating_mw ?? "—"} MW${x.bus_id != null ? ", bus " + x.bus_id : ""})`;
      if (x.status === "Phase1") return `${head} — connects by 2030: readiness ${Math.round(x.readiness_score * 100)}% and no thermal or voltage limits breached in either year.`;
      if (x.status === "Phase2") return `${head} — connects by 2035: ${x.reason ? x.reason.message.replace(/^Held to 2035 — /, "") + " in 2030; headroom opens as demand grows." : "readiness " + Math.round(x.readiness_score * 100) + "% supports 2035 delivery, not 2030."}`;
      if (x.status === "Deferred") return x.reason.type === "readiness" ? `${head} — deferred: ${x.reason.message}; resubmit once land, consent and finance progress.` : `${head} — deferred despite readiness ${Math.round(x.readiness_score * 100)}%: ${x.reason.message}. Needs reinforcement before it can connect.`;
      return `${head} — rejected at intake: ${x.reason.message}.`;
    });
    return t.trim() + "\n\n" + notes.join("\n");
  }

  async function getModel() {
    if (!config.mock) return (await fetch(`${config.base}/model`)).json();
    if (!model) {
      const src = (window.__resources && window.__resources.modelJson) || "./data/model.json";
      model = await (await fetch(src)).json();
      model.lines.forEach((l) => { l.rating_a = fixRating(l.rating_a); l.r_ohm_per_km = l.rating_a >= 645 ? 0.125 : l.rating_a >= 421 ? 0.2 : 0.27; });
      net = buildNet(model);
      model.loads = model.buses.filter((b) => net.load[b.bus_id] > 0).map((b, i) => ({ load_id: i, bus_id: b.bus_id, p_mw: net.load[b.bus_id], lon: b.lon, lat: b.lat }));
    }
    return model;
  }
  async function getCandidates() {
    if (!config.mock) return (await fetch(`${config.base}/optimize/candidates`)).json();
    return [...CANDIDATES, ...extra];
  }
  async function addCandidate(c) {
    if (!config.mock) return (await fetch(`${config.base}/optimize/candidates`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(c) })).json();
    const id = `CR-${2056 + extra.length}`;
    const row = { request_id: id, status: "valid", review_reasons: "", strategic_fit: c.technology === "battery" ? 0.84 : 0.74, ...c };
    extra.push(row);
    return row;
  }
  async function removeCandidate(id) { extra = extra.filter((c) => c.request_id !== id); }
  async function optimize(body) {
    if (!config.mock) return (await fetch(`${config.base}/optimize`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
    await getModel();
    await sleep(config.latencyMs);
    const res = runOptimizer(await getCandidates(), body);
    res.justification = body.with_justification ? justify(res, body) : "";
    res.snapshot_id = "mv_oberrhein-baseline";
    return res;
  }
  // demand forecast used to seed the growth scenario (mock of a forecast service)
  const FORECASTS = [
    { id: "ccr", label: "Consumer Transformation", growth_2030: 1.14, growth_2035: 1.32 },
    { id: "lw", label: "Leading the Way", growth_2030: 1.12, growth_2035: 1.28 },
    { id: "st", label: "System Transformation", growth_2030: 1.1, growth_2035: 1.25 },
    { id: "fs", label: "Falling Short", growth_2030: 1.04, growth_2035: 1.1 },
  ];
  async function getForecasts() { return FORECASTS; }

  // indicative hosting capacity at a bus given already-connected generators (mock-only helper)
  function hostingCapacity(bus_id, gens, growth) {
    if (!net || !(bus_id in net.parent)) return null;
    const base = powerFlow([], growth);
    const test = (mw) => violations(powerFlow([...gens, { bus_id, rating_mw: mw }], growth), base);
    if (!test(MAX_MW).length) return { mw: MAX_MW, binding: null, capped: true };
    let lo = 0, hi = MAX_MW, bind = test(MAX_MW)[0];
    for (let i = 0; i < 14; i++) { const mid = (lo + hi) / 2, v = test(mid); if (v.length) { hi = mid; bind = v[0]; } else lo = mid; }
    return { mw: +lo.toFixed(1), binding: bind, capped: false };
  }

  window.GridForgeAPI = { hostingCapacity, config, getModel, getCandidates, addCandidate, removeCandidate, optimize, getForecasts, _powerFlow: (g, gr) => powerFlow(g, gr) };
})();
