// Engine deferral reasons -> the single shape the UI renders everywhere:
// {kind, element, short, why (plain English), action (what to do next)}.
//
// One normaliser per engine reason type, looked up in NORMALISERS. A new reason type is one entry
// here (plus its Python side in network.py / suggest.py); unknown types fall through to the intake
// normaliser, which reads the message.

import type { RawReason, Reason } from "../types";

// Which planning study case a grid limit bites in, so the operator knows WHEN it's a problem.
const CASE_WHY: Record<string, string> = {
  summer_min:
    " This bites at summer minimum demand: a sunny, low-demand day when little local load is there to soak up the export and the wires are on their lower summer rating.",
  winter_peak: " This bites at winter peak demand.",
};

export interface ReasonContext {
  bus_id?: number | null;
  rating_mw?: number | null;
}

/** Everything a normaliser needs, pre-digested from the raw reason. */
interface Facts {
  reason: RawReason | Reason;
  item: ReasonContext;
  type: string; // the type as the engine (or an older client) spelled it
  val: number | null;
  msg: string;
  eid: number | null;
  pct: number | null;
  prior: Reason["element"];
  base: RawReason & { message: string; value: number | null };
}
type Normaliser = (f: Facts) => Reason;

const gsp: Normaliser = ({ reason, val, msg, base }) => {
  // the transmission boundary: no distribution-side reinforcement can fix this
  const mw = val != null ? Math.round(val) : null;
  return {
    ...base,
    kind: "grid",
    element: null,
    short: `GSP export limit: the region would push ${mw != null ? `${mw} MW` : "too much"} up to transmission`,
    why: `${msg ? msg.charAt(0).toUpperCase() + msg.slice(1) + "." : "The GSP would export more than the transmission boundary allows."}${
      reason.case === "summer_min"
        ? " That's a sunny, low-demand day: the most generation and the least local load at the same time."
        : ""
    } The bottleneck isn't in the local network. It's the supergrid transformers and transmission network above the GSP, which already carry this region's surplus generation out.`,
    action:
      "No local reinforcement fixes this. Options: wait for transmission (NESO) reinforcement, take a flexible / non-firm connection that's curtailed at export peaks, pair it with storage to shift export, or site it under a GSP with headroom.",
  };
};

const line: Normaliser = ({ eid, pct, base }) => ({
  ...base,
  kind: "grid",
  element: { line_id: eid ?? undefined },
  short: `Overloads line ${eid}${pct != null ? ` to ${pct}%` : ""}: a grid limit, not the project`,
  why: `Connecting this would overload line ${eid}${pct != null ? ` to ${pct}% (limit 100%)` : ""}. The wires between here and the rest of the grid are the bottleneck. The project itself is fine.`,
  action: `Reinforce line ${eid} (a parallel circuit), size the project to what its busbar takes or move it to a busbar that takes it, or hold it to a later year. Ask the agents how it could connect: they measure each option.`,
});

const trafo: Normaliser = ({ eid, pct, base }) => ({
  ...base,
  kind: "grid",
  element: null,
  short: `Overloads transformer ${eid}${pct != null ? ` to ${pct}%` : ""}`,
  why: `Connecting this would overload transformer ${eid}${pct != null ? ` to ${pct}% (limit 100%)` : ""}. The substation can't pass this much power.`,
  action: `Uprate or reinforce transformer ${eid}, size the project to what the substation takes or move it, or hold it to a later year. Ask the agents how it could connect.`,
});

const voltage: Normaliser = ({ reason, val, eid, base }) => {
  const high = val != null && val > 1.0;
  // the limit the engine judged that bus against (the grid's own band at its level); it always sends it
  const lim = typeof reason.limit === "number" ? reason.limit.toFixed(2) : null;
  const limShort = lim ? ` (limit ${lim})` : "";
  if (high) {
    return {
      ...base,
      kind: "grid",
      element: { bus_id: eid ?? undefined },
      short: `Too much export: bus ${eid} rises to ${val != null ? val.toFixed(3) : "?"} pu${limShort}`,
      why: `This much generation can't be absorbed here: it would push the voltage at bus ${eid}${val != null ? ` to ${val.toFixed(3)} pu` : ""}, above its ${lim ? `${lim} pu ` : ""}limit. The local network is too weak for this much export.`,
      action: `Reinforce the feeder or add reactive support at bus ${eid}, or site a smaller project at this bus. Ask the agents how it could connect.`,
    };
  }
  return {
    ...base,
    kind: "grid",
    element: { bus_id: eid ?? undefined },
    short: `Bus ${eid} sags to ${val != null ? val.toFixed(3) : "?"} pu${limShort}`,
    why: `Voltage at bus ${eid}${val != null ? ` drops to ${val.toFixed(3)} pu` : ""}, below its ${lim ? `${lim} pu ` : ""}limit. The network is too weak here under this demand.`,
    action: `Reinforce the feeder to bus ${eid}, or hold this project to a later year. Ask the agents how it could connect.`,
  };
};

