// Copilot: the three chat modes. "New project" walks the intake (lib/intake.ts) and adds the
// application to the branch's preliminary queue; "Recommendations" answers from the last run and the
// engine's levers (lib/recs.ts); "Maintenance" plans a works window (lib/maintCopilot.ts) and asks
// the engine for the best one. Nothing here computes physics: the engine does.

import { useCallback } from "react";

import { api } from "../../api";
import { busSuggestions, findBus, indexModel, nameElements, yearResultFor } from "../../lib/derive";
import { answer as intakeAnswer, readinessAnswer, readinessScore, startIntake } from "../../lib/intake";
import type { IntakeCtx } from "../../lib/intake";
import {
  elementSuggestions,
  findElement,
  maintAnswer,
  outageBody,
  scheduledOn,
  searchFailed,
  searchProgress,
  searchRequest,
  startMaint,
  withWindows,
} from "../../lib/maintCopilot";
import type { MaintChat, MaintCtx } from "../../lib/maintCopilot";
import {
  bestAnswer,
  gspAnswer,
  projectAnswer,
  recIntent,
  recsOpening,
  sortByMw2030,
} from "../../lib/recs";
import { EVID, profileOf, techLabel } from "../../theme";
import type { Season, Suggestion } from "../../types";
import type { ChatMode, ChatState, Core, PlannerState, RecMsg } from "./core";
import { withAdded } from "./useRegistry";
import type { EditedFn } from "./useAutoRefresh";
import type { RunFn } from "./useRun";

const nowHM = () => new Date().toTimeString().slice(0, 5);
const branchName = (st: Pick<PlannerState, "activeBranch" | "branches">, bid = st.activeBranch) => st.branches.find((b) => b.branch_id === bid)?.name ?? bid;

/** What the intake needs to know about the branch and the network right now. */
export function intakeCtx(st: Pick<PlannerState, "activeBranch" | "branches" | "maxMw" | "model" | "result" | "year">): IntakeCtx {
  const m = st.model;
  const ix = m ? indexModel(m) : null;
  const yr = yearResultFor(st.result, st.year).yr;
  const branch = st.branches.find((b) => b.branch_id === st.activeBranch);
  return {
    maxMw: st.maxMw,
    branchName: st.activeBranch === "main" ? "a new branch" : (branch?.name ?? st.activeBranch),
    profileLabel: profileOf(branch?.scenario).label,
    busOptions: m && ix ? busSuggestions(m, ix, yr) : [],
    findBus: (t) => (m && ix ? findBus(m, ix, t) : null),
  };
}

/** What the Maintenance chat needs: where it schedules, and the elements it can name. */
export function maintCtx(st: Pick<PlannerState, "activeBranch" | "branches" | "model" | "result" | "sel" | "year">): MaintCtx {
  const m = st.model;
  const ix = m ? indexModel(m) : null;
  const yr = yearResultFor(st.result, st.year).yr;
  const sel = st.sel && st.sel.kind !== "project" && st.sel.kind !== "region" ? st.sel : null;
  return {
    branchName: st.activeBranch === "main" ? "a new branch" : branchName(st),
    suggestions: ix ? elementSuggestions(ix, yr, sel) : [],
    findElement: (t) => (m && ix ? findElement(m, ix, t) : null),
  };
}

