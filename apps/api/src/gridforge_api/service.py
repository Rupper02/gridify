"""Run the engine for a branch: resolve parameters, build candidates, cache, enrich for the map,
solve the plan year by year, judge a merge against the parent, and keep the findings ledger."""

from contextlib import nullcontext
import hashlib
import json
from collections.abc import Callable
from typing import NamedTuple

from .errors import Invalid, NotSolved
from gridforge_optimizer.sources import Pathway
from gridforge_optimizer import (
    Limits,
    element_ratings,
    limits,
    run_digest,
    PLAN_YEARS,
    STUDIES,
    Candidate,
    ConsequenceDiff,
    MergeVerdict,
    OptimizeParams,
    OptimizeResult,
    Outage,
    OutageStudy,
    Reinforcement,
    StudyContext,
    StudyResult,
    Suggestion,
    YearResult,
    against_recommendation,
    apply_reinforcement,
    diff_results,
    energisation_years,
    evaluate_year,
    evaluate_years,
    extract_findings,
    merge_verdict,
    chunk_study,
    merge_chunks,
    optimize,
    run_study,
    suggest_unblock,
)
from gridforge_optimizer.config import FORECASTS
from gridforge_optimizer.naming import name_text

from . import ledger, proposals, repository
from .cache import MAX_PAYLOAD_ENTRIES, ResultCache, cand_key, remember
from .config import now
from .projects import Projects
from .schemas import OptimizeRequest
from .store import ScenarioStore


def resolve_params(body: OptimizeRequest, forecasts: dict[str, Pathway] | None = None) -> OptimizeParams:
    """Resolve a request to concrete OptimizeParams: on a grid with its own pathways (`forecasts`: the built-in grid's
    DFES projections, an import's entered forecast) the pathway's network-wide multiplier for every plan year (the
    engine grows per load where the network carries curves, `network.grow_for`); otherwise a named FES pathway's
    anchors, or the request's own figures ("custom")."""
    weights = {
        k: v for k, v in {
            "w_readiness": body.w_readiness, "w_need": body.w_need, "w_strategic": body.w_strategic,
        }.items() if v is not None
    }
    if forecasts is not None:
        if body.scenario not in forecasts:
            raise Invalid(f"this grid's forecast has no '{body.scenario}' pathway; it has {', '.join(forecasts)}")
        curve = forecasts[body.scenario].curve
        return OptimizeParams(growth_2030=curve[2030], growth_2035=curve[2035], scenario=body.scenario, curve=curve, **weights)
    if body.scenario in FORECASTS:
        scenario = body.scenario
        growth_2030 = FORECASTS[scenario]["growth_2030"]
        growth_2035 = FORECASTS[scenario]["growth_2035"]
    else:
        scenario = "custom"
        growth_2030, growth_2035 = body.growth_2030, body.growth_2035
    return OptimizeParams(growth_2030=growth_2030, growth_2035=growth_2035, scenario=scenario, **weights)


class BranchInputs(NamedTuple):
    """What a branch's run depends on (PlanService.inputs)."""

    req: OptimizeRequest
    cands: list[Candidate]
    ckey: str
    reinforcements: list[Reinforcement]
    outages: list[Outage]
    schedule: dict[str, int]
    project_id: str
    baseline: str  # the project's content identity (its snapshot or file fingerprint): part of every key
    net_factory: Callable  # the project's network WITH the branch's simulated reinforcements applied: studies, suggestions, the boundary
    base_factory: Callable  # the project's network as it is: for the engine calls that take `reinforcements` and apply them themselves
    rows: list[dict]  # the stored project rows `cands` came from (applicant, schedule, control: what the payload adds)


class Freshness(NamedTuple):
    """Whether a branch's stored result matches its current inputs: the merge gate's first question,
    answered from the cache keys (the same ones every run is stored under), never from timestamps."""

    fresh: bool
    reasons: list[str]
    optimize_key: str
    years_key: str