/** The power flow has no solution in that state: the grid cannot carry it at all, before any limit is judged. */
const nonConvergent: Normaliser = ({ msg, base }) => ({
  ...base,
  kind: "grid",
  element: null,
  short: "The power flow has no solution: the network cannot carry this state",
  why: `${msg ? `${msg.charAt(0).toUpperCase()}${msg.slice(1)}. ` : ""}No operating point satisfies the network with this connected, so no limit can even be judged: the grid is too weak for it here.`,
  action: "Size the project down, move it to a stronger busbar, or hold it to a later year. Ask the agents how it could connect: they measure each option.",
});

/** rejected / intake: read the message (the API's triage, the engine's intake) to say what to fix. */
const intake: Normaliser = ({ msg, item, base }) => {
  const m = msg.toLowerCase();
  const cap = /(\d+(?:\.\d+)?) mw connection cap/.exec(m)?.[1]; // the API's triage names the network's cap
  let short: string;
  let why: string;
  let action: string;
  if (m.includes("not in")) {
    short = "Connection point not in the network model";
    why = `The point of connection${item.bus_id != null ? ` (bus ${item.bus_id})` : ""} isn't in this network model, so it can't be assessed.`;
    action = "Pick a real connection point: a busbar in the model. Ask the agents where a project of this size could connect; they propose the change for you to approve.";
  } else if (m.includes("connection cap") || m.includes("out of range")) {
    const what = m.includes("import") ? "import capacity" : "capacity";
    short = `${what === "capacity" ? "Capacity" : "Import capacity"} over the ${cap ? `${cap} MW ` : ""}connection cap`;
    why = `The requested ${what}${what === "capacity" && item.rating_mw != null ? ` (${item.rating_mw} MW)` : ""} is above ${cap ? `the ${cap} MW` : "this network's"} connection cap.`;
    action = `Reduce it${cap ? ` to ≤ ${cap} MW` : " under the cap"}, split it across sites, or connect at a higher-voltage point.`;
  } else if (m.includes("missing") || m.includes("no point of connection") || m.includes("above 0") || m.includes("capacity")) {
    short = "Incomplete application";
    why = msg ? `${msg.charAt(0).toUpperCase()}${msg.slice(1)}.` : "The application is missing required details.";
    action = "Ask the agents to complete it: give them the missing figure and they propose the change for you to approve. The next run assesses it.";
  } else {
    short = "Can't be assessed yet";
    why = msg || "This application can't be assessed yet.";
    action = "Ask the agents to complete it: they propose the change for you to approve. The next run assesses it.";
  }
  return { ...base, kind: "intake", element: null, short, why, action };
};

/** Engine reason type -> normaliser. */
const NORMALISERS: Record<string, Normaliser> = { gsp, line, trafo, voltage, non_convergent: nonConvergent };

function facts(reason: RawReason | Reason, item: ReasonContext): Facts {
  const val = typeof reason.value === "number" ? reason.value : null;
  const prior = (reason as Partial<Reason>).element ?? null;
  const eid: number | null =
    reason.element_id != null ? reason.element_id : prior ? (prior.line_id ?? prior.bus_id ?? null) : null;
  const msg = reason.message || "";
  return {
    reason,
    item,
    type: reason.type,
    val,
    msg,
    eid,
    pct: val != null ? Math.round(val) : null,
    prior,
    base: { ...reason, message: msg, value: val },
  };
}

/**
 * Normalise an engine reason ({type, element_id, value, message, case}) into
 * {kind, element, short, why (plain English), action (what to do next)}.
 */
export function normReason(reason: RawReason | Reason | null | undefined, item?: ReasonContext): Reason | null {
  if (!reason) return null;
  const f = facts(reason, item ?? {});
  const out = (NORMALISERS[reason.type] ?? intake)(f);
  // (a GSP reason already names its case in the message, and explains it itself)
  if (out.kind === "grid" && reason.type !== "gsp" && reason.case && CASE_WHY[reason.case]) out.why = `${out.why}${CASE_WHY[reason.case]}`;
  return out;
}