export function useCopilot(
  { patch, ref, toastMsg }: Core,
  run: RunFn,
  ensureEditableBranch: () => Promise<string | null>,
  tryLever: (bid: string, s: Suggestion) => Promise<boolean>,
  loadExtras: (bid: string) => Promise<void>,
  edited: EditedFn,
) {
  const setChat = useCallback((c: Partial<ChatState> | ((c: ChatState) => Partial<ChatState>)) =>
    patch((st) => ({ chat: { ...st.chat, ...(typeof c === "function" ? c(st.chat) : c) } })), [patch]);
  const setMaint = useCallback((f: (m: MaintChat) => MaintChat) => setChat((c) => (c.maint ? { maint: f(c.maint) } : {})), [setChat]);

  const remember = (c: ChatState, mode: ChatMode, title: string) =>
    [{ mode, title, at: nowHM() }, ...c.recent.filter((r) => r.title !== title)].slice(0, 4);

  const startProject = useCallback(() => {
    const st = ref.current;
    setChat((c) => ({ mode: "project", intake: startIntake(intakeCtx(st)), input: "", recent: remember(c, "project", "New project") }));
    patch({ tab: "copilot", sideOpen: true });
  }, [patch, ref, setChat]);

  const pushRec = useCallback((msgs: RecMsg[]) => setChat((c) => ({ recs: [...c.recs.filter((m) => !m.loading), ...msgs] })), [setChat]);

  /** Answer a Recommendations question from the last run and the engine's levers. */
  const askRecs = useCallback(
    async (text: string) => {
      const st = ref.current;
      const v = text.trim();
      if (!v || !st.result) return;
      const q = st.result.queue;
      const bid = st.activeBranch || "main";
      const intent = recIntent(v, q);
      setChat((c) => ({ input: "", busy: true, recs: [...c.recs, { user: true, text: v }, { user: false, text: "Re-solving the levers…", loading: true }] }));
      try {
        if (intent.kind === "project") {
          const x = q.find((y) => y.request_id === intent.id)!;
          const levers = x.reason?.kind === "grid" ? await api.getSuggestions(bid, { request_id: x.request_id, with_narration: true, limit: 3 }) : [];
          const ix = st.model ? indexModel(st.model) : null;
          const named = x.reason ? { ...x, reason: { ...x.reason, short: nameElements(x.reason.short, ix) } } : x;
          pushRec([{ user: false, text: projectAnswer(named, levers), levers }]);
          setChat((c) => ({ recent: remember(c, "recs", `Why is ${x.request_id} deferred?`) }));
        } else if (intent.kind === "gsp" || intent.kind === "best") {
          const levers = await api.getSuggestions(bid, { with_narration: true, limit: 5 });
          if (intent.kind === "gsp") {
            const yr = yearResultFor(st.result, st.year).yr;
            const gspLevers = levers.filter((s) => s.target_type === "gsp");
            pushRec([{ user: false, text: gspAnswer(yr?.gsp_export_mw ?? null, yr?.gsp_limit_mw ?? null, yr?.year ?? st.year, st.boundary?.sgt_count ?? null), levers: gspLevers }]);
          } else {
            pushRec([{ user: false, text: bestAnswer(levers), levers: sortByMw2030(levers).slice(0, 2) }]);
          }
        } else {
          const first = q.find((y) => y.status === "Deferred");
          pushRec([{ user: false, text: first ? `I can explain or unblock a deferred project. Name one, for example ${first.request_id}, or ask what limits the GSP.` : "Nothing is deferred in the last run. Ask what limits the GSP, or add projects and re-run." }]);
        }
      } catch (e) {
        pushRec([{ user: false, text: `The engine could not re-solve that: ${e instanceof Error ? e.message : "check the API is running"}.` }]);
      } finally {
        setChat({ busy: false });
      }
    },
    [pushRec, ref, setChat],
  );

  /** Start a Recommendations chat (optionally straight into one project: "What would it take?"). */
  const startRecs = useCallback(
    (target?: string) => {
      const st = ref.current;
      const name = branchName(st);
      const prof = st.result ? profileOf(st.result.params.scenario).label : profileOf(null).label;
      setChat((c) => ({ mode: "recs", input: "", recs: [{ user: false, text: recsOpening(name, prof, st.result?.queue ?? []) }], recent: remember(c, "recs", "Recommendations") }));
      patch({ tab: "copilot", sideOpen: true, sel: null });
      if (target) void askRecs(`Unblock ${target}`);
    },
    [askRecs, patch, ref, setChat],
  );

  /** Start a Maintenance chat (the element selected on the map is offered first). */
  const startMaintChat = useCallback(() => {
    const st = ref.current;
    setChat((c) => ({ mode: "maint", maint: startMaint(maintCtx(st)), input: "", recent: remember(c, "maint", "Maintenance") }));
    patch({ tab: "copilot", sideOpen: true });
  }, [patch, ref, setChat]);

  /** Ask the engine for the best window (a background job on the viewed branch; main may be searched). */
  const searchWindows = useCallback(
    async (m: MaintChat) => {
      const st = ref.current;
      const bid = st.activeBranch || "main";
      setChat({ busy: true });
      try {
        const res = await api.bestWindowJob(bid, searchRequest(m), (stage, f) => setMaint((x) => searchProgress(x, stage, f)));
        setMaint((x) => withWindows(x, res.options, maintCtx(ref.current)));
        if (m.element) setChat((c) => ({ recent: remember(c, "maint", `Best window for ${m.element!.label}`) }));
      } catch (e) {
        setMaint((x) => searchFailed(x, e instanceof Error ? e.message : "check the API is running"));
      } finally {
        setChat({ busy: false });
      }
    },
    [ref, setChat, setMaint],
  );

  /** "Schedule on <branch>": store the window on the branch (main opens a branch first). */
  const scheduleWindow = useCallback(
    async (season: Season, year: number) => {
      const m = ref.current.chat.maint;
      if (!m?.element) return;
      const bid = await ensureEditableBranch();
      if (!bid) return;
      try {
        await api.addOutage(bid, outageBody(m, season, year));
        await loadExtras(bid);
        edited("works"); // re-solves that window's year in the background
        const st = ref.current;
        const prof = profileOf(st.branches.find((b) => b.branch_id === bid)?.scenario).label;
        setMaint((x) => scheduledOn(x, season, year, branchName(st, bid), prof));
        patch({ year, tab: "copilot" });
      } catch (e) {
        toastMsg(`Could not schedule it: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
      }
    },
    [edited, ensureEditableBranch, loadExtras, patch, ref, setMaint, toastMsg],
  );

  /** The composer / a quick reply: route to the active mode. */
  const send = useCallback(
    (text: string) => {
      const st = ref.current;
      if (st.chat.mode === "recs") return void askRecs(text);
      if (st.chat.mode === "project" && st.chat.intake) setChat({ intake: intakeAnswer(st.chat.intake, text, intakeCtx(st)), input: "" });
      if (st.chat.mode === "maint" && st.chat.maint) {
        const prev = st.chat.maint;
        const next = maintAnswer(prev, text, maintCtx(st));
        setChat({ maint: next, input: "" });
        if (next.step === "searching" && prev.step !== "searching") void searchWindows(next);
      }
    },
    [askRecs, ref, searchWindows, setChat],
  );

  const toggleEvidence = useCallback(
    (label: string) =>
      setChat((c) => (c.intake ? { intake: { ...c.intake, readySel: c.intake.readySel.includes(label) ? c.intake.readySel.filter((x) => x !== label) : [...c.intake.readySel, label] } } : {})),
    [setChat],
  );
  const evidenceDone = useCallback(() => {
    const it = ref.current.chat.intake;
    if (it) send(readinessAnswer(it.readySel));
  }, [ref, send]);

  /** "Add to preliminary queue": the application goes onto the branch, unranked until the next run. */
  const addPrelim = useCallback(async () => {
    const it = ref.current.chat.intake;
    if (!it || it.step !== "done" || !it.tech || !it.bus) return;
    const bid = await ensureEditableBranch();
    if (!bid) return;
    const ready = it.ready ?? [];
    try {
      const row = await api.addCandidate({
        applicant: it.name || `${techLabel(it.tech)} application`,
        bus_id: it.bus.id,
        technology: it.tech,
        rating_mw: it.mw ?? 0,
        import_mw: it.load,
        readiness_score: readinessScore(ready),
        readiness_rationale: EVID.filter((e) => ready.includes(e.label)).map((e) => e.label).join("; ") || "No evidence supplied",
        commissioning_year: it.year,
        branch_id: bid,
      });
      const st = ref.current;
      const prof = profileOf(st.branches.find((b) => b.branch_id === bid)?.scenario).label;
      patch((x) => ({ added: withAdded(x.added, bid, row), tab: "copilot" }));
      setChat((c) => ({
        intake: c.intake && {
          ...c.intake,
          messages: [
            ...c.intake.messages.map((m) => ({ ...m, action: m.action === "add" ? undefined : m.action })),
            { user: true, text: "Add it" },
            { user: false, text: `Added ${row.request_id} to Preliminary on ${branchName(st, bid)}. It has no phase yet. Run on ${prof} demand to rank it against the rest of the queue.`, action: "run" },
          ],
        },
      }));
    } catch (e) {
      toastMsg(`Could not add the project: ${e instanceof Error ? e.message : "check the API is running"}`, "warn");
    }
  }, [ensureEditableBranch, patch, ref, setChat, toastMsg]);

  const anotherProject = useCallback(() => {
    const st = ref.current;
    setChat((c) => ({ intake: c.intake && { ...startIntake(intakeCtx(st)), messages: [...c.intake.messages, { user: true, text: "Start another project" }, { user: false, text: "Sure. Which technology?" }] } }));
  }, [ref, setChat]);

  /** "Try on <branch>": store the lever's reinforcements, then offer the run that measures them. */
  const applyLever = useCallback(
    async (s: Suggestion) => {
      const bid = await ensureEditableBranch();
      if (!bid) return;
      if (!(await tryLever(bid, s))) return;
      const st = ref.current;
      const prof = profileOf(st.branches.find((b) => b.branch_id === bid)?.scenario).label;
      pushRec([
        { user: true, text: `Try: ${s.action}` },
        { user: false, text: `Added "${s.action}" to ${branchName(st, bid)} as a proposed reinforcement. Run on ${prof} demand to measure it against the queue.`, action: "run" },
      ]);
    },
    [ensureEditableBranch, pushRec, ref, tryLever],
  );

  const newChat = useCallback(() => setChat({ mode: null, input: "" }), [setChat]);
  const resume = useCallback((mode: ChatMode) => setChat({ mode }), [setChat]);
  const setInput = useCallback((input: string) => setChat({ input }), [setChat]);
  const runFromChat = useCallback(() => void run(), [run]);

  return {
    startProject, startRecs, startMaintChat, send, toggleEvidence, evidenceDone, addPrelim, anotherProject, applyLever,
    scheduleWindow, newChat, resume, setInput, runFromChat,
  };
}