def reinf_key(reinforcements) -> str:
    """Cache-key part for simulated reinforcements ("" when none, so plain runs keep their keys). The
    "r2:" salt retires results solved before the engine was handed the plain network: those applied
    every reinforcement twice (once in the factory, once in the engine)."""
    if not reinforcements:
        return ""
    return "r2:" + hashlib.md5(json.dumps([r.model_dump() for r in reinforcements], sort_keys=True).encode()).hexdigest()


def years_key(b: BranchInputs) -> str:
    """Cache-key part for what the years depend on beyond the queue: outages, schedule, reinforcements."""
    sig = [reinf_key(b.reinforcements), [o.model_dump() for o in b.outages], sorted(b.schedule.items())]
    return hashlib.md5(json.dumps(sig, sort_keys=True, default=str).encode()).hexdigest()


def reinforced_factory(reinforcements, base_factory: Callable):
    """A net factory with the branch's simulated reinforcements applied (the project's own when none)."""
    if not reinforcements:
        return base_factory

    def factory():
        net = base_factory()
        for r in reinforcements:
            apply_reinforcement(net, r)
        return net
    return factory


class PlanService:
    """The engine behind the API's optimize / diff / merge-check / suggestion endpoints, with its
    collaborators (the projects and their grids, scenarios store, result cache) handed in."""

    def __init__(self, projects: Projects, store: ScenarioStore, cache: ResultCache):
        self.projects = projects
        self.store = store
        self.cache = cache

    # --- inputs ------------------------------------------------------------------------------------
    def params(self, req: OptimizeRequest, project_id: str) -> OptimizeParams:
        """A request's engine parameters on its project (an imported grid plans on its own forecast)."""
        return resolve_params(req, self.projects.forecasts(project_id))

    @staticmethod
    def candidates(rows: list[dict]) -> list[Candidate]:
        """The optimizer's candidate list from a branch's stored project rows."""
        return [
            Candidate(
                request_id=r["request_id"],
                bus_id=None if r["bus_id"] is None else int(r["bus_id"]),
                technology=r["technology"],
                rating_mw=None if r["rating_mw"] is None else float(r["rating_mw"]),
                readiness_score=float(r["readiness_score"]),
                strategic_fit=float(r["strategic_fit"]),
                readiness_rationale=r.get("readiness_rationale") or "",
                status=r["status"],
                review_reasons=r.get("review_reasons") or "",
                commissioning_year=(None if r.get("commissioning_year") is None else int(r["commissioning_year"])),
                import_mw=(None if r.get("import_mw") is None else float(r["import_mw"])),
                control=repository.control_of(r),
            )
            for r in rows
        ]

    def inputs(self, branch_id: str) -> BranchInputs:
        """Everything a branch's run depends on, read once: its parameters, projects, simulated
        reinforcements, planned outages and the operator's scheduled years."""
        with self.store.cursor() as con:
            row = repository.require_branch(con, branch_id)
            reinf = repository.reinforcements(con, branch_id)
            outages = repository.outages(con, branch_id)
            rows = repository.candidate_rows(con, branch_id)
        cands = self.candidates(rows)
        schedule = {r["request_id"]: int(r["scheduled_year"]) for r in rows if r.get("scheduled_year") is not None}
        pid = row["project_id"]
        base = self.projects.source(pid).build_net
        return BranchInputs(repository.branch_request(row), cands, cand_key(cands), reinf, outages, schedule, pid,
                            self.projects.baseline(pid), reinforced_factory(reinf, base), base, rows)

    def edited(self) -> None:
        """A branch's plan changed. Every engine result is keyed by its inputs and needs nothing; the run payload is
        dropped because a payload hit skips the findings-ledger write, so a branch edited back to an earlier state
        would keep the ledger of the state in between. (It also carries rows no key covers: the applicant.)"""
        self.cache.payload.clear()

    # --- the keys every result is stored under -------------------------------------------------------
    def _optimize_key(self, b: BranchInputs, params: OptimizeParams) -> str:
        return self.cache.key("optimize", params, b.ckey, b.baseline, extra=reinf_key(b.reinforcements))

    def _years_key(self, b: BranchInputs, params: OptimizeParams) -> str:
        return self.cache.key("years", params, b.ckey, b.baseline, extra=years_key(b))

    # --- runs -------------------------------------------------------------------------------------
    def compute(self, b: BranchInputs, progress=None, *, solve: bool = True, wait: bool = True) -> OptimizeResult:
        """Run the deterministic optimizer for a branch's inputs (its request, candidate set and simulated
        reinforcements, on its project's network), through the cache: the in-process dict, the durable
        `result_cache` table (survives restarts, shared by every endpoint that needs the same run), then
        the engine. Keys include the project's baseline, the parameters, the candidate set, the
        reinforcements and the engine fingerprint. `solve` / `wait` as `ResultCache.through` takes them (a read
        that must not solve, or must not queue behind a run)."""
        params = self.params(b.req, b.project_id)
        return self.cache.through(
            self._optimize_key(b, params), "optimize", baseline=b.baseline,
            parse=OptimizeResult.model_validate_json,
            compute=lambda: optimize(b.cands, params, list(b.reinforcements), trial_cache=self.cache.trial_cache(params, b.baseline),
                                     net_factory=b.base_factory, progress=progress),
            dump=lambda r: r.model_dump_json(), solve=solve, wait=wait,
        )

    def branch_result(self, branch_id: str) -> OptimizeResult:
        """A branch's engine result (the queue and phases; what diff and suggestions compare)."""
        return self.compute(self.inputs(branch_id))

    def plan_years(self, b: BranchInputs, result: OptimizeResult, view_year: int | None = None,
                   progress=None, on_year=None, *, solve: bool = True, wait: bool = True) -> dict[str, YearResult]:
        """Every year of the plan (years.evaluate_years), cached like a run: the key adds the outages,
        the schedule and the reinforcements, which change the years but not the queue. A cached plan
        still reaches `on_year` year by year, the same way a fresh one does."""
        params = self.params(b.req, b.project_id)
        return self.cache.through(
            self._years_key(b, params), "years", baseline=b.baseline,
            parse=lambda s: {k: YearResult.model_validate(v) for k, v in json.loads(s).items()},
            compute=lambda: evaluate_years(result, b.cands, params, scheduled=b.schedule, outages=b.outages,
                                           reinforcements=b.reinforcements, view_year=view_year, net_factory=b.base_factory,
                                           progress=progress, on_year=on_year, cache=self.cache.year_cache(b.baseline)),
            dump=lambda years: json.dumps({k: v.model_dump() for k, v in years.items()}),
            on_hit=(lambda years: [on_year(y) for y in years.values()]) if on_year else None, solve=solve, wait=wait,
        )

    def result_with_years(self, b: BranchInputs, *, solve: bool = True, wait: bool = True) -> OptimizeResult:
        """A branch's engine result with every plan year attached (both through the caches)."""
        result = self.compute(b, solve=solve, wait=wait)
        return result.model_copy(update={"years": self.plan_years(b, result, solve=solve, wait=wait)})

    def works_on_plan(self, plan: BranchInputs, result: OptimizeResult, outages: list[Outage], *, wait: bool = True) -> list[OutageStudy]:
        """Another branch's planned windows studied on this plan's energised network (its projects,
        schedule, parameters and reinforcements; the windows' own repowers apply after them), so the
        diff can tell what the branch's projects do to each window. Only the years with a window are
        solved, without the year's own N-1 screen but with the screen during the windows (so the diff
        can compare the second faults each side adds): per year one intact solve pair plus the window
        study, its curtailment search and the backbone screened with the window in place. Cached like the years: the key
        is this plan's years key with the outages swapped for the windows studied."""
        if not outages:
            return []
        params = self.params(plan.req, plan.project_id)
        on = plan._replace(outages=list(outages))

        def study() -> list[OutageStudy]:
            in_service = energisation_years(result, plan.schedule)
            return [
                s
                for y in sorted({o.year for o in outages})
                for s in evaluate_year(y, plan.cands, params, in_service, outages=on.outages,
                                       reinforcements=plan.reinforcements, n1=False, n1_windows=True, net_factory=plan.base_factory).outage_studies
            ]

        return self.cache.through(
            self.cache.key("works", params, on.ckey, plan.baseline, extra=years_key(on)), "works", baseline=plan.baseline,
            parse=lambda s: [OutageStudy.model_validate(x) for x in json.loads(s)],
            compute=study,
            dump=lambda studies: json.dumps([s.model_dump() for s in studies]), wait=wait,
        )

    def limits(self, branch_id: str, *, solve: bool = False, wait: bool = False) -> Limits:
        """What limits a branch's plan (`analysis.limits`): the binding set, the deferrals' chains, the N-1 clusters and
        the works, from the cached run. A read by default: `NotSolved` unless the branch has run for what it holds."""
        b = self.inputs(branch_id)
        res = self.result_with_years(b, solve=solve, wait=wait)
        return limits(res, res.years, self.projects.model(b.project_id), element_ratings(b.net_factory()))

    def digest(self, branch_id: str) -> dict:
        """The run digest the note is written from (`analysis.run_digest`): the limits plus what changed against the
        parent and the gate's verdict. The branch's own plan must be solved (`NotSolved` otherwise); the parent's
        side is solved if need be, so call it under the solver gate."""
        b = self.inputs(branch_id)
        res = self.result_with_years(b, solve=False, wait=True)
        lim = limits(res, res.years, self.projects.model(b.project_id), element_ratings(b.net_factory()))
        with self.store.cursor() as con:
            head = repository.require_branch(con, branch_id)
            base = repository.base_of(con, head)
            name = head.get("name") or branch_id
        d, verdict = None, None
        if base is not None:
            d = self.diff(branch_id, base["branch_id"])
            verdict, _ = self.merge_check(branch_id, base["branch_id"])
        return run_digest(name, lim, res, res.years, diff=d, gate=verdict, assumptions=len(self.projects.assumptions(b.project_id))).model_dump(exclude_none=True)

    def _solved_pair(self, head_in: BranchInputs, base_in: BranchInputs, *, wait: bool = True) -> tuple[OptimizeResult, OptimizeResult, ConsequenceDiff]:
        """Both plans with their years, and the consequence diff between them (the branch's windows
        studied on the base's plan too). `wait=False` never queues behind a run (`NotSolved` instead)."""
        head = self.result_with_years(head_in, wait=wait)
        base = self.result_with_years(base_in, wait=wait)
        works_on_base = self.works_on_plan(base_in, base, head_in.outages, wait=wait)
        return head, base, diff_results(base, head, works_on_base=works_on_base)

    def _base_inputs(self, head_in: BranchInputs, base_id: str) -> tuple[BranchInputs, str | None]:
        """The base's inputs on the branch's demand profile, and the base's own profile. The comparison is like for
        like (merging adopts the branch's profile), so a difference between the two plans is the branch's projects,
        works and reinforcements, never demand; the gate still says the profile changes (`base_profile`)."""
        base_in = self.inputs(base_id)
        req = base_in.req.model_copy(update={"scenario": head_in.req.scenario, "growth_2030": head_in.req.growth_2030,
                                             "growth_2035": head_in.req.growth_2035})
        return base_in._replace(req=req), base_in.req.scenario

    def _named(self, verdict: MergeVerdict, project_id: str) -> MergeVerdict:
        """The gate's findings with their elements named by place (the engine writes "line 1", "bus 16"): what the
        planner, a merge refusal and the agents read."""
        names = self.projects.names(project_id)
        name = lambda fs: [f.model_copy(update={"message": name_text(f.message, names)}) for f in fs]  # noqa: E731
        return verdict.model_copy(update={"blockers": name(verdict.blockers), "warnings": name(verdict.warnings),
                                          "context": name(verdict.context), "summary": name_text(verdict.summary, names)})

    def _require_run(self, head_id: str) -> None:
        """A read that must not solve the branch's own plan: `NotSolved` (run it first) unless its result is current."""
        fresh = self.freshness(head_id)
        if not fresh.fresh:
            raise NotSolved("this branch has not been run for what it holds now: " + "; ".join(fresh.reasons) + ". Run it, then compare.", retry=False)

    def diff(self, head_id: str, base_id: str, *, blocking: bool = True) -> ConsequenceDiff:
        """The consequence diff of a branch against its base: the queue and phases, every plan year,
        and each of the branch's planned windows against the same window on the base's plan. Not `blocking`
        (the planner's reads): the branch's own plan must be solved already, and the base's side and the
        windows on it are computed only while the engine is free, else `NotSolved` (409) at once."""
        if not blocking:
            self._require_run(head_id)
        head_in = self.inputs(head_id)
        return self._solved_pair(head_in, self._base_inputs(head_in, base_id)[0], wait=blocking)[2]

    # --- the merge gate -------------------------------------------------------------------------------
    def freshness(self, branch_id: str) -> Freshness:
        """Is the branch solved for its current inputs? True when the queue AND the plan years are in
        the cache under the keys its current projects, profile, reinforcements, works windows and
        schedule produce. Costs no solve."""
        b = self.inputs(branch_id)
        params = self.params(b.req, b.project_id)
        okey, ykey = self._optimize_key(b, params), self._years_key(b, params)
        reasons: list[str] = []
        if not self.cache.has(okey):
            reasons.append("the queue has not been run for the branch's current projects, demand profile or reinforcements")
        elif not self.cache.has(ykey):
            reasons.append("the plan years have not been solved for the current schedule or works windows")
        return Freshness(not reasons, reasons, okey, ykey)

    def _what_merging_undoes(self, head_id: str, base_id: str) -> dict:
        """What a merge of the head into its base would take away from the base, read from the store (no solve):
        the parent's changes since the fork the branch lacks (None when the fork point is not known), and the works
        windows and reinforcements the branch itself removed."""
        with self.store.cursor() as con:
            head = repository.require_branch(con, head_id)
            onto_parent = head.get("parent_id") == base_id
            plan = repository.rebase_plan(con, head) if onto_parent else None
            removed = proposals.on_merge(repository.outage_rows(con, base_id), repository.outage_rows(con, head_id),
                                         repository.reinforcement_rows(con, base_id), repository.reinforcement_rows(con, head_id))
        works = [w["outage_id"] for w in removed["works_removed"]]
        reinf = [r["reinforcement_id"] for r in removed["reinforcements_removed"]]
        known = plan is not None and plan.fork_kind != "none"
        if known:  # what the parent added after the fork is `behind`, not something the branch removed
            works = [w for w in works if w in plan.fork["works"]]
            reinf = [r for r in reinf if r in plan.fork["reinforcements"]]
        return {"parent_moved": [c.move() for c in plan.behind] if known else None,
                "fork_unknown": plan is not None and not known, "removed_works": works, "removed_reinforcements": reinf}

    def merge_check(self, head_id: str, base_id: str, *, blocking: bool = True) -> tuple[MergeVerdict, dict]:
        """May this branch merge into its base? A stale branch is refused without a solve; otherwise
        both plans (the base solved if need be, as the diff does) go through `gate.merge_verdict`. A branch
        behind its parent is refused either way. Returns the verdict and the evidence it was judged on
        (cache keys, snapshot, engine). Not `blocking`: the base's side is computed only while the engine is
        free, else `NotSolved` (409) at once instead of a request parked behind a run."""
        undoes = self._what_merging_undoes(head_id, base_id)
        fresh = self.freshness(head_id)
        head_in = self.inputs(head_id)
        evidence = {"fresh": fresh.fresh, "stale_reasons": fresh.reasons, "head_optimize_key": fresh.optimize_key,
                    "head_years_key": fresh.years_key, "snapshot_id": head_in.baseline,
                    "engine": self.cache.engine}
        if not fresh.fresh:
            verdict = merge_verdict(None, None, fresh=False, stale_reasons=fresh.reasons, base_label=base_id,
                                    parent_moved=undoes["parent_moved"], fork_unknown=undoes["fork_unknown"])
            return self._named(verdict, head_in.project_id), evidence
        base_in, base_profile = self._base_inputs(head_in, base_id)
        head, base, d = self._solved_pair(head_in, base_in, wait=blocking)
        evidence["base_years_key"] = self._years_key(base_in, self.params(base_in.req, base_in.project_id))
        verdict = merge_verdict(head, base, d, scheduled=head_in.schedule, base_label=base_id, base_profile=base_profile, **undoes)
        return self._named(verdict, head_in.project_id), evidence

    # --- the findings ledger --------------------------------------------------------------------------
    def record_findings(self, branch_id: str, b: BranchInputs, result: OptimizeResult, years: dict[str, YearResult]) -> None:
        """Write what a run found to the ledger: upsert what is still there (same fingerprint, same
        row), resolve what the run no longer reports. The evidence points at the exact cached study."""
        params = self.params(b.req, b.project_id)
        names = self.projects.names(b.project_id)  # the ledger reads by place ("Bicker Fen to Boston 132 kV, circuit 2 (line 1)"), never "line 1"
        found = [f.model_copy(update={"message": name_text(f.message, names)})
                 for f in extract_findings(result.model_copy(update={"years": years}), scheduled=b.schedule)]
        evidence = {"optimize_key": self._optimize_key(b, params),
                    "years_key": self._years_key(b, params), "snapshot_id": b.baseline,
                    "engine": self.cache.engine}
        at = now()
        with self.store.cursor() as con, con.transaction():  # one commit for a thousand rows, under the store's lock once
            ledger.upsert_findings(con, branch_id, found, evidence, at)
            ledger.resolve_missing(con, branch_id, {f.fingerprint for f in found}, at)

    # --- suggestions and windows ------------------------------------------------------------------------
    def suggestions(self, branch_id: str, limit: int, request_id: str | None = None) -> list[Suggestion]:
        """`suggest_unblock` for a branch (optionally for one deferred project), through the same two
        cache layers (it costs dozens of solves). Trialled on the branch's reinforced network."""
        b = self.inputs(branch_id)
        params = self.params(b.req, b.project_id)
        base = self.compute(b)
        return self.cache.through(
            self.cache.key("suggest", params, b.ckey, b.baseline, extra=f"{limit}|{request_id}|{reinf_key(b.reinforcements)}"), "suggest",
            baseline=b.baseline,
            parse=lambda s: [Suggestion.model_validate(x) for x in json.loads(s)],
            compute=lambda: suggest_unblock(b.cands, params, base=base, max_suggestions=limit, request_id=request_id,
                                            net_factory=b.net_factory),
            dump=lambda sugs: json.dumps([x.model_dump() for x in sugs]),
        )

    # --- studies (the agents' tools and POST /branches/{id}/studies/{kind}) --------------------------------------------
    def study_key(self, branch_id: str, kind: str, p) -> str:
        """The cache key of a study on a branch: the branch's inputs, the study's parameters, and the plan
        years' key for the studies that read them (what an agent's recorded step points at)."""
        b = self.inputs(branch_id)
        extra = f"{reinf_key(b.reinforcements)}|{p.model_dump_json()}" + (f"|{years_key(b)}" if STUDIES[kind].needs_plan else "")
        return self.cache.key(f"study:{kind}", self.params(b.req, b.project_id), b.ckey, b.baseline, extra=extra)

    def study(self, branch_id: str, kind: str, params=None, progress=None, *, chunked: bool = False, hold=nullcontext,
              context: StudyContext | None = None) -> StudyResult:
        """Run one study from `studies.STUDIES` on a branch's plan: its reinforced network, and its result with
        the plan years for the studies that read them. Cached like everything else, under the branch's inputs
        and the study's parameters, so an agent asking twice costs one solve. `chunked` runs the study's
        independent parts one by one (each a study with its own parameters, cached on its own, so a retry
        after a crash recomputes only the parts that are not in the cache) and stores the merged result
        under the whole study's key. `hold` wraps every solve (the agents pass `SolverGate.hold`, so an
        operator's job gets the solver between chunks, not after the whole study): the plan the study reads is solved
        once, inside it, and handed to every chunk (`context`)."""
        spec = STUDIES[kind]
        p = params if params is not None and not isinstance(params, dict) else spec.params_model.model_validate(params or {})
        b = self.inputs(branch_id)
        engine_params = self.params(b.req, b.project_id)

        gated = hold is not nullcontext  # an agent's study: every solve through its gate (operators first, its deadline)
        report = progress or (lambda _s, _f: None)

        def plan_context() -> StudyContext:
            """The plan the study reads, solved (when not cached) inside the gate like every other solve."""
            if context is not None:
                return context
            with hold():
                result = self.result_with_years(b) if spec.needs_plan else None
            return StudyContext(net_factory=b.net_factory, params=engine_params, candidates=b.cands,
                                result=result, progress=report, schedule=b.schedule, outages=b.outages)

        def compute() -> StudyResult:
            ctx = plan_context()
            if chunked:
                parts = chunk_study(kind, ctx, p)
                if len(parts) > 1:
                    results = []
                    for i, part in enumerate(parts):  # each chunk lands as a progress report, so a long study is never silent
                        report(f"{kind}: part {i + 1} of {len(parts)}", i / len(parts))
                        results.append(self.study(branch_id, kind, part, progress, hold=hold, context=ctx))
                    report(f"{kind}: {len(parts)} parts done", 1.0)
                    return merge_chunks(kind, p, results)
            with hold():
                return run_study(kind, ctx, p)

        # a gated study takes the solver through its gate, per solve: the cache must not hold it while the gate waits
        return self.cache.through(self.study_key(branch_id, kind, p), f"study:{kind}", baseline=b.baseline,
                                  parse=StudyResult.model_validate_json, compute=compute, dump=lambda r: r.model_dump_json(),
                                  locked=not gated)

    # --- the payload the planner renders -------------------------------------------------------------------
    def _enrich(self, result: OptimizeResult, branch_id: str, b: BranchInputs) -> dict:
        """The engine result shaped for the map: coordinates, applicant, the operator's schedule
        against the recommendation, each phase's generators, and what the run studied."""
        out = result.model_dump()
        coords = self.projects.bus_coords(b.project_id)
        rows_by_id = {r["request_id"]: r for r in b.rows}
        for q in out["queue"]:
            bid = q["bus_id"]
            q["lon"], q["lat"] = coords.get(int(bid), (None, None)) if bid is not None else (None, None)
            row = rows_by_id.get(q["request_id"], {})
            q["applicant"] = row.get("applicant") or ""
            q["import_mw"] = row.get("import_mw")
            q["control"] = repository.control_of(row) if row else None  # how the run ran it (None: not stated, unity)
            # the operator's chosen energisation year (persisted on the branch) vs the optimizer's
            # recommendation (one definition, shared with the findings ledger and the merge gate)
            sy = row.get("scheduled_year")
            q["scheduled_year"] = None if sy is None else int(sy)
            q["against_recommendation"] = against_recommendation(q.get("recommended_year"), q["scheduled_year"])

        queue_by_id = {q["request_id"]: q for q in out["queue"]}
        for phase in out["phases"].values():
            gens = []
            for rid in phase["accepted"]:
                qi = queue_by_id.get(rid)
                if qi and qi.get("lon") is not None:
                    gens.append({
                        "request_id": rid, "bus_id": qi["bus_id"], "lon": qi["lon"], "lat": qi["lat"],
                        "rating_mw": qi["rating_mw"], "technology": qi["technology"],
                    })
            phase["generators"] = gens
        out["years"] = {}
        out["years_total"] = len(PLAN_YEARS)
        out["studied"] = {  # what this result covers, so the planner can tell when it is out of date
            "outage_ids": [o.outage_id for o in b.outages],
            "reinforcements": [r.model_dump() for r in b.reinforcements],
            "schedule": b.schedule,
        }
        out["snapshot_id"] = b.baseline
        out["project_id"] = b.project_id
        out["branch_id"] = branch_id
        # the identity of this result's physics (the plan-years cache key): what a review or an agent event
        # refers to, the same for a re-run with the same inputs, different as soon as anything changes
        out["run_key"] = self._years_key(b, self.params(b.req, b.project_id))
        return out

    def _payload_key(self, b, body: OptimizeRequest, branch_id: str) -> str:
        # the payload is per branch (it carries the branch id, schedule and ledger write), while the engine
        # results underneath it are shared by every branch with the same inputs
        return self.cache.key("payload", self.params(body, b.project_id), b.ckey, b.baseline, extra=f"{branch_id}|{years_key(b)}")

    def payload_key(self, body: OptimizeRequest, branch_id: str) -> str:
        """The identity of `optimize_payload(body, branch_id)`'s result (the view year only orders the work):
        two runs with the same key compute the same thing, so a job for one can serve both."""
        return self._payload_key(self.inputs(branch_id)._replace(req=body), body, branch_id)

    def warm_profiles(self, branch_id: str, idle=lambda: True) -> None:
        """Pre-compute a branch's plan on every selectable demand profile other than its own (its own is a
        real job the planner joins), so switching the profile finds the run in the cache. Best-effort, on
        the job worker: before each profile it checks `idle()` and stops as soon as a real job is waiting."""
        own_in = self.inputs(branch_id)
        own = own_in.req
        for fid in self.projects.pathway_ids(own_in.project_id):
            if not idle():
                return
            if fid != own.scenario:
                self.optimize_payload(own.model_copy(update={"scenario": fid}), branch_id)

    def optimize_payload(self, body: OptimizeRequest, branch_id: str, progress=None,
                         publish=None, view_year: int | None = None) -> dict:
        """Run a branch and enrich the result for the map, then solve every year of the plan.

        The greedy run decides the queue (progress 0..0.5); the years follow (0.5..0.95), the viewed
        year first; then the findings ledger (0.96). `publish(payload)` receives
        the partial payload as soon as the queue is known and again as each year lands, so the planner
        shows results while the rest are still solving. A run on the branch's own demand profile (not a
        warm-up what-if) also writes the findings ledger.
        """
        report = progress or (lambda _s, _f: None)
        stored = self.inputs(branch_id)
        b = stored._replace(req=body)
        params = self.params(body, b.project_id)
        key = self._payload_key(b, body, branch_id)
        if key in self.cache.payload:
            return self.cache.payload[key]

        # the engine's own "done" means the queue is decided; the years are still to come
        result = self.compute(b, progress=lambda s, f: report("queue decided" if s == "done" else s, 0.5 * f))
        out = self._enrich(result, branch_id, b)
        if publish:
            publish(dict(out))

        def on_year(yr: YearResult) -> None:
            out["years"] = {**out["years"], str(yr.year): yr.model_dump()}
            if publish:
                publish(dict(out))

        years = self.plan_years(b, result, view_year, progress=lambda s, f: report(s, 0.5 + 0.45 * f),
                                on_year=on_year)
        out["years"] = {k: v.model_dump() for k, v in years.items()}
        if params == self.params(stored.req, stored.project_id):
            report("writing findings", 0.96)
            self.record_findings(branch_id, b, result, years)
        return remember(self.cache.payload, key, out, MAX_PAYLOAD_ENTRIES)
