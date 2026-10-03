import { describe, expect, it } from "vitest";

import type { Suggestion } from "../types";
import { item } from "./test-fixtures";
import { answer, draftSlots, readinessAnswer, readinessScore, startIntake, techFromText } from "./intake";
import type { IntakeCtx } from "./intake";
import { layoutFor } from "./layout";
import { bestAnswer, leverFrees, leverTryable, projectAnswer, recIntent, recsOpening, recsQuickReplies } from "./recs";
import { stageIndex, stageReadout } from "./runStages";

const ctx: IntakeCtx = {
  maxMw: 300, branchName: "sleaford-batteries", profileLabel: "High",
  busOptions: [{ id: 1102, label: "Bus 1102 · Boston 33 kV" }],
  findBus: (t) => (t.includes("1102") || /boston/i.test(t) ? { id: 1102, label: "Bus 1102 · Boston 33 kV" } : null),
};
const run = (...answers: string[]) => answers.reduce((st, a) => answer(st, a, ctx), startIntake(ctx));

describe("intake", () => {
  it("walks a battery through every step and finishes with a summary and the add action", () => {
    const st = run("Battery", "49.9", "Same as export (49.9)", "Bus 1102 · Boston 33 kV", "2029", readinessAnswer(["Land rights", "Financing"]), "Quadring Fen Storage");
    expect(st.step).toBe("done");
    expect(st).toMatchObject({ tech: "battery", mw: 49.9, load: 49.9, year: 2029, name: "Quadring Fen Storage", bus: { id: 1102 } });
    const last = st.messages[st.messages.length - 1];
    expect(last.action).toBe("add");
    expect(last.summary).toContainEqual(["Readiness", "65%"]);
    expect(last.summary).toContainEqual(["Tested on", "High demand"]);
  });
  it("skips the import step for generation that never draws power, and the export step for demand", () => {
    expect(run("Solar PV", "20").step).toBe("bus");
    const dc = run("Demand (data centre, EV hub)");
    expect(dc.step).toBe("load");
    expect(dc.mw).toBe(0);
    expect(dc.messages[dc.messages.length - 1].text).toContain("studied as demand");
  });
  it("rejects exports over the intake cap and unknown buses, and keeps asking", () => {
    const st = run("Wind", "450");
    expect(st.step).toBe("mw");
    expect(st.messages[st.messages.length - 1].text).toContain("above the 300 MW intake cap");
    const b = run("Wind", "30", "Atlantis");
    expect(b.step).toBe("bus");
    expect(b.messages[b.messages.length - 1].text).toContain("couldn't find that bus");
  });
  it("adds the study-treatment note for firm technologies", () => {
    const st = run("Gas (CCGT / OCGT)");
    expect(st.messages[st.messages.length - 1].text).toContain("firm in both study cases");
  });
  it("reads technologies from free text and scores readiness from the evidence", () => {
    expect(techFromText("a solar + battery hybrid")).toBe("hybrid");
    expect(techFromText("Hydrogen electrolyser")).toBe("electrolyser");
    expect(techFromText("CCGT")).toBe("gas");
    expect(techFromText("gas engines")).toBe("gas_engine");
    expect(readinessScore([])).toBe(0.1);
    expect(readinessScore(["Land rights", "Planning consent", "Financing"])).toBe(1);
  });
  it("marks the slot being asked", () => {
    const slots = draftSlots(run("Battery", "49.9"));
    expect(slots.find((s) => s.current)).toMatchObject({ key: "load", value: "asking…" });
    expect(slots.find((s) => s.key === "mw")?.value).toBe("49.9 MW");
  });
});

const lever = (over: Partial<Suggestion>): Suggestion => ({
  target_type: "line", target_element_id: 1, action: "Add a parallel circuit", reinforcements: [{ kind: "line", element_id: 1, action: "add_parallel", factor: 2 }],
  connects_target: true, freed_mw_2030: 34, freed_mw_2035: 40, newly_connected_project_ids: ["CR-2031"], blocked_project_ids: ["CR-2031"],
  extra_solves: 4, caveat: "", narration: "", ...over,
});

describe("recommendations", () => {
  const reason = { type: "gsp", message: "", kind: "grid" as const, element: null, short: "GSP export limit: the region would push 540 MW up", why: "", action: "" };
  const q = [item({ request_id: "CR-2024", status: "Deferred", rating_mw: 18, reason }), item({ request_id: "CR-1987" })];
  it("opens with the deferred count and MW, and offers quick replies", () => {
    expect(recsOpening("b", "Standard", q)).toContain("1 project is deferred, 18 MW in total");
    expect(recsQuickReplies(q)).toEqual(["Unblock CR-2024", "What limits the GSP?", "Best lever before 2030"]);
  });
  it("routes a question to a project, the GSP or the best lever", () => {
    expect(recIntent("Unblock CR-2024", q)).toEqual({ kind: "project", id: "CR-2024" });
    expect(recIntent("What limits the GSP?", q)).toEqual({ kind: "gsp" });
    expect(recIntent("Best lever before 2030", q)).toEqual({ kind: "best" });
    expect(recIntent("hello", q)).toEqual({ kind: "unknown" });
  });
  it("states the engine's figures, first-order MW as ≈, and only tries network reinforcements", () => {
    expect(projectAnswer(q[0], [lever({})])).toBe("CR-2024 is deferred: GSP export limit: the region would push 540 MW up. I re-solved 1 lever:");
    expect(leverFrees(lever({}))).toBe("≈34 MW by 2030");
    expect(leverFrees(lever({ freed_mw_2030: 0, freed_mw_2035: 12 }))).toBe("≈12 MW by 2035");
    expect(leverTryable(lever({ reinforcements: [] }))).toBe(false);
    expect(bestAnswer([lever({ action: "A", freed_mw_2030: 5 }), lever({ action: "B", freed_mw_2030: 34 })])).toContain('"B"');
  });
});

describe("layout", () => {
  it("collapses the header below 1180 wide, the left cards below 1100, and the dock by height", () => {
    expect(layoutFor(1440, 900, true)).toMatchObject({ wide: true, narrow: false, showDock: true, dockPx: 164, showReadings: true, compactH: false });
    expect(layoutFor(1150, 900, true)).toMatchObject({ wide: false, narrow: false });
    expect(layoutFor(1050, 900, true).narrow).toBe(true);
    expect(layoutFor(1440, 800, true)).toMatchObject({ compactH: true, showReadings: true });
    expect(layoutFor(1440, 740, true).showReadings).toBe(false);
    expect(layoutFor(1440, 700, true).dockPx).toBe(132);
    expect(layoutFor(1440, 540, true).showDock).toBe(false);
    expect(layoutFor(1440, 900, true).sideW).toBe(420);
    expect(layoutFor(1440, 900, false).sideW).toBe(0);
    expect(layoutFor(1000, 900, true).sideW).toBe(320);
  });
});

describe("run stages", () => {
  it("maps the job's stage strings onto the five overlay stages", () => {
    expect(["queued", "starting", "ranking"].map(stageIndex)).toEqual([0, 0, 0]);
    expect(stageIndex("phase 2030: trial 3/12")).toBe(1);
    expect(stageIndex("phase 2035: N-1 screen")).toBe(2);
    expect(stageIndex("year 2029: both cases, N-1")).toBe(3);
    expect(stageIndex("narration")).toBe(4);
    expect(stageReadout("year 2029: both cases, N-1")).toBe("year 2029: both cases, N-1");
  });
});
